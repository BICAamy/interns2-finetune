"""Step 10 offline trials: writes are possible only to a loopback fake."""

from __future__ import annotations

from dataclasses import replace
import socket
import threading
import time

import pytest

from edge_gateway.command_journal import CommandJournal, JournalError
from edge_gateway.fake_motion import FakeMotionTiming, FakeMotionTrial
from edge_gateway.huayan.fake_motion_client import FakeMotionClient
from edge_gateway.huayan.real_motion_client import LocalRealMotionClient
from edge_gateway.huayan.datasheet_client import DatasheetClient
from edge_gateway.huayan.motion_codec import LinearWaypoint, encode_software_stop
from edge_gateway.preflight import (
    FakeControllerReadback, FakeExternalWriterGuard, FakeMotionApproval, LocalArm, MotionLease,
    fingerprint, safety_state_hash,
)
from surgical_contracts import (
    CoordinateFrame, DistanceUnit, GatewayCommandKind, LinkState,
    MotionSafetyLimits, MoveRelativeRequest, Pose6D, RobotCommandEnvelope,
    RobotConnectionState, RobotProvider, RobotTelemetry, RuntimeMode,
    SourceFreshness,
)
from tests.fakes.huayan_controller import (
    CommandAction, FakeHuayanController, datasheet_document, datasheet_frame,
)
from edge_gateway.huayan.models import ReadCommand, ResponseUnknown

SESSION = "a" * 32
BASE_NS = 10_000_000_000
BASE_MS = 1_000_000


def pose(x: float = 100.0) -> Pose6D:
    return Pose6D(
        translation_mm=(x, 100.0, 100.0), rotation_rpy_deg=(0.0, 0.0, 0.0),
        quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        frame=CoordinateFrame.ROBOT_BASE, unit=DistanceUnit.MILLIMETER,
    )


def telemetry(*, sequence: int = 10, x: float = 100.0,
              moving: bool = False, fsm: int = 33,
              in_position: bool = True) -> RobotTelemetry:
    return RobotTelemetry(
        runtime_mode=RuntimeMode.REAL, provider=RobotProvider.HUAYAN_EDGE_GATEWAY,
        control_mode="enabled", sequence=sequence, freshness=SourceFreshness.FRESH,
        connections=RobotConnectionState(
            gateway=LinkState.CONNECTED, datasheet=LinkState.CONNECTED,
            command_socket=LinkState.CONNECTED, controller_box=LinkState.CONNECTED,
        ),
        state_age_ms=10, gateway_session_id=SESSION, device_sn="FAKE-SN",
        robot_model="FAKE-E05", package_version="fake-v1",
        joint_positions_deg=(0, 0, 90, 0, 90, 0),
        actual_pose_robot_base=pose(x), controller_is_simulation=False,
        enabled=True, electrified=True, brakes_released=True, auto_mode=True,
        reduced_mode=True, three_position_enable=True,
        physical_estop_active=False, emergency_stop_circuit_fault=False,
        safeguard_active=False, safeguard_circuit_fault=False,
        free_drive_active=False, force_control_active=False, paused=False,
        potentially_moving=False, moving=moving, in_position=in_position,
        fsm_code=fsm,
    )


def approval() -> FakeMotionApproval:
    return FakeMotionApproval(
        device_sn="FAKE-SN", robot_model="FAKE-E05", package_version="fake-v1",
        config_sha256="f" * 64, tcp_name="FAKE_FLANGE", ucs_name="Base",
        tcp_xyzrpy=(0, 0, 0, 0, 0, 0), ucs_xyzrpy=(0, 0, 0, 0, 0, 0),
        payload_kg=0, center_of_gravity_mm=(0, 0, 0),
        base_installing_angle_deg=(0, 0),
        joint_soft_limits_deg=((-170, 170),) * 6, joint_margin_deg=5,
        workspace_low_mm=(0, 0, 0), workspace_high_mm=(500, 500, 500),
        max_speed_mm_s=5, max_acceleration_mm_s2=10, max_step_mm=2,
        max_start_drift_mm=0.25, max_start_rotation_deg=0.5,
        state_stale_ms=250, ready_fsm_code=33,
    )


