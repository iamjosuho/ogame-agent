import unittest

from scripts.ogame.patrol_contract import (
    PATROL_PHASES,
    PatrolContractError,
    advance_patrol_contract,
    audit_patrol_contract,
    new_patrol_contract,
)


class PatrolRunContractTests(unittest.TestCase):
    def setUp(self):
        self.state = new_patrol_contract("run-1", 100)

    def advance(self, phase, routine=None):
        self.state = advance_patrol_contract(
            self.state,
            phase,
            f"evidence:{phase}",
            routine=routine,
            updated_at=101 + len(self.state["completed_phases"]),
        )

    def test_phases_cannot_be_skipped(self):
        with self.assertRaisesRegex(PatrolContractError, "不得跳步"):
            self.advance("scout_complete")

    def test_strategy_requires_all_four_routine_categories(self):
        for phase in ("memory_loaded", "scout_complete", "safety_reviewed"):
            self.advance(phase)
        with self.assertRaisesRegex(PatrolContractError, "完整包含"):
            self.advance("strategy_complete", {"transport": "not_due"})

    def test_execution_rejects_unresolved_planned_status(self):
        for phase in ("memory_loaded", "scout_complete", "safety_reviewed"):
            self.advance(phase)
        routine = {
            "transport": "not_due",
            "expedition": "planned",
            "farming": "blocked",
            "lifeform": "complete",
        }
        self.advance("strategy_complete", routine)
        with self.assertRaisesRegex(PatrolContractError, "尚為 planned"):
            self.advance("execution_complete", routine)

    def test_audit_passes_only_after_every_phase_and_final_routine(self):
        initial = audit_patrol_contract(self.state, "run-1")
        self.assertFalse(initial["complete"])
        self.assertIn("memory_loaded", initial["missing_phases"])

        for phase in ("memory_loaded", "scout_complete", "safety_reviewed"):
            self.advance(phase)
        strategy = {
            "transport": "not_due",
            "expedition": "planned",
            "farming": "blocked",
            "lifeform": "complete",
        }
        self.advance("strategy_complete", strategy)
        final = {**strategy, "expedition": "complete"}
        self.advance("execution_complete", final)
        self.advance("persistence_complete")

        audit = audit_patrol_contract(self.state, "run-1")
        self.assertTrue(audit["complete"])
        self.assertEqual(self.state["completed_phases"], list(PATROL_PHASES))


if __name__ == "__main__":
    unittest.main()
