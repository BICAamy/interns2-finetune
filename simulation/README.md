# SOFA/LapGym 仿真环境

本目录承载手术导航项目的独立仿真运行时。Step 4 只验证 SOFA、SofaPython3、`sofa_env` 和无头渲染，不连接 InternS2、网页、路径规划或真实机械臂。

## 固定版本

| 组件 | 版本 |
| --- | --- |
| 基础镜像 | Ubuntu 22.04 |
| Python | 3.10 |
| SOFA | v24.06.00 Linux x86_64 |
| SOFA ZIP SHA256 | `9d515e2f25f657c744821be8a5361e22803c18947b33af7a0b357c259202236a` |
| `sofa_env` | 上游提交 `85bf7e05dd088b824794dda0046679df13b13e6e` |
| 默认渲染 | Xvfb + Pyglet + Mesa 软件 OpenGL |

镜像与 InternS2/LMDeploy 镜像完全分离。默认的 Step 4 检查不需要 NVIDIA GPU，也不要在 `xl_interns2_lmdeploy` 容器中安装 SOFA。

## 文件

```text
docker/simulation/Dockerfile
simulation/requirements.txt
simulation/scripts/check_sofa_imports.py
simulation/scripts/check_upstream_env.py
```

- `check_sofa_imports.py` 检查 Python/CPU 架构、SOFA Python 模块、必要插件和最小仿真步。
- `check_upstream_env.py` 加载上游 `controllable_object_example` 场景，执行固定步数、验证位置变化并检查 RGB 帧。

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
  --progress=plain \
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
  xvfb-run -a \
    -s "-screen 0 1280x1024x24 +extension GLX +render -noreset" \
    python3 simulation/scripts/check_upstream_env.py \
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
  xvfb-run -a glxinfo -B
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

## 常见故障

### SHA256 校验失败

不要跳过校验。优先检查 GitHub 下载是否被中断、代理是否返回了 HTML 页面，然后重试构建。

### `libpython3.10.so` 或 Python ABI 错误

确认使用本 Dockerfile 的 Ubuntu 22.04/Python 3.10，且服务器是 `x86_64`。不要改成 Python 3.11/3.12 基础镜像。

### `NoSuchDisplayException`

表示使用了 `--render-backend xvfb` 却没有通过 `xvfb-run` 启动。使用上文完整命令。

### RGB 帧全黑或 OpenGL 上下文失败

先运行 `xvfb-run -a glxinfo -B`。镜像已设置 `LIBGL_ALWAYS_SOFTWARE=1`，此阶段应使用 Mesa 软件渲染，不应为了冒烟测试去修改 LMDeploy 的 NVIDIA 运行时。

### SOFA 插件无法加载

保留完整 JSON、Python traceback 和 `step4-simulation-build.log`。此情况属于 Step 4 停止条件，先定位二进制与系统库兼容问题，不直接进入 Step 5。

## Step 4 验收

只有导入检查和 Xvfb RGB 冒烟测试均输出 `status: ok`，才算完成 Step 4。镜像成功构建但无法生成非空 RGB 帧，不算通过。
