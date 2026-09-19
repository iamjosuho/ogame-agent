"""Lease and evidence boundary tests; all game readers are fakes."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.ogame.cli import build_parser
from scripts.ogame import lifecycle
from scripts.ogame import browser
from scripts.ogame.patrol_start import command_patrol_start


class PatrolStartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.memory = self.root / "runtime" / "memory"
        self.memory.mkdir(parents=True)
        (self.root / "CHECKLIST.md").write_text("check", encoding="utf-8")
        for name in ("GameState.md", "TODO.md", "errors.md"):
            (self.memory / name).write_text("state", encoding="utf-8")
        self.steps = []
        self.finishes = []
        self.calls = []

    def _write(self, path, value):
        Path(path).write_text(json.dumps(value), encoding="utf-8")

    def _step(self, args):
        self.steps.append(args.phase)
        return {"success": True, "phase": args.phase}

    def _finish(self, args):
        self.finishes.append((args.run_id, args.abort_reason, args.commit))
        return {"released": True}

    def _matrix(self, args):
        self.calls.append("matrix")
        value = {
            "success": True,
            "source": "empire.standalone",
            "queue_coverage": "empire.standalone",
            "rates_coverage": "not_provided",
            "active_planet_restored": True,
            "run_id": args.run_id,
            "planets": [{
                "planet_id": 1,
                "resources": {"metal": 10, "crystal": 10, "deuterium": 10},
                "storage": {"metal": 100, "crystal": 100, "deuterium": 100},
                "rates": {"metal": None, "crystal": None, "deuterium": None},
                "queues": [],
                "building_busy": False,
                "research_busy": False,
                "shipyard_busy": False,
                "lifeform_building_busy": False,
                "lifeform_research_busy": False,
                "buildings": {},
                "researches": {},
                "ships": {},
                "defenses": {},
            }],
            "totals": {"rates": {"metal": None, "crystal": None, "deuterium": None}},
        }
        self._write(self.memory / "scout-report.json", value)
        print("FULL MATRIX SHOULD NEVER REACH THE AGENT")
        return value

    def _run(self, *, gate=None, movement=None, matrix=None, step=None, finish=None, release=None):
        output = io.StringIO()
        with redirect_stdout(output):
            result = command_patrol_start(
                argparse.Namespace(output="json"),
                project_root=self.root,
                memory_dir=self.memory,
                gate_fn=gate or (lambda args: {"acquired": True, "run_id": "run-1"}),
                movement_fn=movement or (lambda: {"success": True, "scope": "account", "coverage": "verified", "page_evidence": {"root_verified": True, "empty_state_verified": True}, "threat_status": "none", "events": []}),
                matrix_fn=matrix or self._matrix,
                step_fn=step or self._step,
                finish_fn=finish or self._finish,
                release_fn=release or (lambda run_id: False),
                constants_loader=lambda path: SimpleNamespace(cargo_capacities={"202": 1, "203": 1}),
                write_fn=self._write,
            )
        return result, output.getvalue()

    def test_parser_exposes_single_start_command(self):
        args = build_parser().parse_args(["patrol-start", "--output", "json"])
        self.assertEqual(args.command, "patrol-start")

    def test_skipped_gate_never_reads_game_or_sources(self):
        result, output = self._run(gate=lambda args: {"acquired": False, "reason": "overlap"}, movement=lambda: self.fail("movement called"))
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(output, "")
        self.assertEqual(self.steps, [])
        self.assertEqual(self.finishes, [])

    def test_unverified_movement_aborts_and_releases_before_matrix(self):
        result, output = self._run(movement=lambda: {"success": True, "scope": "account_unverified", "coverage": "unverified", "threat_status": "unknown", "events": []})
        self.assertEqual(result["abort_reason"], "movement_dom_unverified")
        self.assertEqual(self.steps, ["memory_loaded"])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.finishes, [("run-1", "movement_dom_unverified", False)])
        self.assertNotIn("events", output)
        recorded = json.loads((self.memory / "movement-events.json").read_text())
        self.assertEqual(recorded["validation_status"], "unverified")

    def test_unknown_event_handoff_holds_lease_and_blocks_routines(self):
        result, output = self._run(movement=lambda: {"success": True, "scope": "account", "coverage": "verified", "page_evidence": {"root_verified": True}, "threat_status": "unknown", "events": [{"id": "e1", "text": "ambiguous"}]})
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["routine_blocked_until_safety_review"])
        self.assertEqual(result["next_phase"], "safety_reviewed")
        self.assertEqual(self.steps, ["memory_loaded", "scout_complete"])
        self.assertEqual(self.finishes, [])
        self.assertNotIn("FULL MATRIX", output)
        self.assertNotIn("ambiguous", output)

    def test_missing_empire_coverage_aborts_after_movement(self):
        def invalid_matrix(args):
            value = self._matrix(args)
            value["queue_coverage"] = "unknown"
            return value
        result, _ = self._run(matrix=invalid_matrix)
        self.assertEqual(result["abort_reason"], "matrix_queue_unverified")
        self.assertEqual(self.steps, ["memory_loaded"])
        self.assertEqual(len(self.finishes), 1)

    def test_stale_scout_report_cannot_mark_scout_complete(self):
        def stale_matrix(args):
            value = self._matrix(args)
            value["source"] = "empire.standalone+official.accountInfo"
            return value
        result, _ = self._run(matrix=stale_matrix)
        self.assertEqual(result["abort_reason"], "matrix_report_mismatch")
        self.assertEqual(self.steps, ["memory_loaded"])
        self.assertEqual(len(self.finishes), 1)

    def test_matrix_missing_planet_fields_is_not_ready(self):
        def incomplete_matrix(args):
            value = self._matrix(args)
            del value["planets"][0]["storage"]
            self._write(self.memory / "scout-report.json", value)
            return value
        result, _ = self._run(matrix=incomplete_matrix)
        self.assertEqual(result["abort_reason"], "matrix_planets_invalid")
        self.assertEqual(self.steps, ["memory_loaded"])

    def test_none_with_unclassified_event_is_not_safe(self):
        result, _ = self._run(movement=lambda: {"success": True, "scope": "account", "coverage": "verified", "page_evidence": {"root_verified": True}, "threat_status": "none", "events": [{"id": "outbound", "text": "attack"}]})
        self.assertEqual(result["abort_reason"], "movement_direction_unverified")
        self.assertEqual(self.calls, [])

    def test_missing_memory_aborts_without_game_read(self):
        (self.memory / "TODO.md").unlink()
        result, _ = self._run(movement=lambda: self.fail("movement called"))
        self.assertEqual(result["abort_reason"], "memory_source_missing")
        self.assertEqual(self.steps, [])
        self.assertEqual(len(self.finishes), 1)

    def test_step_must_return_success_before_handoff(self):
        result, _ = self._run(step=lambda args: {"success": False})
        self.assertEqual(result["abort_reason"], "memory_checkpoint_failed")
        self.assertEqual(self.calls, [])

    def test_finish_failure_uses_owned_lease_fallback(self):
        released = []
        def broken_finish(args):
            raise OSError("contract write failed")
        result, _ = self._run(
            movement=lambda: {"success": True, "scope": "account_unverified", "coverage": "unverified", "threat_status": "unknown", "events": []},
            finish=broken_finish,
            release=lambda run_id: released.append(run_id) or True,
        )
        self.assertEqual(released, ["run-1"])
        self.assertTrue(result["lease_released_by_fallback"])
        self.assertTrue(result["contract_finalization_failed"])

    def test_gate_rolls_back_lease_when_contract_write_fails(self):
        lease_path = self.memory / "test-patrol-run.json"
        guard_path = self.memory / "test-patrol-run.lock"
        real_write = lifecycle.atomic_write_json
        count = 0
        def fail_second_write(path, value):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("contract write failed")
            real_write(path, value)
        with patch("scripts.ogame.lifecycle.atomic_write_json", side_effect=fail_second_write):
            with self.assertRaises(OSError):
                lifecycle.acquire_run_lease(memory_dir=str(self.memory), lease_file=str(lease_path), guard_file=str(guard_path))
        self.assertFalse(lease_path.exists())

    def test_mutation_gate_requires_ordered_safety_checkpoint(self):
        lease_path = self.memory / "safety-patrol-run.json"
        guard_path = self.memory / "safety-patrol-run.lock"
        lease = lifecycle.acquire_run_lease(memory_dir=str(self.memory), lease_file=str(lease_path), guard_file=str(guard_path))
        run_id = lease["run_id"]
        kwargs = {"memory_dir": str(self.memory), "lease_file": str(lease_path), "guard_file": str(guard_path)}
        with self.assertRaisesRegex(RuntimeError, "safety_reviewed"):
            lifecycle.require_patrol_safety_reviewed(run_id, **kwargs)
        for phase in ("memory_loaded", "scout_complete", "safety_reviewed"):
            lifecycle.command_patrol_step(
                argparse.Namespace(run_id=run_id, phase=phase, evidence_ref="test-evidence", output="json", silent=True),
                **kwargs,
            )
        lifecycle.require_patrol_safety_reviewed(run_id, **kwargs)
        lifecycle.release_run_lease(run_id, **kwargs)

    def test_movement_safety_signal_does_not_navigate_to_restore(self):
        with patch("scripts.ogame.browser.read_active_planet_context", return_value={"planet_id": "42"}), \
             patch("scripts.ogame.browser._execute_in_game_tab", return_value={"success": False, "safety_stop": True, "reason": "captcha"}), \
             patch("scripts.ogame.browser.execute_checked_component") as restore:
            with self.assertRaisesRegex(RuntimeError, "captcha"):
                browser.read_global_movement_evidence()
        restore.assert_not_called()

    def test_global_movement_uses_account_url_without_planet_cp(self):
        captured = {}
        movement = {
            "success": True,
            "scope": "account",
            "coverage": "verified",
            "page_evidence": {"root_verified": True, "empty_state_verified": True},
            "threat_status": "none",
            "events": [],
        }

        def read_page(_js, **kwargs):
            captured.update(kwargs)
            return movement

        with patch("scripts.ogame.browser.read_active_planet_context", return_value={"planet_id": "42"}), \
             patch("scripts.ogame.browser._execute_in_game_tab", side_effect=read_page), \
             patch("scripts.ogame.browser.execute_checked_component", return_value={"planet_id": "42"}) as restore:
            self.assertEqual(browser.read_global_movement_evidence(), movement)

        self.assertEqual(captured["target_url"], browser.game_url("movement"))
        self.assertNotIn("cp=", captured["target_url"])
        restore.assert_called_once()


if __name__ == "__main__":
    unittest.main()
