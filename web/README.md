# Step 11–13：FastAPI + React 网页、远程仿真与语音控制台

本服务是浏览器唯一入口。浏览器只访问 `agent-web`，不能直接访问
`robot-simulation` 或 `planner-adapter`。任务始终先由 InternS2 解析并展示，
医生点击“确认并执行”后，确定性编排器才允许调用工具。

当前范围：

- 文本、最长 30 秒的按键录音和可选图像输入；
- 本地 `faster-whisper-small` 非流式转写，最终转写、置信度和延迟可见；
- 普通语音复用文本解析与人工确认，“停止/急停”精确短语走快速通道；
- 原始 InternS2 工具参数、规范化命令、坐标、TCP 和时间线；
- 取消待确认任务、停止、急停和复位；
- 同源代理 SOFA MJPEG，浏览器不接触仿真服务地址；
- 默认 Z-up 正视相机，支持左键旋转、右键平移、滚轮缩放和双击回正；
- 提供正视、左视、右视、俯视、等轴测五个确定性预设视角；
- 每 100 ms 接收 TCP、入点、误差、进度、关节角、FPS 和当前工具；
- 轨迹在服务端下采样到最多 160 点，网页显示 X–Z 轨迹；
- 只移动到入点或执行有限相对移动；
- 只请求不可执行的 Mock 路径预览，**不执行穿刺**；
- 视频断开只关闭只读代理流，不会使机械臂控制线程崩溃。

## API

```text
GET  /health
GET  /api/asr/status
POST /api/sessions
GET  /api/sessions/{session_id}
POST /api/sessions/{session_id}/commands/text
POST /api/sessions/{session_id}/commands/speech
POST /api/sessions/{session_id}/confirm
POST /api/sessions/{session_id}/cancel
POST /api/sessions/{session_id}/stop
POST /api/sessions/{session_id}/estop
POST /api/sessions/{session_id}/reset-estop
GET  /api/sessions/{session_id}/simulation/telemetry
GET  /api/sessions/{session_id}/simulation/camera
PUT  /api/sessions/{session_id}/simulation/camera
GET  /api/sessions/{session_id}/simulation/stream.mjpeg
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

Step 13 另外需要约 110 MiB 的 Linux ASR wheels 和约 486 MiB 的固定模型。
它们不进入 Git，也不打包进模型镜像；先在联网的本机项目根目录执行：

```bash
./scripts/prepare_step13_asr_assets.sh
```

脚本固定下载 `faster-whisper==1.2.1` 和
`Systran/faster-whisper-small@536b0662742c02347bc0e980a01041f333bce120`，
并生成 SHA256 清单。然后从本机传到服务器宿主机：

```bash
rsync -av --progress \
  third_party/asr-wheelhouse/ \
  xl@192.168.7.202:~/interns2-finetune/third_party/asr-wheelhouse/

rsync -av --progress \
  models/asr/faster-whisper-small/ \
  xl@192.168.7.202:~/interns2-finetune/models/asr/faster-whisper-small/
```

服务器上先校验离线资产：

```bash
cd ~/interns2-finetune

(cd third_party/asr-wheelhouse && sha256sum --check --strict SHA256SUMS)
(cd models/asr/faster-whisper-small && sha256sum --check --strict SHA256SUMS)
```

本版本的交互相机同时修改了 `robot-simulation`，所以必须先按照
`simulation/README.md` 使用 `Dockerfile.offline` 重建
`interns2-robot-simulation:dev`，再构建本网页镜像；只重建网页不会改变 SOFA
默认视角。

```bash
cd ~/interns2-finetune

test -s web/frontend/dist/index.html
docker image inspect interns2-robot-simulation:dev >/dev/null
test -s third_party/asr-wheelhouse/SHA256SUMS
test -s models/asr/faster-whisper-small/model.bin

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

Step 12 演示要求页面断开后暂停运动，因此用下面的明确配置重建仿真容器。
这个配置只适用于网页演示；无网页 CLI 验收仍应使用默认值 `0`：

```bash
docker rm -f robot-simulation-test 2>/dev/null || true

docker run --rm -d \
  --name robot-simulation-test \
  --network surgical-nav-net \
  -p 127.0.0.1:8001:8001 \
  -e SIMULATION_PAUSE_ON_NO_CLIENTS=1 \
  interns2-robot-simulation:dev
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
  -e ASR_BACKEND=faster-whisper \
  -e ASR_MODEL_PATH=/opt/asr-models/faster-whisper-small \
  -e ASR_MODEL_NAME=faster-whisper-small \
  -e ASR_DEVICE=cpu \
  -e ASR_COMPUTE_TYPE=int8 \
  -e ASR_LANGUAGE=zh \
  -e ASR_CPU_THREADS=4 \
  -e ASR_MAX_DURATION_SECONDS=30 \
  -e ASR_LOW_CONFIDENCE_THRESHOLD=0.65 \
  -v /home/xl/interns2-finetune/models/asr/faster-whisper-small:/opt/asr-models/faster-whisper-small:ro \
  interns2-agent-web:dev
```

