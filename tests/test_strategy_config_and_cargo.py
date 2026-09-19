import pathlib
import tempfile
import unittest

from scripts.ogame.farming import evaluate_farming_targets
from scripts.ogame.operations import cargo_capacity
from scripts.ogame.policy import (
    DEFAULT_CONSTANTS_PATH,
    DEFAULT_STRATEGY_PATH,
    load_account_constants,
    load_strategy_policy,
)


class StrategyConfigAndCargoTests(unittest.TestCase):
    def test_strategy_and_account_constants_are_loaded_separately(self):
        strategy = load_strategy_policy(DEFAULT_STRATEGY_PATH)
        constants = load_account_constants(DEFAULT_CONSTANTS_PATH)

        self.assertEqual(strategy.schema_version, 1)
        self.assertEqual(strategy.policy_version, "2026-09-14.2")
        self.assertEqual(constants.cargo_capacity("202"), 5000)
        self.assertEqual(constants.cargo_capacity(203), 25000)
        self.assertEqual(cargo_capacity("203", constants), 25000)
        self.assertEqual(constants.cargo_capacity("999"), 0)

    def test_missing_or_invalid_cargo_capacity_rejects_the_configuration(self):
        config = pathlib.Path(DEFAULT_CONSTANTS_PATH).read_text(encoding="utf-8")
        invalid = config.replace('"203" = 25000', '"203" = 0')
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir, "constants.toml")
            path.write_text(invalid, encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "cargo_capacities"):
                load_account_constants(path.as_posix())

    def test_strategy_rejects_account_constants(self):
        config = pathlib.Path(DEFAULT_STRATEGY_PATH).read_text(encoding="utf-8")
        invalid = config.replace(
            "[power_squeeze]",
            '[cargo_capacities]\n"202" = 5000\n"203" = 25000\n\n[power_squeeze]',
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir, "strategy.toml")
            path.write_text(invalid, encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "cargo_capacities"):
                load_strategy_policy(path.as_posix())

    def test_farming_raid_uses_the_configured_capacity(self):
        constants = load_account_constants(DEFAULT_CONSTANTS_PATH)
        result = evaluate_farming_targets(
            scanned_targets=[{
                "coords": "[1:1:5]",
                "galaxy": 1,
                "system": 1,
                "position": 5,
                "is_inactive": True,
                "is_destroyed": False,
                "is_vacation": False,
                "attacks_24h": 0,
                "report_observed_at": 1789232400,
                "total_resources": 50000,
                "defense_count": 0,
                "fleet_count": 0,
            }],
            available_fleet_slots=3,
            available_ships={"espionage_probe": 0, "small_cargo": 0, "large_cargo": 1},
            cargo_capacities=constants.cargo_capacities,
            now=1789232400,
        )

        self.assertEqual(result["raids_to_launch"][0]["ship_tech"], "203")
        self.assertEqual(result["raids_to_launch"][0]["ship_amount"], 1)


if __name__ == "__main__":
    unittest.main()