def readback() -> FakeControllerReadback:
    return FakeControllerReadback(
        config_sha256="f" * 64,
        tcp_name="FAKE_FLANGE", ucs_name="Base",
        tcp_xyzrpy=(0, 0, 0, 0, 0, 0), ucs_xyzrpy=(0, 0, 0, 0, 0, 0),
        payload_kg=0, center_of_gravity_mm=(0, 0, 0),
        base_installing_angle_deg=(0, 0), group_error_code=0,
        axis_error_codes=(0, 0, 0, 0, 0, 0), active_program=False,
        waypoint_id="FAKE_ONLY",
    )


def envelope(command_id: str = "move-1", *, translation=(1.0, 0.0, 0.0)) -> RobotCommandEnvelope:
    return RobotCommandEnvelope(
        gateway_session_id=SESSION, command_id=command_id,
        command_kind=GatewayCommandKind.MOVE_RELATIVE,
        created_at_ms=BASE_MS - 100, expires_at_ms=BASE_MS + 1000,
        based_on_robot_state_sequence=10,
        expected_start_pose_robot_base=pose(), expected_tcp_name="FAKE_FLANGE",
        expected_ucs_name="Base",
        payload=MoveRelativeRequest(
            command_id=command_id, translation_mm=translation,
            frame=CoordinateFrame.ROBOT_BASE, speed_mm_s=2,
        ),
        safety_limits=MotionSafetyLimits(max_speed_mm_s=5, max_step_mm=2),
        operator_confirmation_id="local-test-1",
    )


def arm(command: RobotCommandEnvelope, sample: RobotTelemetry | None = None) -> LocalArm:
    sample = sample or telemetry()
    return LocalArm(
        test_id="local-test-1", command_fingerprint=fingerprint(command),
        session_id=SESSION, base_sequence=10,
        safety_state_hash=safety_state_hash(sample, readback()),
        expected_start=pose(), expires_monotonic_ns=BASE_NS + 1_000_000_000,
    )


def lease() -> tuple[MotionLease, ...]:
    return (MotionLease("local", SESSION, BASE_NS + 1_000_000_000),)


def timing() -> FakeMotionTiming:
    return FakeMotionTiming(
        response_ms=100, start_ms=150, motion_ms=1000,
        stop_confirmation_ms=200, stable_samples=2, dwell_ms=20,
        position_tolerance_mm=0.1, orientation_tolerance_deg=0.2,
    )


def ik(_point):
    return (0, 0, 90, 0, 90, 0)


def make_trial(fake: FakeHuayanController, tmp_path):
    client = FakeMotionClient("127.0.0.1", fake.command_port, timeout_s=0.1)
    client.connect()
    journal = CommandJournal(tmp_path / "fake-motion.journal")
    trial = FakeMotionTrial(client=client, journal=journal, timing=timing(),
                            approval=approval(), path_ik=ik)
    return client, journal, trial


def assert_no_motion_write(fake: FakeHuayanController) -> None:
    assert not any(frame.startswith((b"WayPoint,", b"GrpStop,"))
                   for frame in fake.received_commands)


def test_fake_motion_client_refuses_private_controller_host() -> None:
    with pytest.raises(ValueError, match="loopback-only"):
        FakeMotionClient("192.168.0.10", 10003)


