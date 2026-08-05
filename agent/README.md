# InternS2 + NavGPT 智能体

当前框架把两个模型职责拆开：

1. **InternS2** 是面向用户的多模态基底模型。它读取图片和用户指令，并通过原生 function calling 决定是否调用导航工具。
2. **NavGPTTool** 接收 InternS2 从图片中提取的、受图像约束的观察文本，再调用 DeepSeek-compatible Chat Completions API，返回结构化导航决策。
3. 工具结果以 `tool` 消息回传 InternS2，由 InternS2 生成最终自然语言回复。

原 NavGPT 的 R2R 评测代码仍保留在 `tools/NavGPT/nav_src`。它需要预生成的八方向场景描述、候选 viewpoint、导航图和 R2R 标注，不能直接把一张普通图片当成完整的可交互环境。因此新增的 `NavGPTTool` 支持两种输入：有真实候选 viewpoint 时选择严格匹配的 ID；只有单张图片时只返回相对方向和保守动作，不伪造 ID。

## 配置

在仓库根目录执行：

```bash
cp .env.example .env
```

然后填写 `.env` 中以下三项：

```dotenv
DEEPSEEK_BASE_URL=你的OpenAI兼容URL
DEEPSEEK_API_KEY=你的测试API Key
DEEPSEEK_MODEL=该URL实际暴露的模型名
```

`.env` 已被根目录 `.gitignore` 忽略，不会随 Git 推送；`.env.example` 会被提交，用于在服务器上复制。

## 安装与分层测试

安装新智能体的最小依赖：

```bash
python3 -m pip install -r agent/requirements.txt
```

先只测试 DeepSeek 与 NavGPT，不需要 GPU，也不加载 InternS2：

```bash
python3 -m agent.tools.NavGPT.nav_src.nav_tool_cli \
  --instruction "从当前位置走向前方出口" \
  --observation "前方是一扇打开的门，左侧有桌子，地面没有明显障碍" \
  --candidates-json '[]'
```

若要运行原始 R2R 数据集评测，再安装旧评测栈：

```bash
python3 -m pip install -r agent/tools/NavGPT/requirements.txt
cd agent/tools/NavGPT/nav_src
python3 NavGPT.py \
  --llm_provider deepseek \
  --llm_model_name "$DEEPSEEK_MODEL" \
  --llm_base_url "$DEEPSEEK_BASE_URL" \
  --output_dir ../datasets/R2R/exprs/deepseek-test \
  --val_env_name R2R_val_unseen_instr \
  --iters 10
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

保持服务运行，在容器的第二个终端执行端到端调用：

```bash
cd /home/xl/interns2-finetune
python3 -m agent.main \
  --image /path/to/navigation.jpg \
  --prompt "根据图片判断我下一步应该往哪里走，并给出安全的导航建议" \
  --json
```

`--json` 会同时输出工具调用参数和 NavGPT 结果，便于联调；去掉它时只输出最终回答。
