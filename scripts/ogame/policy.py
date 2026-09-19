"""Hard-coded safety policy and strictly validated strategy configuration."""

from __future__ import annotations

import os
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Tuple


_ALLOWED_ECONOMY_ACTIONS = {
    "metal_mine",
    "crystal_mine",
    "deuterium_synthesizer",
}


@dataclass(frozen=True)
class SafetyPolicy:
    """Non-configurable hard safety limits.

    ``init=False`` fields prevent TOML, CLI arguments, or skill advice from
    weakening these values at runtime.
    """

    version: str = field(default="2", init=False)
    min_safe_energy: int = field(default=-20, init=False)
    max_actions_per_run: int = field(default=999, init=False)
    max_storage_spend_fraction: float = field(default=0.90, init=False)
    minimum_free_fleet_slots: int = field(default=1, init=False)
    max_inactive_raids_per_target_24h: int = field(default=999, init=False)
    require_zero_defense: bool = field(default=True, init=False)
    require_zero_fleet: bool = field(default=True, init=False)
    forbid_dark_matter: bool = field(default=True, init=False)
    forbid_messages: bool = field(default=True, init=False)
    fail_closed_on_anomaly: bool = field(default=True, init=False)

    def energy_is_safe(self, current: int | None, delta: int | None) -> bool:
        return current is not None and delta is not None and current + delta >= self.min_safe_energy

    def storage_cost_is_safe(self, costs: Mapping[str, int], capacities: Mapping[str, int]) -> bool:
        for resource, raw_cost in costs.items():
            capacity = int(capacities.get(resource, 0) or 0)
            cost = int(raw_cost)
            if cost > 0 and capacity <= 0:
                return False
            if cost > capacity * self.max_storage_spend_fraction:
                return False
        return True


SAFETY_POLICY = SafetyPolicy()


@dataclass(frozen=True)
class StrategyPolicy:
    schema_version: int
    policy_version: str
    profile: str
    power_squeeze_enabled: bool
    power_surplus_threshold: int
    target_energy: int
    colonization_cycle_enabled: bool
    preferred_colony_position: int
    colony_scan_radius: int
    max_colony_candidates: int
    logistics_enabled: bool
    minimum_transport_amount: int
    maximum_transport_per_resource: int
    farming_enabled: bool
    minimum_raid_loot: int
    max_farming_targets: int
    max_concurrent_raids: int
    preferred_economy_actions: Tuple[str, ...]


@dataclass(frozen=True)
class AccountConstants:
    """Validated, user-maintained account facts that may change over time."""

    schema_version: int
    cargo_capacities: Mapping[str, int]

    def cargo_capacity(self, ship_tech: str | int) -> int:
        """Return the configured live capacity for a supported cargo ship."""
        return int(self.cargo_capacities.get(str(ship_tech), 0))


def _exact_keys(value: Mapping[str, Any], expected: set[str], section: str) -> None:
    missing = expected - set(value)
    extras = set(value) - expected
    if missing or extras:
        details = []
        if missing:
            details.append(f"缺少 {', '.join(sorted(missing))}")
        if extras:
            details.append(f"未知 {', '.join(sorted(extras))}")
        raise ValueError(f"strategy.toml [{section}] schema 無效：{'；'.join(details)}")


def _plain_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"strategy.toml {name} 必須是整數。")
    return value