def test_real_writer_uses_same_guarded_trial_against_loopback_fake(monkeypatch, tmp_path) -> None:
    from edge_gateway import commissioning_cli
    from tests.unit.edge_gateway.test_real_motion_client import real_shaped_config

    with FakeHuayanController(accept_fake_motion=True) as fake:
        original_connect = socket.create_connection

        def fake_private_connect(address, timeout=None):
            assert address == ("192.168.0.10", 10003)
            return original_connect(("127.0.0.1", fake.command_port), timeout)

        monkeypatch.setattr(socket, "create_connection", fake_private_connect)
        monkeypatch.setattr(commissioning_cli, "require_local_mac_terminal", lambda: None)
        with LocalRealMotionClient(real_shaped_config(), timeout_s=0.1) as client:
            with CommandJournal(tmp_path / "local-real-fake.journal") as journal:
                allowed = replace(
                    approval(), robot_model="E05-Pro", package_version="6.3.6.20240305",
                    tcp_name="TCP",
                )
                actual = telemetry().model_copy(update={
                    "robot_model": "E05-Pro", "package_version": "6.3.6.20240305",
                })
                setup = replace(readback(), tcp_name="TCP")
                command = envelope().model_copy(update={"expected_tcp_name": "TCP"})
                local_arm = LocalArm(
                    test_id="local-test-1", command_fingerprint=fingerprint(command),
                    session_id=SESSION, base_sequence=actual.sequence,
                    safety_state_hash=safety_state_hash(actual, setup),
                    expected_start=pose(), expires_monotonic_ns=BASE_NS + 1_000_000_000,
                )
                trial = FakeMotionTrial(
                    client=client, journal=journal, timing=timing(),
                    approval=allowed, path_ik=ik,
                )
                assert trial.submit(
                    command, actual, setup, local_arm, lease(),
                    now_ms=BASE_MS, now_monotonic_ns=BASE_NS,
                ) == "accepted"
                assert trial.observe(
                    actual.model_copy(update={"sequence": 11, "moving": True, "fsm_code": 25,
                                              "in_position": False}),
                    now_monotonic_ns=BASE_NS + 10_000_000,
                ) == "executing"
                assert trial.observe(
                    actual.model_copy(update={"sequence": 12, "actual_pose_robot_base": pose(101)}),
                    now_monotonic_ns=BASE_NS + 20_000_000,
                ) == "executing"
                assert trial.observe(
                    actual.model_copy(update={"sequence": 13, "actual_pose_robot_base": pose(101)}),
                    now_monotonic_ns=BASE_NS + 45_000_000,
                ) == "succeeded"
                assert journal.unresolved() == ()
        assert len([frame for frame in fake.received_commands if frame.startswith(b"WayPoint,")]) == 1


def test_motion_client_requires_fake_only_identity_before_any_write() -> None:
    with FakeHuayanController() as fake:
        client = FakeMotionClient("127.0.0.1", fake.command_port)
        with pytest.raises(ValueError, match="did not prove"):
            client.connect()
        assert_no_motion_write(fake)


def test_waypoint_frame_is_move_l_without_blend_seek_or_joint_target() -> None:
    frame = LinearWaypoint((1, 2, 3, 4, 5, 6), "FAKE_FLANGE", "Base", 2, 10,
                           "F123", (11, 12, 13, 14, 15, 16)).encode()
    fields = frame[:-2].decode().split(",")
    assert fields[:2] == ["WayPoint", "0"]
    assert fields[8:14] == ["11", "12", "13", "14", "15", "16"]
    assert fields[18:24] == ["0", "1", "0", "0", "0", "0"]
    assert fields[24] == "F123"
    assert encode_software_stop() == b"GrpStop,0,;"


def test_ok_is_only_accepted_then_feedback_confirms_success(tmp_path) -> None:
    with FakeHuayanController(accept_fake_motion=True) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            assert trial.submit(command, telemetry(), readback(), arm(command), lease(),
                                now_ms=BASE_MS, now_monotonic_ns=BASE_NS) == "accepted"
            assert trial.potentially_moving
            assert journal.record("move-1")["state"] == "accepted"
            assert trial.observe(telemetry(sequence=11, moving=True, fsm=25, in_position=False),
                                 now_monotonic_ns=BASE_NS + 10_000_000) == "executing"
            assert trial.observe(telemetry(sequence=12, x=101),
                                 now_monotonic_ns=BASE_NS + 20_000_000) == "executing"
            assert trial.observe(telemetry(sequence=13, x=101),
                                 now_monotonic_ns=BASE_NS + 45_000_000) == "succeeded"
            assert not trial.potentially_moving
            assert len([x for x in fake.received_commands if x.startswith(b"WayPoint,")]) == 1
            journal.close()
            with CommandJournal(tmp_path / "fake-motion.journal") as recovered:
                assert recovered.unresolved() == ()
        finally:
            client.close()


def test_waypoint_fail_is_not_proof_of_no_motion_and_requests_stop(tmp_path) -> None:
    with FakeHuayanController(
        accept_fake_motion=True,
        motion_actions={"WayPoint": [CommandAction((b"WayPoint,Fail,20006,rejected,;",))]},
    ) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            assert trial.submit(command, telemetry(), readback(), arm(command), lease(),
                                now_ms=BASE_MS, now_monotonic_ns=BASE_NS) == "stopping"
            assert journal.record(command.command_id)["state"] == "stopping"
            assert trial.potentially_moving
            assert len([frame for frame in fake.received_commands if frame.startswith(b"GrpStop,")]) == 1
            assert trial.observe(telemetry(sequence=11), now_monotonic_ns=BASE_NS + 10_000_000) == "stopping"
            assert trial.observe(telemetry(sequence=12), now_monotonic_ns=BASE_NS + 20_000_000) == "stopped"
        finally:
            client.close()
            journal.close()


