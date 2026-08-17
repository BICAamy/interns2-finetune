# InternS2 手术机械臂智能体

当前完成到 Step 8：InternS2 通过 LMDeploy 的 OpenAI-compatible API，将文本和
可选图片解析成统一 `ParsedCommand`；确定性状态机再决定是否调用机械臂与路径规划。
Step 8 仅提供内存 Mock 工具验收入口，尚未连接 Step 6 的仿真 HTTP 服务，更不会
连接真实机械臂或执行穿刺。

## Step 7 解析边界

InternS2 只看到一个高层函数：

```text
submit_surgical_task
```

函数参数包括任务意图、入点、靶点、相对移动、缺失字段、置信度和摘要。模型不会
获得 `robot-simulation`、planner 地址或任何底层控制函数。

模型返回的参数还要经过确定性代码处理：

- 运行时重新生成 `command_id`，忽略模型生成的 ID；
- JSON 解码后再用 Pydantic `ParsedCommand` 二次校验；
- 兼容 LMDeploy 0.14 XML tool parser 将对象、数组、布尔值或 `null` 二次编码为
  JSON 字符串的响应，但不接受 Python 字面量或任意文本；
- 模型侧使用 LMDeploy XML parser 稳定支持的扁平 `relative_*` 参数，运行时再组装
  为统一 `ParsedCommand.relative_motion`；同时受限兼容已观察到的旧嵌套/提升格式；
- 明确要求穿刺但缺靶点时，即使模型误判为 `move_to_entry`，运行时也会强制降级为
  `clarify`；类型错误、未知字段和内外冲突仍会被拒绝；
- 对外距离统一为 `mm`；仿真模式缺失坐标系时使用 `robot_base`；
- “往上抬一点”规范化为 `robot_base +Z 5 mm`，5 mm 来自配置；
- 完整穿刺缺入点或靶点、三维坐标不完整、坐标顺序含糊时降级为 `clarify`；
- 其他坐标系在尚无确定性变换时只能澄清，不能直接运动；
- 无 tool call、多个/未知 tool call、非法 JSON、超时和服务不可用都有稳定错误码；
- 图片是可选输入，二维像素不能直接成为三维机械臂坐标。

`clarify`、非法输出和模型调用错误都不会触发任何工具。InternS2 只能生成上述高层
任务，不能选择或重排底层工具。

## Step 8 编排边界

状态机固定执行以下顺序：

```text
IDLE → PARSING → VALIDATING
  ├→ CLARIFICATION_REQUIRED
  ├→ EXECUTING_RELATIVE → COMPLETED
  └→ MOVING_TO_ENTRY → AT_ENTRY
       ├→ COMPLETED
       └→ PATH_PLANNING → PLAN_READY / PLAN_FAILED / PLANNER_UNAVAILABLE
```

关键安全规则：

- 普通运动前读取机械臂状态，急停、模式不匹配或已有运动时拒绝执行；
- 相对运动只能调用 `robot.move_relative`，且受单次位移和速度上限约束；
- 到达入点后重新调用 `robot.get_state`，按最终 TCP 独立计算误差，不能只相信
  `move_to_entry` 返回的 `reached=true`；
- 完整任务只有在到点复核通过后才能调用 planner；定位失败、误差超限、停止和急停
  都会阻断 planner；
- planner 返回的数据被固定为 `executable=false`，`PLAN_READY` 只表示规划结果就绪，
  不表示穿刺完成；
- 同一进程内缓存已完成普通任务的 `command_id`，重复请求直接返回原结果，不产生
  第二次运动；停止/急停始终允许重复下发；
- 同一时刻只允许一条普通命令，停止和急停可以中断活动命令；
- 每次状态变化和工具调用都有结构化事件记录。

## 配置

在仓库根目录复制配置示例：

```bash
cp .env.example .env
```

Step 7/8 使用的主要配置：

