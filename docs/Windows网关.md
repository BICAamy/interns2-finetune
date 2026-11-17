# Windows 本地机械臂网关

这是现有 `edge_gateway` 的 Windows 启动方式，使用同一套控制协议和执行代码。
模型、网页、仿真服务继续运行在原来的服务器。Windows 电脑只运行本地网关，
通过网线连接机械臂，并通过原来的 SSH 隧道连接服务器。
不使用 Translator 或 Cloudflare。

## 1. 安装一次 Python

从 Python 官方 Windows 下载页安装 **Python 3.13 的 Windows installer (64-bit)**：

https://www.python.org/downloads/windows/

安装时保留 pip 和 Python launcher，勾选 `Add python.exe to PATH`。
不要选 embeddable package，也不要使用 LibreOffice 自带的 Python。
已经安装的 64 位 Python 3.10～3.12 也可以使用。

安装后重新打开 **PowerShell**，验证：

```powershell
py -3.13 --version
```

## 2. 放好轻量包和配置

解压 `interns2-edge-gateway-windows.zip`，例如放到：

```text
C:\InternS2\interns2-edge-gateway
```

路径含空格或中文也可以；下文的路径只是放置示例，请使用实际解压位置。
在 PowerShell 中进入该目录（应能看到 `edge_gateway`、`configs`、`scripts`）：

```powershell
cd C:\InternS2\interns2-edge-gateway
```

如果你直接使用完整仓库，也可以在原来的 `app` 目录执行后续命令，不需要换项目。

确认有这两个文件，内容与原来可用的 Mac 网关一致：

- `configs/robot-real.local.yaml`
- `configs/gateway-auth.local`

使用 `--include-local-config` 打的个人包已经包含它们。
普通源码包不含本地配置，需要从原网关复制；不要重新随机生成密钥，否则服务器认证不匹配。
`configs/simulation.yaml` 和少量 `simulation/entry_point_env` 代码用于复用关节 FK 数学模型，
不代表要在 Windows 启动仿真，也不需要安装 SOFA 或复制 STL 模型。

## 3. 安装独立网关环境（首次执行）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\edge\setup_gateway.ps1
```

此步骤需要联网下载依赖。脚本会创建 `.venv-edge`，只安装网关所需的 Python 包，
不修改 LibreOffice 的 Python，不安装 CUDA、模型权重或服务器环境。
Windows 上会将网关密钥文件的 ACL 限制为当前用户。
最后的离线检查只验证依赖、配置、密钥和文件锁，不连接机械臂、不发送运动命令。

若 Python 安装在特殊位置，可显式指定：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\edge\setup_gateway.ps1 -PythonExe "C:\你的Python目录\python.exe"
```

以后单独检查环境：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\edge\start_gateway.ps1 --check
```

看到 `Gateway check OK` 表示本地环境检查通过，尚不代表机械臂或 SSH 已连接。

## 4. 连网线、建立 SSH 隧道、启动网关

机械臂网线及 Windows 网卡使用与原来相同的网络设置，避免与机械臂地址冲突。
先在 PowerShell 验证原 YAML 中的地址可达（本项目当前为 `192.168.0.10`）：

```powershell
Test-NetConnection 192.168.0.10 -Port 10003
Test-NetConnection 192.168.0.10 -Port 10004
```

确认 `TcpTestSucceeded : True`。这些命令仅测试 TCP 建连，不发送机械臂指令。

另开 PowerShell，建立原来已验证可用的 SSH 转发：

```powershell
ssh -N -o ExitOnForwardFailure=yes -L 18000:127.0.0.1:8000 -L 18001:127.0.0.1:8001 你的SSH目标
```

把 `你的SSH目标` 换成实际可登录的 `用户名@服务器地址`，如需非默认端口添加 `-p 实际端口`。
如果你使用原来的 `5090` 别名，必须先在 Windows 的 SSH config 中配置该别名及可用密钥；
新电脑不会自动拥有 Mac 的 SSH 配置。这里不预设公网 IP 或端口映射。

保持隧道窗口开启。在网关目录的另一个 PowerShell 中启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\edge\start_gateway.ps1
```

网关默认连接 `ws://127.0.0.1:18001/v1/gateway/connect`，读取上述配置和密钥。
`mac-huayan-ph590320009` 是已有服务器认可的 gateway ID，名字带 mac 不影响 Windows 使用。
不要同时运行原 Mac 网关和 Windows 网关连接同一台机械臂。
按 `Ctrl+C` 退出网关；SSH 隧道窗口同样用 `Ctrl+C` 关闭。

浏览器访问 `http://127.0.0.1:18000/inside/`，按原流程选择真机模式。
当前 Python 检查、fake controller 测试不替代 Windows 现场连接和真机验收。

## 5. 原来几个 GB 的包能删什么

轻量网关已复制配置、独立环境检查通过，并确认能连接机械臂后，Windows 上原来的
`interns2-dev-bundle.tar.gz`、Linux `runtime`、`archives`、SOFA/CUDA/模型软件目录都不再需要。
可以删除多余副本以释放空间；不要删当前轻量网关目录中的 `configs`、`.venv-edge` 和 `logs`。
只保留压缩包外的旧 `app` 目录时，也必须先备份配置和密钥，避免随父目录一起删掉。

## 6. 从现有仓库重新打包

在有完整源码和本地配置的电脑上运行，不会安装软件或访问机械臂：

```bash
python3 scripts/edge/package_gateway.py --include-local-config
```

输出在 `artifacts/gateway/interns2-edge-gateway-windows.zip`，此目录已被 Git 忽略。
个人包包含网关密钥，只复制给自己的操作电脑。已有输出不会被覆盖；更新时请用
`--output 新文件名.zip` 指定新的文件名，或自行移走旧输出。
