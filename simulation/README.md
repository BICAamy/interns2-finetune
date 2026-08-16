# SOFA/LapGym 仿真环境

本目录承载手术导航项目的独立仿真运行时。Step 4 验证了 SOFA、SofaPython3、`sofa_env` 和无头渲染；Step 5 使用已购买的华沿 E05-Pro 力控版六轴机械臂，实现针尖/TCP 到入点的连续定位和相对移动；Step 6 将该环境封装为单 worker 的 HTTP/WebSocket/MJPEG 服务。当前仍不连接 InternS2、网页、路径规划或真实机械臂，也不包含穿刺执行逻辑。

## 固定版本

| 组件 | 版本 |
| --- | --- |
| 基础镜像 | Ubuntu 22.04 |
| Python | 3.10 |
| SOFA | v24.06.00 Linux x86_64 |
| SOFA ZIP SHA256 | `9d515e2f25f657c744821be8a5361e22803c18947b33af7a0b357c259202236a` |
| `sofa_env` | 上游提交 `85bf7e05dd088b824794dda0046679df13b13e6e` |
| 华沿 E05 网格/URDF | 官方 `elfin_model` 提交 `84baf18d37eefa46b6f092c7fa1f105f81f70ecb`，`485/elfin5` |
| 力控末端修正 | J6 到法兰 `184 mm`，来自 E05-Pro 力控尺寸图 |
| 默认渲染 | Xvfb + Pyglet + Mesa 软件 OpenGL |

镜像与 InternS2/LMDeploy 镜像完全分离。默认的 Step 4 检查不需要 NVIDIA GPU，也不要在 `xl_interns2_lmdeploy` 容器中安装 SOFA。

## 文件

```text
docker/simulation/Dockerfile
docker/simulation/Dockerfile.offline
simulation/requirements.txt
simulation/step5-requirements.txt
simulation/service-requirements.txt
simulation/server/
simulation/scripts/check_sofa_imports.py
simulation/scripts/check_upstream_env.py
simulation/scripts/check_entry_point_env.py
simulation/scripts/verify_e05_model.sh
simulation/scripts/prepare_e05_model.sh
simulation/scripts/healthcheck_simulation_service.py
simulation/scripts/check_simulation_service.py
simulation/entry_point_env/
simulation/assets/unit_cylinder_z.obj
configs/simulation.yaml
tests/simulation/
tests/integration/test_simulation_api.py
tests/integration/test_simulation_api_sofa.py
third_party/elfin_model/
third_party/wheelhouse/
```

- `check_sofa_imports.py` 检查 Python/CPU 架构、SOFA Python 模块、必要插件和最小仿真步。
- `check_upstream_env.py` 加载上游 `controllable_object_example` 场景，执行固定步数、验证位置变化并检查 RGB 帧。
- `verify_e05_model.sh` 校验随项目传输的厂家 E05 最小网格/xacro 快照的逐文件 SHA256。
- `prepare_e05_model.sh` 在镜像内为厂家大写 `.STL` 创建小写 `.stl` 符号链接，以兼容 `sofa_env` 的大小写敏感加载器；原文件内容和校验值保持不变。
- `entry_point_env` 提供 E05-Pro 六轴正逆运动学、毫米制连续轨迹、关节速度限制、SOFA 场景适配、状态输出和 RGB 轨迹叠加。
- `check_entry_point_env.py` 验证绝对入点定位、相对 `+Z 5 mm`、六轴关节变化、有限步长、SOFA 位姿同步和 RGB 输出。
- `Dockerfile.offline` 以已验证的 Step 4 镜像为基座，从项目内 wheelhouse 安装 Step 5/6 增量依赖，全程不访问网络。

SOFA v24.06 中的旧 `splib` Python 包是一个会主动抛错的迁移提示桩，不是必需运行时模块。Step 4 的 `controllable_object_example` 不依赖它，因此导入检查不会导入 `splib`，也不需要为当前场景额外安装 STLIB。

`sofa_env.base` 会通过 `sofa_env.utils.io` 在导入阶段直接导入 `open3d`，场景工具又会导入 `numba`。即使当前冒烟测试不写点云，这些仍是上游源码的导入时依赖，已纳入镜像。

## 服务器执行流程

以下命令全部在服务器宿主机的 `~/interns2-finetune` 中执行，不要先 `docker exec` 进入 LMDeploy 容器。

### 1. 无网服务器：先保留已经验证的 Step 4 镜像

当前实验室服务器不能访问外网。正在等待 SOFA 下载的构建可直接按
`Ctrl+C` 停止；失败构建不会覆盖已有的 `interns2-robot-simulation:dev`
标签。不要执行 `docker system prune` 或删除旧镜像。

在拉取/传输 Step 5 代码后、再次构建之前，先将现有 Step 4 镜像固定为
独立标签：

