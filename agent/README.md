# InternS2 手术机械臂智能体

当前仓库已移除旧的离散导航代码。InternS2 作为多模态基底模型，通过 LMDeploy 提供的 OpenAI-compatible API 接收文本和可选图片。

目前处于架构迁移阶段：

- 已保留 InternS2 客户端、模型发现和多模态输入；
- 尚未接入机械臂仿真工具；
- 尚未接入穿刺路径规划适配器；
- 当前回复不能代表机械臂已经移动或已经完成穿刺。

后续将按 `docs/手术导航技术实现流程文档.md` 增加结构化任务契约、机械臂定位工具和路径规划 Mock。

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

## 启动 InternS2 服务

在服务器容器中开一个终端启动 LMDeploy（标准 BF16 模型需要约 70GB 权重，示例使用两卡 TP）：

```bash
cd /home/xl/interns2-finetune
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