```dotenv
INTERNS2_BASE_URL=http://127.0.0.1:23333/v1
INTERNS2_API_KEY=EMPTY
INTERNS2_MODEL=/home/xl/interns2-finetune/models/Intern-S2-Preview
INTERNS2_TIMEOUT=300
INTERNS2_MAX_RETRIES=2
INTERNS2_MAX_TOKENS=2048
INTERNS2_TEMPERATURE=0
INTERNS2_TOP_P=0.95

RUNTIME_MODE=simulation
DEFAULT_COORDINATE_FRAME=robot_base
DEFAULT_DISTANCE_UNIT=mm
DEFAULT_RELATIVE_STEP_MM=5
ENTRY_TOLERANCE_MM=1
MAX_TRANSLATION_PER_COMMAND_MM=20
ROBOT_MOVE_SPEED_MM_S=5
MAX_ROBOT_SPEED_MM_S=10
```

`RUNTIME_MODE=simulation` 时，用户缺失单位/坐标系可以采用页面以后会明确展示的
默认值。`RUNTIME_MODE=real` 时，缺失单位或坐标系必须返回澄清。当前项目仍禁止
连接真实机械臂。

## 安装与离线单元测试

`surgical_contracts` 由 requirements 以 editable 方式安装：

```bash
python3 -m pip install -r agent/requirements.txt
python3 -m pytest agent/tests tests/unit -q
```

伪造 OpenAI 响应和 Mock 工具测试不需要 GPU 或正在运行的 InternS2，覆盖 tool
schema、可选图片、默认值、可信 ID、缺字段澄清，以及 Step 8 的工具顺序、到点
复核、幂等、并发拒绝、停止和急停。

## 启动 InternS2

在服务器的 LMDeploy 容器中使用两张指定 GPU：

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

必须保留 `--tool-call-parser interns2-preview`，否则 OpenAI 响应中可能没有可读取的
`message.tool_calls`。

## 真实解析冒烟测试

保持 LMDeploy 运行，在容器的另一个终端执行。完整坐标任务：

```bash
cd /home/xl/interns2-finetune

python3 -m agent.main \
  --prompt '入点为基座坐标系下(20,35,80)毫米，靶点为(24,38,120)毫米，请准备穿刺' \
  --parse-only \
  --json
```

期望 `parsed_command.intent` 为 `puncture`，并包含两组三维坐标。

相对移动：

```bash
python3 -m agent.main \
  --prompt '机械臂往上抬一点' \
  --parse-only \
  --json
```

期望结果包含：

```json
{
  "intent": "move_relative",
  "relative_motion": {
    "axis": "z",
    "direction": "positive",
    "distance_mm": 5.0,
    "frame": "robot_base",
    "distance_source": "configured_default"
  }
}
```

可选图片：

```bash
python3 -m agent.main \
  --image /path/to/image.jpg \
  --prompt '请结合图片判断任务；如果没有经过标定的三维入点，请要求我补充' \
  --parse-only \
  --json
```

## 固定语料评测

固定测试集位于 `agent/evals/step7_cases.json`，涵盖明确/缺失坐标、相对移动、
默认值、含糊顺序、多组坐标、否定、停止、急停和无关问题。

先运行两个核心用例：

```bash
python3 -m agent.evals.run_step7_eval \
  --case puncture_explicit \
  --case relative_vague
```

再运行全部用例：

```bash
python3 -m agent.evals.run_step7_eval
```

全部通过时输出 `"status": "ok"`、`"passed": 13`、`"total": 13`。评测失败
只表示解析结果不符合固定预期，不会调用机械臂或 planner。

## Step 8 Mock 编排冒烟测试

先启动 InternS2，然后用显式的 `--mock-execute` 将解析结果交给内存 Fake 工具：

```bash
python3 -m agent.main \
  --prompt '入点为基座坐标系下(20,35,80)毫米，靶点为(24,38,120)毫米，请准备穿刺' \
  --mock-execute \
  --json
```

期望 `orchestration.final_state` 为 `plan_ready`，工具事件顺序为读取状态、移动到
入点、再次读取状态、调用路径规划，且消息明确包含“未执行穿刺”。这里的机械臂和
planner 都是进程内 Fake；Step 10 才会把相同编排器连接到真实的仿真服务适配器。

相对移动：

```bash
python3 -m agent.main \
  --prompt '机械臂沿基座坐标系 Z 轴正方向移动 8 毫米' \
  --mock-execute \
  --json
```

期望终态为 `completed`，只出现 `robot.get_state` 和 `robot.move_relative`，planner
调用次数为零。
