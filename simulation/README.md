# SOFA/LapGym 仿真环境

本目录承载手术导航项目的独立仿真运行时。Step 4 验证了 SOFA、SofaPython3、`sofa_env` 和无头渲染；Step 5 使用已购买的华沿 E05-Pro 力控版六轴机械臂，实现针尖/TCP 到入点的连续定位和相对移动。当前仍不连接 InternS2、网页、路径规划或真实机械臂，也不包含穿刺执行逻辑。

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
simulation/requirements.txt
simulation/scripts/check_sofa_imports.py
simulation/scripts/check_upstream_env.py
simulation/scripts/check_entry_point_env.py
simulation/scripts/fetch_e05_model.sh
simulation/entry_point_env/
simulation/assets/unit_cylinder_z.obj
configs/simulation.yaml
tests/simulation/
```

- `check_sofa_imports.py` 检查 Python/CPU 架构、SOFA Python 模块、必要插件和最小仿真步。
- `check_upstream_env.py` 加载上游 `controllable_object_example` 场景，执行固定步数、验证位置变化并检查 RGB 帧。
- `fetch_e05_model.sh` 在镜像构建时稀疏拉取厂家 E05 网格和 xacro，并校验完整提交及逐文件 SHA256。
- `entry_point_env` 提供 E05-Pro 六轴正逆运动学、毫米制连续轨迹、关节速度限制、SOFA 场景适配、状态输出和 RGB 轨迹叠加。
- `check_entry_point_env.py` 验证绝对入点定位、相对 `+Z 5 mm`、六轴关节变化、有限步长、SOFA 位姿同步和 RGB 输出。

SOFA v24.06 中的旧 `splib` Python 包是一个会主动抛错的迁移提示桩，不是必需运行时模块。Step 4 的 `controllable_object_example` 不依赖它，因此导入检查不会导入 `splib`，也不需要为当前场景额外安装 STLIB。

`sofa_env.base` 会通过 `sofa_env.utils.io` 在导入阶段直接导入 `open3d`，场景工具又会导入 `numba`。即使当前冒烟测试不写点云，这些仍是上游源码的导入时依赖，已纳入镜像。

## 服务器执行流程

以下命令全部在服务器宿主机的 `~/interns2-finetune` 中执行，不要先 `docker exec` 进入 LMDeploy 容器。

### 1. 更新并检查基线

```bash
cd ~/interns2-finetune
git pull
git status --short
uname -m
docker version
```

`uname -m` 必须输出 `x86_64`。建议保存镜像构建日志：

```bash
docker build \
  -f docker/simulation/Dockerfile \
  -t interns2-robot-simulation:dev \
  . 2>&1 | tee step4-simulation-build.log
```

构建时会从 SOFA 官方 GitHub Release 下载 Linux ZIP，并在解压前强制校验 SHA256。镜像构建末尾也会自动执行一次导入检查。

### 2. SOFA/SofaPython3 导入和最小步进

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

### 3. Xvfb 无头渲染与上游场景

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

### 4. 可选诊断

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
