from __future__ import annotations
import asyncio
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from surgical_contracts import RuntimeMode, MotionStepKind
from web.backend.manual_control import ManualController, ManualInput
from web.backend.main import create_app
from web.backend.sessions import SessionStore, SessionConflict
from web.backend.models import SessionStatus


class Transport:
    def __init__(self, *, delay=0, running=False, fail_stop=False):
        self.delay=delay; self.running=running; self.fail_stop=fail_stop
        self.events=[]; self.commands=[]; self.closed=False
    async def submit(self, request):
        self.events.append('submit-start')
        if self.delay: await asyncio.sleep(self.delay)
        self.commands.append(request); self.events.append('submit-ack')
        return {'status':'running' if self.running else 'succeeded'}
    async def record(self, command_id):
        return {'status':'running' if self.running else 'succeeded'}
    async def stop(self):
        self.events.append('stop')
        if self.fail_stop: raise TimeoutError('no stop feedback')
        self.running=False
    async def close(self): self.closed=True


def setup(transport=None, *, mode=RuntimeMode.SIMULATION):
    store=SessionStore(); session=store.create(robot_mode=mode)
    runtime=SimpleNamespace(store=store, _robots={RuntimeMode.SIMULATION:SimpleNamespace(base_url='http://invalid')})
    runtime._session_mode=lambda sid:RuntimeMode(store.snapshot(sid).robot_mode)
    runtime.get_robot_telemetry=lambda sid:SimpleNamespace(connected=True,estop=False,motion_state='idle')
    fake=transport or Transport(); clock=[100.0]
    controller=ManualController(runtime,clock=lambda:clock[0],transport_factory=lambda:fake)
    runtime.manual=controller
    return runtime,controller,session.session_id,fake,clock


@pytest.mark.parametrize('kind,axis', [('translation',i) for i in range(3)]+[('rotation',i) for i in range(3)]+[('joint',i) for i in range(6)])
@pytest.mark.parametrize('direction',[-1,1])
def test_all_24_directions_are_structured_without_model(kind,axis,direction):
    async def case():
        runtime,ctl,sid,transport,_=setup()
        before=runtime.store.snapshot(sid).model_dump()
        lease=await ctl.acquire(sid)
        await ctl.input(sid,ManualInput(token=lease['token'],sequence=1,kind=kind,axis=axis,direction=direction,amount=1))
        await ctl.lease.task
        step=transport.commands[0].steps[0]
        if kind=='translation':
            assert step.kind==MotionStepKind.CARTESIAN_RELATIVE
            assert step.translation_mm[axis]==direction
        elif kind=='rotation':
            assert step.kind==MotionStepKind.TCP_ROTATION_RELATIVE
            assert step.rotation_axis.value==('x','y','z')[axis]
            assert step.rotation_deg==direction
        else:
            assert step.kind==MotionStepKind.JOINT_RELATIVE
            assert step.joint_index==axis+1 and step.rotation_deg==direction
        assert runtime.store.snapshot(sid).model_dump()==before
        await ctl.release(sid,lease['token']); await ctl.shutdown()
    asyncio.run(case())


def test_release_cannot_overtake_a_slow_submit():
    async def case():
        _,ctl,sid,transport,_=setup(Transport(delay=.08,running=True))
        token=(await ctl.acquire(sid))['token']
        await ctl.input(sid,ManualInput(token=token,sequence=1,kind='translation',continuous=True))
        await asyncio.sleep(.01)
        await ctl.release(sid,token)
        assert transport.events==['submit-start','submit-ack','stop']
        assert ctl.lease is None and transport.closed
        await ctl.shutdown()
    asyncio.run(case())


def test_hold_watchdog_stops_even_while_ownership_heartbeat_is_fresh():
    async def case():
        _,ctl,sid,transport,clock=setup(Transport(running=True))
        token=(await ctl.acquire(sid))['token']
        await ctl.input(sid,ManualInput(token=token,sequence=1,kind='joint',axis=5,continuous=True))
        await asyncio.sleep(.01); clock[0]+=.6
        await ctl.heartbeat(sid,token)
        await asyncio.sleep(.12)
        assert 'stop' in transport.events
        assert ctl.lease is not None and not ctl.lease.active
        await ctl.release(sid,token); await ctl.shutdown()
    asyncio.run(case())


def test_sequence_and_token_prevent_replayed_or_other_tab_inputs():
    async def case():
        _,ctl,sid,_,_=setup()
        token=(await ctl.acquire(sid))['token']
        await ctl.input(sid,ManualInput(token=token,sequence=2))
        with pytest.raises(SessionConflict):
            await ctl.input(sid,ManualInput(token=token,sequence=1,kind='translation'))
        with pytest.raises(SessionConflict):
            await ctl.input(sid,ManualInput(token='wrong-token-123456',sequence=3,kind='joint'))
        with pytest.raises(SessionConflict): await ctl.acquire(sid)
        await ctl.release(sid,token); await ctl.shutdown()
    asyncio.run(case())


