import copy
import random
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.config import AgentSettings
from agent.parsing.normalizer import CommandNormalizer
from robot_runtime.api import create_app
from simulation.entry_point_env.config import EntryPointEnvConfig
from simulation.entry_point_env.controller import ContinuousTrajectoryController
from simulation.entry_point_env.random_commands import generate_random_commands
from surgical_contracts import MoveSequenceRequest, RuntimeMode
from web.backend.random_commands import router
from web.backend.sessions import SessionStore
from web.backend.models import SessionStatus


CONFIG = EntryPointEnvConfig.from_yaml()


@pytest.mark.parametrize('seed', [0, 1, 3])
def test_generation_from_current_pose_runs_through_existing_parser_and_controller(seed):
    controller = ContinuousTrajectoryController(CONFIG)
    if seed == 3:
        controller.move_joint_relative(1, 15)
        while controller.get_state().motion_state == 'moving':
            controller.step()
    before = copy.deepcopy(controller.snapshot())
    suggestion = generate_random_commands(CONFIG, controller.joint_positions_deg, rng=random.Random(seed))
    assert controller.snapshot() == before
    rotations = [step for step in suggestion['steps'] if step['kind'] == 'joint_relative']
    assert len(rotations) == 3
    assert all(1 <= step['joint_index'] <= 5 for step in rotations)
    assert len({step['joint_index'] for step in rotations}) >= 2
    assert max(abs(v) for step in suggestion['steps'] for v in step.get('translation_mm', [])) > 180
    assert '第6关节' not in suggestion['prompt']
    settings = AgentSettings(base_url='http://unused', api_key='unused', model='unused', timeout=1, max_retries=0, max_tokens=1, temperature=0, top_p=1, max_tool_rounds=1)
    command = CommandNormalizer(settings).try_normalize_sequence_text(suggestion['prompt'])
    assert len(command.motion_sequence.steps) == suggestion['stepCount']
    for actual, expected in zip(command.motion_sequence.steps, suggestion['steps']):
        for key, value in expected.items():
            assert actual.model_dump(mode='json')[key] == value
    controller.move_sequence(MoveSequenceRequest(command_id='offline-suggestion', steps=command.motion_sequence.steps, translation_speed_mm_s=70, joint_speed_deg_s=15, joint_acceleration_deg_s2=30))
    for _ in range(2000):
        controller.step()
        assert CONFIG.workspace.contains(controller.get_state().tcp_position.as_tuple())
        if controller.get_state().motion_state != 'moving':
            break
    assert controller.get_state().motion_state != 'moving'
    assert np.linalg.norm(np.asarray(controller.get_state().tcp_position.as_tuple()) - before.state.tcp_position.as_tuple()) > 10


def test_runtime_suggestion_does_not_submit_commands(monkeypatch):
    import simulation.entry_point_env.random_commands as generator
    snapshot = SimpleNamespace(state=SimpleNamespace(active_command_id=None, estop=False, motion_state='idle'), joint_positions_deg=CONFIG.robot.initial_joint_positions_deg)
    calls = []
    monkeypatch.setattr(generator, 'generate_random_commands', lambda config, joints: calls.append(joints) or {'prompt': '向前移动 200 毫米。', 'stepCount': 1})
    provider = SimpleNamespace(mode=RuntimeMode.SIMULATION, get_telemetry=lambda: snapshot)
    with TestClient(create_app(provider=provider, manage_provider=False)) as client:
        assert client.post('/v1/suggestions/random-motion').status_code == 200
        snapshot.state.active_command_id = 'active'
        assert client.post('/v1/suggestions/random-motion').status_code == 409
    assert calls == [CONFIG.robot.initial_joint_positions_deg]


def test_web_suggestion_is_read_only_and_refuses_changed_pose(monkeypatch):
    import web.backend.random_commands as web_random
    store = SessionStore()
    session = store.create(robot_mode=RuntimeMode.SIMULATION)
    before = store.snapshot(session.session_id).model_dump()
    positions = list(CONFIG.robot.initial_joint_positions_deg)
    moved = [False]
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, path):
            calls.append(path)
            return httpx.Response(200, json={'name': '随机混合运动', 'prompt': '向前移动 200 毫米。', 'stepCount': 1, 'start_joint_positions_deg': positions})
        async def get(self, path):
            calls.append(path)
            return httpx.Response(200, json={'joint_positions_deg': [positions[0] + int(moved[0]), *positions[1:]]}, request=httpx.Request('GET', 'http://simulation'+path))
    monkeypatch.setattr(web_random.httpx, 'AsyncClient', Client)
    app = FastAPI()
    app.state.runtime = SimpleNamespace(store=store, _robots={RuntimeMode.SIMULATION: SimpleNamespace(base_url='http://simulation')}, manual=SimpleNamespace(assert_task_allowed=lambda mode: None))
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(f'/api/sessions/{session.session_id}/commands/random-suggestion')
        assert response.status_code == 200
        assert set(response.json()) == {'name', 'prompt', 'stepCount'}
        assert store.snapshot(session.session_id).model_dump() == before
        moved[0] = True
        assert client.post(f'/api/sessions/{session.session_id}/commands/random-suggestion').status_code == 409
        store.mutate(session.session_id, lambda record: setattr(record, 'status', SessionStatus.PARSING))
        count = len(calls)
        assert client.post(f'/api/sessions/{session.session_id}/commands/random-suggestion').status_code == 409
        assert len(calls) == count
    assert set(calls) == {'/v1/suggestions/random-motion', '/v1/state'}
