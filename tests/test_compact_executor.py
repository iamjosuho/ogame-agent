import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import ogame_ctl
from scripts.ogame import workflow


class CompactExecutorTests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            "plan_id": "plan-1",
            "candidates": [
                {
                    "action_id": "supplies:2",
                    "component": "supplies",
                    "name": "晶體礦",
                    "target_level": 13,
                    "actionable_now": True,
                    "evidence": {"large": "must-not-leak"},
                },
                {
                    "action_id": "lfresearch:2",
                    "component": "lfresearch",
                    "name": "晶體礦",
                    "target_level": 13,
                    "actionable_now": True,
                },
            ],
        }

    def test_semantic_target_requires_exact_unique_match(self):
        ambiguous = workflow.select_candidates(self.plan, target_name="晶體礦")
        self.assertEqual(len(ambiguous), 2)

        selected = workflow.select_candidates(
            self.plan,
            target_name=" 晶體礦 ",
            component="supplies",
            target_level=13,
        )
        self.assertEqual([item["action_id"] for item in selected], ["supplies:2"])

        missing = workflow.select_candidates(
            self.plan,
            target_name="晶體礦",
            component="supplies",
            target_level=14,
        )
        self.assertEqual(missing, [])

    def test_compact_results_drop_full_evidence(self):
        compact = workflow.compact_results([
            {
                "step_id": "step-1",
                "action_id": "supplies:2",
                "planet_id": "42",
                "status": "applied",
                "reason": "verified",
                "verification": {"html": "large"},
                "postcondition": {"resources": {"metal": 1}},
            }
        ])
        self.assertEqual(
            compact,
            [{
                "step_id": "step-1",
                "action_id": "supplies:2",
                "planet_id": "42",
                "status": "applied",
                "reason": "verified",
            }],
        )

    def test_errors_are_bounded(self):
        text = workflow.bounded_text("x" * 5000)
        self.assertLessEqual(len(text), workflow.MAX_ERROR_CHARS + 1)
        self.assertTrue(text.endswith("…"))

    def test_format_compact_json_has_a_hard_stdout_budget(self):
        output = workflow.format_compact_json({"status": "blocked", "reason": "x" * 10000})
        self.assertLessEqual(len(output.encode("utf-8")), workflow.MAX_STDOUT_BYTES)
        self.assertEqual(json.loads(output)["reason"], "compact_output_budget_exceeded")

    def test_apply_requires_explicit_confirmation_before_execution(self):
        args = argparse.Namespace(
            planet_id=42,
            run_id="run-1",
            target_name="晶體礦",
            component="supplies",
            target_level=13,
            amount=None,
            kind="apply",
            include_lifeforms=False,
            include_production=False,
            confirm=False,
            pretty=False,
        )
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            with self.assertRaises(SystemExit):
                ogame_ctl.command_execute_decision(args)
        out = json.loads(stdout.getvalue().strip())
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(out["reason"], "confirmation_required")

    def test_large_plan_and_workflow_evidence_never_reach_stdout(self):
        large = "secret-evidence-" * 10000
        plan = {
            "plan_id": "plan-1",
            "candidates": [{
                "action_id": "supplies:2",
                "component": "supplies",
                "name": "晶體礦",
                "target_level": 13,
                "actionable_now": True,
                "raw_dom": large,
            }],
        }
        wf_plan = {"workflow_id": "workflow-1"}
        wf_result = {
            "status": "completed",
            "state_certainty": "certain",
            "results": [{
                "step_id": "step-1",
                "action_id": "supplies:2",
                "planet_id": "42",
                "status": "applied",
                "reason": "verified",
                "verification": {"raw_dom": large},
            }],
        }
        args = argparse.Namespace(
            planet_id=42,
            run_id="run-1",
            target_name="晶體礦",
            component="supplies",
            target_level=13,
            amount=None,
            kind="apply",
            include_lifeforms=False,
            include_production=False,
            confirm=True,
            pretty=False,
            intent_file=None,
            delay=0,
        )
        with patch.object(ogame_ctl, "command_plan", return_value=plan):
            with patch.object(ogame_ctl, "command_workflow_plan", return_value=wf_plan):
                with patch.object(ogame_ctl, "command_workflow_run", return_value=wf_result):
                    with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                        ogame_ctl.command_execute_decision(args)

        output = stdout.getvalue().strip()
        self.assertLess(len(output.encode("utf-8")), 1024)
        self.assertNotIn("secret-evidence", output)
        self.assertNotIn("raw_dom", output)
        self.assertIn('"global_stop":false', output)


if __name__ == "__main__":
    unittest.main()
