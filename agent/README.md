# InternS2 手术机械臂智能体

当前仓库已移除旧的离散导航代码。InternS2 作为多模态基底模型，通过 LMDeploy 提供的 OpenAI-compatible API 接收文本和可选图片。

目前处于接口和 Mock 阶段：

- 已保留 InternS2 客户端、模型发现和多模态输入；
- 已建立 `surgical_contracts` 共享数据契约；
- 已建立机械臂与路径规划抽象接口；
- 已提供不连接硬件和仿真器的内存 Fake；
- 尚未接入机械臂仿真工具；
- 尚未接入学长的真实穿刺路径规划工具；
- 当前回复不能代表机械臂已经移动或已经完成穿刺。

共享契约是一个独立的可安装包：

```text
packages/surgical_contracts
```

Mock 编排严格保证：定位失败、相对移动或仅移动到入点时不调用路径规划；完整穿刺任务只有在 Fake 机械臂成功到达入点后才会调用 Fake planner，并且 planner 结果始终为 `executable=false`。

## 配置

在仓库根目录执行：

```bash
cp .env.example .env
```

本地或服务器端运行 agent 时可配置：

```dotenv
INTERNS2_BASE_URL=http://127.0.0.1:23333/v1
INTERNS2_API_KEY=EMPTY
INTERNS2_MODEL=/home/xl/interns2-finetune/models/Intern-S2-Preview
```

`.env` 已被根目录 `.gitignore` 忽略，不会随 Git 推送；`.env.example` 会被提交，用于在服务器上复制。

## 安装

安装最小依赖：

```bash
python3 -m pip install -r agent/requirements.txt
```

运行离线测试：

```bash
python3 -m unittest discover -s agent/tests -v
python3 -m unittest discover -s tests -v
```

## 启动 InternS2 服务

在服务器容器中开一个终端启动 LMDeploy（标准 BF16 模型需要约 70GB 权重，示例使用两卡 TP）：

```bash
cd /home/xl/interns2-finetune
export CUDA_VISIBLE_DEVICES=2,3
lmdeploy serve api_server \
  /home/xl/interns2-finetune/models/Intern-S2-Preview \
  --trust-remote-code \
  --backend pytorch \
  --tp 2 \
  --server-port 23333 \
  --reasoning-parser default \
  --tool-call-parser interns2-preview
```

保持服务运行，在容器的第二个终端执行文本调用：

```bash
cd /home/xl/interns2-finetune
python3 -m agent.main \
  --prompt "请确认当前 InternS2 服务已经可以正常响应" \
  --json
```

可选图片输入：

```bash
python3 -m agent.main \
  --image /path/to/image.jpg \
  --prompt "请描述这张图片" \
  --json
```

`--json` 输出回答和实际模型 ID；去掉时只输出回答。