```bash
cd ~/interns2-finetune
docker image inspect interns2-robot-simulation:dev >/dev/null
docker tag \
  interns2-robot-simulation:dev \
  interns2-robot-simulation:step4-base

docker run --rm \
  interns2-robot-simulation:step4-base \
  python3 simulation/scripts/check_sofa_imports.py
```

随后确认通过 VSCode/Git 传到服务器的离线资产完整。Step 6 增加服务 wheel
后，E05 模型约 `8.8 MB`、wheelhouse 约 `8.8 MB`；不能只传文本源码而漏掉
`.STL` 和 `.whl` 文件：

```bash
test "$(uname -m)" = "x86_64"
test -f third_party/elfin_model/model/485/elfin5/elfin_link6.STL
test -f third_party/wheelhouse/pydantic_core-2.27.2-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
du -sh third_party/elfin_model third_party/wheelhouse

sh simulation/scripts/verify_e05_model.sh third_party/elfin_model
(
  cd third_party/wheelhouse
  sha256sum --check --strict SHA256SUMS
)
```

### 2. 无网增量构建 Step 5/6

使用离线 Dockerfile，并显式禁用构建网络。该构建只在 Step 4 镜像上增加
E05-Pro 资产、共享契约、Step 5/6 代码和离线 Python 包：

```bash
docker build \
  --network=none \
  -f docker/simulation/Dockerfile.offline \
  --build-arg BASE_IMAGE=interns2-robot-simulation:step4-base \
  -t interns2-robot-simulation:dev \
  . 2>&1 | tee step6-robot-simulation-offline-build.log
```

构建日志中不应出现 `curl`、`git clone`、`apt-get update` 或访问 PyPI。
如报 `pull access denied for interns2-robot-simulation:step4-base`，说明尚未执行
上一步的 `docker tag`，而不是需要登录镜像仓库。

`docker/simulation/Dockerfile` 保留为有网环境从 Ubuntu 22.04 开始的完整、
可复现构建入口；实验室无网服务器不要使用它从零重建，因为它需要下载
SOFA 和完整的 Step 4 Python 依赖。

### 3. SOFA/SofaPython3 导入和最小步进

```bash
docker run --rm \
  interns2-robot-simulation:dev \
  python3 simulation/scripts/check_sofa_imports.py
```

成功输出是 JSON，必须包含：

```json
{
  "machine": "x86_64",
  "python": "3.10.x",
  "simulation_step": "ok",
  "status": "ok"
}
```

`plugins` 应包含 `SofaPython3`、`Sofa.Component.AnimationLoop`、`Sofa.Component.StateContainer` 和 `Sofa.GL.Component.Rendering3D`。

### 4. Xvfb 无头渲染与上游场景

```bash
docker run --rm \
  interns2-robot-simulation:dev \
  timeout --signal=INT --kill-after=10s 180s \
    run-with-xvfb \
    python3 -u simulation/scripts/check_upstream_env.py \
      --steps 10 \
      --render-backend xvfb
```

成功时必须同时满足：

- `status` 为 `ok`；
- `completed_steps` 为 `10`；
- `displacement` 不为零；
- `rgb.generated` 为 `true`；
- `rgb.shape` 为 `[600, 600, 3]`；
- `rgb.minimum` 和 `rgb.maximum` 不相等；
- `opengl.renderer` 有值，使用软件渲染时通常可见 `llvmpipe`。

### 5. 可选诊断

只检查物理场景，不生成 RGB：

```bash
docker run --rm \
  interns2-robot-simulation:dev \
  python3 simulation/scripts/check_upstream_env.py \
    --steps 10 \
    --render-backend none
```

检查容器内 Mesa/GLX：

```bash
docker run --rm \
  interns2-robot-simulation:dev \
  timeout --signal=INT --kill-after=5s 30s \
    run-with-xvfb glxinfo -B
```

EGL 是可选路线，其是否可用取决于宿主机和 Docker 图形栈，不作为 Step 4 必须验收项：

```bash
docker run --rm \
  interns2-robot-simulation:dev \
  python3 simulation/scripts/check_upstream_env.py \
    --steps 10 \
    --render-backend egl
```

## 上游示例兼容处理

固定提交中的 `controllable_env.py` 存在两个示例级问题：

1. `step()` 用未定义的 `done` 计算奖励；
2. 平移时将四元数 `w` 分量每步加一。

本项目不修改 `third_party/sofa_env`。`check_upstream_env.py` 通过仅用于冒烟测试的子类修正上述逻辑，场景描述、物理组件、网格和渲染仍全部使用上游实现。

## Step 5 连续入点定位

### 坐标、单位与控制边界