如三个容器的实际名称不同，只替换对应 URL 中的主机名。不要把服务 URL 写成
`127.0.0.1`，因为四个服务处于不同容器。

服务器宿主机检查：

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/api/asr/status
docker logs --tail 100 interns2-agent-web
```

先执行视频、遥测、默认正视相机和五个预设视角检查：

```bash
docker exec interns2-agent-web \
  python3 -m web.backend.scripts.check_step12
```

再明确允许一次仿真 `+Z 8 mm`，同时检查 InternS2、视频连接、遥测、轨迹和
最终 TCP：

```bash
docker exec interns2-agent-web \
  python3 -m web.backend.scripts.check_step12 \
    --execute-relative \
    --timeout 180
```

成功时顶层为 `"status": "ok"`，并包含：

```json
{
  "relative_motion": "completed",
  "tcp_delta_mm": [0.0, 0.0, 8.0]
}
```

Step 13 的静态 ASR 就绪检查：

```bash
docker exec interns2-agent-web \
  python3 -m web.backend.scripts.check_step13
```

首次真实录音会懒加载约 486 MiB 模型，耗时会明显高于后续请求。浏览器页面打开后，
点击“开始语音指令”，说完后点击“结束录音”。普通指令会自动完成转写和 InternS2
解析，但仍必须由医生点击“确认并执行”；页面必须能看到最终转写、置信度、ASR
延迟和端到端延迟。

本地电脑通过 VSCode SSH 转发，或执行：

```bash
ssh -N -L 8000:127.0.0.1:8000 xl@192.168.7.202
```

然后在本地浏览器打开 <http://127.0.0.1:8000>。

麦克风 API 要求安全上下文。通过 SSH 转发后必须使用上述 `localhost` 或
`127.0.0.1` 地址打开，不要直接使用 `http://192.168.7.202:8000`。若浏览器曾拒绝
权限，请在地址栏站点权限中重新允许麦克风。

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
WebSocket、临时图像清理、停止、急停、复位、禁止 planner 直通、遥测下采样、
MJPEG 代理、Z-up 轨道相机、五个预设视角、浏览器断开后的上游流清理、语音上传
边界、临时音频删除、低置信度人工确认和停止快速通道。

## Step 13 数据与安全语义

- 浏览器使用 `MediaRecorder` 采集单声道音频，用户手动开始/结束；30 秒时自动结束；
- 音频以原始请求体上传，服务端同时检查 MIME、报告时长和 10 MiB 大小上限；
- 临时录音只在系统临时目录存在，ASR 成功或失败后均立即删除，默认不持久化；
- ASR 只从只读本地目录加载，并强制 `local_files_only=True`，运行时不联网下载；
- 普通语音自动进入同一个 InternS2 `submit_text` 入口，绝不会跳过结构化校验；
- 所有普通语音，无论置信度高低，都必须再次点击“确认并执行”；低于 0.65 时页面
  明确要求逐字核对数字、正负号、单位和 XYZ 顺序；
- 只有“停止、停止机械臂、机械臂停止、停下来、立即停止”和“急停、紧急停止、
  立即急停、机械臂急停”等精确短语绕过 InternS2，直接进入确定性停止工具；
- `confidence` 是基于 Whisper segment 平均对数概率和 no-speech 概率的启发式分数，
  不是医疗级校准概率；最终安全边界仍是页面核对、确定性验证与人工确认；
- 第一版不做 VAD 自动开录和流式转写，这两项留到语音指令集实测稳定之后。

## Step 12 数据与断连语义

- MJPEG 由 `agent-web` 流式转发，不把整帧缓存在会话 JSON 中；
- 相机请求是有边界的观察操作，经 `agent-web` 代理并在 SOFA worker 线程串行
  执行；它不进入 InternS2 工具编排，也不能改变机械臂状态；
- 相机为仿真实例共享视角，当前单医生演示下网页拖动会更新服务器 MJPEG 画面；
- 页面 WebSocket 在仿真序列变化时推送遥测，空闲和错误时最多每秒一次；
- 页面只接收最多 160 个下采样轨迹点，不高频传输完整历史；
- 浏览器关闭 MJPEG 后，`agent-web` 会关闭上游响应，仿真服务随即注销客户端；
- `SIMULATION_PAUSE_ON_NO_CLIENTS=1` 时，所有视频/WebSocket 客户端断开会暂停
  活动轨迹，重新打开页面视频后继续；
- X11 Forwarding、VNC 和服务器桌面窗口不属于最终访问方案。
