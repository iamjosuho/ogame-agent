import argparse
import json
import pathlib
import tempfile
import threading
import time
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from scripts import ogame_ctl
from scripts.ogame.atoms import PlannedMutationCallbacks, apply_planned_action_atom
from scripts.ogame.browser import _execute_in_game_tab
from scripts.ogame.models import ActionResult, ActionStatus, Intent, IntentKind, WorkflowPlan, WorkflowStep
from scripts.ogame.operations import assess_workflow_candidate, build_patrol_fleet_candidates
from scripts.ogame.planning import POLICY_PRECEDENCE, build_workflow_plan, feasible_packages
from scripts.ogame.policy import (
    DEFAULT_CONSTANTS_PATH,
    DEFAULT_STRATEGY_PATH,
    SAFETY_POLICY,
    SafetyPolicy,
    load_account_constants,
    load_strategy_policy,
)
from scripts.ogame.workflow import WorkflowJournal, WorkflowRunner


ACCOUNT_CONSTANTS = load_account_constants(DEFAULT_CONSTANTS_PATH)


class OGameLayerTests(unittest.TestCase):
    @staticmethod
    def confirmed_plan(now=None):
        now = int(time.time() if now is None else now)
        return {
            "plan_id": "confirmed-1",
            "run_id": "run-1",
            "planet_id": "42",
            "status": "active",
            "created_at": now,
            "expires_at": now + 600,
            "snapshot_hash": "snapshot-hash",
            "action_count": 0,
            "resources": {"metal": 10000, "crystal": 10000, "deuterium": 10000},
            "spendable_resources": {"metal": 10000, "crystal": 10000, "deuterium": 10000},
            "storage_capacities": {"metal": 40000, "crystal": 40000, "deuterium": 40000},
            "energy": 20,
            "queue_busy": {"building": False, "research": False},
            "watch_action_id": None,
            "candidates": [
                {
                    "action_id": "supplies:1",
                    "section": "supplies",
                    "component": "supplies",
                    "queue": "building",
                    "tech_id": "1",
                    "can_upgrade": True,
                    "energy_safe": True,
                    "energy_delta": -10,
                    "costs": {"metal": 1000, "crystal": 500, "deuterium": 0},
                },
                {
                    "action_id": "research:117",
                    "section": "research",
                    "component": "research",
                    "queue": "research",
                    "tech_id": "117",
                    "can_upgrade": True,
                    "energy_safe": True,
                    "energy_delta": 0,
                    "costs": {"metal": 2000, "crystal": 2000, "deuterium": 500},
                },
            ],
        }

    @staticmethod
    def manual_workflow(workflow_id, steps):
        now = int(time.time())
        return WorkflowPlan(
            schema_version=1,
            workflow_id=workflow_id,
            run_id="run-1",
            created_at=now,
            expires_at=now + 600,
            confirmed_plan_id="confirmed-1",
            confirmed_plan_hash="snapshot-hash",
            safety_policy_version="1",
            strategy_policy_version="test",
            policy_precedence=POLICY_PRECEDENCE,
            steps=tuple(steps),
        )

    def test_safety_policy_is_frozen_and_non_configurable(self):
        self.assertEqual(SAFETY_POLICY.version, "2")
        self.assertEqual(SAFETY_POLICY.min_safe_energy, -20)
        self.assertEqual(SAFETY_POLICY.max_storage_spend_fraction, 0.90)
        self.assertFalse(SAFETY_POLICY.energy_is_safe(None, -10))
        self.assertFalse(SAFETY_POLICY.energy_is_safe(100, None))
        with self.assertRaises(FrozenInstanceError):
            SAFETY_POLICY.min_safe_energy = -21
        with self.assertRaises(TypeError):
            SafetyPolicy(min_safe_energy=-21)
        self.assertTrue(SAFETY_POLICY.forbid_dark_matter)
        self.assertIn("premium_control_rejected", ogame_ctl.apply_action_js(
            {"action_id": "x", "tech_id": "1", "costs": {"metal": 1, "crystal": 0, "deuterium": 0}},
            {"metal": 0, "crystal": 0, "deuterium": 0},
        ))

    def test_strategy_policy_uses_strict_versioned_schema(self):
        strategy = load_strategy_policy(DEFAULT_STRATEGY_PATH)
        self.assertEqual(strategy.schema_version, 1)
        self.assertEqual(strategy.policy_version, "2026-09-14.2")
        self.assertTrue(strategy.power_squeeze_enabled)
        self.assertEqual(strategy.target_energy, 0)

        invalid = """\
schema_version = 1
[strategy]
policy_version = "bad"
profile = "test"
[power_squeeze]
enabled = true
surplus_threshold = 30
target_energy = -21
preferred_economy_actions = ["metal_mine"]
[growth]
colonization_cycle_enabled = true
preferred_colony_position = 8
scan_radius = 2
max_candidates = 2
[logistics]
enabled = true
minimum_transport_amount = 1000
maximum_transport_per_resource = 10000
[farming]
enabled = true
minimum_raid_loot = 5000
max_targets = 10
max_concurrent_raids = 2
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir, "strategy.toml")
            path.write_text(invalid, encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "MIN_SAFE_ENERGY"):
                load_strategy_policy(path.as_posix())

        invalid_action = invalid.replace("target_energy = -21", "target_energy = 0").replace(
            'preferred_economy_actions = ["metal_mine"]',
            'preferred_economy_actions = ["unknown_action"]',
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir, "strategy.toml")
            path.write_text(invalid_action, encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "未知 typed action"):
                load_strategy_policy(path.as_posix())

    def test_typed_models_reject_executable_skill_payloads(self):
        intent = Intent.from_dict(
            {
                "schema_version": 1,
                "kind": "apply",
                "planet_id": "42",
                "confirmed_plan_id": "plan-1",
                "action_ids": ["supplies:1"],
            }
        )
        self.assertEqual(intent.action_ids, ("supplies:1",))
        with self.assertRaisesRegex(ValueError, "未知欄位"):
            Intent.from_dict(
                {
                    **intent.to_dict(),
                    "selector": "button.upgrade",
                }
            )
        with self.assertRaisesRegex(ValueError, "action_ids"):
            Intent.from_dict({**intent.to_dict(), "action_ids": [1]})

        result = ActionResult(ActionStatus.BLOCKED, "supplies:1", "42", "energy")
        self.assertEqual(result.to_dict()["status"], "blocked")
        with self.assertRaises(FrozenInstanceError):
            result.reason = "changed"

    def test_pure_planner_uses_policy_energy_and_storage_limits(self):
        base = {
            "can_upgrade": True,
            "costs": {"metal": 900, "crystal": 0, "deuterium": 0},
            "energy_safe": True,
        }
        at_floor = {**base, "action_id": "a", "queue": "q-a", "energy_delta": -25}
        below_floor = {**base, "action_id": "b", "queue": "q-b", "energy_delta": -26}
        resources = {"metal": 10000, "crystal": 10000, "deuterium": 10000}
        capacities = {"metal": 1000, "crystal": 1000, "deuterium": 1000}

        packages = feasible_packages(
            [at_floor, below_floor],
            resources,
            storage_capacities=capacities,
            initial_energy=5,
        )
        self.assertIn(["a"], [item["action_ids"] for item in packages])
        self.assertNotIn(["b"], [item["action_ids"] for item in packages])

        over_storage = {**base, "action_id": "c", "queue": "q-c", "costs": {"metal": 901, "crystal": 0, "deuterium": 0}, "energy_delta": 0}
        self.assertEqual(
            feasible_packages([over_storage], resources, storage_capacities=capacities, initial_energy=5),
            [],
        )

        self.assertEqual(feasible_packages([at_floor], resources, initial_energy=5), [])

    def test_workflow_plan_has_no_fixed_action_count_limit(self):
        strategy = load_strategy_policy(DEFAULT_STRATEGY_PATH)
        confirmed = self.confirmed_plan()
        confirmed["candidates"] = [
            {
                "action_id": f"research:test-{index}",
                "section": "research",
                "component": "research",
                "queue": f"independent-{index}",
                "tech_id": str(900 + index),
                "can_upgrade": True,
                "energy_safe": True,
                "energy_delta": 0,
                "costs": {"metal": 1, "crystal": 1, "deuterium": 0},
            }
            for index in range(6)
        ]
        intent = Intent.from_dict(
            {
                "schema_version": 1,
                "kind": "apply",
                "planet_id": "42",
                "confirmed_plan_id": "confirmed-1",
                "action_ids": [candidate["action_id"] for candidate in confirmed["candidates"]],
            }
        )

        plan = build_workflow_plan(intent, confirmed, "run-1", strategy, ACCOUNT_CONSTANTS)

        self.assertEqual(len(plan.steps), 6)

    def test_workflow_plan_is_built_only_from_confirmed_candidates(self):
        strategy = load_strategy_policy(DEFAULT_STRATEGY_PATH)
        intent = Intent.from_dict(
            {
                "schema_version": 1,
                "kind": "apply",
                "planet_id": "42",
                "confirmed_plan_id": "confirmed-1",
                "action_ids": ["supplies:1", "research:117"],
            }
        )
        plan = build_workflow_plan(intent, self.confirmed_plan(), "run-1", strategy, ACCOUNT_CONSTANTS)
        self.assertEqual(plan.policy_precedence, POLICY_PRECEDENCE)
        self.assertEqual([step.action_id for step in plan.steps], list(intent.action_ids))
        self.assertTrue(all(step.mutation for step in plan.steps))
        with self.assertRaises(TypeError):
            plan.steps[0].payload["candidate"]["tech_id"] = "999"

        unknown = Intent.from_dict({**intent.to_dict(), "action_ids": ["supplies:999"]})
        with self.assertRaisesRegex(RuntimeError, "不在 confirmed plan"):
            build_workflow_plan(unknown, self.confirmed_plan(), "run-1", strategy, ACCOUNT_CONSTANTS)

    def test_workflow_plan_fail_closes_on_unknown_energy_or_storage(self):
        strategy = load_strategy_policy(DEFAULT_STRATEGY_PATH)
        intent = Intent.from_dict(
            {
                "schema_version": 1,
                "kind": "apply",
                "planet_id": "42",
                "confirmed_plan_id": "confirmed-1",
                "action_ids": ["supplies:1"],
            }
        )
        no_energy = self.confirmed_plan()
        no_energy["energy"] = None
        with self.assertRaisesRegex(RuntimeError, "能源"):
            build_workflow_plan(intent, no_energy, "run-1", strategy, ACCOUNT_CONSTANTS)

        no_storage = self.confirmed_plan()
        no_storage["storage_capacities"] = {}
        with self.assertRaisesRegex(RuntimeError, "倉庫"):
            build_workflow_plan(intent, no_storage, "run-1", strategy, ACCOUNT_CONSTANTS)

    def test_typed_transport_candidate_enters_workflow_without_exposing_payload_to_skill(self):
        now = int(time.time())
        confirmed = self.confirmed_plan(now)
        candidate = {
            "action_id": "fleet:transport:opaque-1",
            "operation": "fleet_dispatch",
            "planet_id": "42",
            "queue": "fleet",
            "can_apply": True,
            "mission": "transport",
            "target": {"galaxy": 1, "system": 41, "position": 8},
            "ship_tech": "202",
            "ship_amount": 1,
            "ships_before": {"202": 2},
            "fleet_slots": {"free": 3},
            "payload": {"metal": 1000, "crystal": 0, "deuterium": 0},
            "target_resources": {"metal": 1000, "crystal": 1000, "deuterium": 1000},
            "target_storage_capacities": {"metal": 40000, "crystal": 40000, "deuterium": 40000},
            "owner_authorized_large_transport": False,
            "target_evidence": {
                "owned_planet": True,
                "destroyed": False,
                "vacation": False,
            },
        }
        confirmed["candidates"] = [candidate]
        intent = Intent.from_dict({
            "schema_version": 1,
            "kind": "apply",
            "planet_id": "42",
            "confirmed_plan_id": "confirmed-1",
            "action_ids": [candidate["action_id"]],
        })

        workflow = build_workflow_plan(
            intent,
            confirmed,
            "run-1",
            load_strategy_policy(DEFAULT_STRATEGY_PATH),
            ACCOUNT_CONSTANTS,
            now=now,
        )

        self.assertEqual(workflow.steps[0].action_id, candidate["action_id"])
        self.assertNotIn("target", intent.to_dict())
        self.assertEqual(workflow.steps[0].payload["candidate"]["mission"], "transport")

    def test_fleet_candidate_policy_rejects_unknown_raid_evidence_and_unauthorized_large_transport(self):
        now = int(time.time())
        confirmed = self.confirmed_plan(now)
        raid = {
            "action_id": "fleet:raid:opaque-1",
            "operation": "fleet_dispatch",
            "can_apply": True,
            "mission": "raid",
            "target": {"galaxy": 1, "system": 40, "position": 7},
            "ship_tech": "202",
            "ship_amount": 1,
            "ships_before": {"202": 2},
            "fleet_slots": {"free": 3},
            "payload": {"metal": 0, "crystal": 0, "deuterium": 0},
            "target_evidence": {
                "inactive": True,
                "destroyed": False,
                "vacation": False,
                "defense_count": None,
                "fleet_count": 0,
                "report_observed_at": now,
                "attacks_24h": 0,
            },
        }
        with self.assertRaisesRegex(RuntimeError, "defense_count"):
            assess_workflow_candidate(
                raid,
                confirmed,
                constants=ACCOUNT_CONSTANTS,
                now=now,
            )

        transport = {
            **raid,
            "action_id": "fleet:transport:opaque-2",
            "mission": "transport",
            "ship_tech": "203",
            "ships_before": {"203": 2},
            "target_evidence": {"owned_planet": True, "destroyed": False, "vacation": False},
            "payload": {"metal": 21000, "crystal": 0, "deuterium": 0},
            "target_resources": {"metal": 0, "crystal": 0, "deuterium": 0},
            "target_storage_capacities": {"metal": 40000, "crystal": 40000, "deuterium": 40000},
            "owner_authorized_large_transport": False,
        }
        with self.assertRaisesRegex(RuntimeError, "User授權"):
            assess_workflow_candidate(
                transport,
                confirmed,
                constants=ACCOUNT_CONSTANTS,
                now=now,
            )

    def test_patrol_fleet_candidate_builder_emits_only_typed_alternatives(self):
        now = int(time.time())
        built = build_patrol_fleet_candidates(
            planet_id="42",
            origin_resources={"metal": 20000, "crystal": 10000, "deuterium": 10000},
            origin_storage_capacities={"metal": 40000, "crystal": 40000, "deuterium": 40000},
            watch_costs={"metal": 5000, "crystal": 0, "deuterium": 0},
            ships_before={"202": 4, "203": 1, "208": 1, "210": 2},
            fleet_slots={"free": 3, "used": 0, "total": 3},
            owned_targets=[{
                "planet_id": "43",
                "target": {"galaxy": 1, "system": 2, "position": 8},
                "resources": {"metal": 1000, "crystal": 1000, "deuterium": 1000},
                "storage_capacities": {"metal": 40000, "crystal": 40000, "deuterium": 40000},
            }],
            farming_suggestions={
                "probes_to_send": [{
                    "coords": "[1:3:7]", "galaxy": 1, "system": 3, "position": 7, "probes": 1,
                }],
                "raids_to_launch": [],
            },
            live_farming_evidence={
                "[1:3:7]": {
                    "owned_planet": False, "empty": False, "inactive": True,
                    "destroyed": False, "vacation": False,
                },
            },
            empty_colony_targets=[{"galaxy": 1, "system": 4, "position": 8}],
            strategy=load_strategy_policy(DEFAULT_STRATEGY_PATH),
            constants=ACCOUNT_CONSTANTS,
            observed_at=now,
        )

        self.assertEqual(
            {candidate["mission"] for candidate in built["candidates"]},
            {"transport", "spy", "colonize"},
        )
        provisional = {
            "planet_id": "42",
            "storage_capacities": {"metal": 40000, "crystal": 40000, "deuterium": 40000},
        }
        for candidate in built["candidates"]:
            self.assertTrue(candidate["action_id"].startswith("fleet:"))
            self.assertEqual(candidate["queue"], "fleet")
            assess_workflow_candidate(
                candidate,
                provisional,
                constants=ACCOUNT_CONSTANTS,
                now=now,
            )

    def test_feasible_packages_accounts_for_transport_payload_and_single_fleet_queue(self):
        transport = {
            "action_id": "fleet:a", "operation": "fleet_dispatch", "mission": "transport",
            "queue": "fleet", "can_apply": True, "energy_safe": True,
            "costs": {"metal": 0, "crystal": 0, "deuterium": 0},
            "payload": {"metal": 8000, "crystal": 0, "deuterium": 0},
        }
        upgrade = {
            "action_id": "supplies:1", "queue": "building", "can_upgrade": True,
            "energy_safe": True, "energy_delta": 0,
            "costs": {"metal": 3000, "crystal": 0, "deuterium": 0},
        }
        packages = feasible_packages(
            [transport, upgrade],
            {"metal": 10000, "crystal": 0, "deuterium": 0},
            storage_capacities={"metal": 40000, "crystal": 40000, "deuterium": 40000},
            initial_energy=0,
        )
        self.assertIn(["fleet:a"], [item["action_ids"] for item in packages])
        self.assertNotIn(["fleet:a", "supplies:1"], [item["action_ids"] for item in packages])

    def test_fleet_prevalidation_blocks_changed_stationed_ship_state(self):
        candidate = {
            "action_id": "fleet:transport:opaque-3",
            "operation": "fleet_dispatch",
            "planet_id": "42",
            "queue": "fleet",
            "can_apply": True,
            "mission": "transport",
            "target": {"galaxy": 1, "system": 41, "position": 8},
            "ship_tech": "202",
            "ship_amount": 1,
            "ships_before": {"202": 2},
            "fleet_slots": {"free": 3},
            "payload": {"metal": 1000, "crystal": 0, "deuterium": 0},
            "target_resources": {"metal": 0, "crystal": 0, "deuterium": 0},
            "target_storage_capacities": {"metal": 40000, "crystal": 40000, "deuterium": 40000},
            "owner_authorized_large_transport": False,
            "target_evidence": {"owned_planet": True, "destroyed": False, "vacation": False},
        }
        pinned = {
            "planet_id": "42",
            "fleet_state": {
                "ships": {"202": 3},
                "fleet_slots": {"known": True, "free": 3, "used": 0, "total": 3},
                "resources": {"metal": 10000, "crystal": 10000, "deuterium": 10000},
            },
            "origin_storage_capacities": {"metal": 40000, "crystal": 40000, "deuterium": 40000},
            "target_evidence": candidate["target_evidence"],
            "target_resources": candidate["target_resources"],
            "target_storage_capacities": candidate["target_storage_capacities"],
        }

        result = ogame_ctl.prevalidate_fleet_dispatch(
            candidate,
            pinned,
            self.confirmed_plan(),
            {"metal": 0, "crystal": 0, "deuterium": 0},
            ACCOUNT_CONSTANTS,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "stationed_ship_state_changed")

    def test_workflow_runner_parallel_reads_then_serializes_and_stops_on_uncertain(self):
        steps = (
            WorkflowStep("read-01", IntentKind.READ, "read:a", "42", False),
            WorkflowStep("read-02", IntentKind.READ, "read:b", "42", False),
            WorkflowStep("apply-01", IntentKind.APPLY, "apply:a", "42", True),
            WorkflowStep("apply-02", IntentKind.APPLY, "apply:b", "42", True),
        )
        plan = self.manual_workflow("wf-uncertain", steps)
        barrier = threading.Barrier(2)
        calls = []
        lock = threading.Lock()

        def execute(step, _run_id):
            with lock:
                calls.append(step.step_id)
            if step.kind == IntentKind.READ:
                barrier.wait(timeout=1)
                return ActionResult(ActionStatus.APPLIED, step.action_id, step.planet_id)
            if step.step_id == "apply-01":
                return ActionResult(ActionStatus.UNCERTAIN, step.action_id, step.planet_id, "missing_postcondition")
            return ActionResult(ActionStatus.APPLIED, step.action_id, step.planet_id)

        with tempfile.TemporaryDirectory() as tmpdir:
            journal = WorkflowJournal(tmpdir)
            journal.create(plan)
            state = WorkflowRunner(journal, execute).run(plan.workflow_id, "run-1")
            self.assertEqual(state["status"], "uncertain")
            self.assertTrue(pathlib.Path(journal.active_dir, f"{plan.workflow_id}.json").exists())

        self.assertIn("read-01", calls)
        self.assertIn("read-02", calls)
        self.assertIn("apply-01", calls)
        self.assertNotIn("apply-02", calls)

    def test_workflow_runner_serializes_mutations_across_workflows(self):
        active = 0
        maximum_active = 0
        counter_lock = threading.Lock()

        def execute(step, _run_id):
            nonlocal active, maximum_active
            with counter_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.02)
            with counter_lock:
                active -= 1
            return ActionResult(ActionStatus.APPLIED, step.action_id, step.planet_id)

        with tempfile.TemporaryDirectory() as tmpdir:
            journal = WorkflowJournal(tmpdir)
            plans = [
                self.manual_workflow(
                    f"wf-serial-{index}",
                    (WorkflowStep("apply-01", IntentKind.APPLY, f"apply:{index}", "42", True),),
                )
                for index in range(2)
            ]
            for plan in plans:
                journal.create(plan)
            states = []

            def run(plan):
                states.append(WorkflowRunner(journal, execute).run(plan.workflow_id, "run-1"))

            threads = [threading.Thread(target=run, args=(plan,)) for plan in plans]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)

        self.assertEqual(len(states), 2)
        self.assertTrue(all(state["status"] == "completed" for state in states))
        self.assertEqual(maximum_active, 1)

    def test_workflow_journal_archives_completion_and_guards_resume(self):
        applied_step = WorkflowStep("apply-01", IntentKind.APPLY, "apply:a", "42", True)
        complete_plan = self.manual_workflow("wf-complete", (applied_step,))

        with tempfile.TemporaryDirectory() as tmpdir:
            journal = WorkflowJournal(tmpdir)
            journal.create(complete_plan)
            state = WorkflowRunner(
                journal,
                lambda step, _run_id: ActionResult(ActionStatus.APPLIED, step.action_id, step.planet_id),
            ).run(complete_plan.workflow_id, "run-1")
            self.assertEqual(state["status"], "completed")
            self.assertFalse(pathlib.Path(journal.active_dir, "wf-complete.json").exists())
            self.assertTrue(pathlib.Path(journal.archive_dir, "wf-complete.json").exists())

            certain_plan = self.manual_workflow("wf-certain", (applied_step,))
            journal.create(certain_plan)
            journal.start(certain_plan.workflow_id, "run-1")
            journal.mark_interrupted(certain_plan.workflow_id, state_certain=True)
            resumed = journal.start(certain_plan.workflow_id, "run-2")
            self.assertEqual(resumed["active_run_id"], "run-2")
            self.assertEqual(resumed["lease_history"], ["run-1", "run-2"])

            uncertain_plan = self.manual_workflow("wf-interrupted-uncertain", (applied_step,))
            journal.create(uncertain_plan)
            journal.start(uncertain_plan.workflow_id, "run-1")
            journal.mark_interrupted(uncertain_plan.workflow_id, state_certain=False)
            with self.assertRaisesRegex(RuntimeError, "不確定"):
                journal.start(uncertain_plan.workflow_id, "run-2")

            in_flight_plan = self.manual_workflow("wf-in-flight", (applied_step,))
            journal.create(in_flight_plan)
            journal.start(in_flight_plan.workflow_id, "run-1")
            journal.begin_stateful_step(in_flight_plan.workflow_id, applied_step)
            in_flight = journal.load(in_flight_plan.workflow_id)
            self.assertEqual(in_flight["state_certainty"], "uncertain")
            self.assertEqual(in_flight["in_flight_step_id"], "apply-01")
            with self.assertRaisesRegex(RuntimeError, "in-flight"):
                journal.mark_interrupted(in_flight_plan.workflow_id, state_certain=True)
            with self.assertRaisesRegex(RuntimeError, "in-flight mutation"):
                journal.start(in_flight_plan.workflow_id, "run-2")

            duplicate_plan = self.manual_workflow("wf-duplicate-step", (applied_step,))
            journal.create(duplicate_plan)
            journal.start(duplicate_plan.workflow_id, "run-1")
            journal.begin_stateful_step(duplicate_plan.workflow_id, applied_step)
            journal.append_result(
                duplicate_plan.workflow_id,
                ActionResult(
                    ActionStatus.APPLIED,
                    applied_step.action_id,
                    applied_step.planet_id,
                    evidence={"workflow_step_id": applied_step.step_id},
                ),
            )
            with self.assertRaisesRegex(RuntimeError, "拒絕重複"):
                journal.begin_stateful_step(duplicate_plan.workflow_id, applied_step)

    def test_workflow_cli_plans_runs_and_archives_without_browser_access(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = pathlib.Path(tmpdir, "patrol-plan.json")
            intent_path = pathlib.Path(tmpdir, "intent.json")
            workflow_root = pathlib.Path(tmpdir, "workflows")
            confirmed = self.confirmed_plan()
            ogame_ctl.atomic_write_json(plan_path.as_posix(), confirmed)
            intent_path.write_text(json.dumps({
                "schema_version": 1,
                "kind": "apply",
                "planet_id": "42",
                "confirmed_plan_id": "confirmed-1",
                "action_ids": ["supplies:1"],
            }), encoding="utf-8")

            with patch.object(ogame_ctl, "PLAN_FILE", plan_path.as_posix()), \
                 patch.object(ogame_ctl, "WORKFLOW_DIR", workflow_root.as_posix()), \
                 patch.object(ogame_ctl, "require_run_lease"):
                planned = ogame_ctl.command_workflow_plan(argparse.Namespace(
                    intent_file=intent_path.as_posix(),
                    run_id="run-1",
                    strategy=DEFAULT_STRATEGY_PATH,
                ))
                self.assertEqual(planned["status"], "pending")

                run_args = argparse.Namespace(
                    workflow_id=planned["workflow_id"], run_id="run-1", confirm=False,
                )
                with self.assertRaisesRegex(RuntimeError, "--confirm"):
                    ogame_ctl.command_workflow_run(run_args)

                run_args.confirm = True
                typed_result = ActionResult(
                    ActionStatus.APPLIED, "supplies:1", "42", evidence={"mocked": True},
                ).to_dict()
                with patch.object(ogame_ctl, "command_apply", return_value=typed_result) as apply:
                    completed = ogame_ctl.command_workflow_run(run_args)

                self.assertEqual(completed["status"], "completed")
                self.assertEqual(completed["steps_finished"], 1)
                apply.assert_called_once()
                self.assertTrue(apply.call_args.args[0].mutation_lock_held)
                archived = ogame_ctl.command_workflow_status(argparse.Namespace(
                    workflow_id=planned["workflow_id"],
                ))
                self.assertEqual(archived["status"], "completed")
                self.assertFalse((workflow_root / "active" / f"{planned['workflow_id']}.json").exists())
                self.assertTrue((workflow_root / "archive" / f"{planned['workflow_id']}.json").exists())

    def test_private_browser_primitive_is_injectable_without_ogame_connection(self):
        scripts = []

        def fake_applescript(script):
            scripts.append(script)
            return '{"success":true,"value":"測試"}'

        result = _execute_in_game_tab(
            "JSON.stringify({success:true})",
            target_url="https://s1-en.ogame.gameforge.com/game/index.php?page=ingame&component=supplies&cp=42",
            applescript_runner=fake_applescript,
        )
        self.assertEqual(result["value"], "測試")
        self.assertEqual(len(scripts), 1)
        self.assertIn("cp=42", scripts[0])
        self.assertIn("window.atob", scripts[0])
        self.assertIn('contains "page=standalone"', scripts[0])
        self.assertIn('contains "component=empire"', scripts[0])

        movement_scripts = []
        _execute_in_game_tab(
            "JSON.stringify({success:true})",
            target_url="https://s1-en.ogame.gameforge.com/game/index.php?page=ingame&component=movement",
            applescript_runner=lambda script: movement_scripts.append(script) or '{"success":true}',
        )
        self.assertIn("c === 'movement' || c === 'fleetdispatch'", movement_scripts[0])

        with self.assertRaisesRegex(RuntimeError, "找不到 OGame"):
            _execute_in_game_tab("1", applescript_runner=lambda _script: "NO_OGAME_TAB")

    def test_public_mutation_atom_returns_all_typed_statuses(self):
        candidate = {"action_id": "supplies:1"}
        calls = []

        def callbacks(*, pin=None, validation=None, execution=None, verification=None):
            return PlannedMutationCallbacks(
                pin_and_read=lambda _candidate, _planet: calls.append("pin") or (pin or {"planet_id": "42"}),
                prevalidate=lambda _candidate, _pinned: calls.append("prevalidate") or (validation or {"ok": True}),
                execute=lambda _candidate, _planet: calls.append("execute") or (execution or {"success": True}),
                read_postcondition=lambda _candidate, _planet: calls.append("post-read") or {"level": 12},
                verify_postcondition=lambda _candidate, _execution, _after: calls.append("post-verify") or (verification or {"success": True}),
            )

        applied = apply_planned_action_atom(candidate, 42, callbacks())
        self.assertEqual(applied.status, ActionStatus.APPLIED)
        self.assertEqual(calls, ["pin", "prevalidate", "execute", "post-read", "post-verify"])

        calls.clear()
        blocked = apply_planned_action_atom(candidate, 42, callbacks(validation={"ok": False, "reason": "cost"}))
        self.assertEqual(blocked.status, ActionStatus.BLOCKED)
        self.assertEqual(calls, ["pin", "prevalidate"])

        calls.clear()
        skipped = apply_planned_action_atom(candidate, 42, callbacks(validation={"ok": False, "skip": True}))
        self.assertEqual(skipped.status, ActionStatus.SKIPPED)
        self.assertEqual(calls, ["pin", "prevalidate"])

        calls.clear()
        uncertain = apply_planned_action_atom(
            candidate,
            42,
            callbacks(verification={"success": False, "reasons": ["missing_evidence"]}),
        )
        self.assertEqual(uncertain.status, ActionStatus.UNCERTAIN)
        self.assertEqual(calls, ["pin", "prevalidate", "execute", "post-read", "post-verify"])

        calls.clear()
        known_no_click = apply_planned_action_atom(
            candidate,
            42,
            callbacks(execution={"success": False, "mutation_submitted": False, "reason": "button_disabled"}),
        )
        self.assertEqual(known_no_click.status, ActionStatus.BLOCKED)


if __name__ == "__main__":
    unittest.main()