- 外部命令、共享契约、状态和轨迹一律使用毫米；
- 坐标系固定为 `robot_base`，当前与仿真世界坐标轴对齐；
- 六个关节原点/轴采用厂家新版 `485/elfin5` xacro，力控版 J6 到法兰距离由普通版 `146 mm` 修正为尺寸图中的 `184 mm`；
- 只有 `EntryPointReachEnv` 的 SOFA 适配边界执行毫米到米的转换，厂家 STL 本身以米建模；
- TCP 固定命名为 `needle_tip`；
- 当前法兰到针尖暂定为法兰局部 `+Z 150 mm`、零姿态偏移，配置明确标记为临时值且禁止实机运动；
- 每步最大欧氏位移为 `speed_mm_s × time_step_s`，最后一步同样不会跳变；
- 每步关节角变化同时受 E05-Pro 各关节最大速度限制；
- 工作空间、速度、误差阈值、初始位置和图像尺寸来自 `configs/simulation.yaml`；
- 工作空间盒只做第一层过滤，所有目标还必须通过固定安全姿态下的六轴逆解；
- 入点是定位目标；本环境没有靶点运动和穿刺逻辑。

官方仓库只提供普通新版 E05 网格；当前将第六连杆沿局部 Z 方向按 `184/146` 缩放作为力控末端的可视化代理，运动学法兰位置使用准确的 `184 mm`。厂家提供的 E05-Pro STEP 用于尺寸交叉核对，暂不在运行时直接解析。待取得单独的力控末端网格后，只替换第六连杆可视资产，不修改运动学、命令或工具协议。

针架 CAD 不是 Step 5 阻塞项，但真实法兰到针尖的刚体变换是实机阻塞项。安装后应使用厂家 TCP 标定接口测得 XYZ/RPY，更新 `tool_transform`，并在独立实机安全评审后才能将 `provisional` 改为 `false`、允许实机运动。

### 快速单元测试

不启动 SOFA 的轨迹、边界、停止和 RGB 叠加测试：

```bash
docker run --rm \
  interns2-robot-simulation:dev \
  python3 -m pytest \
    tests/simulation/test_e05_pro_kinematics.py \
    tests/simulation/test_entry_point_env.py \
    tests/simulation/test_relative_motion.py \
    -q
```

默认会跳过两项显式标记的 SOFA 集成测试。

### SOFA 集成测试

绝对定位和 RGB 测试需要 Xvfb：

```bash
docker run --rm \
  -e ENTRY_POINT_SOFA_TESTS=1 \
  interns2-robot-simulation:dev \
  timeout --signal=INT --kill-after=10s 180s \
    run-with-xvfb \
    python3 -m pytest \
      tests/simulation/test_entry_point_env.py \
      -q

docker run --rm \
  -e ENTRY_POINT_SOFA_TESTS=1 \
  interns2-robot-simulation:dev \
  timeout --signal=INT --kill-after=10s 120s \
    python3 -m pytest \
      tests/simulation/test_relative_motion.py \
      -q
```

两个文件分别在独立容器中运行，避免在同一个 Python 进程中创建多个 SOFA 仿真实例。

### Step 5 综合冒烟测试

```bash
docker run --rm \
  interns2-robot-simulation:dev \
  timeout --signal=INT --kill-after=10s 180s \
    run-with-xvfb \
    python3 -u simulation/scripts/check_entry_point_env.py
```

成功输出必须满足：

- `status` 为 `ok`；
- 机器人型号为 `E05-Pro` 且 `force_control_variant` 为 `true`；
- 入点为 `[500, 0, 500]` mm，之后相对移动 `[0, 0, 5]` mm；
- 最终位置在 `[500, 0, 505]` mm 附近，绝对定位残差不超过配置阈值；
- `tcp_transform_provisional` 为 `true`、`real_robot_ready` 为 `false`；
- 初始与最终六轴关节角不同；
- `entry_error_mm` 不超过配置阈值；
- `maximum_step_mm` 不超过 `allowed_maximum_step_mm`；
- `rgb.generated` 为 `true`，图像形状为 `[600, 600, 3]`；
- `puncture_logic_present` 为 `false`。

## 常见故障

### SHA256 校验失败

不要跳过校验。优先检查 GitHub 下载是否被中断、代理是否返回了 HTML 页面，然后重试构建。

### `libpython3.10.so` 或 Python ABI 错误

确认使用本 Dockerfile 的 Ubuntu 22.04/Python 3.10，且服务器是 `x86_64`。不要改成 Python 3.11/3.12 基础镜像。

### `NoSuchDisplayException`

表示使用了 `--render-backend xvfb` 却没有通过镜像内的 `run-with-xvfb` 启动。使用上文完整命令。项目不再使用 `xvfb-run -a`：自动显示号模式会在 Xvfb 本身启动失败时不断换端口重试，看起来像永久卡住。`run-with-xvfb` 固定使用 `:99`，通过 `xdpyinfo` 最多等待 15 秒，启动失败时会输出 Xvfb 日志并清理子进程。

