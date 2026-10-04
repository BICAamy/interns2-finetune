"""Small typed vocabulary for the V6 read-only protocol subset."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProtocolError(ValueError):
    """A received frame is malformed or disagrees with the pending request."""


class ResponseUnknown(RuntimeError):
    """A request may have reached the controller, but its reply was lost.

    Callers must never infer success or automatically replay a request.
    """

# 把huayan厂商那边的字符串整理为项目内统一的Enum
class ReadCommand(str, Enum):
    IS_SIMULATION = "IsSimulation" # 当前控制器是不是仿真模式
    CONTROLLER_STATE = "ReadControllerState" # 控制器是否启动/工作
    ROBOT_MODEL = "ReadRobotModel" # 机器人型号
    PACKAGE_VERSION = "PackageVersion" # 控制器软件/API Package 版本
    FAST_COMMAND_PORT = "ReadFastCmdPort" # 查询厂家快速命令端口
    ROBOT_STATE = "ReadRobotState" # 一次读取一大组机器人状态
    CURRENT_FSM = "ReadCurFSM" # 当前 FSM 状态码
    ACTUAL_POSITION = "ReadActPos" # 实际关节与笛卡尔位置等
    EMERGENCY_INFO = "ReadEmergencyInfo" #
    CURRENT_WAYPOINT_ID = "ReadCurWayPointID" # 当前 WayPoint ID
    OVERRIDE = "ReadOverride"
    AXIS_ERROR_CODE = "ReadAxisErrorCode" # 总组错误 + 六个轴错误
    PAYLOAD = "ReadPayload" # 当前负载质量和质心
    JOINT_MAX_VELOCITY = "ReadJointMaxVel" # 六轴最大角速度配置
    JOINT_MAX_ACCELERATION = "ReadJointMaxAcc" # 六轴最大角加速度配置
    LINEAR_MAX_MOTION = "ReadLinearMaxVel" # 线性最大速度
    BASE_INSTALLING_ANGLE = "GetBaseInstallingAngle" # 机器人底座安装角
    CURRENT_TCP = "ReadCurTCP" # 当前选中的 TCP 参数
    CURRENT_UCS = "ReadCurUCS" # 当前选中的 UCS 参数
    TCP_BY_NAME = "ReadTCPByName" # 按名称读取某个 TCP
    UCS_BY_NAME = "ReadUCSByName" # 按名称读取某个 UCS


ROBOT_ID_COMMANDS = frozenset({
    ReadCommand.ROBOT_STATE,
    ReadCommand.CURRENT_FSM,
    ReadCommand.ACTUAL_POSITION,
    ReadCommand.EMERGENCY_INFO,
    ReadCommand.CURRENT_WAYPOINT_ID,
    ReadCommand.OVERRIDE,
    ReadCommand.AXIS_ERROR_CODE,
    ReadCommand.PAYLOAD,
    ReadCommand.JOINT_MAX_VELOCITY,
    ReadCommand.JOINT_MAX_ACCELERATION,
    ReadCommand.LINEAR_MAX_MOTION,
    ReadCommand.BASE_INSTALLING_ANGLE,
    ReadCommand.CURRENT_TCP,
    ReadCommand.CURRENT_UCS,
    ReadCommand.TCP_BY_NAME,
    ReadCommand.UCS_BY_NAME,
})

NAMED_READ_COMMANDS = frozenset({ReadCommand.TCP_BY_NAME, ReadCommand.UCS_BY_NAME})

# Each command here is explicitly marked as fast-port capable in V6 1.0.19.1.
FAST_PORT_COMMANDS = frozenset({
    ReadCommand.IS_SIMULATION,
    ReadCommand.CONTROLLER_STATE,
    ReadCommand.ROBOT_MODEL,
    ReadCommand.PACKAGE_VERSION,
    ReadCommand.ROBOT_STATE,
    ReadCommand.CURRENT_FSM,
    ReadCommand.ACTUAL_POSITION,
    ReadCommand.CURRENT_WAYPOINT_ID,
    ReadCommand.OVERRIDE,
    ReadCommand.AXIS_ERROR_CODE,
    ReadCommand.PAYLOAD,
    ReadCommand.JOINT_MAX_VELOCITY,
    ReadCommand.JOINT_MAX_ACCELERATION,
    ReadCommand.LINEAR_MAX_MOTION,
    ReadCommand.CURRENT_TCP,
    ReadCommand.CURRENT_UCS,
    ReadCommand.TCP_BY_NAME,
    ReadCommand.UCS_BY_NAME,
})
# 对应命令正常返回时，我期望后面有几个数据字段，比如：ReadCurFSM,OK,33,; 就只有1个返回值
REPLY_FIELD_COUNTS = {
    ReadCommand.IS_SIMULATION: 1,
    ReadCommand.CONTROLLER_STATE: 1,
    ReadCommand.ROBOT_MODEL: 1,
    ReadCommand.PACKAGE_VERSION: 1,
    ReadCommand.FAST_COMMAND_PORT: 1,
    ReadCommand.ROBOT_STATE: 13,
    ReadCommand.CURRENT_FSM: 1,
    ReadCommand.ACTUAL_POSITION: 24,
    ReadCommand.EMERGENCY_INFO: 4,
    ReadCommand.CURRENT_WAYPOINT_ID: 1,
    ReadCommand.OVERRIDE: 1,
    ReadCommand.AXIS_ERROR_CODE: 7,
    ReadCommand.PAYLOAD: 4,
    ReadCommand.JOINT_MAX_VELOCITY: 6,
    ReadCommand.JOINT_MAX_ACCELERATION: 6,
    # The V6 PDF's success-line labels are erroneous; its return table,
    # example and vendor CPS.py all describe three linear values.
    ReadCommand.LINEAR_MAX_MOTION: 3,
    ReadCommand.BASE_INSTALLING_ANGLE: 2,
    ReadCommand.CURRENT_TCP: 6,
    ReadCommand.CURRENT_UCS: 6,
    ReadCommand.TCP_BY_NAME: 6,
    ReadCommand.UCS_BY_NAME: 6,
}

# 解析10003控制器那边返回的命令成醒目中的python格式对象 （一问一答）
@dataclass(frozen=True)
class CommandReply:
    command: ReadCommand
    values: tuple[str, ...] = ()
    vendor_error_code: int | None = None
    vendor_error_message: str | None = None
    protocol_deviation: bool = False

    @property
    def ok(self) -> bool:
        return self.vendor_error_code is None

# 10004 持续推过来的实时状态数据解析之后的 Python 对象格式。（持续推流）
@dataclass(frozen=True)
class DatasheetSample:
    source_timestamp_ms: int # 控制器则时间戳
    received_wall_ms: int # Mac 收到这帧时的系统时间
    received_monotonic_ns: int # Mac 收到这帧时的单调时钟
    joint_positions_deg: tuple[float, ...] # J1～J6 实际关节角，单位 °
    current_pose: tuple[float, ...] # 随关节值一起给出的 6D 实际位姿（六元组：x, y, z, rx, ry, rz）
    base_pose: tuple[float, ...] # 当前实际位姿，以 Base 坐标系表达
    tcp_pose: tuple[float, ...] # 当前实际位姿，以 TCP 相关坐标表达
    joint_velocities_deg_s: tuple[float, ...] # J1～J6 当前角速度，°/s
    joint_accelerations_deg_s2: tuple[float, ...] # J1～J6 当前角加速度，°/s²
    override: float # 当前速度倍率
    fsm_code: int # 厂商 FSM 状态码
    enabled: bool # 机器人是否使能
    moving: bool # 是否正在运动
    paused: bool # 是否暂停
    blending_done: bool #
    in_position: bool # 是否到位
    error_code: int # 当前机器人错误码
    error_axis: int # 错误对应轴号
    auto_mode: bool # 是否自动模式（自动模式：让机器人按照程序、外部控制命令自动运行）
    reduced_mode: bool # 是否缩减模式（缩减模式：）
    free_drive_mode: bool # 是否自由拖拽模式
    axis_error_codes: tuple[int, ...] # 六个轴各自错误码
    force_control_state: int # 力控状态
    device_sn: str | None # 机械臂设备序列号
