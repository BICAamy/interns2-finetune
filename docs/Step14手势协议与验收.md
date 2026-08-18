# Step 14 手势协议与验收

> 状态：实现分支施工中，未完成真实 InternS2 / 浏览器验收。  
> 分支：`agent/step14-gesture-vlm`  
> 基线：`c3a2ee0c82082388c53deaeb7dc8fbe249649130`

## 1. 固定手势协议

手势语义一律采用**操作者自身视角**，不是网页镜像预览的左右方向。

| 手势 | 固定定义 |
|---|---|
| `up` | 食指向上 |
| `down` | 食指向下 |
| `left` | 食指指向操作者自己的左侧 |
| `right` | 食指指向操作者自己的右侧 |
| `forward` | 食指直接指向摄像头 |
| `backward` | 大拇指指向操作者自己的胸口 |
| `stop` | 拇指和食指组成清晰圆圈；本系统固定解释为停止 |
| `estop` | 五指张开且掌心正对摄像头 |

InternS2 还允许输出 `none`（没有检测到协议手势）和 `uncertain`（有手但无法明确分类），这两种结果永远不产生控制命令。

## 2. 识别与控制边界

第一版不使用 MediaPipe。浏览器只负责：

1. `getUserMedia` 获取本地摄像头；
2. 页面用 CSS 镜像预览，方便操作者观察；
3. 截取**未镜像**的原始 JPEG 帧；
4. 低频提交给 `agent-web`。

`agent-web` 将帧交给现有 InternS2 多模态服务。InternS2 只能输出固定手势枚举、置信度和 `hand_detected`，不得输出机械臂坐标、关节角或控制量。

方向手势由确定性代码映射到当前仿真的 `robot_base`：

```text
up        -> +Z
 down      -> -Z
left      -> -X
right     -> +X
forward   -> +Y
backward  -> -Y
```

当前映射基于 Step 12 正视相机定义：相机位于 `robot_base -Y` 一侧朝 `+Y` 观看，画面右侧对应 `+X`，世界上方对应 `+Z`。

普通方向使用 `DEFAULT_RELATIVE_STEP_MM`，当前默认 `5 mm`，并继续遵守网页“人工确认后执行”的安全策略。

`stop` / `estop` 不等待人工确认：

```text
stop  -> WebRuntime.stop(emergency=False)
estop -> WebRuntime.stop(emergency=True)
```

## 3. 多输入仲裁

服务端最终优先级固定为：

```text
estop > stop > voice > gesture
```

普通手势默认要求：

- InternS2 置信度 `>= 0.85`；
- 连续 `2` 次采样分类一致；
- 通过后等待 `1.5 s` 语音冲突窗口；
- 同一手势触发后锁存，持续保持不能重复触发；
- 必须出现 `none/uncertain`（松手或离开画面）后才能再次触发；
- 冷却时间默认 `1.0 s`。

`stop/estop` 为安全通道：单次高置信度分类即可触发，默认安全阈值 `0.80`，但同样使用锁存避免持续手势重复发送停止请求。

当前 Step 13 尚未实现真正的流式 VAD，因此“语音活动”由浏览器已有录音状态以及“正在转写并解析”状态共同表示。录音或 ASR/解析阶段都压制普通手势。

## 4. 配置

`.env` 可覆盖：

```dotenv
GESTURE_MIN_CONFIDENCE=0.85
GESTURE_SAFETY_MIN_CONFIDENCE=0.80
GESTURE_STABLE_FRAMES=2
GESTURE_COOLDOWN_SECONDS=1.0
GESTURE_VOICE_CONFLICT_WINDOW_SECONDS=1.5
```

## 5. API

```text
POST /api/sessions/{session_id}/commands/gesture
PUT  /api/sessions/{session_id}/gesture/voice-activity
POST /api/sessions/{session_id}/gesture/reset
```

浏览器只能上传感知数据。最终分类、稳定性检查、优先级、锁存、冷却和命令映射均在 `agent-web` 服务端完成。

## 6. 自动化测试

后端源代码拉取后运行：

```bash
python3 -m pytest tests/unit/web/test_gesture.py -q
python3 -m pytest tests/unit/core/test_command_arbiter.py -q
python3 -m pytest tests/integration/test_agent_web.py -q
```

其中 `test_gesture.py` 至少检查：

- 六个方向到 `robot_base` 的确定性映射；
- 普通手势必须等待确认；
- 连续稳定帧；
- 语音压制普通手势；
- `estop` 抢占语音；
- 低置信度不触发；
- 持续 `estop` 只触发一次，松手后才能再次触发。

## 7. 真实 InternS2 图片冒烟

`agent-web`、InternS2、robot-simulation 已启动后，可先用静态手势照片验证模型链路，避免同时排查浏览器摄像头：

```bash
python3 -m web.backend.scripts.check_step14_gesture \
  --image /tmp/up.jpg \
  --expected up
```

普通方向脚本会自动提交两次，以满足默认稳定帧要求。

停止手势：

```bash
python3 -m web.backend.scripts.check_step14_gesture \
  --image /tmp/stop.jpg \
  --expected stop
```

急停手势：

```bash
python3 -m web.backend.scripts.check_step14_gesture \
  --image /tmp/estop.jpg \
  --expected estop
```

成功必须打印：

```text
STEP14_GESTURE_SMOKE_OK
```

## 8. 前端构建是服务器验收前置条件

实验室离线 `agent-web` 镜像复制仓库中的 `web/frontend/dist`。修改 `src` 后必须在有 Node 环境的开发机先重建：

```bash
cd web/frontend
npm ci
npm run build
cd ../..
git status --short web/frontend/dist
```

确认新 `dist` 与 Step 14 源码对应后再提交。否则服务器即使拉到了新后端，也仍会显示旧的 Step 13 页面。

## 9. 浏览器人工验收

至少逐项验证：

1. `up` 连续保持后只形成一个 `+Z 5 mm` 待确认任务；
2. 持续保持 `up` 不会连续触发；
3. 松手/移出画面后重新做 `up` 可以再次触发；
4. 语音“向下”与 `up` 手势冲突时只接受语音；
5. 普通语音/普通运动期间做 `estop`，急停仍可抢占；
6. 圆圈手势触发 `stop`；
7. 张开手掌、掌心正对摄像头触发 `estop`；
8. 摄像头断开或权限拒绝不产生随机命令，文本/语音仍可使用；
9. 页面切到后台后不积压手势，回来时不补执行旧命令；
10. 左/右按操作者自身视角识别，不受页面镜像预览影响。

## 10. Step 14 完成条件

只有自动化测试、静态图片真实 InternS2 冒烟和浏览器人工验收全部通过，才能在施工文档中将 Step 14 标记为完成。
