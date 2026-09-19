import unittest

from scripts.ogame.colony_bootstrap import (
    BootstrapPolicy,
    allocate_transport,
    choose_next_action,
    delivery_need,
    energy_delta,
    forecast_budget,
    optimal_infrastructure,
    optimal_robotics_level,
    technology_cost,
)
from scripts.ogame.matrix import calc_storage_capacity
from scripts.ogame.policy import DEFAULT_CONSTANTS_PATH, load_account_constants


CONFIGURED_CARGO_CAPACITIES = load_account_constants(DEFAULT_CONSTANTS_PATH).cargo_capacities


def candidate(tech_id, level, *, energy=0, resources=None):
    costs = technology_cost(tech_id, level + 1)
    resources = resources or {"metal": 10**9, "crystal": 10**9, "deuterium": 10**9}
    safe = energy + energy_delta(tech_id, level + 1) >= -20
    return {
        "action_id": f"x:{tech_id}", "operation": "upgrade", "tech_id": tech_id,
        "name": tech_id, "level": level, "target_level": level + 1, "costs": costs,
        "energy_safe": safe,
        "actionable_now": safe and all(resources[key] >= costs[key] for key in resources),
        "resource_shortfall": {key: max(0, costs[key] - resources[key]) for key in resources},
    }


def plan(levels=None, *, energy=1000, resources=None, capacities=None, busy=False, end_epoch=None):
    levels = {"1": 0, "2": 0, "3": 0, "4": 0, "14": 0, "15": 0, "22": 0, "23": 0, "24": 0, **(levels or {})}
    resources = resources or {"metal": 10**9, "crystal": 10**9, "deuterium": 10**9}
    capacities = capacities or {key: calc_storage_capacity(12) for key in resources}
    return {
        "candidates": [candidate(tech_id, level, energy=energy, resources=resources) for tech_id, level in levels.items()],
        "energy": energy, "resources": resources, "storage_capacities": capacities,
        "queue_busy": {"building": busy}, "building_queue": {"active": busy, "end_epoch": end_epoch},
    }


class ColonyBootstrapTests(unittest.TestCase):
    def test_standard_formula_costs(self):
        self.assertEqual(technology_cost("1", 1), {"metal": 60, "crystal": 15, "deuterium": 0})
        self.assertEqual(technology_cost("14", 3), {"metal": 1600, "crystal": 480, "deuterium": 800})

    def test_robotics_is_front_loaded_when_it_reduces_total_target_time(self):
        policy = BootstrapPolicy(target_metal=20, target_crystal=20, target_deuterium=17, max_robotics=10)
        levels = {"1": 0, "2": 0, "3": 0, "4": 0, "14": 0, "15": 0, "22": 0, "23": 0, "24": 0}
        self.assertGreaterEqual(optimal_robotics_level(levels, policy), 8)
        self.assertEqual(choose_next_action(plan(levels), policy)["tech_id"], "14")

    def test_default_mature_floor_uses_robotics_10_and_nanite_1(self):
        policy = BootstrapPolicy()
        levels = {"1": 0, "2": 0, "3": 0, "4": 0, "14": 0, "15": 0, "22": 0, "23": 0, "24": 0}
        self.assertEqual(optimal_infrastructure(levels, policy), (10, 1))

    def test_solar_is_selected_before_an_energy_unsafe_mine(self):
        policy = BootstrapPolicy(target_metal=1, target_crystal=0, target_deuterium=0, max_robotics=0, max_nanite=0)
        self.assertEqual(choose_next_action(plan(energy=-15), policy)["tech_id"], "4")

    def test_storage_is_just_in_time_for_large_single_build(self):
        policy = BootstrapPolicy(target_metal=20, target_crystal=0, target_deuterium=0, max_robotics=0, max_nanite=0)
        capacities = {"metal": 10_000, "crystal": 10_000, "deuterium": 10_000}
        self.assertEqual(choose_next_action(plan({"1": 19}, capacities=capacities), policy)["tech_id"], "22")

    def test_busy_queue_returns_exact_timer(self):
        decision = choose_next_action(plan(busy=True, end_epoch=123456), BootstrapPolicy())
        self.assertEqual(decision, {"status": "waiting", "reason": "building_queue_busy", "end_epoch": 123456})

    def test_forecast_and_delivery_are_bounded_by_headroom(self):
        policy = BootstrapPolicy(target_metal=2, target_crystal=2, target_deuterium=0, max_robotics=0, max_nanite=0, lookahead_steps=3)
        p = plan(resources={"metal": 0, "crystal": 0, "deuterium": 0},
                 capacities={"metal": 100, "crystal": 80, "deuterium": 50})
        self.assertGreater(sum(forecast_budget(p, policy).values()), 0)
        need = delivery_need(p, policy)
        self.assertLessEqual(need["metal"], 100)
        self.assertLessEqual(need["crystal"], 80)

    def test_transport_uses_ssot_capacity_and_preserves_half_source_stock(self):
        allocation = allocate_transport(
            {"metal": 100_000, "crystal": 100_000, "deuterium": 0},
            {"resources": {"metal": 100_000, "crystal": 80_000, "deuterium": 20_000}, "ships": {"203": 2}},
            {"metal": 0, "crystal": 0, "deuterium": 0},
            cargo_capacities=CONFIGURED_CARGO_CAPACITIES,
        )
        self.assertIsNotNone(allocation)
        self.assertLessEqual(sum(allocation["payload"].values()), 2 * CONFIGURED_CARGO_CAPACITIES["203"])
        self.assertLessEqual(allocation["payload"]["metal"], 50_000)
        self.assertLessEqual(allocation["payload"]["crystal"], 40_000)


if __name__ == "__main__":
    unittest.main()
