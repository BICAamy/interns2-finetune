from __future__ import annotations

import unittest

from agent.core import AgentTaskState, InvalidStateTransition, TaskStateMachine


class StateMachineTests(unittest.TestCase):
    def test_valid_history_is_recorded(self):
        machine = TaskStateMachine()
        machine.transition(AgentTaskState.VALIDATING)
        machine.transition(AgentTaskState.MOVING_TO_ENTRY)
        machine.transition(AgentTaskState.AT_ENTRY)
        machine.transition(AgentTaskState.COMPLETED)

        self.assertEqual(machine.state, AgentTaskState.COMPLETED)
        self.assertEqual(machine.history[0], AgentTaskState.IDLE)

    def test_invalid_transition_is_rejected(self):
        machine = TaskStateMachine()

        with self.assertRaises(InvalidStateTransition):
            machine.transition(AgentTaskState.PATH_PLANNING)


if __name__ == "__main__":
    unittest.main()
