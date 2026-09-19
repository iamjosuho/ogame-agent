import argparse
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ogame import browser, expedition_agent
from scripts.ogame.execution import verify_fleet_dispatch
from scripts.ogame.operations import (
    FleetMission,
    assess_workflow_candidate,
    build_fleet_candidate,
    resolve_expedition_preset,
)
from scripts.ogame.policy import DEFAULT_CONSTANTS_PATH, load_account_constants


ACCOUNT_CONSTANTS = load_account_constants(DEFAULT_CONSTANTS_PATH)


class ExpeditionAgentTests(unittest.TestCase):
    def test_fleet_state_parses_labeled_expedition_slots_from_combined_slot_text(self):
        raw_state = {
            "success": True,
            "fleet_slots": {"known": True, "used": 9, "total": 18, "free": 9, "raw": "艦隊:9/18\n遠征艦隊: 7/7"},
            "expedition_slots": {"known": False, "used": None, "total": None, "free": None, "raw": ""},
        }
        with patch.object(browser, "execute_checked_component", return_value=raw_state):
            state = browser.read_fleet_state(12345680)
        self.assertEqual(
            state["expedition_slots"],
            {"known": True, "used": 7, "total": 7, "free": 0, "raw": "遠征艦隊: 7/7"},
        )

    def test_fleet_state_parses_dynamic_named_preset_from_live_row_contract(self):
        raw_state = {
            "success": True,
            "fleet_slots": {"known": True, "used": 9, "total": 18, "free": 9, "raw": "艦隊:9/18 遠征艦隊:7/7"},
            "expedition_slots": {"known": True, "used": 7, "total": 7, "free": 0, "raw": "遠征艦隊:7/7"},
            "expedition_templates": [],
            "expedition_template_rows": [{
                "name": "Agent",
                "template_id": "118",
                "edit_onclick": "setExpeditionFleetTemplateShips({&quot;218&quot;:1,&quot;219&quot;:1,&quot;203&quot;:60,&quot;210&quot;:1}, &quot;Agent&quot;, 118, 1, 100);",
            }],
        }
        with patch.object(browser, "execute_checked_component", return_value=raw_state):
            state = browser.read_fleet_state(12345680)
        self.assertEqual(state["expedition_templates"], [{
            "name": "Agent",
            "ships": {"218": 1, "219": 1, "203": 60, "210": 1},
        }])

    def test_preset_name_is_case_insensitive_and_duplicates_fail_closed(self):
        templates = [
            {"name": "Agent", "ships": {"203": 50, "219": 1}},
            {"name": "trial", "ships": {"203": 5}},
        ]
        self.assertEqual(
            resolve_expedition_preset(templates, " agent "),
            {"name": "Agent", "ships": {"203": 50, "219": 1}},
        )
        with self.assertRaisesRegex(RuntimeError, "重複"):
            resolve_expedition_preset(templates + [{"name": "AGENT", "ships": {"203": 2}}], "agent")

    def test_full_preset_composition_is_hashed_and_policy_checked(self):
        base = dict(
            planet_id="42",
            mission=FleetMission.EXPEDITION,
            target={"galaxy": 1, "system": 40, "position": 16},
            ship_tech="203",
            ship_amount=50,
            ships_before={"203": 60, "219": 1},
            fleet_slots={"free": 3, "used": 2, "total": 5},
            expedition_slots={"free": 1, "used": 6, "total": 7},
            payload={"metal": 0, "crystal": 0, "deuterium": 0},
            target_evidence={
                "owned_planet": False,
                "empty": True,
                "inactive": False,
                "destroyed": False,
                "vacation": False,
            },
            observed_at=100,
        )
        candidate = build_fleet_candidate(
            **base,
            ship_composition={"203": 50, "219": 1},
        )
        without_pathfinder = build_fleet_candidate(
            **base,
            ship_composition={"203": 50},
        )
        self.assertNotEqual(candidate["action_id"], without_pathfinder["action_id"])
        plan = {
            "planet_id": "42",
            "storage_capacities": {"metal": 1, "crystal": 1, "deuterium": 1},
            "queue_busy": {"fleet": False},
        }
        assess_workflow_candidate(candidate, plan, constants=ACCOUNT_CONSTANTS, now=100)
        candidate["ships_before"]["219"] = 0
        with self.assertRaisesRegex(RuntimeError, "219.*數量不足"):
            assess_workflow_candidate(candidate, plan, constants=ACCOUNT_CONSTANTS, now=100)

    def test_movement_deduplicates_legs_and_uses_confirmed_return(self):
        movement = {
            "success": True,
            "coverage": "verified",
            "threat_status": "none",
            "events": [
                {
                    "fleet_id": "fleet-1",
                    "mission_type": "15",
                    "return_flight": False,
                    "origin_coords": "[1:1:1]",
                    "dest_coords": "[1:9:16]",
                    "direction": "own",
                    "direction_evidence": "peaceful_mission_type:15",
                    "end_epoch": 100,
                },
                {
                    "fleet_id": "fleet-1",
                    "mission_type": "15",
                    "return_flight": True,
                    "origin_coords": "[1:9:16]",
                    "dest_coords": "[1:1:1]",
                    "direction": "own",
                    "direction_evidence": "own_fleet:return_flight",
                    "end_epoch": 200,
                },
                {
                    "fleet_id": "manual-2",
                    "mission_type": "15",
                    "return_flight": True,
                    "origin_coords": "[1:15:16]",
                    "dest_coords": "[1:1:1]",
                    "direction": "own",
                    "direction_evidence": "own_fleet:return_flight",
                    "end_epoch": 180,
                },
            ],
        }
        summary = expedition_agent.summarize_expeditions(movement)
        self.assertEqual(summary["active_count"], 2)
        self.assertEqual(summary["system_counts"], {"1:9": 1, "1:15": 1})
        self.assertEqual(summary["earliest_return_epoch"], 180)

    def test_movement_rejects_unstable_ids_and_conflicting_return_times(self):
        base = {
            "success": True,
            "coverage": "verified",
            "threat_status": "none",
            "events": [{
                "fleet_id": "",
                "mission_type": "15",
                "return_flight": True,
                "origin_coords": "[1:9:16]",
                "dest_coords": "[1:1:1]",
                "direction": "own",
                "direction_evidence": "own_fleet:return_flight",
                "end_epoch": 200,
            }],
        }
        with self.assertRaisesRegex(RuntimeError, "fleet_id 與 event id"):
            expedition_agent.summarize_expeditions(base)
        first = dict(base["events"][0], fleet_id="fleet-1")
        second = dict(first, end_epoch=201)
        with self.assertRaisesRegex(RuntimeError, "衝突"):
            expedition_agent.summarize_expeditions({**base, "events": [first, second]})

    def test_seven_manual_expeditions_use_return_rows_without_fleet_ids(self):
        events = []
        systems = [10, 10, 9, 9, 9, 11, 11]
        for index, system in enumerate(systems):
            common = {
                "fleet_id": "",
                "mission_type": "15",
                "origin_coords": "[1:1:1]",
                "dest_coords": f"[1:{system}:16]",
                "direction": "own",
                "direction_evidence": "own_fleet:test",
            }
            events.append({**common, "id": f"out-{index}", "return_flight": False, "end_epoch": 100 + index})
            events.append({**common, "id": f"ret-{index}", "return_flight": True, "end_epoch": 200 + index})
        summary = expedition_agent.summarize_expeditions({
            "success": True,
            "coverage": "verified",
            "threat_status": "none",
            "events": events,
        })
        self.assertEqual(summary["active_count"], 7)
        self.assertEqual(summary["system_counts"], {"1:10": 2, "1:9": 3, "1:11": 2})
        self.assertEqual(summary["earliest_return_epoch"], 200)

    def test_round_robin_balances_origin_and_adjacent_systems(self):
        counts = {"1:10": 2, "1:9": 2, "1:11": 1, "1:15": 9}
        chosen, cursor = expedition_agent.choose_target_system(
            galaxy=1,
            origin_system=10,
            system_counts=counts,
            cursor=0,
        )
        self.assertEqual((chosen, cursor), (11, 0))
        self.assertEqual(expedition_agent.adjacent_systems(1), (1, 499, 2))

    def test_postcondition_requires_exact_full_composition_deduction(self):
        candidate = {
            "planet_id": "42",
            "mission": "expedition",
            "target": {"galaxy": 1, "system": 10, "position": 16},
            "ship_tech": "203",
            "ship_amount": 50,
            "ship_composition": {"203": 50, "219": 1},
            "ships_before": {"203": 60, "219": 2},
            "expedition_slots": {"known": True, "used": 6, "total": 7, "free": 1},
        }
        after = {
            "planet_id": "42",
            "fleet_state": {
                "ships": {"203": 10, "219": 2},
                "expedition_slots": {"known": True, "used": 7, "total": 7, "free": 0},
            },
            "events": {"events": [{"text": "Expedition [1:10:16]", "mission_type": "15"}]},
        }
        result = verify_fleet_dispatch(candidate, {"success": True}, after)
        self.assertFalse(result["success"])
        self.assertFalse(result["evidence"]["ship_deducted"])

    def test_command_fills_one_vacancy_then_defers_exact_return(self):
        now = int(time.time())
        first = (
            {},
            {"active_count": 0, "system_counts": {}, "earliest_return_epoch": None},
            {
                "planet_id": "42",
                "origin_coords": "1:1:1",
                "fleet_slots": {"known": True, "free": 2, "used": 3, "total": 5},
                "expedition_slots": {"known": True, "free": 1, "used": 0, "total": 1},
                "expedition_templates": [{"name": "Agent", "ships": {"203": 5, "219": 1}}],
            },
        )
        second = (
            {},
            {"active_count": 1, "system_counts": {"1:1": 1}, "earliest_return_epoch": now + 3600},
            {
                "planet_id": "42",
                "origin_coords": "1:1:1",
                "fleet_slots": {"known": True, "free": 1, "used": 4, "total": 5},
                "expedition_slots": {"known": True, "free": 0, "used": 1, "total": 1},
                "expedition_templates": [{"name": "agent", "ships": {"203": 5, "219": 1}}],
            },
        )
        plan = {"plan_id": "p1", "candidates": [{"action_id": "fleet:one"}]}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(expedition_agent.lifecycle, "require_run_lease"), \
             patch.object(expedition_agent.lifecycle, "load_next_wake", return_value=None), \
             patch.object(expedition_agent, "_validated_cycle_state", side_effect=[first, second]), \
             patch.object(expedition_agent.execution, "create_fleet_confirmed_plan", return_value=plan) as create, \
             patch.object(expedition_agent.execution, "command_apply", return_value={"status": "applied"}), \
             patch.object(expedition_agent.lifecycle, "write_next_wake") as write_wake, \
             patch.object(expedition_agent.lifecycle, "print_command_output"), \
             patch.object(expedition_agent.time, "sleep"):
            result = expedition_agent.command_expedition_agent(argparse.Namespace(
                planet_id=42,
                run_id="run-1",
                preset="agent",
                max_wait_seconds=900,
                max_cycles=8,
                state_file=str(Path(tmp) / "state.json"),
                constants=DEFAULT_CONSTANTS_PATH,
                confirm=True,
                output="json",
            ))
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(len(result["dispatched"]), 1)
        self.assertEqual(create.call_args.args[0].system, 1)
        write_wake.assert_called_once()

    def test_deferred_wake_preserves_an_earlier_global_wake(self):
        with patch.object(expedition_agent.time, "time", return_value=100), \
             patch.object(expedition_agent.lifecycle, "write_next_wake") as write_wake:
            selected = expedition_agent._write_earliest_next_wake(500, 400)
        self.assertEqual(selected, 400)
        write_wake.assert_called_once_with(400)


if __name__ == "__main__":
    unittest.main()