def test_fake_tcp_waypoint_then_actual_datasheet_frames_complete_motion(tmp_path) -> None:
    def frame(*, x: int, moving: bool, fsm: int, in_position: bool) -> bytes:
        document = datasheet_document()
        document["RobotAuthorization"]["DeviceSN"] = "FAKE-SN"
        document["PosAndVel"]["Actual_PCS_Base"] = [str(x), "100", "100", "0", "0", "0"]
        document["StateAndError"].update({
            "robotState": fsm, "robotMoving": int(moving),
            "InPos": int(in_position),
        })
        return datasheet_frame(document)

    stream = [
        frame(x=100, moving=True, fsm=25, in_position=False),
        frame(x=101, moving=False, fsm=33, in_position=True),
        frame(x=101, moving=False, fsm=33, in_position=True),
    ]
    with FakeHuayanController(accept_fake_motion=True, data_actions=stream) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            assert trial.submit(command, telemetry(), readback(), arm(command), lease(),
                                now_ms=BASE_MS, now_monotonic_ns=BASE_NS) == "accepted"
            with DatasheetClient("127.0.0.1", fake.datasheet_port, byte_order="little") as data:
                samples = []
                while len(samples) < 3:
                    data.poll()
                    samples.extend(data.last_batch)
            assert [sample.device_sn for sample in samples] == ["FAKE-SN"] * 3
            for index, sample in enumerate(samples, start=1):
                feedback = telemetry(
                    sequence=10 + index, x=sample.base_pose[0],
                    moving=sample.moving, fsm=sample.fsm_code,
                    in_position=sample.in_position,
                )
                outcome = trial.observe(
                    feedback, now_monotonic_ns=BASE_NS + index * 25_000_000,
                )
            assert outcome == "succeeded"
            assert journal.record("move-1")["state"] == "succeeded"
        finally:
            client.close()


def test_response_loss_is_unknown_and_restart_never_replays(tmp_path) -> None:
    with FakeHuayanController(
        accept_fake_motion=True,
        motion_actions={"WayPoint": [CommandAction(None)]},
    ) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            with pytest.raises(ResponseUnknown):
                trial.submit(command, telemetry(), readback(), arm(command), lease(),
                             now_ms=BASE_MS, now_monotonic_ns=BASE_NS)
            assert journal.record("move-1")["state"] == "unknown"
            journal.close()
            with CommandJournal(tmp_path / "fake-motion.journal") as recovered:
                assert recovered.unresolved() == ("move-1",)
                with pytest.raises(JournalError, match="unresolved"):
                    recovered.prepare(command_id="move-2", fingerprint="a", session_id=SESSION,
                                      safety_state_hash="b", start_sequence=11,
                                      encoded_frame=b"WayPoint,0,;")
            assert len([x for x in fake.received_commands if x.startswith(b"WayPoint,")]) == 1
        finally:
            client.close()


def test_start_timeout_requests_only_ordinary_stop_and_waits_for_feedback(tmp_path) -> None:
    with FakeHuayanController(accept_fake_motion=True) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            trial.submit(command, telemetry(), readback(), arm(command), lease(),
                         now_ms=BASE_MS, now_monotonic_ns=BASE_NS)
            assert trial.observe(telemetry(sequence=11),
                                 now_monotonic_ns=BASE_NS + 160_000_000) == "stopping"
            assert journal.record("move-1")["state"] == "stopping"
            assert trial.observe(telemetry(sequence=12),
                                 now_monotonic_ns=BASE_NS + 170_000_000) == "stopping"
            assert trial.observe(telemetry(sequence=13),
                                 now_monotonic_ns=BASE_NS + 180_000_000) == "stopped"
            assert fake.received_commands.count(b"GrpStop,0,;") == 1
        finally:
            client.close()


