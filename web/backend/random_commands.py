"""Suggest text commands without submitting, parsing or moving the robot."""

import httpx
from fastapi import APIRouter, HTTPException, Request
from surgical_contracts import RuntimeMode

from .manual_control import BUSY

router = APIRouter()


@router.post("/api/sessions/{session_id}/commands/random-suggestion")
async def random_suggestion(session_id: str, request: Request):
    runtime = request.app.state.runtime

    def require_idle():
        session = runtime.store.snapshot(session_id)
        if session.robot_mode != "simulation" or session.status in BUSY or session.pending_confirmation:
            raise HTTPException(status_code=409, detail="请在仿真空闲时生成随机指令")
        runtime.manual.assert_task_allowed(RuntimeMode.SIMULATION)

    require_idle()
    base = runtime._robots[RuntimeMode.SIMULATION].base_url
    try:
        async with httpx.AsyncClient(base_url=base, timeout=40, trust_env=False) as client:
            response = await client.post('/v1/suggestions/random-motion')
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.json().get('message', '当前姿态无法生成随机指令'))
            suggestion = response.json()
            state_response = await client.get('/v1/state')
            state_response.raise_for_status()
            current = state_response.json()
        require_idle()
        if current.get('state', {}).get('active_command_id') or max(abs(a - b) for a, b in zip(current['joint_positions_deg'], suggestion['start_joint_positions_deg'])) > 0.2:
            raise HTTPException(status_code=409, detail="机械臂位置已变化，请重新生成")
        return {key: suggestion[key] for key in ('name', 'prompt', 'stepCount')}
    except httpx.HTTPError as error:
        raise HTTPException(status_code=503, detail="随机指令生成暂时不可用，请重试") from error
