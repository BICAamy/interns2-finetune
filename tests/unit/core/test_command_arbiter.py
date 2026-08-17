from __future__ import annotations

import unittest

from agent.core import CommandCandidate, CommandSource, choose_command
from surgical_contracts import CommandIntent, ParsedCommand


def candidate(
    command_id: str,
    intent: CommandIntent,
    source: CommandSource,
    received_at_ms: int,
) -> CommandCandidate:
    clarification = (
        {
            "missing_fields": ["intent"],
            "needs_confirmation": True,
            "summary": "Clarification required",
        }
        if intent == CommandIntent.CLARIFY
        else {}
    )
    return CommandCandidate(
        command=ParsedCommand(
            command_id=command_id,
            intent=intent,
            **clarification,
        ),
        source=source,
        received_at_ms=received_at_ms,
    )


class CommandArbiterTests(unittest.TestCase):
    def test_emergency_stop_beats_newer_normal_inputs(self):
        selected = choose_command(
            [
                candidate("gesture", CommandIntent.CLARIFY, CommandSource.GESTURE, 300),
                candidate("voice", CommandIntent.CLARIFY, CommandSource.VOICE, 200),
                candidate(
                    "estop",
                    CommandIntent.EMERGENCY_STOP,
                    CommandSource.GESTURE,
                    100,
                ),
            ]
        )

        self.assertEqual(selected.command.command_id, "estop")

    def test_voice_beats_newer_normal_gesture(self):
        selected = choose_command(
            [
                candidate("voice", CommandIntent.CLARIFY, CommandSource.VOICE, 100),
                candidate("gesture", CommandIntent.CLARIFY, CommandSource.GESTURE, 200),
            ]
        )

        self.assertEqual(selected.command.command_id, "voice")

    def test_empty_candidates_return_none(self):
        self.assertIsNone(choose_command([]))


if __name__ == "__main__":
    unittest.main()