def test_external_waypoint_revokes_motion_and_stop_is_not_estop(tmp_path) -> None:
    with FakeHuayanController(
        accept_fake_motion=True,
        command_actions={ReadCommand.CURRENT_WAYPOINT_ID: [
            CommandAction((b"ReadCurWayPointID,OK,EXTERNAL_WRITER,;",))
        ]},
    ) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            trial.submit(command, telemetry(), readback(), arm(command), lease(),
                         now_ms=BASE_MS, now_monotonic_ns=BASE_NS)
            assert trial.observe(telemetry(sequence=11, moving=True, fsm=25, in_position=False),
                                 now_monotonic_ns=BASE_NS + 10_000_000) == "stopping"
            assert fake.received_commands[-1] == b"GrpStop,0,;"
            assert journal.unresolved() == ("move-1",)
            assert trial.observe(telemetry(sequence=12),
                                 now_monotonic_ns=BASE_NS + 20_000_000) == "stop_unconfirmed"
            assert trial.potentially_moving
        finally:
            client.close()


@pytest.mark.parametrize("snapshot,waypoint,expected", [
    (telemetry(sequence=11, x=100.5), "FAKE_ONLY", "unowned_pose_change"),
    (telemetry(sequence=11), "OTHER", "external_waypoint"),
    (telemetry(sequence=11, moving=True, fsm=25), "FAKE_ONLY", "unexpected_program_or_fsm"),
    (telemetry(sequence=11).model_copy(update={"freshness": SourceFreshness.STALE}),
     "FAKE_ONLY", "feedback_lost"),
])
def test_unowned_changes_revoke_local_arm(snapshot, waypoint, expected) -> None:
    command = envelope()
    local_arm = arm(command)
    guard = FakeExternalWriterGuard(
        arm=local_arm, baseline=telemetry(), baseline_waypoint_id="FAKE_ONLY",
        noise_threshold_mm=0.1,
    )
    assert guard.observe(snapshot, waypoint_id=waypoint) == expected
    assert local_arm.used


@pytest.mark.parametrize("change", [
    {"auto_mode": None},
    {"reduced_mode": None},
    {"safeguard_active": True},
    {"freshness": SourceFreshness.STALE},
    {"state_age_ms": 300},
    {"controller_is_simulation": True},
])
def test_fail_closed_safety_fields_prevent_any_write(tmp_path, change) -> None:
    with FakeHuayanController(accept_fake_motion=True) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            sample = telemetry().model_copy(update=change)
            with pytest.raises(ValueError):
                trial.submit(command, sample, readback(), arm(command, sample), lease(),
                             now_ms=BASE_MS, now_monotonic_ns=BASE_NS)
            assert_no_motion_write(fake)
            assert journal.unresolved() == ()
        finally:
            client.close()


@pytest.mark.parametrize("auto_mode", [False, True])
def test_confirmed_modes_do_not_require_reduced_mode_or_inactive_3pe(tmp_path, auto_mode) -> None:
    with FakeHuayanController(accept_fake_motion=True) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            initial = telemetry().model_copy(update={
                "auto_mode": auto_mode, "reduced_mode": False,
                "three_position_enable": None,
            })
            assert trial.submit(command, initial, readback(), arm(command, initial), lease(),
                                now_ms=BASE_MS, now_monotonic_ns=BASE_NS) == "accepted"
            moving = initial.model_copy(update={
                "sequence": 11, "moving": True, "fsm_code": 25, "in_position": False,
            })
            assert trial.observe(moving, now_monotonic_ns=BASE_NS + 10_000_000) == "executing"
            arrived = initial.model_copy(update={"sequence": 12, "actual_pose_robot_base": pose(101)})
            assert trial.observe(arrived, now_monotonic_ns=BASE_NS + 20_000_000) == "executing"
            assert trial.observe(arrived.model_copy(update={"sequence": 13}),
                                 now_monotonic_ns=BASE_NS + 45_000_000) == "succeeded"
            assert journal.unresolved() == ()
        finally:
            client.close()


@pytest.mark.parametrize("change", [
    {"auto_mode": True},
    {"reduced_mode": True},
])
def test_mode_change_during_owned_motion_requests_stop(tmp_path, change) -> None:
    with FakeHuayanController(accept_fake_motion=True) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            initial = telemetry().model_copy(update={
                "auto_mode": False, "reduced_mode": False,
                "three_position_enable": None,
            })
            assert trial.submit(command, initial, readback(), arm(command, initial), lease(),
                                now_ms=BASE_MS, now_monotonic_ns=BASE_NS) == "accepted"
            changed = initial.model_copy(update={"sequence": 11, **change})
            assert trial.observe(changed, now_monotonic_ns=BASE_NS + 10_000_000) == "stopping"
            assert trial.stop_delivery == "sent"
            assert trial.potentially_moving
        finally:
            client.close()