def load_strategy_policy(path: str) -> StrategyPolicy:
    """Load a versioned strategy policy; malformed or unknown fields stop execution."""
    try:
        with open(path, "rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"無法載入 strategy policy：{exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("strategy.toml 根節點必須是 table。")
    try:
        _exact_keys(
            raw,
            {"schema_version", "strategy", "power_squeeze", "growth", "logistics", "farming"},
            "root",
        )
        strategy = raw["strategy"]
        power = raw["power_squeeze"]
        growth = raw["growth"]
        logistics = raw["logistics"]
        farming = raw["farming"]
        if not all(isinstance(section, dict) for section in (strategy, power, growth, logistics, farming)):
            raise ValueError("strategy/power_squeeze/growth/logistics/farming 必須是 table。")
        _exact_keys(strategy, {"policy_version", "profile"}, "strategy")
        _exact_keys(power, {"enabled", "surplus_threshold", "target_energy", "preferred_economy_actions"}, "power_squeeze")
        _exact_keys(
            growth,
            {"colonization_cycle_enabled", "preferred_colony_position", "scan_radius", "max_candidates"},
            "growth",
        )
        _exact_keys(
            logistics,
            {"enabled", "minimum_transport_amount", "maximum_transport_per_resource"},
            "logistics",
        )
        _exact_keys(
            farming,
            {"enabled", "minimum_raid_loot", "max_targets", "max_concurrent_raids"},
            "farming",
        )
        schema_version = _plain_int(raw["schema_version"], "schema_version")
        if schema_version != 1:
            raise ValueError("strategy.toml schema_version 必須為 1。")
        if not isinstance(strategy["policy_version"], str) or not strategy["policy_version"]:
            raise ValueError("strategy.policy_version 必須是非空字串。")
        if not isinstance(strategy["profile"], str) or not strategy["profile"]:
            raise ValueError("strategy.profile 必須是非空字串。")
        if not isinstance(power["enabled"], bool):
            raise ValueError("power_squeeze.enabled 必須是 boolean。")
        if not isinstance(growth["colonization_cycle_enabled"], bool):
            raise ValueError("growth.colonization_cycle_enabled 必須是 boolean。")
        if not isinstance(logistics["enabled"], bool):
            raise ValueError("logistics.enabled 必須是 boolean。")
        if not isinstance(farming["enabled"], bool):
            raise ValueError("farming.enabled 必須是 boolean。")
        preferred = power["preferred_economy_actions"]
        if not isinstance(preferred, list) or not preferred or not all(isinstance(item, str) and item for item in preferred):
            raise ValueError("preferred_economy_actions 必須是非空字串陣列。")
        if len(set(preferred)) != len(preferred):
            raise ValueError("preferred_economy_actions 不得重複。")
        unknown_actions = set(preferred) - _ALLOWED_ECONOMY_ACTIONS
        if unknown_actions:
            raise ValueError(
                "preferred_economy_actions 含未知 typed action："
                + ", ".join(sorted(unknown_actions))
            )
        surplus = _plain_int(power["surplus_threshold"], "power_squeeze.surplus_threshold")
        target = _plain_int(power["target_energy"], "power_squeeze.target_energy")
        if surplus < 0:
            raise ValueError("power_squeeze.surplus_threshold 不得小於 0。")
        if target < SAFETY_POLICY.min_safe_energy:
            raise ValueError("Strategy target_energy 不得低於 SafetyPolicy MIN_SAFE_ENERGY。")
        preferred_colony_position = _plain_int(growth["preferred_colony_position"], "growth.preferred_colony_position")
        colony_scan_radius = _plain_int(growth["scan_radius"], "growth.scan_radius")
        max_colony_candidates = _plain_int(growth["max_candidates"], "growth.max_candidates")
        minimum_transport_amount = _plain_int(logistics["minimum_transport_amount"], "logistics.minimum_transport_amount")
        maximum_transport_per_resource = _plain_int(
            logistics["maximum_transport_per_resource"],
            "logistics.maximum_transport_per_resource",
        )
        minimum_raid_loot = _plain_int(farming["minimum_raid_loot"], "farming.minimum_raid_loot")
        max_farming_targets = _plain_int(farming["max_targets"], "farming.max_targets")
        max_concurrent_raids = _plain_int(farming["max_concurrent_raids"], "farming.max_concurrent_raids")
        if not 1 <= preferred_colony_position <= 15:
            raise ValueError("growth.preferred_colony_position 必須介於 1 到 15。")
        if not 0 <= colony_scan_radius <= 10:
            raise ValueError("growth.scan_radius 必須介於 0 到 10。")
        if not 0 <= max_colony_candidates <= 5:
            raise ValueError("growth.max_candidates 必須介於 0 到 5。")
        if minimum_transport_amount < 1:
            raise ValueError("logistics.minimum_transport_amount 必須大於 0。")
        if maximum_transport_per_resource < minimum_transport_amount:
            raise ValueError("logistics.maximum_transport_per_resource 不得低於 minimum_transport_amount。")
        if minimum_raid_loot < 1:
            raise ValueError("farming.minimum_raid_loot 必須大於 0。")
        if not 0 <= max_farming_targets <= 25:
            raise ValueError("farming.max_targets 必須介於 0 到 25。")
        if not 0 <= max_concurrent_raids <= 5:
            raise ValueError("farming.max_concurrent_raids 必須介於 0 到 5。")
        return StrategyPolicy(
            schema_version=schema_version,
            policy_version=strategy["policy_version"],
            profile=strategy["profile"],
            power_squeeze_enabled=power["enabled"],
            power_surplus_threshold=surplus,
            target_energy=target,
            colonization_cycle_enabled=growth["colonization_cycle_enabled"],
            preferred_colony_position=preferred_colony_position,
            colony_scan_radius=colony_scan_radius,
            max_colony_candidates=max_colony_candidates,
            logistics_enabled=logistics["enabled"],
            minimum_transport_amount=minimum_transport_amount,
            maximum_transport_per_resource=maximum_transport_per_resource,
            farming_enabled=farming["enabled"],
            minimum_raid_loot=minimum_raid_loot,
            max_farming_targets=max_farming_targets,
            max_concurrent_raids=max_concurrent_raids,
            preferred_economy_actions=tuple(preferred),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError):
            raise RuntimeError(str(exc)) from exc
        raise RuntimeError(f"strategy.toml schema 無效：{exc}") from exc


DEFAULT_STRATEGY_PATH = os.path.join(os.path.dirname(__file__), "config", "strategy.toml")
DEFAULT_CONSTANTS_PATH = os.path.join(os.path.dirname(__file__), "config", "constants.toml")


def load_account_constants(path: str) -> AccountConstants:
    """Load account-specific constants; missing or malformed capacity blocks execution."""
    try:
        with open(path, "rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"無法載入 account constants：{exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("constants.toml 根節點必須是 table。")
    try:
        _exact_keys(raw, {"schema_version", "cargo_capacities"}, "root")
        schema_version = _plain_int(raw["schema_version"], "schema_version")
        if schema_version != 1:
            raise ValueError("constants.toml schema_version 必須為 1。")
        cargo_capacities = raw["cargo_capacities"]
        if not isinstance(cargo_capacities, dict):
            raise ValueError("constants.toml cargo_capacities 必須是 table。")
        _exact_keys(cargo_capacities, {"202", "203"}, "cargo_capacities")
        parsed_cargo_capacities = {
            tech_id: _plain_int(cargo_capacities[tech_id], f"cargo_capacities.{tech_id}")
            for tech_id in ("202", "203")
        }
        if any(capacity <= 0 for capacity in parsed_cargo_capacities.values()):
            raise ValueError("cargo_capacities 的所有容量必須大於 0。")
        return AccountConstants(
            schema_version=schema_version,
            cargo_capacities=MappingProxyType(parsed_cargo_capacities),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError):
            raise RuntimeError(str(exc)) from exc
        raise RuntimeError(f"constants.toml schema 無效：{exc}") from exc
