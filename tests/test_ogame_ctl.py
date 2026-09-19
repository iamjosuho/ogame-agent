import argparse
import importlib.util
import json
import os
import pathlib
import tempfile
import time
import unittest
from unittest.mock import patch


SCRIPT = pathlib.Path(__file__).parents[1] / "scripts" / "ogame_ctl.py"
SPEC = importlib.util.spec_from_file_location("ogame_ctl", SCRIPT)
ogame_ctl = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ogame_ctl)
import sys
sys.modules["scripts.ogame_ctl"] = ogame_ctl


class OGameControllerTests(unittest.TestCase):
    @staticmethod
    def official_account_info_fixture():
        return {
            "playerId": 7,
            "playerName": "must-not-enter-stable-contract",
            "characterClassId": 3,
            "allianceClassId": None,
            "officers": {"commander": True, "admiral": False},
            "researches": {"106": 4, "124": 2},
            "newAjaxToken": "must-not-enter-stable-contract",
            "planets": {
                "42": {
                    "id": 42,
                    "galaxy": 1,
                    "system": 1,
                    "position": 1,
                    "resources": {"metal": 1234, "crystal": 567, "deuterium": 89, "energy": -20},
                    "production": {"metal": 8457.9, "crystal": 5612.6, "deuterium": 2380.3},
                    "baseProduction": {"metal": 150, "crystal": 75, "deuterium": 0},
                    "buildings": {"1": 13, "14": 6, "22": 4, "23": 5, "24": 2},
                    "ships": {"202": 3},
                    "defenses": {"401": 14},
                    "speciesBuildings": {"11101": 5},
                    "speciesResearches": [],
                }
            },
        }

    @staticmethod
    def empire_raw_fixture():
        return {
            "success": True,
            "planets": [{
                "planet_id": "42",
                "name": "Home",
                "coords": "[1:1:1]",
                "equipment": ["No items equipped"],
                "fields": {"used": 117, "total": 173},
                "energy": -20,
                "temperature": {"min": -13, "max": 27},
                "groups": {
                    "resources": {"metal": 1234, "crystal": 567, "deuterium": 89, "food": 10, "population": 20},
                    "storage": {"metalStorage": 140000, "crystalStorage": 255000, "deuteriumStorage": 40000, "foodStorage": 100, "populationStorage": 200},
                    "supply": {"1": 13, "22": 4, "23": 5, "24": 2},
                    "station": {"14": 6, "31": 4},
                    "research": {"106": 4, "124": 2},
                    "ships": {"202": 3, "212": 7},
                    "defence": {"401": 14},
                    "lifeform1buildings": {"11101": 5},
                    "lifeform1research": {"11201": 1},
                },
                "queues": [
                    {"group": "supply", "technology_id": "1", "current": 13, "active_target": 14, "queued_targets": [], "summary": "Metal Mine"},
                    {"group": "lifeform1buildings", "technology_id": "11101", "current": 5, "active_target": 6, "queued_targets": [7], "summary": "Residential Sector"},
                ],
            }],
        }

    def test_game_url_pins_a_planet_and_encodes_parameters(self):
        url = ogame_ctl.game_url("galaxy", 12345678, galaxy=1, system=1)
        self.assertIn("component=galaxy", url)
        self.assertIn("cp=12345678", url)
        self.assertIn("galaxy=1", url)
        self.assertIn("system=1", url)

    def test_empire_url_is_fixed_same_origin_standalone_read(self):
        self.assertEqual(
            ogame_ctl.empire_url(),
            "https://s1-en.ogame.gameforge.com/game/index.php?page=standalone&component=empire",
        )
        gate = ogame_ctl.checked_js("JSON.stringify({success:true})")
        self.assertIn('page === "standalone"', gate)
        self.assertIn('component === "empire"', gate)

    def test_mutation_requires_explicit_confirmation(self):
        with self.assertRaisesRegex(RuntimeError, "--confirm"):
            ogame_ctl.require_confirmed_mutation(argparse.Namespace(planet_id=42, confirm=False))
        with self.assertRaisesRegex(RuntimeError, "--planet-id"):
            ogame_ctl.require_confirmed_mutation(argparse.Namespace(planet_id=None, confirm=True))

    def test_galaxy_spy_shortcut_dispatches_exactly_one_probe_without_fleet_form(self):
        candidate = {
            "action_id": "fleet:spy:one",
            "mission": "spy",
            "ship_amount": 1,
            "target": {"galaxy": 1, "system": 42, "position": 7},
        }
        with patch.object(ogame_ctl, "execute_in_game_tab", return_value={
            "success": True,
            "mutation_submitted": True,
            "dispatch_path": "galaxy_quick_spy",
        }) as execute:
            result = ogame_ctl.execute_galaxy_spy_shortcut(candidate, 99)

        self.assertTrue(result["success"])
        js_code = execute.call_args.args[0]
        target_url = execute.call_args.kwargs["target_url"]
        self.assertIn("window.sendShips(6, 1, 42, 7, 1, 1)", js_code)
        self.assertIn("galaxy_spy_shortcut_unavailable", js_code)
        self.assertIn("component=galaxy", target_url)
        self.assertIn("cp=99", target_url)
        self.assertNotIn("component=fleetdispatch", target_url)

    def test_galaxy_spy_shortcut_rejects_more_than_one_probe(self):
        with self.assertRaisesRegex(RuntimeError, "只允許一架"):
            ogame_ctl.galaxy_spy_shortcut_js({
                "mission": "spy",
                "ship_amount": 2,
                "target": {"galaxy": 1, "system": 42, "position": 7},
            })

    def test_spy_apply_selects_galaxy_shortcut_instead_of_fleet_form(self):
        candidate = {
            "action_id": "fleet:spy:one",
            "operation": "fleet_dispatch",
            "section": "fleet",
            "can_apply": True,
            "mission": "spy",
            "ship_amount": 1,
            "target": {"galaxy": 1, "system": 42, "position": 7},
        }
        plan = {
            "plan_id": "plan-spy",
            "planet_id": "99",
            "action_count": 0,
            "candidates": [candidate],
            "watch_action_id": None,
            "watch_costs": {"metal": 0, "crystal": 0, "deuterium": 0},
        }

        def fake_atom(selected, planet_id, callbacks):
            callbacks.execute(selected, planet_id)
            return ogame_ctl.ActionResult(
                ogame_ctl.ActionStatus.BLOCKED,
                selected["action_id"],
                str(planet_id),
                "test_stop_after_route_selection",
            )

        args = argparse.Namespace(
            plan_id="plan-spy",
            action_id="fleet:spy:one",
            planet_id=99,
            run_id="run-1",
            confirm=True,
            mutation_lock_held=True,
            output="json",
            silent=True,
        )
        with patch.object(ogame_ctl, "require_active_plan", return_value=plan), \
             patch.object(ogame_ctl, "assess_workflow_candidate"), \
             patch.object(ogame_ctl, "apply_planned_action_atom", side_effect=fake_atom), \
             patch.object(ogame_ctl, "execute_galaxy_spy_shortcut", return_value={
                 "success": False, "mutation_submitted": False, "reason": "test",
             }) as quick_spy, \
             patch.object(ogame_ctl, "execute_checked_component_followup") as fleet_form, \
             patch.object(ogame_ctl, "atomic_write_json"), \
             patch("time.sleep", return_value=None):
            result = ogame_ctl.command_apply(args)

        self.assertEqual(result["status"], "blocked")
        quick_spy.assert_called_once_with(candidate, 99)
        fleet_form.assert_not_called()

    def test_sync_pins_every_page_to_the_requested_planet(self):
        calls = []

        def fake_execute(_js_code, wait_after_nav=3.0, target_url=None):
            calls.append(target_url)
            if "component=overview" in target_url:
                return {"metal": 100, "crystal": 200, "deuterium": 300, "planetId": "42"}
            if "component=supplies" in target_url:
                return {"22": {"level": 2}, "23": {"level": 2}, "24": {"level": 2}}
            return {}

        with patch.object(ogame_ctl, "execute_in_game_tab", side_effect=fake_execute):
            state = ogame_ctl.cmd_sync(argparse.Namespace(planet_id=42))

        self.assertEqual(state["planet_id"], "42")
        self.assertEqual(len(calls), 6)
        self.assertTrue(all("cp=42" in call for call in calls))

    def test_build_compatibility_wrapper_uses_a_fresh_plan_and_pinned_apply(self):
        args = argparse.Namespace(tech_id=1, planet_id=42, run_id="run-1", confirm=True)
        with patch.object(ogame_ctl, "command_plan", return_value={
                 "plan_id": "fresh-plan",
                 "candidates": [{"action_id": "supplies:1"}],
             }) as plan, \
             patch.object(ogame_ctl, "command_apply", return_value={
                 "success": True, "status": "applied",
             }) as apply:
            result = ogame_ctl.cmd_build(args)

        self.assertTrue(result["success"])
        self.assertEqual(plan.call_args.args[0].planet_id, 42)
        self.assertEqual(plan.call_args.args[0].run_id, "run-1")
        applied_args = apply.call_args.args[0]
        self.assertEqual(applied_args.plan_id, "fresh-plan")
        self.assertEqual(applied_args.action_id, "supplies:1")
        self.assertEqual(applied_args.planet_id, 42)

    def test_lifeform_read_wrapper_pins_both_components(self):
        calls = []

        def fake_read(component, planet_id):
            calls.append((component, planet_id))
            return {"success": True, "planet_id": str(planet_id), "items": {}}

        with patch.object(ogame_ctl, "read_technology_list", side_effect=fake_read):
            result = ogame_ctl.cmd_lifeform(argparse.Namespace(
                planet_id=42, output="json", silent=True,
            ))

        self.assertTrue(result["success"])
        self.assertEqual(calls, [("lfbuildings", 42), ("lfresearch", 42)])

    def test_lifeform_build_compatibility_wrapper_selects_only_fresh_typed_candidate(self):
        candidate = {
            "action_id": "lifeform:opaque",
            "operation": "lifeform_upgrade",
            "component": "lfresearch",
            "tech_id": "11201",
            "can_apply": True,
        }
        args = argparse.Namespace(
            tech_id=11201,
            component="lfresearch",
            planet_id=42,
            run_id="run-1",
            confirm=True,
            output="json",
        )
        with patch.object(ogame_ctl, "command_plan", return_value={
                 "plan_id": "fresh-plan", "candidates": [candidate],
             }) as plan, patch.object(ogame_ctl, "command_apply", return_value={
                 "status": "applied", "success": True,
             }) as apply:
            result = ogame_ctl.cmd_lifeform_build(args)

        self.assertTrue(result["success"])
        self.assertTrue(plan.call_args.args[0].include_lifeforms)
        self.assertEqual(apply.call_args.args[0].action_id, "lifeform:opaque")

    def test_lifeform_building_candidate_fails_closed_when_energy_delta_is_unknown(self):
        candidate = ogame_ctl.lifeform_action_from_item(
            "lfbuildings",
            "11101",
            {
                "level": 1,
                "name": "Residential Sector",
                "can_upgrade": True,
                "costs_raw": "金屬 100 水晶 100 重氫 0",
                "energy_raw": "",
            },
            {"metal": 1000, "crystal": 1000, "deuterium": 1000},
            100,
            42,
        )

        self.assertIsNotNone(candidate)
        self.assertFalse(candidate["energy_delta_known"])
        self.assertFalse(candidate["can_apply"])

    def test_cancel_building_wrapper_uses_only_fresh_queue_token_candidate(self):
        candidate = {
            "action_id": "cancel:opaque",
            "operation": "cancel_building",
        }
        args = argparse.Namespace(
            planet_id=42, run_id="run-1", confirm=True, output="json",
        )
        with patch.object(ogame_ctl, "command_plan", return_value={
                 "plan_id": "fresh-plan", "candidates": [candidate],
             }) as plan, patch.object(ogame_ctl, "command_apply", return_value={
                 "status": "applied", "success": True,
             }) as apply:
            result = ogame_ctl.cmd_cancel_building(args)

        self.assertTrue(result["success"])
        self.assertTrue(plan.call_args.args[0].include_cancel)
        self.assertEqual(apply.call_args.args[0].action_id, "cancel:opaque")

    def test_cancel_building_apply_requires_pin_prevalidation_and_queue_clear_postcondition(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = pathlib.Path(tmpdir, "plan.json").as_posix()
            wake_path = pathlib.Path(tmpdir, "wake.txt").as_posix()
            queue = {
                "active": True,
                "queue_token": "1|100|200|Metal Mine 12",
                "tech_id": "1",
                "summary": "Metal Mine 12",
                "cancel_available": True,
            }
            candidate = ogame_ctl.cancel_building_action_from_snapshot(
                {"building_queue": queue}, 42,
            )
            self.assertIsNotNone(candidate)
            ogame_ctl.atomic_write_json(plan_path, {
                "plan_id": "cancel-plan",
                "planet_id": "42",
                "expires_at": int(time.time()) + 1000,
                "action_count": 0,
                "resources": {"metal": 5000, "crystal": 5000, "deuterium": 5000},
                "watch_costs": {"metal": 0, "crystal": 0, "deuterium": 0},
                "rates": {"metal": 0, "crystal": 0, "deuterium": 0},
                "candidates": [candidate],
                "status": "active",
            })
            pre = {
                "success": True,
                "planet_id": "42",
                "building_queue": queue,
                "items": {},
                "resources": {"metal": 5000, "crystal": 5000, "deuterium": 5000},
            }
            post = {
                "success": True,
                "planet_id": "42",
                "building_queue": {"active": False, "queue_token": "", "cancel_available": False},
                "items": {},
                "resources": {"metal": 5500, "crystal": 5250, "deuterium": 5000},
            }
            with patch.object(ogame_ctl, "PLAN_FILE", plan_path), \
                 patch.object(ogame_ctl, "NEXT_WAKE_FILE", wake_path), \
                 patch.object(ogame_ctl, "read_technology_list", side_effect=[pre, post]) as reads, \
                 patch.object(ogame_ctl, "read_header_snapshot", return_value={
                     "resources": pre["resources"], "energy": 100,
                 }), \
                 patch.object(ogame_ctl, "execute_checked_component_result", return_value={
                     "success": True,
                     "mutation_submitted": True,
                     "queue_token": queue["queue_token"],
                 }), \
                 patch("time.sleep", return_value=None):
                result = ogame_ctl.command_apply(argparse.Namespace(
                    plan_id="cancel-plan",
                    action_id=candidate["action_id"],
                    planet_id=42,
                    run_id=None,
                    confirm=True,
                    output="json",
                    silent=True,
                ))

        self.assertEqual(result["status"], "applied")
        self.assertTrue(result["postcondition"]["evidence"]["queue_cleared"])
        self.assertEqual(reads.call_count, 2)

    def test_produce_wrapper_resolves_exact_amount_to_fresh_typed_candidate(self):
        candidate = {
            "action_id": "produce:opaque",
            "operation": "produce",
            "tech_id": "202",
            "amount": 2,
            "can_apply": True,
        }
        args = argparse.Namespace(
            tech_id=202, amount=2, planet_id=42, run_id="run-1", confirm=True, output="json",
        )
        with patch.object(ogame_ctl, "command_plan", return_value={
                 "plan_id": "fresh-plan", "candidates": [candidate],
             }) as plan, patch.object(ogame_ctl, "command_apply", return_value={
                 "status": "applied", "success": True,
             }) as apply:
            result = ogame_ctl.cmd_produce(args)

        self.assertTrue(result["success"])
        self.assertEqual(plan.call_args.args[0].production_request, ("202", 2))
        self.assertEqual(apply.call_args.args[0].action_id, "produce:opaque")

    def test_production_apply_requires_cost_revalidation_and_target_postcondition(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = pathlib.Path(tmpdir, "plan.json").as_posix()
            wake_path = pathlib.Path(tmpdir, "wake.txt").as_posix()
            candidate = ogame_ctl.production_action_from_item(
                "shipyard",
                "202",
                {
                    "level": 0,
                    "name": "Small Cargo",
                    "can_upgrade": True,
                    "costs_raw": "金屬 2,000 水晶 2,000 重氫 0",
                },
                {"metal": 10000, "crystal": 10000, "deuterium": 10000},
                42,
                2,
            )
            self.assertIsNotNone(candidate)
            ogame_ctl.atomic_write_json(plan_path, {
                "plan_id": "produce-plan",
                "planet_id": "42",
                "expires_at": int(time.time()) + 1000,
                "action_count": 0,
                "resources": {"metal": 10000, "crystal": 10000, "deuterium": 10000},
                "storage_capacities": {"metal": 40000, "crystal": 40000, "deuterium": 40000},
                "watch_costs": {"metal": 0, "crystal": 0, "deuterium": 0},
                "rates": {"metal": 0, "crystal": 0, "deuterium": 0},
                "candidates": [candidate],
                "status": "active",
            })
            pre = {
                "success": True,
                "planet_id": "42",
                "items": {"202": {
                    "level": 0,
                    "can_upgrade": True,
                    "costs_raw": "金屬 2,000 水晶 2,000 重氫 0",
                }},
                "queue_busy": {"shipyard": False},
                "production_queue": {"active": False, "entries": []},
                "resources": {"metal": 10000, "crystal": 10000, "deuterium": 10000},
            }
            post = {
                "success": True,
                "planet_id": "42",
                "items": {"202": {"level": 2, "can_upgrade": True}},
                "queue_busy": {"shipyard": False},
                "production_queue": {"active": False, "entries": []},
                "resources": {"metal": 6000, "crystal": 6000, "deuterium": 10000},
            }
            with patch.object(ogame_ctl, "PLAN_FILE", plan_path), \
                 patch.object(ogame_ctl, "NEXT_WAKE_FILE", wake_path), \
                 patch.object(ogame_ctl, "read_technology_list", side_effect=[pre, post]), \
                 patch.object(ogame_ctl, "read_header_snapshot", return_value={
                     "resources": pre["resources"], "energy": 100,
                 }), \
                 patch.object(ogame_ctl, "execute_checked_component_followup", return_value={
                     "success": True,
                     "mutation_submitted": True,
                     "resources_before": pre["resources"],
                     "clicked_at": int(time.time()),
                 }), \
                 patch("time.sleep", return_value=None):
                result = ogame_ctl.command_apply(argparse.Namespace(
                    plan_id="produce-plan",
                    action_id=candidate["action_id"],
                    planet_id=42,
                    run_id=None,
                    confirm=True,
                    output="json",
                    silent=True,
                ))

        self.assertEqual(result["status"], "applied")
        self.assertTrue(result["postcondition"]["evidence"]["amount_advanced"])

    def test_transport_wrapper_uses_a_fresh_typed_fleet_candidate(self):
        args = argparse.Namespace(
            galaxy=1,
            system=40,
            position=7,
            planet_id=42,
            metal=1000,
            crystal=0,
            deuterium=0,
            ship_tech="202",
            ship_amount=1,
            mission=3,
            run_id="run-1",
            confirm=True,
            output="json",
        )
        candidate = {"action_id": "fleet:opaque", "operation": "fleet_dispatch"}
        with patch.object(ogame_ctl, "create_fleet_confirmed_plan", return_value={
                 "plan_id": "fleet-plan", "candidates": [candidate],
             }) as plan, patch.object(ogame_ctl, "command_apply", return_value={
                 "status": "applied", "success": True,
             }) as apply:
            result = ogame_ctl.cmd_transport(args)

        self.assertTrue(result["success"])
        plan.assert_called_once_with(args, "transport")
        self.assertEqual(apply.call_args.args[0].action_id, "fleet:opaque")

    def test_auto_transport_wrapper_selects_only_matching_typed_candidate(self):
        args = argparse.Namespace(
            origin_id=42, target_id=43, galaxy=1, system=41, position=8,
            run_id="run-1", strategy=ogame_ctl.DEFAULT_STRATEGY_PATH,
            dry_run=False, confirm=True, output="json",
        )
        candidate = {
            "action_id": "fleet:transport-opaque",
            "operation": "fleet_dispatch",
            "mission": "transport",
            "target": {"galaxy": 1, "system": 41, "position": 8},
            "target_evidence": {"target_planet_id": "43"},
            "payload": {"metal": 5000, "crystal": 0, "deuterium": 0},
            "ship_tech": "202",
            "ship_amount": 1,
        }
        with patch.object(ogame_ctl, "command_plan", return_value={
                 "plan_id": "typed-plan", "planet_id": "42", "candidates": [candidate],
             }) as plan, patch.object(ogame_ctl, "command_apply", return_value={
                 "status": "applied", "success": True,
             }) as apply:
            result = ogame_ctl.cmd_auto_transport(args)

        self.assertTrue(result["success"])
        self.assertTrue(plan.call_args.args[0].include_fleet)
        self.assertEqual(apply.call_args.args[0].action_id, "fleet:transport-opaque")

    def test_plan_include_fleet_merges_typed_candidates_into_packages(self):
        supplies = {
            "items": {
                "22": {"level": 2}, "23": {"level": 2}, "24": {"level": 2},
            },
            "queue_busy": {"building": False, "research": False},
        }
        fleet_candidate = {
            "action_id": "fleet:transport-opaque",
            "operation": "fleet_dispatch",
            "planet_id": "42",
            "section": "fleet",
            "component": "fleetdispatch",
            "queue": "fleet",
            "can_apply": True,
            "energy_safe": True,
            "mission": "transport",
            "target": {"galaxy": 1, "system": 41, "position": 8},
            "tech_id": "202",
            "ship_tech": "202",
            "ship_amount": 1,
            "ships_before": {"202": 2},
            "fleet_slots": {"free": 3, "used": 0, "total": 3},
            "payload": {"metal": 1000, "crystal": 0, "deuterium": 0},
            "target_resources": {"metal": 1000, "crystal": 1000, "deuterium": 1000},
            "target_storage_capacities": {"metal": 40000, "crystal": 40000, "deuterium": 40000},
            "owner_authorized_large_transport": False,
            "target_evidence": {"owned_planet": True, "destroyed": False, "vacation": False},
            "costs": {"metal": 0, "crystal": 0, "deuterium": 0},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = pathlib.Path(tmpdir, "plan.json").as_posix()
            with patch.object(ogame_ctl, "PLAN_FILE", plan_path), \
                 patch.object(ogame_ctl, "require_run_lease"), \
                 patch.object(ogame_ctl, "read_header_snapshot", return_value={
                     "resources": {"metal": 10000, "crystal": 10000, "deuterium": 10000},
                     "energy": 20, "rate_tooltips": {},
                 }), \
                 patch.object(ogame_ctl, "get_rates_for_plan", return_value=(
                     {"metal": 1, "crystal": 1, "deuterium": 1}, "test",
                 )), \
                 patch.object(ogame_ctl, "read_technology_list", side_effect=[supplies, {"items": {}}, {"items": {}}]), \
                 patch.object(ogame_ctl, "collect_patrol_fleet_candidates", return_value={
                     "candidates": [fleet_candidate], "diagnostics": [],
                 }):
                plan = ogame_ctl.command_plan(argparse.Namespace(
                    planet_id=42, run_id="run-1", diagnose=False,
                    include_lifeforms=False, include_cancel=False, include_production=False,
                    include_fleet=True, strategy=ogame_ctl.DEFAULT_STRATEGY_PATH,
                    output="json", silent=True,
                ))

        self.assertIn("fleet:transport-opaque", [item["action_id"] for item in plan["candidates"]])
        self.assertIn(["fleet:transport-opaque"], [item["action_ids"] for item in plan["packages"]])

    def test_fleet_apply_requires_live_revalidation_and_two_part_postcondition(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = pathlib.Path(tmpdir, "plan.json").as_posix()
            wake_path = pathlib.Path(tmpdir, "wake.txt").as_posix()
            candidate = {
                "action_id": "fleet:opaque",
                "operation": "fleet_dispatch",
                "planet_id": "42",
                "section": "fleet",
                "component": "fleetdispatch",
                "queue": "fleet",
                "can_apply": True,
                "energy_safe": True,
                "mission": "transport",
                "target": {"galaxy": 1, "system": 1, "position": 2},
                "ship_tech": "202",
                "ship_amount": 1,
                "ships_before": {"202": 2},
                "fleet_slots": {"free": 3, "used": 2, "total": 5},
                "payload": {"metal": 1000, "crystal": 0, "deuterium": 0},
                "target_resources": {"metal": 1000, "crystal": 1000, "deuterium": 1000},
                "target_storage_capacities": {"metal": 40000, "crystal": 40000, "deuterium": 40000},
                "owner_authorized_large_transport": False,
                "target_evidence": {
                    "owned_planet": True,
                    "destroyed": False,
                    "vacation": False,
                },
                "costs": {"metal": 0, "crystal": 0, "deuterium": 0},
                "estimated_duration": 300,
                "tech_id": "202",
            }
            plan = {
                "plan_id": "fleet-plan",
                "planet_id": "42",
                "expires_at": int(time.time()) + 1000,
                "action_count": 0,
                "resources": {"metal": 10000, "crystal": 10000, "deuterium": 10000},
                "spendable_resources": {"metal": 10000, "crystal": 10000, "deuterium": 10000},
                "storage_capacities": {"metal": 40000, "crystal": 40000, "deuterium": 40000},
                "watch_costs": {"metal": 0, "crystal": 0, "deuterium": 0},
                "rates": {"metal": 0, "crystal": 0, "deuterium": 0},
                "candidates": [candidate],
                "status": "active",
            }
            ogame_ctl.atomic_write_json(plan_path, plan)
            pinned = {
                "planet_id": "42",
                "fleet_state": {
                    "planet_id": "42",
                    "ships": {"202": 2},
                    "fleet_slots": {"known": True, "free": 3, "used": 2, "total": 5},
                    "resources": plan["resources"],
                },
                "origin_storage_capacities": plan["storage_capacities"],
                "target_evidence": candidate["target_evidence"],
                "target_resources": candidate["target_resources"],
                "target_storage_capacities": candidate["target_storage_capacities"],
            }
            post = {
                "planet_id": "42",
                "fleet_state": {"ships": {"202": 1}},
                "events": {"events": [{"text": "Transport fleet to [1:1:2]"}]},
            }
            with patch.object(ogame_ctl, "PLAN_FILE", plan_path), \
                 patch.object(ogame_ctl, "NEXT_WAKE_FILE", wake_path), \
                 patch.object(ogame_ctl, "read_fleet_precondition", return_value=pinned) as preflight, \
                 patch.object(ogame_ctl, "execute_checked_component_followup", return_value={
                     "success": True, "mutation_submitted": True,
                 }) as execute, \
                 patch.object(ogame_ctl, "read_fleet_postcondition", return_value=post), \
                 patch("time.sleep", return_value=None):
                result = ogame_ctl.command_apply(argparse.Namespace(
                    plan_id="fleet-plan",
                    action_id="fleet:opaque",
                    planet_id=42,
                    run_id=None,
                    confirm=True,
                    output="json",
                    silent=True,
                ))

        self.assertEqual(result["status"], "applied")
        self.assertTrue(result["postcondition"]["evidence"]["ship_deducted"])
        self.assertTrue(result["postcondition"]["evidence"]["event_match"])
        preflight.assert_called_once()
        execute.assert_called_once()

    def test_deterministic_cost_formula_engine(self):
        # Crystal Mine Level 12
        costs, energy_delta = ogame_ctl.calculate_technology_cost("2", 12)
        self.assertEqual(costs, {"metal": 8444, "crystal": 4222, "deuterium": 0})
        self.assertIsNotNone(energy_delta)
        self.assertLess(energy_delta, 0)

        # Impulse Drive Level 2
        costs, energy_delta = ogame_ctl.calculate_technology_cost("117", 2)
        self.assertEqual(costs, {"metal": 4000, "crystal": 8000, "deuterium": 1200})
        self.assertIsNone(energy_delta)

        # Solar Plant Level 13
        costs, energy_delta = ogame_ctl.calculate_technology_cost("4", 13)
        self.assertGreater(costs["metal"], 0)
        self.assertGreater(energy_delta, 0)

    def test_plan_creates_feasible_packages_without_assigning_roi(self):
        overview = {
            "success": True,
            "resources": {"metal": 10000, "crystal": 10000, "deuterium": 10000},
            "energy": "+100",
            "rate_tooltips": {},
        }
        supplies = {
            "success": True,
            "items": {
                "1": {
                    "name": "金屬礦", "level": 11, "can_upgrade": True,
                    "costs_raw": "金屬 1,000 水晶 500 重氫 0", "duration_raw": "5分鐘",
                    "requirements_raw": "", "energy_raw": "-10",
                },
                "22": {"name": "金屬儲存器", "level": 2, "can_upgrade": False, "costs_raw": ""},
                "23": {"name": "晶體儲存器", "level": 2, "can_upgrade": False, "costs_raw": ""},
                "24": {"name": "重氫儲存槽", "level": 2, "can_upgrade": False, "costs_raw": ""},
            },
        }
        facilities = {
            "success": True,
            "items": {
                "14": {
                    "name": "機器人工廠", "level": 5, "can_upgrade": True,
                    "costs_raw": "金屬 800 水晶 240 重氫 400", "duration_raw": "3分鐘",
                    "requirements_raw": "", "energy_raw": "",
                },
            },
        }
        research = {
            "success": True,
            "items": {
                "117": {
                    "name": "脈衝引擎", "level": 1, "can_upgrade": True,
                    "costs_raw": "金屬 2,000 水晶 2,000 重氫 500", "duration_raw": "10分鐘",
                    "requirements_raw": "", "energy_raw": "",
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(ogame_ctl, "PLAN_FILE", pathlib.Path(tmpdir, "plan.json").as_posix()), \
             patch.object(ogame_ctl, "RATES_FILE", pathlib.Path(tmpdir, "rates.json").as_posix()), \
             patch.object(ogame_ctl, "read_header_snapshot", return_value=overview), \
             patch.object(ogame_ctl, "read_technology_list", side_effect=[supplies, facilities, research]), \
             patch.object(ogame_ctl, "get_rates_for_plan", return_value=({"metal": 1000, "crystal": 1000, "deuterium": 1000}, "test")):
            plan = ogame_ctl.command_plan(argparse.Namespace(planet_id=42))

        self.assertEqual(plan["planet_id"], "42")
        candidate_ids = {candidate["action_id"] for candidate in plan["candidates"]}
        self.assertTrue({"supplies:1", "facilities:14", "research:117"}.issubset(candidate_ids))
        self.assertGreater(len(plan["packages"]), 0)
        self.assertNotIn("roi", plan["candidates"][0])

    def test_plan_falls_back_to_deterministic_formula_when_costs_raw_is_empty(self):
        item = {
            "name": "晶體礦", "level": 11, "can_upgrade": True,
            "costs_raw": "", "duration_raw": "", "requirements_raw": "", "energy_raw": "",
        }
        action = ogame_ctl.action_from_item("supplies", "2", item, {"metal": 10000, "crystal": 10000, "deuterium": 10000}, 100)
        self.assertIsNotNone(action)
        self.assertEqual(action["costs"]["metal"], 8444)
        self.assertEqual(action["costs"]["crystal"], 4222)
        self.assertTrue(action["actionable_now"])

    def test_watch_reserves_costs_and_schedules_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = pathlib.Path(tmpdir, "plan.json").as_posix()
            wake_path = pathlib.Path(tmpdir, "next_wake.txt").as_posix()
            candidate = {"action_id": "research:117", "costs": {"metal": 4000, "crystal": 8000, "deuterium": 1200}}
            ogame_ctl.atomic_write_json(plan_path, {
                "plan_id": "test-plan", "expires_at": 4_000_000_000, "resources": {"metal": 5000, "crystal": 1000, "deuterium": 5000},
                "rates": {"metal": 1000, "crystal": 3500, "deuterium": 1000}, "candidates": [candidate], "status": "active",
            })
            with patch.object(ogame_ctl, "PLAN_FILE", plan_path), patch.object(ogame_ctl, "NEXT_WAKE_FILE", wake_path):
                result = ogame_ctl.command_watch(argparse.Namespace(plan_id="test-plan", action_id="research:117"))
                saved = ogame_ctl.load_json_file(plan_path)

        self.assertEqual(result["watch_action_id"], "research:117")
        self.assertEqual(saved["spendable_resources"]["crystal"], 0)
        self.assertGreater(result["next_wake"], 0)

    def test_check_wake_gate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            wake_path = pathlib.Path(tmpdir, "next_wake.txt").as_posix()
            future_epoch = int(time.time()) + 1000
            with open(wake_path, "w") as f:
                f.write(f"{future_epoch}\n")
            with patch.object(ogame_ctl, "NEXT_WAKE_FILE", wake_path):
                with self.assertRaises(SystemExit) as cm:
                    ogame_ctl.command_check_wake(argparse.Namespace(force=False))
                self.assertEqual(cm.exception.code, 0)
                res = ogame_ctl.command_check_wake(argparse.Namespace(force=True))
                self.assertTrue(res["due"])

    def test_patrol_lease_rejects_overlap_and_releases_only_owner(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lease_path = pathlib.Path(tmpdir, "patrol-run.json").as_posix()
            guard_path = pathlib.Path(tmpdir, ".patrol-run.lock").as_posix()
            with patch.object(ogame_ctl, "MEMORY_DIR", tmpdir), \
                 patch.object(ogame_ctl, "RUN_LEASE_FILE", lease_path), \
                 patch.object(ogame_ctl, "RUN_LEASE_GUARD_FILE", guard_path):
                first = ogame_ctl.acquire_run_lease(ttl_seconds=60)
                self.assertIsNotNone(first)
                self.assertIsNone(ogame_ctl.acquire_run_lease(ttl_seconds=60))
                renewed = ogame_ctl.require_run_lease(first["run_id"], ttl_seconds=120)
                self.assertGreater(renewed["expires_at"], first["expires_at"])
                with self.assertRaisesRegex(RuntimeError, "其他巡邏"):
                    ogame_ctl.release_run_lease("not-the-owner")
                self.assertTrue(ogame_ctl.release_run_lease(first["run_id"]))
                second = ogame_ctl.acquire_run_lease(ttl_seconds=60)
                self.assertNotEqual(second["run_id"], first["run_id"])

    def test_finish_run_blocks_normal_commit_when_patrol_contract_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lease_path = pathlib.Path(tmpdir, "patrol-run.json").as_posix()
            guard_path = pathlib.Path(tmpdir, ".patrol-run.lock").as_posix()
            with patch.object(ogame_ctl, "MEMORY_DIR", tmpdir), \
                 patch.object(ogame_ctl, "RUN_LEASE_FILE", lease_path), \
                 patch.object(ogame_ctl, "RUN_LEASE_GUARD_FILE", guard_path), \
                 patch("scripts.ogame.tokens.record_tokens", return_value={"recorded": True, "run_id": "test", "delta": {"total": 0}, "cumulative": {"total": 0}, "step_count": 0}):
                lease = ogame_ctl.acquire_run_lease(ttl_seconds=60)
                with patch.object(ogame_ctl, "command_commit_patrol") as commit:
                    result = ogame_ctl.command_finish_run(argparse.Namespace(
                        run_id=lease["run_id"],
                        commit=True,
                        output="json",
                    ))
                saved = ogame_ctl.load_json_file(ogame_ctl.patrol_contract_file())
                last_run = ogame_ctl.load_json_file(ogame_ctl.patrol_last_run_file())

        self.assertFalse(result["patrol_complete"])
        self.assertEqual(result["commit"]["reason"], "patrol_contract_incomplete")
        self.assertTrue(result["released"])
        self.assertEqual(saved["status"], "incomplete")
        self.assertEqual(last_run["run_id"], lease["run_id"])
        self.assertEqual(last_run["status"], "incomplete")
        commit.assert_not_called()

    def test_apply_postcondition_rejects_item_presence_without_state_change(self):
        candidate = {
            "action_id": "supplies:1", "tech_id": "1", "queue": "building",
            "level": 11, "target_level": 12,
            "costs": {"metal": 1000, "crystal": 500, "deuterium": 0},
        }
        click_result = {
            "success": True,
            "resources_before": {"metal": 5000, "crystal": 5000, "deuterium": 5000},
            "clicked_at": 1000,
        }
        verification = {
            "items": {"1": {"level": 11, "can_upgrade": True}},
            "resources": {"metal": 5000, "crystal": 5000, "deuterium": 5000},
            "queue_busy": {"building": False, "research": False},
        }
        result = ogame_ctl.verify_applied_action(
            candidate, click_result, verification,
            {"metal": 0, "crystal": 0, "deuterium": 0}, now=1005,
        )
        self.assertFalse(result["success"])
        self.assertIn("no_target_level_or_queue_evidence", result["reasons"])
        self.assertIn("resource_deduction_mismatch", result["reasons"])

    def test_apply_postcondition_accepts_target_queue_and_resource_deduction(self):
        candidate = {
            "action_id": "research:117", "tech_id": "117", "queue": "research",
            "level": 2, "target_level": 3,
            "costs": {"metal": 4000, "crystal": 8000, "deuterium": 1200},
        }
        result = ogame_ctl.verify_applied_action(
            candidate,
            {
                "success": True,
                "resources_before": {"metal": 10000, "crystal": 12000, "deuterium": 5000},
                "clicked_at": 1000,
            },
            {
                "items": {"117": {"level": 2, "can_upgrade": False}},
                "resources": {"metal": 6000, "crystal": 4000, "deuterium": 3800},
                "queue_busy": {"building": False, "research": True},
            },
            {"metal": 0, "crystal": 0, "deuterium": 0},
            now=1005,
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["evidence"]["queue_started"])
        self.assertTrue(result["evidence"]["button_locked"])

    def test_apply_postcondition_accepts_target_queued_status_with_resource_deduction(self):
        candidate = {
            "tech_id": "1", "queue": "building", "level": 10, "target_level": 11,
            "costs": {"metal": 100, "crystal": 50, "deuterium": 0},
        }
        result = ogame_ctl.verify_applied_action(
            candidate,
            {
                "success": True,
                "clicked_at": 100,
                "resources_before": {"metal": 1000, "crystal": 1000, "deuterium": 1000},
            },
            {
                "resources": {"metal": 900, "crystal": 950, "deuterium": 1000},
                "queue_busy": {"building": True},
                "items": {"1": {"level": 10, "status": "queued", "can_upgrade": True}},
            },
            {"metal": 0, "crystal": 0, "deuterium": 0},
            now=105,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["evidence"]["target_status"], "queued")
        self.assertTrue(result["evidence"]["queue_started"])
        self.assertFalse(result["evidence"]["button_locked"])
        self.assertTrue(result["evidence"]["target_status_evidence"])

    def test_active_plan_rejects_a_mismatched_run_lease(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = pathlib.Path(tmpdir, "plan.json").as_posix()
            ogame_ctl.atomic_write_json(plan_path, {
                "plan_id": "leased-plan",
                "run_id": "owner-run",
                "expires_at": 4_000_000_000,
            })
            with patch.object(ogame_ctl, "PLAN_FILE", plan_path), \
                 patch.object(ogame_ctl, "require_run_lease") as require_lease:
                with self.assertRaisesRegex(RuntimeError, "租約不符"):
                    ogame_ctl.require_active_plan("leased-plan", "other-run")
                plan = ogame_ctl.require_active_plan("leased-plan", "owner-run")
                require_lease.assert_called_once_with("owner-run")
                self.assertEqual(plan["run_id"], "owner-run")

    def test_apply_rejects_a_planet_mismatch_before_clicking(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = pathlib.Path(tmpdir, "plan.json").as_posix()
            ogame_ctl.atomic_write_json(plan_path, {"plan_id": "test-plan", "planet_id": "42", "expires_at": 4_000_000_000, "action_count": 0, "candidates": []})
            args = argparse.Namespace(plan_id="test-plan", action_id="supplies:1", planet_id=43, confirm=True)
            with patch.object(ogame_ctl, "PLAN_FILE", plan_path):
                with self.assertRaisesRegex(RuntimeError, "不符"):
                    ogame_ctl.command_apply(args)

    def test_apply_blocks_cost_drift_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = pathlib.Path(tmpdir, "plan.json").as_posix()
            candidate = {
                "action_id": "supplies:1",
                "section": "supplies",
                "component": "supplies",
                "tech_id": "1",
                "queue": "building",
                "level": 11,
                "target_level": 12,
                "costs": {"metal": 1000, "crystal": 500, "deuterium": 0},
                "energy_delta": -10,
                "energy_safe": True,
            }
            ogame_ctl.atomic_write_json(plan_path, {
                "plan_id": "cost-drift-plan",
                "planet_id": "42",
                "expires_at": int(time.time()) + 1000,
                "action_count": 0,
                "candidates": [candidate],
                "watch_action_id": None,
                "watch_costs": {},
                "storage_capacities": {"metal": 40000, "crystal": 40000, "deuterium": 40000},
                "status": "active",
            })
            live_state = {
                "items": {"1": {
                    "level": 11,
                    "can_upgrade": True,
                    "costs_raw": "金屬 1,001 水晶 500 重氫 0",
                }},
                "resources": {"metal": 5000, "crystal": 5000, "deuterium": 5000},
                "queue_busy": {"building": False, "research": False},
            }
            args = argparse.Namespace(
                plan_id="cost-drift-plan", action_id="supplies:1", planet_id=42, confirm=True,
            )
            with patch.object(ogame_ctl, "PLAN_FILE", plan_path), \
                 patch.object(ogame_ctl, "read_technology_list", return_value=live_state), \
                 patch.object(ogame_ctl, "read_header_snapshot", return_value={
                     "resources": live_state["resources"], "energy": 100,
                 }), \
                 patch.object(ogame_ctl, "execute_checked_component_result") as execute, \
                 patch("time.sleep", return_value=None):
                result = ogame_ctl.command_apply(args)

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["reason"], "cost_revalidation_mismatch")
            execute.assert_not_called()
            saved_plan = ogame_ctl.load_json_file(plan_path)
            self.assertEqual(saved_plan["action_count"], 0)
            self.assertEqual(saved_plan["status"], "active")

    def test_lifeform_prevalidation_never_falls_back_to_standard_tech_formula(self):
        candidate = {
            "action_id": "lifeform:opaque",
            "operation": "lifeform_upgrade",
            "component": "lfbuildings",
            "tech_id": "1",
            "queue": "lifeform_building",
            "level": 0,
            "target_level": 1,
            "costs": {"metal": 60, "crystal": 15, "deuterium": 0},
            "energy_delta": 0,
        }
        pinned = {
            "technology": {
                "items": {"1": {"level": 0, "can_upgrade": True, "costs_raw": ""}},
                "resources": {"metal": 1000, "crystal": 1000, "deuterium": 1000},
                "queue_busy": {"lifeform_building": False},
            },
            "header": {"energy": 10},
        }

        result = ogame_ctl.prevalidate_planned_action(
            candidate,
            pinned,
            {"storage_capacities": {"metal": 40000, "crystal": 40000, "deuterium": 40000}},
            {"metal": 0, "crystal": 0, "deuterium": 0},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "cost_revalidation_mismatch")
        self.assertIsNone(result["observed_costs"])

    def test_resource_settings_parser_accepts_the_live_traditional_chinese_hourly_row(self):
        text = "基本收入 150 75 0\n時産量:\t7,211\t3,997\t1,367\t42/1,073"
        self.assertEqual(
            ogame_ctl.parse_resource_settings_rates(text),
            {"metal": 7211, "crystal": 3997, "deuterium": 1367},
        )

    def test_query_trace_sanitizer_redacts_credentials_but_keeps_operational_ids(self):
        trace = {
            "request": {
                "url": "https://s1-en.ogame.gameforge.com/game/index.php?page=ajax&component=technologydetails&technology=1&token=secret-token&cp=12345678",
                "headers": {"Authorization": "Bearer secret", "X-Requested-With": "XMLHttpRequest"},
                "body": "technology=1&csrfToken=secret-csrf&planet=12345678",
            },
            "response": {"body": '<input name="token" value="secret-response">', "status": 200},
        }
        sanitized = ogame_ctl.sanitize_query_trace(trace)
        rendered = str(sanitized)
        self.assertNotIn("secret-token", rendered)
        self.assertNotIn("secret-csrf", rendered)
        self.assertNotIn("secret-response", rendered)
        self.assertNotIn("Bearer secret", rendered)
        self.assertIn("12345678", rendered)
        self.assertIn("technology=1", rendered)

        socket_url = ogame_ctl.sanitize_trace_url("https://s1-en.ogame.gameforge.com:24412/socket.io/?EIO=4&transport=polling&sid=socket-secret")
        self.assertNotIn("socket-secret", socket_url)
        class_ids = ogame_ctl.sanitize_query_trace({"characterClassId": 3, "allianceClassId": 0, "sid": "secret"})
        self.assertEqual(class_ids["characterClassId"], 3)
        self.assertEqual(class_ids["allianceClassId"], 0)
        self.assertEqual(class_ids["sid"], "[REDACTED]")

    def test_query_replay_allowlist_accepts_only_same_origin_get_technology_details(self):
        safe = {
            "request": {
                "method": "GET",
                "url": "https://s1-en.ogame.gameforge.com/game/index.php?page=ajax&component=technologydetails&technology=1",
            }
        }
        self.assertTrue(ogame_ctl.is_safe_query_replay(safe))
        self.assertFalse(ogame_ctl.is_safe_query_replay({"request": {**safe["request"], "method": "POST"}}))
        self.assertFalse(ogame_ctl.is_safe_query_replay({"request": {"method": "GET", "url": "https://example.com/?page=ajax&component=technologydetails"}}))
        self.assertFalse(ogame_ctl.is_safe_query_replay({"request": {"method": "GET", "url": "https://s1-en.ogame.gameforge.com/game/index.php?page=ingame&component=supplies"}}))
        safe_page = {"request": {"method": "GET", "url": "https://s1-en.ogame.gameforge.com/game/index.php?page=ingame&component=supplies&cp=12345678"}}
        self.assertTrue(ogame_ctl.is_safe_query_replay(safe_page))
        unsafe_page = {"request": {"method": "GET", "url": "https://s1-en.ogame.gameforge.com/game/index.php?page=ingame&component=fleetdispatch&cp=12345678"}}
        self.assertFalse(ogame_ctl.is_safe_query_replay(unsafe_page))

    def test_response_schema_reports_json_and_html_shapes(self):
        self.assertEqual(
            ogame_ctl.response_schema('{"success":true,"items":[]}', "application/json")["shape"],
            {"success": "bool", "items": "list"},
        )
        html_schema = ogame_ctl.response_schema("<div><span>Cost</span></div>", "text/html")
        self.assertEqual(html_schema["kind"], "html")
        self.assertEqual(html_schema["tags"], ["div", "span"])

    def test_external_data_export_path_allows_only_fixed_read_actions(self):
        path = ogame_ctl.external_data_export_path("accountInfo")
        self.assertIn("page=componentOnly", path)
        self.assertIn("component=externaldataexport", path)
        self.assertIn("action=accountInfo", path)
        self.assertIn("asJson=1", path)
        self.assertNotIn("cp=", path)
        with self.assertRaisesRegex(ValueError, "不允許"):
            ogame_ctl.external_data_export_path("sendFleet")

    def test_external_data_export_classifier_rejects_http_200_plain_error(self):
        unavailable = ogame_ctl.classify_external_data_export_response(
            200,
            "text/plain",
            "An error has occured!",
        )
        self.assertFalse(unavailable["available"])
        self.assertEqual(unavailable["reason"], "endpoint_unavailable_or_missing_required_header")

        available = ogame_ctl.classify_external_data_export_response(
            200,
            "application/json",
            '{"status":"success","planets":[{"id":42}]}',
        )
        self.assertTrue(available["available"])
        self.assertEqual(available["data"]["planets"][0]["id"], 42)

        failure = ogame_ctl.classify_external_data_export_response(
            200,
            "application/json",
            '{"status":"failure","success":false,"errors":[{"error":100053}]}',
        )
        self.assertFalse(failure["available"])
        self.assertEqual(failure["reason"], "api_failure")

    def test_external_data_export_probe_js_is_same_origin_get_without_cp(self):
        js = ogame_ctl.external_data_export_probe_js()
        self.assertIn("method: 'GET'", js)
        self.assertIn("credentials: 'same-origin'", js)
        self.assertIn("X-Requested-With", js)
        self.assertNotIn("&cp=", js)
        for action in ogame_ctl.EXTERNAL_DATA_EXPORT_ACTIONS:
            self.assertIn(action, js)

    def test_export_probe_restores_original_planet_and_persists_sanitized_results(self):
        raw_results = [
            {
                "action": action,
                "request": {
                    "method": "GET",
                    "url": f"https://s1-en.ogame.gameforge.com{ogame_ctl.external_data_export_path(action)}",
                    "headers": {"X-Requested-With": "XMLHttpRequest"},
                    "has_cp_parameter": False,
                },
                "response": {
                    "status": 200,
                    "response_url": f"https://s1-en.ogame.gameforge.com{ogame_ctl.external_data_export_path(action)}",
                    "content_type": "application/json",
                    "headers": {},
                    "body": '{"success":true,"token":"secret","planet":42}',
                },
                "duration_ms": 5,
            }
            for action in ogame_ctl.EXTERNAL_DATA_EXPORT_ACTIONS
        ]
        written = {}
        restore_calls = []

        def fake_write(path, value):
            written["path"] = path
            written["value"] = value

        def fake_restore(component, planet_id, _expression):
            restore_calls.append((component, planet_id))
            return {"success": True, "planet_id": str(planet_id)}

        with patch.object(ogame_ctl, "require_run_lease"), \
             patch.object(ogame_ctl, "read_active_planet_context", return_value={
                 "success": True,
                 "planet_id": "41",
                 "owned_planet_ids": ["41", "42"],
             }), \
             patch.object(ogame_ctl, "execute_checked_component_followup", return_value={
                 "success": True,
                 "active_planet": "42",
                 "probe": {"results": raw_results},
             }), \
             patch.object(ogame_ctl, "execute_checked_component", side_effect=fake_restore), \
             patch.object(ogame_ctl, "atomic_write_json", side_effect=fake_write):
            result = ogame_ctl.command_export_probe(argparse.Namespace(planet_id=42, run_id="run-test"))

        self.assertEqual(result["available_count"], 4)
        self.assertTrue(result["restored"])
        self.assertEqual(restore_calls, [("overview", 41)])
        self.assertEqual(written["path"], ogame_ctl.EXPORT_PROBE_FILE)
        rendered = str(written["value"])
        self.assertNotIn("secret", rendered)
        self.assertIn("42", rendered)

    def test_official_account_info_normalizes_to_a_stable_versioned_contract(self):
        snapshot = ogame_ctl.normalize_official_account_info(
            self.official_account_info_fixture(),
            planet_metadata=[{"id": 42, "name": "Home", "coords": "[1:1:1]"}],
            captured_at=123,
        )

        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(snapshot["source"], "official.accountInfo")
        self.assertEqual(snapshot["captured_at"], 123)
        self.assertEqual(snapshot["planet_count"], 1)
        self.assertEqual(snapshot["account"]["player_id"], "7")
        self.assertIsNone(snapshot["account"]["alliance_class_id"])
        self.assertEqual(snapshot["account"]["researches"]["124"], 2)
        self.assertEqual(snapshot["planets"][0]["planet_id"], "42")
        self.assertEqual(snapshot["planets"][0]["name"], "Home")
        self.assertEqual(snapshot["planets"][0]["energy"], -20)
        self.assertEqual(snapshot["planets"][0]["production"]["metal"], 8457)
        self.assertNotIn("playerName", str(snapshot))
        self.assertNotIn("newAjaxToken", str(snapshot))

    def test_account_info_reader_uses_one_allowlisted_same_origin_get_without_cp(self):
        js = ogame_ctl.external_data_export_fetch_js("accountInfo")
        self.assertIn("method:'GET'", js)
        self.assertIn("credentials:'same-origin'", js)
        self.assertIn("X-Requested-With", js)
        self.assertNotIn("cp=", js)

        response = {
            "success": True,
            "export_read": {
                "action": "accountInfo",
                "response": {
                    "status": 200,
                    "content_type": "application/json",
                    "body": json.dumps(self.official_account_info_fixture()),
                },
            },
        }
        with patch.object(ogame_ctl, "execute_in_game_tab", return_value=response) as browser_read:
            snapshot = ogame_ctl.read_official_account_snapshot()

        self.assertEqual(snapshot["source"], "official.accountInfo")
        self.assertEqual(snapshot["planet_count"], 1)
        _, kwargs = browser_read.call_args
        self.assertNotIn("target_url", kwargs)
        self.assertEqual(kwargs["wait_after_js"], 2.0)

    def test_official_snapshot_projects_to_legacy_sync_shape_without_claiming_queue_state(self):
        snapshot = ogame_ctl.normalize_official_account_info(
            self.official_account_info_fixture(), captured_at=123
        )
        state = ogame_ctl.official_planet_to_sync_state(snapshot, snapshot["planets"][0])

        self.assertEqual(state["overview"]["metal"], 1234)
        self.assertEqual(state["overview"]["production"]["crystal"], 5612)
        self.assertEqual(state["supplies"]["1"]["level"], 13)
        self.assertEqual(state["facilities"]["14"]["level"], 6)
        self.assertEqual(state["research"]["124"]["level"], 2)
        self.assertEqual(state["shipyard"]["202"]["amount"], 3)
        self.assertFalse(state["queue_busy"]["known"])
        self.assertIsNone(state["queue_busy"]["building"])

    def test_empire_snapshot_normalizes_full_state_and_queue_evidence(self):
        snapshot = ogame_ctl.normalize_empire_snapshot(self.empire_raw_fixture(), captured_at=123)
        planet = snapshot["planets"][0]

        self.assertEqual(snapshot["source"], "empire.standalone")
        self.assertEqual(snapshot["queue_coverage"], "empire.standalone")
        self.assertEqual(snapshot["rates_coverage"], "not_provided")
        self.assertEqual(planet["storage"]["metal"], 140000)
        self.assertEqual(planet["equipment"], ["No items equipped"])
        self.assertEqual(planet["buildings"]["14"], 6)
        self.assertEqual(planet["species_researches"]["11201"], 1)
        self.assertTrue(planet["queue_busy"]["building"])
        self.assertTrue(planet["queue_busy"]["lifeform_building"])
        self.assertFalse(planet["queue_busy"]["shipyard"])

    def test_empire_reader_uses_fixed_standalone_url(self):
        with patch.object(ogame_ctl, "execute_in_game_tab", return_value=self.empire_raw_fixture()) as browser_read:
            snapshot = ogame_ctl.read_empire_snapshot()

        self.assertEqual(snapshot["planet_count"], 1)
        _, kwargs = browser_read.call_args
        self.assertEqual(kwargs["target_url"], ogame_ctl.empire_url())
        self.assertNotIn("cp=", kwargs["target_url"])

    def test_empire_reader_raises_non_fallback_safety_stop(self):
        with patch.object(ogame_ctl, "execute_in_game_tab", return_value={
            "success": False, "safety_stop": True, "reason": "captcha",
        }):
            with self.assertRaisesRegex(ogame_ctl.SafetyStopError, "captcha"):
                ogame_ctl.read_empire_snapshot()

    def test_empire_enrichment_adds_rates_without_replacing_display_resources(self):
        empire = ogame_ctl.normalize_empire_snapshot(self.empire_raw_fixture(), captured_at=123)
        official = ogame_ctl.normalize_official_account_info(
            self.official_account_info_fixture(), captured_at=123
        )
        enriched = ogame_ctl.enrich_empire_with_official(empire, official)

        self.assertEqual(enriched["source"], "empire.standalone+official.accountInfo")
        self.assertEqual(enriched["rates_coverage"], "official.accountInfo")
        self.assertEqual(enriched["planets"][0]["resources"]["metal"], 1234)
        self.assertEqual(enriched["planets"][0]["production"]["metal"], 8457)

    def test_sync_all_auto_prefers_empire_and_restores_active_planet(self):
        empire = ogame_ctl.normalize_empire_snapshot(self.empire_raw_fixture(), captured_at=123)
        official = ogame_ctl.normalize_official_account_info(self.official_account_info_fixture(), captured_at=123)
        with patch.object(ogame_ctl, "read_active_planet_context", return_value={"success": True, "planet_id": "42"}), \
             patch.object(ogame_ctl, "read_empire_snapshot", return_value=empire) as empire_read, \
             patch.object(ogame_ctl, "read_official_account_snapshot", return_value=official), \
             patch.object(ogame_ctl, "execute_checked_component", return_value={"success": True, "planet_id": "42"}) as restore, \
             patch.object(ogame_ctl, "cmd_sync_all_html") as html_fallback:
            result = ogame_ctl.cmd_sync_all(argparse.Namespace(source="auto"))

        self.assertEqual(result["source"], "empire.standalone+official.accountInfo")
        self.assertEqual(result["planet_count"], 1)
        self.assertTrue(result["planets"][0]["queue_busy"]["known"])
        self.assertEqual(result["planets"][0]["storage"]["metal"]["capacity"], 140000)
        empire_read.assert_called_once()
        restore.assert_called_once()
        html_fallback.assert_not_called()

    def test_sync_all_auto_falls_back_after_both_consolidated_sources_fail(self):
        fallback = {"success": True, "source": "html.pages", "planet_count": 1, "planets": []}
        with patch.object(ogame_ctl, "read_active_planet_context", return_value={"success": True, "planet_id": "42"}), \
             patch.object(ogame_ctl, "read_empire_snapshot", side_effect=RuntimeError("empire offline")), \
             patch.object(ogame_ctl, "read_official_account_snapshot", side_effect=RuntimeError("official offline")), \
             patch.object(ogame_ctl, "execute_checked_component", return_value={"success": True, "planet_id": "42"}), \
             patch.object(ogame_ctl, "cmd_sync_all_html", return_value=fallback) as html_fallback:
            self.assertIs(ogame_ctl.cmd_sync_all(argparse.Namespace(source="auto")), fallback)
            html_fallback.assert_called_once()

    def test_sync_all_never_falls_back_after_safety_stop(self):
        with patch.object(ogame_ctl, "read_active_planet_context", return_value={"success": True, "planet_id": "42"}), \
             patch.object(ogame_ctl, "read_empire_snapshot", side_effect=ogame_ctl.SafetyStopError("captcha")), \
             patch.object(ogame_ctl, "read_official_account_snapshot") as official, \
             patch.object(ogame_ctl, "cmd_sync_all_html") as html_fallback, \
             patch.object(ogame_ctl, "execute_checked_component", return_value={"success": True, "planet_id": "42"}):
            with self.assertRaisesRegex(ogame_ctl.SafetyStopError, "captcha"):
                ogame_ctl.cmd_sync_all(argparse.Namespace(source="auto"))

        official.assert_not_called()
        html_fallback.assert_not_called()

    def test_sync_all_official_remains_fail_closed(self):
        with patch.object(ogame_ctl, "read_official_account_snapshot", side_effect=RuntimeError("offline")), \
             patch.object(ogame_ctl, "cmd_sync_all_html") as html_fallback:
            with self.assertRaisesRegex(RuntimeError, "offline"):
                ogame_ctl.cmd_sync_all(argparse.Namespace(source="official"))
            html_fallback.assert_not_called()

    def test_empire_matrix_never_reads_planet_pages_for_queues(self):
        empire = ogame_ctl.normalize_empire_snapshot(self.empire_raw_fixture(), captured_at=123)
        official = ogame_ctl.normalize_official_account_info(self.official_account_info_fixture(), captured_at=123)
        snapshot = ogame_ctl.enrich_empire_with_official(empire, official)
        with patch.object(ogame_ctl, "read_technology_list") as queue_read:
            result = ogame_ctl.cmd_matrix_empire(snapshot)

        queue_read.assert_not_called()
        self.assertEqual(result["queue_source"], "empire.standalone")
        self.assertEqual(result["planets"][0]["rates"]["metal"], 8457)
        self.assertEqual(result["planets"][0]["storage"]["metal"], 140000)
        self.assertTrue(result["planets"][0]["building_busy"])
        self.assertEqual(result["planets"][0]["species_buildings"]["11101"], 5)

    def test_matrix_auto_routes_through_empire_and_restores_active_planet(self):
        empire = ogame_ctl.normalize_empire_snapshot(self.empire_raw_fixture(), captured_at=123)
        official = ogame_ctl.normalize_official_account_info(self.official_account_info_fixture(), captured_at=123)
        matrix_result = {"success": True, "source": "empire.standalone+official.accountInfo", "planets": []}
        with patch.object(ogame_ctl, "read_active_planet_context", return_value={
                 "success": True, "planet_id": "42", "owned_planet_ids": ["42"]
             }), \
             patch.object(ogame_ctl, "read_empire_snapshot", return_value=empire), \
             patch.object(ogame_ctl, "read_official_account_snapshot", return_value=official), \
             patch.object(ogame_ctl, "cmd_matrix_empire", return_value=matrix_result) as empire_matrix, \
             patch.object(ogame_ctl, "cmd_matrix_official") as official_matrix, \
             patch.object(ogame_ctl, "execute_checked_component", return_value={
                 "success": True, "planet_id": "42"
             }) as restore, \
             patch.object(ogame_ctl, "atomic_write_json"):
            result = ogame_ctl.cmd_matrix(argparse.Namespace(source="auto", output="json"))

        empire_matrix.assert_called_once()
        official_matrix.assert_not_called()
        restore.assert_called_once()
        self.assertTrue(result["active_planet_restored"])

    def test_matrix_never_falls_back_after_safety_stop(self):
        with patch.object(ogame_ctl, "read_active_planet_context", return_value={
                 "success": True, "planet_id": "42", "owned_planet_ids": ["42"]
             }), \
             patch.object(ogame_ctl, "read_empire_snapshot", side_effect=ogame_ctl.SafetyStopError("captcha")), \
             patch.object(ogame_ctl, "read_official_account_snapshot") as official, \
             patch.object(ogame_ctl, "cmd_matrix_html") as html_fallback, \
             patch.object(ogame_ctl, "execute_checked_component", return_value={
                 "success": True, "planet_id": "42"
             }), \
             patch.object(ogame_ctl, "atomic_write_json"):
            with self.assertRaisesRegex(ogame_ctl.SafetyStopError, "captcha"):
                ogame_ctl.cmd_matrix(argparse.Namespace(source="auto", output="json"))

        official.assert_not_called()
        html_fallback.assert_not_called()

    def test_patrol_matrix_fails_without_official_or_html_fallback(self):
        with patch.object(ogame_ctl, "read_active_planet_context", return_value={
                 "success": True, "planet_id": "42", "owned_planet_ids": ["42"]
             }), \
             patch.object(ogame_ctl, "read_empire_snapshot", side_effect=RuntimeError("empire unavailable")), \
             patch.object(ogame_ctl, "read_official_account_snapshot") as official, \
             patch.object(ogame_ctl, "cmd_matrix_html") as html_fallback, \
             patch.object(ogame_ctl, "execute_checked_component") as restore:
            with self.assertRaisesRegex(RuntimeError, "empire unavailable"):
                ogame_ctl.cmd_matrix(argparse.Namespace(source="patrol", output="json"))

        official.assert_not_called()
        html_fallback.assert_not_called()
        restore.assert_not_called()

    def test_empire_only_matrix_keeps_missing_rates_explicit(self):
        snapshot = ogame_ctl.normalize_empire_snapshot(self.empire_raw_fixture(), captured_at=123)
        result = ogame_ctl.cmd_matrix_empire(snapshot, quiet=True)

        self.assertEqual(result["rates_coverage"], "not_provided")
        self.assertEqual(result["planets"][0]["rates"], {
            "metal": None, "crystal": None, "deuterium": None,
        })
        self.assertEqual(result["totals"]["rates"], {
            "metal": None, "crystal": None, "deuterium": None,
        })

    def test_official_matrix_uses_account_info_for_state_and_html_only_for_queue_evidence(self):
        snapshot = ogame_ctl.normalize_official_account_info(
            self.official_account_info_fixture(), captured_at=123
        )
        with patch.object(ogame_ctl, "read_technology_list", return_value={
            "queue_busy": {"building": True, "research": False}
        }) as queue_read:
            result = ogame_ctl.cmd_matrix_official(snapshot)

        queue_read.assert_called_once_with("supplies", 42)
        self.assertEqual(result["source"], "official.accountInfo")
        self.assertEqual(result["queue_source"], "html.supplies")
        self.assertEqual(result["planets"][0]["rates"]["metal"], 8457)
        self.assertEqual(result["planets"][0]["energy"], -20)
        self.assertTrue(result["planets"][0]["building_busy"])

    def test_matrix_restores_the_original_active_planet(self):
        snapshot = ogame_ctl.normalize_official_account_info(
            self.official_account_info_fixture(), captured_at=123
        )
        matrix_result = {"success": True, "source": "official.accountInfo", "planets": []}
        with patch.object(ogame_ctl, "read_active_planet_context", return_value={
                 "success": True, "planet_id": "41", "owned_planet_ids": ["41", "42"]
             }), \
             patch.object(ogame_ctl, "read_official_account_snapshot", return_value=snapshot), \
             patch.object(ogame_ctl, "read_owned_planets", return_value=[]), \
             patch.object(ogame_ctl, "cmd_matrix_official", return_value=matrix_result), \
             patch.object(ogame_ctl, "execute_checked_component", return_value={
                 "success": True, "planet_id": "41"
             }) as restore, \
             patch.object(ogame_ctl, "atomic_write_json"):
            result = ogame_ctl.cmd_matrix(argparse.Namespace(source="official"))

        restore.assert_called_once()
        self.assertEqual(restore.call_args.args[:2], ("overview", 41))
        self.assertEqual(result["active_planet_before"], "41")
        self.assertTrue(result["active_planet_restored"])

    def test_parse_signed_number_preserves_numeric_negative_values(self):
        self.assertEqual(ogame_ctl.parse_signed_number(-20), -20)
        self.assertEqual(ogame_ctl.parse_signed_number("−20"), -20)


    def test_knapsack_queue_mutex_building_vs_research(self):
        c_metal_mine = {
            "action_id": "supplies:1",
            "queue": "building",
            "can_upgrade": True,
            "costs": {"metal": 1000, "crystal": 500, "deuterium": 0},
            "energy_delta": -10,
            "energy_safe": True,
        }
        c_robotics = {
            "action_id": "facilities:14",
            "queue": "building",
            "can_upgrade": True,
            "costs": {"metal": 800, "crystal": 240, "deuterium": 400},
            "energy_delta": 0,
            "energy_safe": True,
        }
        c_research = {
            "action_id": "research:108",
            "queue": "research",
            "can_upgrade": True,
            "costs": {"metal": 0, "crystal": 800, "deuterium": 1200},
            "energy_delta": 0,
            "energy_safe": True,
        }
        spendable = {"metal": 10000, "crystal": 10000, "deuterium": 10000}
        storage = {"metal": 100000, "crystal": 100000, "deuterium": 100000}

        packages = ogame_ctl.feasible_packages(
            [c_metal_mine, c_robotics, c_research],
            spendable,
            storage_capacities=storage,
            initial_energy=100,
        )
        multi_pkgs = [p for p in packages if len(p["action_ids"]) > 1]
        
        # Verify: supplies:1 and facilities:14 cannot be in the same package (same "building" queue)
        for pkg in multi_pkgs:
            actions = set(pkg["action_ids"])
            self.assertFalse(
                {"supplies:1", "facilities:14"}.issubset(actions),
                "Building queue items must be mutually exclusive in a single bundle",
            )
        
        # Verify: supplies:1 + research:108 CAN be in a package (different queues: building vs research)
        found_mine_research = any(
            set(pkg["action_ids"]) == {"supplies:1", "research:108"} for pkg in multi_pkgs
        )
        self.assertTrue(found_mine_research, "Building and research queues can be combined")

    def test_energy_deficit_exclusion(self):
        # 1. The frozen policy explicitly permits energy down to -20.
        item_mine = {
            "name": "金屬礦",
            "level": 11,
            "can_upgrade": True,
            "costs_raw": "金屬 1,000 水晶 500 重氫 0",
            "energy_raw": "-20",
        }
        action = ogame_ctl.action_from_item(
            "supplies", "1", item_mine,
            {"metal": 10000, "crystal": 10000, "deuterium": 10000},
            energy=5,
        )
        self.assertTrue(action["energy_safe"])
        self.assertTrue(action["actionable_now"])

        below_floor = ogame_ctl.action_from_item(
            "supplies", "1", item_mine,
            {"metal": 10000, "crystal": 10000, "deuterium": 10000},
            energy=-5,
        )
        self.assertFalse(below_floor["energy_safe"])
        self.assertFalse(below_floor["actionable_now"])

        # 2. feasible_packages excludes energy unsafe single actions
        unsafe_candidate = {
            "action_id": "supplies:1",
            "queue": "building",
            "can_upgrade": True,
            "costs": {"metal": 1000, "crystal": 500, "deuterium": 0},
            "energy_delta": -20,
            "energy_safe": False,
        }
        packages = ogame_ctl.feasible_packages(
            [unsafe_candidate],
            {"metal": 10000, "crystal": 10000, "deuterium": 10000},
            initial_energy=5,
        )
        self.assertEqual(len(packages), 0)

        # 3. Multi-action cumulative energy below -20 is excluded.
        c1 = {
            "action_id": "supplies:1",
            "queue": "building",
            "can_upgrade": True,
            "costs": {"metal": 100, "crystal": 50, "deuterium": 0},
            "energy_delta": -20,
            "energy_safe": True,
        }
        c2 = {
            "action_id": "research:108",
            "queue": "research",
            "can_upgrade": True,
            "costs": {"metal": 100, "crystal": 50, "deuterium": 0},
            "energy_delta": -20,
            "energy_safe": True,
        }
        packages_cum = ogame_ctl.feasible_packages(
            [c1, c2],
            {"metal": 1000, "crystal": 1000, "deuterium": 1000},
            initial_energy=15,
        )
        bundle_2 = [p for p in packages_cum if len(p["action_ids"]) == 2]
        self.assertEqual(len(bundle_2), 0, "Cumulative energy deficit must exclude multi-action package")

    def test_storage_90_percent_guardrail(self):
        storage_cap = {"metal": 10000, "crystal": 10000, "deuterium": 10000}
        cand_over = {
            "action_id": "supplies:1",
            "queue": "building",
            "can_upgrade": True,
            "costs": {"metal": 9500, "crystal": 1000, "deuterium": 0},
            "energy_delta": 0,
            "energy_safe": True,
        }
        cand_under = {
            "action_id": "supplies:2",
            "queue": "building",
            "can_upgrade": True,
            "costs": {"metal": 8500, "crystal": 1000, "deuterium": 0},
            "energy_delta": 0,
            "energy_safe": True,
        }
        spendable = {"metal": 20000, "crystal": 20000, "deuterium": 20000}
        
        pkgs_over = ogame_ctl.feasible_packages([cand_over], spendable, storage_capacities=storage_cap)
        self.assertEqual(len(pkgs_over), 0, "Must exclude candidate exceeding 90% storage capacity")

        pkgs_under = ogame_ctl.feasible_packages([cand_under], spendable, storage_capacities=storage_cap)
        self.assertEqual(len(pkgs_under), 1)

        cand_a = {
            "action_id": "supplies:1",
            "queue": "building",
            "can_upgrade": True,
            "costs": {"metal": 5000, "crystal": 1000, "deuterium": 0},
            "energy_delta": 0,
            "energy_safe": True,
        }
        cand_b = {
            "action_id": "research:108",
            "queue": "research",
            "can_upgrade": True,
            "costs": {"metal": 5000, "crystal": 1000, "deuterium": 0},
            "energy_delta": 0,
            "energy_safe": True,
        }
        pkgs_multi = ogame_ctl.feasible_packages([cand_a, cand_b], spendable, storage_capacities=storage_cap)
        bundle_2 = [p for p in pkgs_multi if len(p["action_ids"]) == 2]
        self.assertEqual(len(bundle_2), 0, "Multi-action bundle exceeding 90% capacity must be excluded")

    def test_watch_priority_spendable_calculation_and_packages(self):
        resources = {"metal": 5000, "crystal": 200, "deuterium": 1000}
        watch_candidate = {
            "action_id": "research:117",
            "queue": "research",
            "can_upgrade": True,
            "costs": {"metal": 4000, "crystal": 8000, "deuterium": 1200},
        }
        other_candidate_crystal = {
            "action_id": "supplies:2",
            "queue": "building",
            "can_upgrade": True,
            "costs": {"metal": 500, "crystal": 100, "deuterium": 0},
            "energy_safe": True,
        }
        other_candidate_metal_only = {
            "action_id": "supplies:1",
            "queue": "building",
            "can_upgrade": True,
            "costs": {"metal": 500, "crystal": 0, "deuterium": 0},
            "energy_safe": True,
        }
        spendable = {
            key: max(0, resources.get(key, 0) - watch_candidate["costs"].get(key, 0))
            for key in ogame_ctl.RESOURCE_KEYS
        }
        self.assertEqual(spendable, {"metal": 1000, "crystal": 0, "deuterium": 0})

        pkgs = ogame_ctl.feasible_packages(
            [other_candidate_crystal, other_candidate_metal_only],
            spendable,
            storage_capacities={"metal": 10000, "crystal": 10000, "deuterium": 10000},
        )
        action_ids_in_pkgs = [p["action_ids"] for p in pkgs]
        self.assertIn(["supplies:1"], action_ids_in_pkgs)
        self.assertNotIn(["supplies:2"], action_ids_in_pkgs)

    def test_check_wake_gate_three_states(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            wake_path = pathlib.Path(tmpdir, "next_wake.txt").as_posix()
            
            with patch.object(ogame_ctl, "NEXT_WAKE_FILE", wake_path):
                # State 1: 未達時間 (future epoch, force=False) -> SystemExit(0)
                future_epoch = int(time.time()) + 3600
                with open(wake_path, "w") as f:
                    f.write(f"{future_epoch}\n")
                with self.assertRaises(SystemExit) as cm:
                    ogame_ctl.command_check_wake(argparse.Namespace(force=False))
                self.assertEqual(cm.exception.code, 0)

                # State 2: --force 覆寫 (future epoch, force=True) -> returns {"due": True}
                res_force = ogame_ctl.command_check_wake(argparse.Namespace(force=True))
                self.assertEqual(res_force, {"due": True})

                # State 3: 已達時間 (past epoch, force=False) -> returns {"due": True}
                past_epoch = int(time.time()) - 100
                with open(wake_path, "w") as f:
                    f.write(f"{past_epoch}\n")
                res_past = ogame_ctl.command_check_wake(argparse.Namespace(force=False))
                self.assertEqual(res_past, {"due": True})

                # State 3b: 無 next_wake 檔案 (force=False) -> returns {"due": True}
                os.remove(wake_path)
                res_nofile = ogame_ctl.command_check_wake(argparse.Namespace(force=False))
                self.assertEqual(res_nofile, {"due": True})

    def test_apply_success_extends_next_wake(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = pathlib.Path(tmpdir, "plan.json").as_posix()
            wake_path = pathlib.Path(tmpdir, "next_wake.txt").as_posix()
            
            candidate = {
                "action_id": "supplies:1",
                "section": "supplies",
                "component": "supplies",
                "tech_id": "1",
                "queue": "building",
                "level": 11,
                "target_level": 12,
                "costs": {"metal": 1000, "crystal": 500, "deuterium": 0},
                "estimated_duration": 300,
                "energy_delta": -10,
                "energy_safe": True,
            }
            ogame_ctl.atomic_write_json(plan_path, {
                "plan_id": "test-apply-plan",
                "planet_id": "42",
                "expires_at": int(time.time()) + 1000,
                "action_count": 0,
                "candidates": [candidate],
                "watch_action_id": None,
                "watch_costs": {},
                "rates": {"metal": 0, "crystal": 0, "deuterium": 0},
                "resources": {"metal": 5000, "crystal": 5000, "deuterium": 5000},
                "energy": 100,
                "storage_capacities": {"metal": 40000, "crystal": 40000, "deuterium": 40000},
                "status": "active",
            })

            def fake_execute_component_result(_component, _planet_id, _js):
                return {
                    "success": True,
                    "mutation_submitted": True,
                    "action_id": "supplies:1",
                    "resources_before": {"metal": 5000, "crystal": 5000, "deuterium": 5000},
                    "clicked_at": int(time.time()),
                }

            pre_state = {
                "items": {"1": {
                    "level": 11,
                    "name": "金屬礦",
                    "can_upgrade": True,
                    "costs_raw": "金屬 1,000 水晶 500 重氫 0",
                }},
                "resources": {"metal": 5000, "crystal": 5000, "deuterium": 5000},
                "queue_busy": {"building": False, "research": False},
            }
            post_state = {
                "items": {"1": {"level": 12, "name": "金屬礦", "can_upgrade": True}},
                "resources": {"metal": 4000, "crystal": 4500, "deuterium": 5000},
                "queue_busy": {"building": False, "research": False},
            }

            now_before = int(time.time())
            with patch.object(ogame_ctl, "PLAN_FILE", plan_path), \
                 patch.object(ogame_ctl, "NEXT_WAKE_FILE", wake_path), \
                 patch.object(ogame_ctl, "execute_checked_component_result", side_effect=fake_execute_component_result), \
                 patch.object(ogame_ctl, "read_technology_list", side_effect=[pre_state, post_state]), \
                 patch.object(ogame_ctl, "read_header_snapshot", return_value={
                     "resources": pre_state["resources"], "energy": 100,
                 }), \
                 patch("time.sleep", return_value=None):
                args = argparse.Namespace(plan_id="test-apply-plan", action_id="supplies:1", planet_id=42, confirm=True)
                result = ogame_ctl.command_apply(args)

            now_after = int(time.time())
            self.assertTrue(result["success"])
            self.assertEqual(result["status"], "applied")
            self.assertEqual(result["action_count"], 1)

            expected_min_wake = now_before + 300 + 120
            expected_max_wake = now_after + 300 + 120
            self.assertTrue(expected_min_wake <= result["next_wake"] <= expected_max_wake)

            with open(wake_path, "r", encoding="utf-8") as f:
                saved_wake = int(f.read().strip())
            self.assertEqual(saved_wake, result["next_wake"])

            saved_plan = ogame_ctl.load_json_file(plan_path)
            self.assertEqual(saved_plan["next_wake"], result["next_wake"])
            self.assertEqual(saved_plan["action_count"], 1)

    def test_commit_patrol_nothing_to_commit(self):
        with patch("subprocess.run") as mock_run:
            # mock git add, then git diff --cached --quiet returning 0 (no diff)
            mock_run.side_effect = [
                unittest.mock.MagicMock(returncode=0),  # git add
                unittest.mock.MagicMock(returncode=0),  # git diff --cached --quiet
            ]
            args = argparse.Namespace(output="json", run_id="run-123", all=False, message=None)
            result = ogame_ctl.command_commit_patrol(args)
            self.assertFalse(result["committed"])
            self.assertEqual(result["reason"], "nothing_to_commit")
            self.assertTrue(result["commit_msg"].startswith("Cronjob "))
            self.assertIn("[run-123]", result["commit_msg"])

    def test_commit_patrol_success(self):
        with patch("subprocess.run") as mock_run:
            # git add, git diff (returncode 1 means diff exists), git commit
            mock_run.side_effect = [
                unittest.mock.MagicMock(returncode=0),  # git add
                unittest.mock.MagicMock(returncode=1),  # git diff (staged changes exist)
                unittest.mock.MagicMock(returncode=0, stdout="[main abcdef1] Cronjob ...", stderr=""),  # git commit
            ]
            args = argparse.Namespace(output="json", run_id="run-456", all=False, message="test upgrade")
            result = ogame_ctl.command_commit_patrol(args)
            self.assertTrue(result["committed"])
            self.assertIn("Cronjob ", result["commit_msg"])
            self.assertIn("[run-456]", result["commit_msg"])
            self.assertIn("test upgrade", result["commit_msg"])

    def test_commit_patrol_failure_resets_staging(self):
        with patch("subprocess.run") as mock_run:
            # git add, git diff (returncode 1), git commit (failure returncode 1), git reset
            mock_run.side_effect = [
                unittest.mock.MagicMock(returncode=0),  # git add
                unittest.mock.MagicMock(returncode=1),  # git diff
                unittest.mock.MagicMock(returncode=1, stdout="", stderr="error: user.name not set"),  # git commit fail
                unittest.mock.MagicMock(returncode=0),  # git reset
            ]
            args = argparse.Namespace(output="json", run_id="run-789", all=False, message=None)
            result = ogame_ctl.command_commit_patrol(args)
            self.assertFalse(result["committed"])
            self.assertIn("user.name not set", result["stderr"])
            # Verify git reset was called as the 4th subprocess call
            self.assertEqual(mock_run.call_count, 4)
            self.assertEqual(mock_run.call_args_list[3][0][0], ["git", "reset"])

    def test_finish_run_with_commit_integration(self):
        with patch.object(ogame_ctl, "command_commit_patrol") as mock_commit, \
             patch.object(ogame_ctl, "release_run_lease", return_value=True), \
             patch("scripts.ogame.tokens.record_tokens", return_value={"recorded": True, "run_id": "run-abc", "delta": {"total": 0}, "cumulative": {"total": 0}, "step_count": 0}):
            mock_commit.return_value = {"committed": True, "commit_msg": "Cronjob 26-09-06 06:30"}
            args = argparse.Namespace(run_id="run-abc", commit=True, output="json")
            res = ogame_ctl.command_finish_run(args)
            self.assertTrue(res["released"])
            self.assertEqual(res["run_id"], "run-abc")
            self.assertTrue(res["commit"]["committed"])
            mock_commit.assert_called_once_with(args)

    def test_commit_patrol_git_not_found_exception(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("git command not found")):
            args = argparse.Namespace(output="json", run_id="run-err", all=False, message=None)
            result = ogame_ctl.command_commit_patrol(args)
            self.assertFalse(result["committed"])
            self.assertEqual(result["reason"], "git_exception")
            self.assertIn("git command not found", result["error"])

    def test_finish_run_release_lease_guaranteed_even_on_commit_exception(self):
        with patch.object(ogame_ctl, "command_commit_patrol", side_effect=RuntimeError("unexpected disk crash")), \
             patch.object(ogame_ctl, "release_run_lease", return_value=True) as mock_release, \
             patch("scripts.ogame.tokens.record_tokens", return_value={"recorded": True, "run_id": "run-crash", "delta": {"total": 0}, "cumulative": {"total": 0}, "step_count": 0}):
            args = argparse.Namespace(run_id="run-crash", commit=True, output="json")
            res = ogame_ctl.command_finish_run(args)
            self.assertTrue(res["released"])
            self.assertEqual(res["run_id"], "run-crash")
            self.assertFalse(res["commit"]["committed"])
            self.assertEqual(res["commit"]["reason"], "commit_exception")
            mock_release.assert_called_once_with("run-crash")

    def test_commit_patrol_stages_targets(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                unittest.mock.MagicMock(returncode=0),  # git add
                unittest.mock.MagicMock(returncode=0),  # git diff (quiet)
            ]
            args = argparse.Namespace(output="json", run_id="run-flag", all=False, message=None)
            ogame_ctl.command_commit_patrol(args)
            git_add_args = mock_run.call_args_list[0][0][0]
            self.assertIn("git", git_add_args)
            self.assertIn("add", git_add_args)


if __name__ == "__main__":
    unittest.main()