def test_auto_task_and_manual_control_are_mutually_exclusive():
    async def case():
        runtime,ctl,sid,_,_=setup()
        runtime.store.mutate(sid,lambda r:setattr(r,'status',SessionStatus.PARSING))
        with pytest.raises(SessionConflict): await ctl.acquire(sid)
        runtime.store.mutate(sid,lambda r:setattr(r,'status',SessionStatus.READY))
        token=(await ctl.acquire(sid))['token']
        with pytest.raises(SessionConflict):ctl.assert_task_allowed(RuntimeMode.SIMULATION)
        ctl.assert_task_allowed(RuntimeMode.REAL)
        await ctl.release(sid,token)
        ctl.assert_task_allowed(RuntimeMode.SIMULATION)
        await ctl.shutdown()
    asyncio.run(case())


def test_real_mode_remains_unavailable_without_mac_upgrade():
    async def case():
        _,ctl,sid,transport,_=setup(mode=RuntimeMode.REAL)
        assert not ctl.status(sid)['available']
        with pytest.raises(SessionConflict):await ctl.acquire(sid)
        assert transport.commands==[] and ctl.lease is None
    asyncio.run(case())


def test_missing_stop_confirmation_retains_the_control_lock():
    async def case():
        _,ctl,sid,transport,_=setup(Transport(running=True,fail_stop=True))
        token=(await ctl.acquire(sid))['token']
        await ctl.input(sid,ManualInput(token=token,sequence=1,kind='translation',continuous=True))
        await asyncio.sleep(.01)
        with pytest.raises(SessionConflict):await ctl.release(sid,token)
        assert ctl.lease is not None
        with pytest.raises(SessionConflict):ctl.assert_task_allowed(RuntimeMode.SIMULATION)
        transport.fail_stop=False
        await ctl.release(sid,token);await ctl.shutdown()
    asyncio.run(case())


def test_manual_routes_keep_tokens_out_of_status_and_reject_unknown_fields():
    runtime,ctl,sid,transport,_=setup()
    with TestClient(create_app(runtime,static_dir='/does-not-exist')) as client:
        token=client.post(f'/api/sessions/{sid}/manual/acquire').json()['token']
        assert 'token' not in client.get(f'/api/sessions/{sid}/manual').json()
        assert client.post(f'/api/sessions/{sid}/manual/input',json={'token':token,'sequence':1,'kind':'translation','axis':0,'vendor_command':'MoveL'}).status_code==422
        assert client.post(f'/api/sessions/{sid}/manual/input',json={'token':token,'sequence':2,'kind':'rotation','axis':5}).status_code==422
        assert client.post(f'/api/sessions/{sid}/manual/release',json={'token':token}).status_code==200
    assert transport.commands==[]


def test_existing_text_flow_is_unchanged_after_manual_release():
    from tests.integration.test_agent_web import make_client, relative_command
    client,parser,robot,planner,observer=make_client(relative_command())
    with client:
        runtime=client.app.state.runtime
        runtime.manual.transport_factory=lambda:Transport()
        sid=client.post('/api/sessions').json()['session_id']
        before=client.get('/api/sessions/'+sid).json()
        token=client.post(f'/api/sessions/{sid}/manual/acquire').json()['token']
        other=client.post('/api/sessions').json()['session_id']
        blocked=client.post(f'/api/sessions/{other}/commands/text',json={'prompt':'沿 Z 正方向移动 8 mm'})
        assert blocked.status_code==409 and parser.calls==0
        assert client.get('/api/sessions/'+sid).json()==before
        assert client.post(f'/api/sessions/{sid}/manual/release',json={'token':token}).status_code==200
        accepted=client.post(f'/api/sessions/{sid}/commands/text',json={'prompt':'沿 Z 正方向移动 8 mm'})
        assert accepted.status_code==200 and parser.calls==1
        assert accepted.json()['pending_confirmation'] is True


@pytest.mark.parametrize('kind',['translation','rotation','joint'])
@pytest.mark.parametrize('amount',[10,20])
def test_large_manual_increments_use_configured_speed_without_microsegment_clamp(kind,amount):
    _,ctl,_,_,_=setup()
    request=ctl._request(ManualInput(token='test-token-123456789',sequence=1,kind=kind,amount=amount,continuous=True))
    step=request.steps[0]
    if kind=='translation':assert step.translation_mm[0]==amount
    else:assert step.rotation_deg==amount
    assert request.translation_speed_mm_s==ctl.policy.move_speed_mm_s
    assert request.joint_speed_deg_s==ctl.policy.joint_speed_deg_s


def test_manual_large_increment_limit_is_still_enforced():
    async def case():
        from fastapi import HTTPException
        _,ctl,sid,transport,_=setup()
        token=(await ctl.acquire(sid))['token']
        for sequence,kind in enumerate(('translation','rotation','joint'),1):
            with pytest.raises(HTTPException):
                await ctl.input(sid,ManualInput(token=token,sequence=sequence,kind=kind,amount=21))
        assert transport.commands==[]
        await ctl.release(sid,token);await ctl.shutdown()
    asyncio.run(case())
