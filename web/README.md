# Step 11：FastAPI + React 网页控制台

本服务是浏览器唯一入口。浏览器只访问 `agent-web`，不能直接访问
`robot-simulation` 或 `planner-adapter`。任务始终先由 InternS2 解析并展示，
医生点击“确认并执行”后，确定性编排器才允许调用工具。

当前范围：

- 文本和可选图像输入；
- 原始 InternS2 工具参数、规范化命令、坐标、TCP 和时间线；
- 取消待确认任务、停止、急停和复位；
- 只移动到入点或执行有限相对移动；
- 只请求不可执行的 Mock 路径预览，**不执行穿刺**；
- 仿真视频留到 Step 12。

## API

```text
GET  /health
POST /api/sessions
GET  /api/sessions/{session_id}
POST /api/sessions/{session_id}/commands/text
POST /api/sessions/{session_id}/confirm
POST /api/sessions/{session_id}/cancel
POST /api/sessions/{session_id}/stop
POST /api/sessions/{session_id}/estop
POST /api/sessions/{session_id}/reset-estop
WS   /ws/sessions/{session_id}
```

会话保存在服务内存中，所以 Uvicorn 必须保持一个 worker。网页在当前标签页的
`sessionStorage` 中保存会话 ID；刷新后只执行 `GET` 恢复状态，不会重新提交或
确认旧命令。

## 联网环境构建

```bash
docker build \
  -f docker/agent-web/Dockerfile \
  -t interns2-agent-web:dev \
  .
```

## 实验室服务器离线构建

前端 `dist` 已在联网开发机生成并纳入 Git。服务器不需要 Node/npm，也不会下载
Python 包，而是复用已经验收的 Step 6 镜像：

```bash
cd ~/interns2-finetune

test -s web/frontend/dist/index.html
docker image inspect interns2-robot-simulation:dev >/dev/null

docker build --network=none \
  -f docker/agent-web/Dockerfile.offline \
  --build-arg BASE_IMAGE=interns2-robot-simulation:dev \
  -t interns2-agent-web:dev \
  .
```

## 在现有容器网络中启动

以下名称与 Step 10 的 `surgical-nav-net` 保持一致。先确认 LMDeploy、仿真和
planner 三个容器都已经加入该网络：

```bash
docker network inspect surgical-nav-net \
  --format '{{range .Containers}}{{println .Name}}{{end}}'
```

再启动网页服务：

```bash
docker rm -f interns2-agent-web 2>/dev/null || true

docker run --rm -d \
  --name interns2-agent-web \
  --network surgical-nav-net \
  -p 127.0.0.1:8000:8000 \
  -e INTERNS2_BASE_URL=http://xl_interns2_lmdeploy:23333/v1 \
  -e INTERNS2_API_KEY=EMPTY \
  -e INTERNS2_MODEL=/home/xl/interns2-finetune/models/Intern-S2-Preview \
  -e INTERNS2_TEMPERATURE=0 \
  -e RUNTIME_MODE=simulation \
  -e DEFAULT_COORDINATE_FRAME=robot_base \
  -e DEFAULT_DISTANCE_UNIT=mm \
  -e ROBOT_SIMULATION_BASE_URL=http://robot-simulation-test:8001 \
  -e PLANNER_ADAPTER_BASE_URL=http://interns2-planner-adapter:8002 \
  -e PUNCTURE_EXECUTION_ENABLED=false \
  interns2-agent-web:dev
```

如三个容器的实际名称不同，只替换对应 URL 中的主机名。不要把服务 URL 写成
`127.0.0.1`，因为四个服务处于不同容器。

服务器宿主机检查：

```bash
curl -sS http://127.0.0.1:8000/health
docker logs --tail 100 interns2-agent-web
```

本地电脑通过 VSCode SSH 转发，或执行：

```bash
ssh -N -L 8000:127.0.0.1:8000 xl@192.168.7.202
```

然后在本地浏览器打开 <http://127.0.0.1:8000>。

## 自动化验收

无需 InternS2、SOFA 进程或 planner 进程即可执行网页 API 测试：

```bash
docker run --rm \
  interns2-agent-web:dev \
  python3 -m pytest \
    tests/integration/test_agent_web.py \
    agent/tests \
    tests/unit \
    -q
```

API 测试覆盖人工确认、刷新不重放、取消、相对运动、入点定位、Mock planner、
WebSocket、临时图像清理、停止、急停、复位和禁止 planner 直通。