def test_inactive_3pe_is_not_a_motion_gate(tmp_path) -> None:
    with FakeHuayanController(accept_fake_motion=True) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            initial = telemetry().model_copy(update={"three_position_enable": None})
            assert trial.submit(command, initial, readback(), arm(command, initial), lease(),
                                now_ms=BASE_MS, now_monotonic_ns=BASE_NS) == "accepted"
            changed = initial.model_copy(update={
                "sequence": 11, "three_position_enable": False,
                "moving": True, "fsm_code": 25, "in_position": False,
            })
            assert trial.observe(changed, now_monotonic_ns=BASE_NS + 10_000_000) == "executing"
            assert fake.received_commands.count(b"GrpStop,0,;") == 0
        finally:
            client.close()


def test_arm_single_use_and_path_ik_fail_closed(tmp_path) -> None:
    with FakeHuayanController(accept_fake_motion=True) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            local_arm = arm(command)
            trial.path_ik = lambda point: None if point[0] > 100.5 else ik(point)
            with pytest.raises(ValueError, match="IK"):
                trial.submit(command, telemetry(), readback(), local_arm, lease(),
                             now_ms=BASE_MS, now_monotonic_ns=BASE_NS)
            assert local_arm.used
            trial.path_ik = ik
            local_arm = arm(command)
            assert trial.submit(command, telemetry(), readback(), local_arm, lease(),
                                now_ms=BASE_MS, now_monotonic_ns=BASE_NS) == "accepted"
            assert local_arm.used
            with pytest.raises(JournalError):
                trial.submit(command, telemetry(), readback(), local_arm, lease(),
                             now_ms=BASE_MS, now_monotonic_ns=BASE_NS)
        finally:
            client.close()


def test_prepared_journal_proves_not_sent_but_send_started_is_unknown(tmp_path) -> None:
    path = tmp_path / "journal"
    with CommandJournal(path) as journal:
        journal.prepare(command_id="a", fingerprint="fp-a", session_id=SESSION,
                        safety_state_hash="safe", start_sequence=10,
                        encoded_frame=b"WayPoint,0,;")
    with CommandJournal(path) as journal:
        assert journal.unresolved() == ("a",)
        journal.transition("a", "not_sent", evidence="durable send-start marker absent")
        journal.prepare(command_id="b", fingerprint="fp-b", session_id=SESSION,
                        safety_state_hash="safe", start_sequence=11,
                        encoded_frame=b"WayPoint,0,;")
        journal.transition("b", "send_started")
    with CommandJournal(path) as journal:
        assert journal.unresolved() == ("b",)
        with pytest.raises(JournalError, match="unresolved"):
            journal.prepare(command_id="c", fingerprint="fp-c", session_id=SESSION,
                            safety_state_hash="safe", start_sequence=12,
                            encoded_frame=b"WayPoint,0,;")
        with pytest.raises(JournalError, match="never replay"):
            journal.prepare(command_id="b", fingerprint="fp-b", session_id=SESSION,
                            safety_state_hash="safe", start_sequence=11,
                            encoded_frame=b"WayPoint,0,;")


def test_journal_refuses_second_owner_and_corrupt_recovery(tmp_path) -> None:
    path = tmp_path / "journal"
    with CommandJournal(path) as journal:
        with pytest.raises(JournalError, match="already owned"):
            CommandJournal(path)
        journal.prepare(command_id="a", fingerprint="fp", session_id=SESSION,
                        safety_state_hash="safe", start_sequence=10,
                        encoded_frame=b"WayPoint,0,;")
    with path.open("ab") as stream:
        stream.write(b'{"incomplete":')
    with pytest.raises(JournalError, match="corrupt"):
        CommandJournal(path)


@pytest.mark.parametrize("field,value", [
    ("config_sha256", "0" * 64),
    ("tcp_name", "CHANGED"),
    ("ucs_name", "OTHER"),
    ("payload_kg", 0.1),
    ("base_installing_angle_deg", (1, 0)),
    ("group_error_code", 20018),
    ("axis_error_codes", (0, 0, 1, 0, 0, 0)),
    ("active_program", True),
])
def test_changed_readback_blocks_fake_write(tmp_path, field, value) -> None:
    with FakeHuayanController(accept_fake_motion=True) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            with pytest.raises(ValueError):
                trial.submit(command, telemetry(), replace(readback(), **{field: value}),
                             arm(command), lease(), now_ms=BASE_MS,
                             now_monotonic_ns=BASE_NS)
            assert_no_motion_write(fake)
            assert journal.unresolved() == ()
        finally:
            client.close()


