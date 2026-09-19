import pathlib
import tempfile
import unittest

from scripts.ogame.farming import evaluate_farming_targets, parse_farm_targets_md
from scripts.ogame.policy import DEFAULT_CONSTANTS_PATH, load_account_constants


CONFIGURED_CARGO_CAPACITIES = load_account_constants(DEFAULT_CONSTANTS_PATH).cargo_capacities


class FarmingStrategyTests(unittest.TestCase):
    def test_fleet_capability_must_be_explicit_non_negative_integers(self):
        with self.assertRaisesRegex(ValueError, "available_ships.espionage_probe"):
            evaluate_farming_targets([], 2, {}, cargo_capacities=CONFIGURED_CARGO_CAPACITIES)
        with self.assertRaisesRegex(ValueError, "available_ships.small_cargo"):
            evaluate_farming_targets(
                [],
                2,
                {"espionage_probe": 1, "small_cargo": True, "large_cargo": 0},
                cargo_capacities=CONFIGURED_CARGO_CAPACITIES,
            )

    def test_memory_parser_never_invents_zero_combat_evidence(self):
        content = """\
| 目標座標 | 類型 | 狀態 | 最後報告 | 攻擊 | 資源 |
| --- | --- | --- | --- | --- | --- |
| [1:2:3] | 星球 | (i) | 2026-08-30 10:00 | 1/6 | 總資源: **12,000** |
| [1:2:4] | 已毀滅 | (I) | 2026-08-30 10:00 | 0/6 | 總資源: **9,000** |
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir, "farm_targets.md")
            path.write_text(content, encoding="utf-8")
            targets = parse_farm_targets_md(path.as_posix())

        self.assertEqual(len(targets), 2)
        self.assertTrue(targets[0]["is_inactive"])
        self.assertIsNone(targets[0]["defense_count"])
        self.assertIsNone(targets[0]["fleet_count"])
        self.assertTrue(targets[1]["is_destroyed"])
        self.assertFalse(targets[1]["is_inactive"])

    def test_incomplete_or_stale_report_can_only_propose_a_probe(self):
        result = evaluate_farming_targets(
            scanned_targets=[{
                "coords": "[1:2:3]",
                "galaxy": 1,
                "system": 2,
                "position": 3,
                "is_inactive": True,
                "is_destroyed": False,
                "is_vacation": False,
                "attacks_24h": 1,
                "report_observed_at": 1,
                "defense_count": None,
                "fleet_count": None,
                "total_resources": 12000,
            }],
            available_fleet_slots=3,
            available_ships={"espionage_probe": 1, "small_cargo": 2, "large_cargo": 0},
            cargo_capacities=CONFIGURED_CARGO_CAPACITIES,
            now=10000,
        )

        self.assertEqual(result["raids_to_launch"], [])
        self.assertEqual(result["probes_to_send"][0]["coords"], "[1:2:3]")

    def test_raid_requires_fresh_exact_zero_evidence_and_capacity(self):
        result = evaluate_farming_targets(
            scanned_targets=[{
                "coords": "[1:2:3]",
                "galaxy": 1,
                "system": 2,
                "position": 3,
                "is_inactive": True,
                "is_destroyed": False,
                "is_vacation": False,
                "attacks_24h": 5,
                "report_observed_at": 9000,
                "defense_count": 0,
                "fleet_count": 0,
                "resources": {"metal": 7000, "crystal": 2000, "deuterium": 1000},
            }],
            available_fleet_slots=3,
            available_ships={"espionage_probe": 0, "small_cargo": 1, "large_cargo": 0},
            min_loot_threshold=500,
            cargo_capacities=CONFIGURED_CARGO_CAPACITIES,
            now=10000,
        )

        self.assertEqual(result["probes_to_send"], [])
        self.assertEqual(result["raids_to_launch"][0]["ship_tech"], "202")
        self.assertEqual(result["raids_to_launch"][0]["evidence"]["attacks_24h"], 5)


if __name__ == "__main__":
    unittest.main()