### RGB 帧全黑或 OpenGL 上下文失败

先运行上文 `run-with-xvfb glxinfo -B` 命令。镜像已设置 `LIBGL_ALWAYS_SOFTWARE=1`，此阶段应使用 Mesa 软件渲染，不应为了冒烟测试去修改 LMDeploy 的 NVIDIA 运行时。

### SOFA 插件无法加载

保留完整 JSON、Python traceback 和 `step4-simulation-build.log`。此情况属于 Step 4 停止条件，先定位二进制与系统库兼容问题，不直接进入 Step 5。

## Step 4 验收

只有导入检查和 Xvfb RGB 冒烟测试均输出 `status: ok`，才算完成 Step 4。镜像成功构建但无法生成非空 RGB 帧，不算通过。

## Step 5 验收

只有控制器测试、SOFA 集成测试和 Step 5 综合冒烟测试全部通过，才算完成 Step 5。纯数学控制器到达目标但 SOFA TCP 未同步，或 SOFA 成功移动但没有有效 RGB/轨迹输出，均不算通过。

## Step 6 `robot-simulation` 服务

### 并发与安全边界

- 只有 `robot-simulation-worker` 线程创建、步进和关闭 SOFA/OpenGL 环境；
- FastAPI 请求线程只验证共享契约并把命令放入队列；
- 普通命令 FIFO 串行执行，不能覆盖正在运行的轨迹；
- `stop`/`estop` 使用独立高优先级队列，会取消正在运行及此前排队的普通命令；
- `estop` 是锁存状态，后续运动返回 `ESTOP_ACTIVE`，仿真 `reset` 后才清除；
- 相同 `command_id` 和相同参数幂等返回原记录；相同 ID 配不同参数返回 HTTP 409；
- `SIMULATION_PAUSE_ON_NO_CLIENTS=1` 时，MJPEG/WebSocket 客户端全部断开会暂停轨迹；默认值 `0`，HTTP 提交后即使页面刷新也继续执行；
- Uvicorn 固定一个进程，禁止通过 `--workers` 启动多个 SOFA 实例。

### API

```text
GET  /health
GET  /v1/state
POST /v1/reset
POST /v1/commands/move-to-entry
POST /v1/commands/move-relative
POST /v1/commands/stop
POST /v1/commands/estop
GET  /v1/commands/{command_id}
GET  /v1/stream.mjpeg
WS   /v1/events
```

所有 JSON 请求、响应和事件都使用 `surgical_contracts` 的 `schema_version=1.0`
模型。运动 POST 返回 HTTP 202 和命令记录，客户端通过命令查询或 WebSocket
观察 `queued → running → succeeded/failed/rejected/cancelled`。

### 无 SOFA API/并发测试

```bash
docker run --rm \
  interns2-robot-simulation:dev \
  python3 -m pytest tests/integration/test_simulation_api.py -q
```

### 真实 SOFA worker HTTP 集成测试

```bash
docker run --rm \
  -e ROBOT_SIMULATION_SOFA_TESTS=1 \
  interns2-robot-simulation:dev \
  timeout --signal=INT --kill-after=10s 180s \
    run-with-xvfb \
    python3 -m pytest \
      tests/integration/test_simulation_api_sofa.py \
      -q -s
```

### 启动服务并验收

服务只映射到服务器回环地址，当前版本没有认证，不得直接暴露到局域网或公网：

```bash
docker run --rm -d \
  --name robot-simulation-test \
  -p 127.0.0.1:8001:8001 \
  interns2-robot-simulation:dev

docker logs -f robot-simulation-test
```

日志出现 Uvicorn 启动成功后，另开服务器终端执行：

```bash
curl -s http://127.0.0.1:8001/health
curl -s http://127.0.0.1:8001/v1/state

python3 simulation/scripts/check_simulation_service.py \
  --base-url http://127.0.0.1:8001 \
  --timeout 30
```

验收脚本会通过真实 HTTP 依次 reset、移动到 `[500,0,500] mm`、相对移动
`+Z 5 mm`，校验最终 TCP、轨迹和一帧 MJPEG。成功输出包含
`"status": "ok"`。浏览器/后续网页可直接使用：

```text
http://127.0.0.1:8001/v1/stream.mjpeg
ws://127.0.0.1:8001/v1/events
```

验收结束后停止测试服务：

```bash
docker stop robot-simulation-test
```

### Step 6 验收

以下各项全部通过才算完成：无 SOFA API 测试、真实 SOFA worker HTTP 测试、
独立服务 `/health`、HTTP 绝对/相对运动、状态/轨迹、MJPEG、幂等与冲突、
普通命令串行、停止/急停抢占和可配置断连暂停。