@pytest.mark.parametrize("leases", [
    (),
    (MotionLease("remote", SESSION, BASE_NS + 1_000_000_000),),
    (MotionLease("local", SESSION, BASE_NS - 1),),
    (MotionLease("local", SESSION, BASE_NS + 1_000_000_000),
     MotionLease("remote", SESSION, BASE_NS + 1_000_000_000)),
])
def test_lease_missing_expired_or_conflicting_blocks_write(tmp_path, leases) -> None:
    with FakeHuayanController(accept_fake_motion=True) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            with pytest.raises(ValueError, match="lease"):
                trial.submit(command, telemetry(), readback(), arm(command), leases,
                             now_ms=BASE_MS, now_monotonic_ns=BASE_NS)
            assert_no_motion_write(fake)
        finally:
            client.close()


def test_arm_fingerprint_sequence_and_start_pose_are_bound(tmp_path) -> None:
    with FakeHuayanController(accept_fake_motion=True) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            wrong = arm(command)
            wrong.command_fingerprint = "0" * 64
            with pytest.raises(ValueError, match="ARM"):
                trial.submit(command, telemetry(), readback(), wrong, lease(),
                             now_ms=BASE_MS, now_monotonic_ns=BASE_NS)
            assert wrong.used
            old = arm(command)
            old.base_sequence = 11
            with pytest.raises(ValueError, match="ARM"):
                trial.submit(command, telemetry(), readback(), old, lease(),
                             now_ms=BASE_MS, now_monotonic_ns=BASE_NS)
            moved = telemetry(x=101)
            with pytest.raises(ValueError, match="drifted"):
                trial.submit(command, moved, readback(), arm(command), lease(),
                             now_ms=BASE_MS, now_monotonic_ns=BASE_NS)
            assert_no_motion_write(fake)
        finally:
            client.close()


def test_stop_without_owned_command_never_reaches_fake_controller(tmp_path) -> None:
    with FakeHuayanController(accept_fake_motion=True) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            assert trial.request_stop(now_monotonic_ns=BASE_NS) == "not_sent"
            assert_no_motion_write(fake)
            assert journal.unresolved() == ()
        finally:
            client.close()


def test_authenticated_stop_is_idempotent_rate_limited_and_never_physical_estop(tmp_path) -> None:
    with FakeHuayanController(accept_fake_motion=True) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            trial.submit(command, telemetry(), readback(), arm(command), lease(),
                         now_ms=BASE_MS, now_monotonic_ns=BASE_NS)
            with pytest.raises(PermissionError):
                trial.request_authenticated_stop("stop-1", authenticated=False,
                                                 now_monotonic_ns=BASE_NS + 1_000_000)
            first = trial.request_authenticated_stop(
                "stop-1", authenticated=True, now_monotonic_ns=BASE_NS + 2_000_000,
            )
            assert first.delivery.value == "sent"
            assert first.motion_stop.value == "unconfirmed"
            assert trial.request_authenticated_stop(
                "stop-1", authenticated=True, now_monotonic_ns=BASE_NS + 3_000_000,
            ) == first
            with pytest.raises(ValueError, match="rate limit"):
                trial.request_authenticated_stop(
                    "stop-2", authenticated=True, now_monotonic_ns=BASE_NS + 4_000_000,
                )
            assert fake.received_commands.count(b"GrpStop,0,;") == 1
            assert trial.observe(telemetry(sequence=11),
                                 now_monotonic_ns=BASE_NS + 12_000_000) == "stopping"
            assert trial.observe(telemetry(sequence=12),
                                 now_monotonic_ns=BASE_NS + 22_000_000) == "stopped"
            confirmed = trial.request_authenticated_stop(
                "stop-1", authenticated=True, now_monotonic_ns=BASE_NS + 23_000_000,
            )
            assert confirmed.motion_stop.value == "confirmed"
            assert fake.received_commands.count(b"GrpStop,0,;") == 1
            assert journal.record("move-1")["state"] == "stopped"
        finally:
            client.close()


