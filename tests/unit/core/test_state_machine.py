from __future__ import annotations

import unittest

from agent.core import AgentTaskState, InvalidStateTransition, TaskStateMachine


class StateMachineTests(unittest.TestCase):
    def test_valid_history_is_recorded(self):
        machine = TaskStateMachine()
        machine.transition(AgentTaskState.PARSING)
        machine.transition(AgentTaskState.VALIDATING)
        machine.transition(AgentTaskState.MOVING_TO_ENTRY)
        machine.transition(AgentTaskState.AT_ENTRY)
        machine.transition(AgentTaskState.COMPLETED)

        self.assertEqual(machine.state, AgentTaskState.COMPLETED)
        self.assertEqual(machine.history[0], AgentTaskState.IDLE)
        self.assertEqual(len(machine.events), len(machine.history) - 1)
        self.assertEqual(machine.events[0].sequence, 1)
        self.assertEqual(machine.events[0].from_state, AgentTaskState.IDLE)
        self.assertEqual(machine.events[0].to_state, AgentTaskState.PARSING)

    def test_planning_outcomes_are_distinct_terminal_states(self):
        for terminal in (
            AgentTaskState.PLAN_READY,
            AgentTaskState.PLAN_FAILED,
            AgentTaskState.PLANNER_UNAVAILABLE,
        ):
            with self.subTest(terminal=terminal):
                machine = TaskStateMachine()
                machine.transition(AgentTaskState.PARSING)
                machine.transition(AgentTaskState.VALIDATING)
                machine.transition(AgentTaskState.MOVING_TO_ENTRY)
                machine.transition(AgentTaskState.AT_ENTRY)
                machine.transition(AgentTaskState.PATH_PLANNING)
                machine.transition(terminal)
                self.assertEqual(machine.state, terminal)

    def test_invalid_transition_is_rejected(self):
        machine = TaskStateMachine()

        with self.assertRaises(InvalidStateTransition):
            machine.transition(AgentTaskState.PATH_PLANNING)


if __name__ == "__main__":
    unittest.main()