def test_lost_stop_reply_cannot_be_reported_as_confirmed(tmp_path) -> None:
    with FakeHuayanController(
        accept_fake_motion=True,
        motion_actions={"GrpStop": [CommandAction(None)]},
    ) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            trial.submit(command, telemetry(), readback(), arm(command), lease(),
                         now_ms=BASE_MS, now_monotonic_ns=BASE_NS)
            assert trial.request_stop(now_monotonic_ns=BASE_NS + 10_000_000) == "unknown"
            assert journal.record("move-1")["state"] == "stop_unconfirmed"
            assert trial.potentially_moving
            assert fake.received_commands.count(b"GrpStop,0,;") == 1
        finally:
            client.close()


def test_command_socket_loss_after_waypoint_does_not_imply_robot_stopped(tmp_path) -> None:
    with FakeHuayanController(accept_fake_motion=True) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            assert trial.submit(command, telemetry(), readback(), arm(command), lease(),
                                now_ms=BASE_MS, now_monotonic_ns=BASE_NS) == "accepted"
            client.close()  # Vendor says the controller continues the current WayPoint.
            moving = telemetry(sequence=11, moving=True, fsm=25, in_position=False)
            assert trial.observe(moving, now_monotonic_ns=BASE_NS + 10_000_000) == "stop_unconfirmed"
            assert trial.potentially_moving
            assert journal.unresolved() == ("move-1",)
            assert fake.received_commands.count(b"GrpStop,0,;") == 0
            assert len([frame for frame in fake.received_commands if frame.startswith(b"WayPoint,")]) == 1
        finally:
            client.close()


def test_stop_cannot_overtake_in_flight_waypoint_on_single_socket(tmp_path) -> None:
    with FakeHuayanController(
        accept_fake_motion=True,
        motion_actions={"WayPoint": [CommandAction((b"WayPoint,OK,;",), delay_s=0.4)]},
    ) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        errors = []
        command = envelope()

        def submit_in_background() -> None:
            try:
                trial.submit(command, telemetry(), readback(), arm(command), lease(),
                             now_ms=BASE_MS, now_monotonic_ns=BASE_NS)
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=submit_in_background)
        worker.start()
        try:
            deadline = time.monotonic() + 1
            while not any(item.startswith(b"WayPoint,") for item in fake.received_commands):
                if time.monotonic() > deadline:
                    pytest.fail("fake did not receive WayPoint")
                time.sleep(0.005)
            assert trial.request_stop(now_monotonic_ns=BASE_NS + 5_000_000) == "unknown"
            worker.join(timeout=1)
            assert errors
            assert journal.record("move-1")["state"] == "stop_unconfirmed"
            assert journal.unresolved() == ("move-1",)
            assert fake.received_commands.count(b"GrpStop,0,;") == 0
        finally:
            worker.join(timeout=1)
            client.close()


def test_watchdog_without_feedback_requests_stop_and_latches_unconfirmed(tmp_path) -> None:
    with FakeHuayanController(accept_fake_motion=True) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            trial.submit(command, telemetry(), readback(), arm(command), lease(),
                         now_ms=BASE_MS, now_monotonic_ns=BASE_NS)
            assert trial.watchdog(now_monotonic_ns=BASE_NS + 260_000_000) == "stopping"
            assert trial.watchdog(now_monotonic_ns=BASE_NS + 470_000_000) == "stop_unconfirmed"
            assert trial.potentially_moving
            assert fake.received_commands.count(b"GrpStop,0,;") == 1
        finally:
            client.close()


def test_contradictory_moving_and_ready_feedback_requests_stop(tmp_path) -> None:
    with FakeHuayanController(accept_fake_motion=True) as fake:
        client, journal, trial = make_trial(fake, tmp_path)
        try:
            command = envelope()
            trial.submit(command, telemetry(), readback(), arm(command), lease(),
                         now_ms=BASE_MS, now_monotonic_ns=BASE_NS)
            contradictory = telemetry(sequence=11, moving=True, fsm=33)
            assert trial.observe(contradictory,
                                 now_monotonic_ns=BASE_NS + 10_000_000) == "stopping"
            assert fake.received_commands.count(b"GrpStop,0,;") == 1
            assert journal.unresolved() == ("move-1",)
        finally:
            client.close()
