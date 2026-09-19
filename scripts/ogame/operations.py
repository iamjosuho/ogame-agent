"""Pure domain validation for confirmed OGame action candidates.

The patrol skill never constructs these payloads.  Python read adapters create
them from live evidence, the skill selects only opaque ``action_id`` values,
and this module applies the hard policy before a WorkflowPlan can be created.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .policy import AccountConstants, SAFETY_POLICY, SafetyPolicy, StrategyPolicy


RESOURCE_KEYS = ("metal", "crystal", "deuterium")
MAX_ESPIONAGE_REPORT_AGE_SECONDS = 2 * 60 * 60


class OperationKind(str, Enum):
    UPGRADE = "upgrade"
    PRODUCE = "produce"
    FLEET_DISPATCH = "fleet_dispatch"
    CANCEL_BUILDING = "cancel_building"
    LIFEFORM_UPGRADE = "lifeform_upgrade"


class FleetMission(str, Enum):
    TRANSPORT = "transport"
    DEPLOY = "deploy"
    COLONIZE = "colonize"
    SPY = "spy"
    RAID = "raid"
    EXPEDITION = "expedition"
    LIFEFORM_EXPLORE = "lifeform_explore"


@dataclass(frozen=True)
class CandidateAssessment:
    """Normalized constraints consumed by the pure WorkflowPlan builder."""

    operation: OperationKind
    queue_key: str
    committed_resources: Mapping[str, int]
    storage_limited_resources: Mapping[str, int]
    energy_delta: Optional[int]


def _fleet_action_id(material: Mapping[str, Any]) -> str:
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"fleet:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:16]}"


def build_fleet_candidate(
    *,
    planet_id: str,
    mission: FleetMission,
    target: Mapping[str, int],
    ship_tech: str,
    ship_amount: int,
    ships_before: Mapping[str, int],
    fleet_slots: Mapping[str, int],
    ship_composition: Optional[Mapping[str, int]] = None,
    expedition_slots: Optional[Mapping[str, int]] = None,
    payload: Optional[Mapping[str, int]] = None,
    target_evidence: Mapping[str, Any],
    target_resources: Optional[Mapping[str, int]] = None,
    target_storage_capacities: Optional[Mapping[str, int]] = None,
    owner_authorized_large_transport: bool = False,
    observed_at: Optional[int] = None,
) -> Dict[str, Any]:
    """Create one opaque typed fleet candidate from already-observed evidence."""
    observed_at = int(time.time() if observed_at is None else observed_at)
    normalized_target = _coordinates(target)
    normalized_payload = _resource_vector(
        payload or {key: 0 for key in RESOURCE_KEYS},
        "payload",
    )
    normalized_composition = {
        str(key): int(value)
        for key, value in (ship_composition or {str(ship_tech): int(ship_amount)}).items()
    }
    material = {
        "planet_id": str(planet_id),
        "mission": mission.value,
        "target": normalized_target,
        "ship_tech": str(ship_tech),
        "ship_amount": int(ship_amount),
        "ship_composition": normalized_composition,
        "payload": normalized_payload,
        "target_evidence": dict(target_evidence),
        "observed_at": observed_at,
    }
    candidate: Dict[str, Any] = {
        "action_id": _fleet_action_id(material),
        "operation": OperationKind.FLEET_DISPATCH.value,
        "planet_id": str(planet_id),
        "section": "fleet",
        "component": "fleetdispatch",
        "queue": "fleet",
        "can_apply": True,
        "energy_safe": True,
        "mission": mission.value,
        "target": normalized_target,
        "tech_id": str(ship_tech),
        "ship_tech": str(ship_tech),
        "ship_amount": int(ship_amount),
        "ship_composition": normalized_composition,
        "ships_before": {str(key): int(value) for key, value in ships_before.items()},
        "fleet_slots": {str(key): int(value) for key, value in fleet_slots.items() if value is not None},
        "payload": normalized_payload,
        "owner_authorized_large_transport": bool(owner_authorized_large_transport),
        "target_evidence": dict(target_evidence),
        "costs": {key: 0 for key in RESOURCE_KEYS},
        "estimated_duration": 300,
    }
    if expedition_slots is not None:
        candidate["expedition_slots"] = {
            str(key): int(value)
            for key, value in expedition_slots.items()
            if value is not None and not isinstance(value, bool)
        }
    if target_resources is not None:
        candidate["target_resources"] = _resource_vector(target_resources, "target_resources")
    if target_storage_capacities is not None:
        candidate["target_storage_capacities"] = _resource_vector(
            target_storage_capacities,
            "target_storage_capacities",
        )
    return candidate


def resolve_expedition_preset(
    templates: Any,
    name: str = "agent",
) -> Dict[str, Any]:
    """Resolve one exact, case-insensitive expedition preset."""
    if not isinstance(name, str) or not name.strip():
        raise RuntimeError("expedition preset 名稱不得為空。")
    if not isinstance(templates, Sequence) or isinstance(templates, (str, bytes)):
        raise RuntimeError("expedition preset 清單無法可靠解析。")
    wanted = name.strip().casefold()
    matches = [
        item for item in templates
        if isinstance(item, Mapping)
        and isinstance(item.get("name"), str)
        and str(item["name"]).strip().casefold() == wanted
    ]
    if len(matches) != 1:
        reason = "不存在" if not matches else "重複"
        raise RuntimeError(f"expedition preset {name!r} {reason}；已 fail closed。")
    raw_ships = matches[0].get("ships")
    if not isinstance(raw_ships, Mapping) or not raw_ships:
        raise RuntimeError(f"expedition preset {name!r} 缺少可驗證艦隊編成。")
    ships: Dict[str, int] = {}
    for raw_tech, raw_amount in raw_ships.items():
        tech = str(raw_tech)
        if not tech.isdigit() or isinstance(raw_amount, bool) or not isinstance(raw_amount, int) or raw_amount <= 0:
            raise RuntimeError(f"expedition preset {name!r} 含無效艦船資料。")
        ships[tech] = raw_amount
    return {"name": str(matches[0]["name"]).strip(), "ships": ships}


def cargo_capacity(ship_tech: str | int, constants: AccountConstants) -> int:
    """Return one cargo ship's live, configuration-validated capacity."""
    return constants.cargo_capacity(ship_tech)


def _cargo_selection(
    ships: Mapping[str, int],
    payload_total: int,
    constants: AccountConstants,
) -> Optional[tuple[str, int]]:
    for tech_id in ("203", "202"):
        capacity = cargo_capacity(tech_id, constants)
        if capacity <= 0:
            continue
        needed = max(1, math.ceil(payload_total / capacity))
        if int(ships.get(tech_id, 0) or 0) >= needed:
            return tech_id, needed
    return None


def build_patrol_fleet_candidates(
    *,
    planet_id: str,
    origin_resources: Mapping[str, int],
    origin_storage_capacities: Mapping[str, int],
    watch_costs: Mapping[str, int],
    ships_before: Mapping[str, int],
    fleet_slots: Mapping[str, int],
    owned_targets: Sequence[Mapping[str, Any]],
    farming_suggestions: Mapping[str, Any],
    live_farming_evidence: Mapping[str, Mapping[str, Any]],
    empty_colony_targets: Sequence[Mapping[str, Any]],
    strategy: StrategyPolicy,
    constants: AccountConstants,
    observed_at: Optional[int] = None,
    safety: SafetyPolicy = SAFETY_POLICY,
) -> Dict[str, Any]:
    """Build patrol alternatives without browser access or subjective ROI scoring.

    Every returned candidate is an alternative for the single ``fleet`` queue;
    the Skill can only select its opaque action ID.
    """
    observed_at = int(time.time() if observed_at is None else observed_at)
    resources = _resource_vector(origin_resources, "origin_resources")
    capacities = _resource_vector(origin_storage_capacities, "origin_storage_capacities")
    reserve = _resource_vector(watch_costs, "watch_costs")
    ships = {str(key): int(value) for key, value in ships_before.items()}
    slots = {str(key): int(value) for key, value in fleet_slots.items() if value is not None}
    free_slots = int(slots.get("free", 0) or 0)
    if free_slots <= safety.minimum_free_fleet_slots:
        return {"candidates": [], "diagnostics": [{"reason": "no_usable_fleet_slot"}]}
    spendable = {key: max(0, resources[key] - reserve[key]) for key in RESOURCE_KEYS}
    candidates: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []

    if strategy.logistics_enabled:
        for target in owned_targets:
            try:
                target_resources = _resource_vector(target.get("resources"), "owned_target.resources")
                target_capacities = _resource_vector(
                    target.get("storage_capacities"),
                    "owned_target.storage_capacities",
                )
                payload = {}
                for key in RESOURCE_KEYS:
                    destination_headroom = max(
                        0,
                        target_capacities[key] - target_resources[key],
                    )
                    payload[key] = min(
                        spendable[key],
                        strategy.maximum_transport_per_resource,
                        capacities[key] // 2,
                        destination_headroom,
                    )
                if sum(payload.values()) < strategy.minimum_transport_amount:
                    diagnostics.append({"target": target.get("target"), "reason": "transport_below_strategy_minimum"})
                    continue
                cargo = _cargo_selection(ships, sum(payload.values()), constants)
                if cargo is None:
                    cargo_options = [
                        (tech_id, int(ships.get(tech_id, 0) or 0), cargo_capacity(tech_id, constants))
                        for tech_id in ("203", "202")
                        if int(ships.get(tech_id, 0) or 0) > 0
                    ]
                    if not cargo_options:
                        diagnostics.append({"target": target.get("target"), "reason": "transport_cargo_unavailable"})
                        continue
                    tech_id, amount, capacity = max(
                        cargo_options,
                        key=lambda item: int(item[1] * item[2]),
                    )
                    remaining = int(amount * capacity)
                    for key in RESOURCE_KEYS:
                        payload[key] = min(payload[key], remaining)
                        remaining -= payload[key]
                    if sum(payload.values()) < strategy.minimum_transport_amount:
                        diagnostics.append({"target": target.get("target"), "reason": "transport_cargo_unavailable"})
                        continue
                    cargo = (tech_id, amount)
                candidate = build_fleet_candidate(
                    planet_id=planet_id,
                    mission=FleetMission.TRANSPORT,
                    target=target["target"],
                    ship_tech=cargo[0],
                    ship_amount=cargo[1],
                    ships_before=ships,
                    fleet_slots=slots,
                    payload=payload,
                    target_resources=target_resources,
                    target_storage_capacities=target_capacities,
                    target_evidence={
                        "owned_planet": True,
                        "target_planet_id": str(target["planet_id"]),
                        "empty": False,
                        "inactive": False,
                        "destroyed": False,
                        "vacation": False,
                    },
                    observed_at=observed_at,
                )
                candidates.append(candidate)
            except (KeyError, RuntimeError, TypeError, ValueError) as exc:
                diagnostics.append({"target": target.get("target"), "reason": f"transport_evidence_invalid:{exc}"})

    if strategy.farming_enabled:
        for suggestion in farming_suggestions.get("probes_to_send", []):
            coords = str(suggestion.get("coords") or "")
            evidence = live_farming_evidence.get(coords)
            if not isinstance(evidence, Mapping):
                diagnostics.append({"target": coords, "reason": "live_farming_evidence_missing"})
                continue
            candidates.append(build_fleet_candidate(
                planet_id=planet_id,
                mission=FleetMission.SPY,
                target={key: int(suggestion[key]) for key in ("galaxy", "system", "position")},
                ship_tech="210",
                ship_amount=int(suggestion.get("probes", 1) or 1),
                ships_before=ships,
                fleet_slots=slots,
                target_evidence={
                    "owned_planet": bool(evidence.get("owned_planet")),
                    "empty": bool(evidence.get("empty")),
                    "inactive": bool(evidence.get("inactive")),
                    "destroyed": bool(evidence.get("destroyed")),
                    "vacation": bool(evidence.get("vacation")),
                },
                observed_at=observed_at,
            ))
        for suggestion in farming_suggestions.get("raids_to_launch", []):
            coords = str(suggestion.get("coords") or "")
            live = live_farming_evidence.get(coords)
            report = suggestion.get("evidence")
            if not isinstance(live, Mapping) or not isinstance(report, Mapping):
                diagnostics.append({"target": coords, "reason": "raid_evidence_missing"})
                continue
            candidates.append(build_fleet_candidate(
                planet_id=planet_id,
                mission=FleetMission.RAID,
                target={key: int(suggestion[key]) for key in ("galaxy", "system", "position")},
                ship_tech=str(suggestion["ship_tech"]),
                ship_amount=int(suggestion["ship_amount"]),
                ships_before=ships,
                fleet_slots=slots,
                target_evidence={
                    "owned_planet": bool(live.get("owned_planet")),
                    "empty": bool(live.get("empty")),
                    "inactive": bool(live.get("inactive")),
                    "destroyed": bool(live.get("destroyed")),
                    "vacation": bool(live.get("vacation")),
                    "defense_count": report.get("defense_count"),
                    "fleet_count": report.get("fleet_count"),
                    "report_observed_at": report.get("report_observed_at"),
                    "attacks_24h": report.get("attacks_24h"),
                },
                observed_at=observed_at,
            ))

    if strategy.colonization_cycle_enabled and int(ships.get("208", 0) or 0) >= 1:
        for target in empty_colony_targets[:strategy.max_colony_candidates]:
            candidates.append(build_fleet_candidate(
                planet_id=planet_id,
                mission=FleetMission.COLONIZE,
                target=target,
                ship_tech="208",
                ship_amount=1,
                ships_before=ships,
                fleet_slots=slots,
                target_evidence={
                    "owned_planet": False,
                    "empty": True,
                    "inactive": False,
                    "destroyed": False,
                    "vacation": False,
                },
                observed_at=observed_at,
            ))

    return {"candidates": candidates, "diagnostics": diagnostics}


def _plain_int(value: Any, field: str, *, minimum: Optional[int] = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"confirmed candidate {field} 必須是整數。")
    if minimum is not None and value < minimum:
        raise RuntimeError(f"confirmed candidate {field} 不得小於 {minimum}。")
    return value


def _resource_vector(value: Any, field: str) -> Dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != set(RESOURCE_KEYS):
        raise RuntimeError(f"confirmed candidate {field} 必須完整包含 metal/crystal/deuterium。")
    return {
        key: _plain_int(value[key], f"{field}.{key}", minimum=0)
        for key in RESOURCE_KEYS
    }


def _coordinates(value: Any) -> Dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {"galaxy", "system", "position"}:
        raise RuntimeError("fleet target 必須完整包含 galaxy/system/position。")
    target = {
        "galaxy": _plain_int(value["galaxy"], "target.galaxy", minimum=1),
        "system": _plain_int(value["system"], "target.system", minimum=1),
        "position": _plain_int(value["position"], "target.position", minimum=1),
    }
    if target["galaxy"] > 9 or target["system"] > 499 or target["position"] > 16:
        raise RuntimeError("fleet target 座標超出可接受範圍。")
    return target


def _require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimeError(f"confirmed candidate {field} 必須是 boolean。")
    return value


def _assess_fleet_candidate(
    candidate: Mapping[str, Any],
    confirmed_plan: Mapping[str, Any],
    safety: SafetyPolicy,
    now: int,
    constants: AccountConstants,
) -> CandidateAssessment:
    try:
        mission = FleetMission(str(candidate.get("mission")))
    except ValueError as exc:
        raise RuntimeError("confirmed fleet candidate mission 無效。") from exc
    _coordinates(candidate.get("target"))
    ship_tech = candidate.get("ship_tech")
    if not isinstance(ship_tech, str) or not ship_tech.isdigit():
        raise RuntimeError("confirmed fleet candidate ship_tech 無效。")
    ship_amount = _plain_int(candidate.get("ship_amount"), "ship_amount", minimum=1)
    ships_before = candidate.get("ships_before")
    if not isinstance(ships_before, Mapping):
        raise RuntimeError("confirmed fleet candidate 缺少 ships_before。")
    available = _plain_int(ships_before.get(ship_tech), f"ships_before.{ship_tech}", minimum=0)
    if ship_amount > available:
        raise RuntimeError("confirmed fleet candidate 艦船數量不足。")
    raw_composition = candidate.get("ship_composition")
    if raw_composition is None:
        legacy_composition = {ship_tech: ship_amount}
        legacy_combat_tech = str(candidate.get("combat_tech") or "")
        legacy_combat_amount = candidate.get("combat_amount", 0)
        if legacy_combat_tech.isdigit() and isinstance(legacy_combat_amount, int) and legacy_combat_amount > 0:
            legacy_composition[legacy_combat_tech] = legacy_composition.get(legacy_combat_tech, 0) + legacy_combat_amount
        raw_composition = legacy_composition
    if not isinstance(raw_composition, Mapping) or not raw_composition:
        raise RuntimeError("confirmed fleet candidate 缺少 ship_composition。")
    composition: Dict[str, int] = {}
    for raw_tech, raw_amount in raw_composition.items():
        tech = str(raw_tech)
        if not tech.isdigit():
            raise RuntimeError("confirmed fleet candidate ship_composition tech 無效。")
        amount = _plain_int(raw_amount, f"ship_composition.{tech}", minimum=1)
        available_amount = _plain_int(ships_before.get(tech), f"ships_before.{tech}", minimum=0)
        if amount > available_amount:
            raise RuntimeError(f"confirmed fleet candidate 艦船 {tech} 數量不足。")
        composition[tech] = amount
    if composition.get(ship_tech) != ship_amount:
        raise RuntimeError("confirmed fleet candidate 主艦數量與 ship_composition 不一致。")

    slots = candidate.get("fleet_slots")
    if not isinstance(slots, Mapping):
        raise RuntimeError("confirmed fleet candidate 缺少 fleet_slots。")
    free_slots = _plain_int(slots.get("free"), "fleet_slots.free", minimum=0)
    if free_slots - 1 < safety.minimum_free_fleet_slots:
        raise RuntimeError("Fleet dispatch 後無法保留至少一個 Fleet Slot。")

    target_evidence = candidate.get("target_evidence")
    if not isinstance(target_evidence, Mapping):
        raise RuntimeError("confirmed fleet candidate 缺少 target_evidence。")
    if _require_bool(target_evidence.get("destroyed"), "target_evidence.destroyed"):
        raise RuntimeError("已毀滅目標不得當成可殖民或可收割目標。")
    if _require_bool(target_evidence.get("vacation"), "target_evidence.vacation"):
        raise RuntimeError("假期模式目標不得派遣。")

    payload = _resource_vector(candidate.get("payload", {key: 0 for key in RESOURCE_KEYS}), "payload")
    committed = {key: 0 for key in RESOURCE_KEYS}
    if mission in {FleetMission.TRANSPORT, FleetMission.DEPLOY}:
        if not _require_bool(target_evidence.get("owned_planet"), "target_evidence.owned_planet"):
            raise RuntimeError("運輸／部署只允許 confirmed owned planet。")
        if not any(payload.values()):
            raise RuntimeError("運輸／部署 payload 不得全為 0。")
        cargo_per_ship = cargo_capacity(ship_tech, constants)
        if not cargo_per_ship:
            raise RuntimeError("運輸／部署只允許 Small/Large Cargo。")
        total_capacity = int(cargo_per_ship * ship_amount)
        if sum(payload.values()) > total_capacity:
            raise RuntimeError("運輸 payload 超過 cargo capacity 總空間。")
        committed = payload
        target_resources = _resource_vector(candidate.get("target_resources"), "target_resources")
        target_capacities = _resource_vector(candidate.get("target_storage_capacities"), "target_storage_capacities")
        for resource in RESOURCE_KEYS:
            limit = target_capacities[resource]
            if target_resources[resource] + payload[resource] > limit:
                if not candidate.get("owner_authorized_large_transport"):
                    raise RuntimeError(f"運輸會使目標 {resource} 超過倉庫容量上限。")
        origin_caps = confirmed_plan.get("storage_capacities")
        if not isinstance(origin_caps, Mapping):
            raise RuntimeError("大額運輸檢查缺少來源倉庫容量。")
        large = any(
            payload[key] > int(_plain_int(origin_caps.get(key), f"storage_capacities.{key}", minimum=1) * 0.5)
            for key in RESOURCE_KEYS
        )
        if large and not _require_bool(
            candidate.get("owner_authorized_large_transport"),
            "owner_authorized_large_transport",
        ):
            raise RuntimeError("超過來源倉庫 50% 的大額運輸缺少User授權。")
    elif any(payload.values()):
        raise RuntimeError("非運輸任務不得夾帶資源 payload。")

    elif mission == FleetMission.EXPEDITION:
        if int(candidate.get("target", {}).get("position", 0)) != 16:
            raise RuntimeError("遠征目標 position 必須為 16。")
        if ship_tech not in {"202", "203"}:
            raise RuntimeError("遠征任務必須使用運輸艦（大運或小運）。")
        before_cargo = int(ships_before.get(ship_tech, 0) or 0)
        if before_cargo - ship_amount < 2:
            raise RuntimeError("遠征出發星必須保留至少 2 艘運輸艦備用。")
        expedition_slots = candidate.get("expedition_slots")
        if not isinstance(expedition_slots, Mapping):
            raise RuntimeError("遠征任務缺少 expedition slot 證據。")
        exp_free = _plain_int(expedition_slots.get("free"), "expedition_slots.free", minimum=0)
        if exp_free < 1:
            raise RuntimeError("沒有可用 Expedition Slot。")
    elif mission == FleetMission.LIFEFORM_EXPLORE:
        # Lifeform discoveries require a free slot and fixed resource costs (5k M / 1k C / 500 D)
        explore_cost = {"metal": 5000, "crystal": 1000, "deuterium": 500}
        committed = explore_cost
        origin_res = confirmed_plan.get("resources")
        if isinstance(origin_res, Mapping):
            for res_k, cost_v in explore_cost.items():
                if int(origin_res.get(res_k, 0) or 0) < cost_v:
                    raise RuntimeError(f"生命形式探索來源星 {res_k} 不足 {cost_v}。")
    elif mission == FleetMission.COLONIZE:
        if ship_tech != "208" or ship_amount != 1:
            raise RuntimeError("殖民任務必須使用一艘殖民船。")
        if not _require_bool(target_evidence.get("empty"), "target_evidence.empty"):
            raise RuntimeError("殖民目標未被 live evidence 確認為空位。")
    elif mission == FleetMission.SPY:
        if ship_tech != "210":
            raise RuntimeError("偵察任務必須使用間諜探測機。")
        if not _require_bool(target_evidence.get("inactive"), "target_evidence.inactive"):
            raise RuntimeError("只允許偵察 (i)/(I) 閒置目標。")
    elif mission == FleetMission.RAID:
        if ship_tech not in {"202", "203"}:
            raise RuntimeError("收割任務只允許使用運輸艦。")
        if not _require_bool(target_evidence.get("inactive"), "target_evidence.inactive"):
            raise RuntimeError("只允許收割 (i)/(I) 閒置目標。")
        defense = _plain_int(target_evidence.get("defense_count"), "target_evidence.defense_count", minimum=0)
        fleet = _plain_int(target_evidence.get("fleet_count"), "target_evidence.fleet_count", minimum=0)
        if safety.require_zero_defense and defense != 0:
            raise RuntimeError("收割目標 Defense 必須精確等於 0。")
        if safety.require_zero_fleet and fleet != 0:
            raise RuntimeError("收割目標 Fleet 必須精確等於 0。")
        observed_at = _plain_int(
            target_evidence.get("report_observed_at"),
            "target_evidence.report_observed_at",
            minimum=1,
        )
        if observed_at > now or now - observed_at > MAX_ESPIONAGE_REPORT_AGE_SECONDS:
            raise RuntimeError("收割使用的間諜報告已超過 2 小時或時間無效。")
        raw_attacks = target_evidence.get("attacks_24h")
        attacks = _plain_int(raw_attacks if raw_attacks is not None else 0, "target_evidence.attacks_24h", minimum=0)
        if safety.max_inactive_raids_per_target_24h is not None and attacks > safety.max_inactive_raids_per_target_24h:
            raise RuntimeError("收割目標已達 24 小時 Bashing 上限。")

    return CandidateAssessment(
        operation=OperationKind.FLEET_DISPATCH,
        queue_key="fleet",
        committed_resources=committed,
        storage_limited_resources={key: 0 for key in RESOURCE_KEYS},
        energy_delta=None,
    )


def assess_workflow_candidate(
    candidate: Mapping[str, Any],
    confirmed_plan: Mapping[str, Any],
    *,
    constants: AccountConstants,
    safety: SafetyPolicy = SAFETY_POLICY,
    now: Optional[int] = None,
) -> CandidateAssessment:
    """Validate one Python-created candidate and expose its plan constraints."""
    now = int(time.time() if now is None else now)
    try:
        operation = OperationKind(str(candidate.get("operation", OperationKind.UPGRADE.value)))
    except ValueError as exc:
        raise RuntimeError("confirmed candidate operation 無效。") from exc
    if not isinstance(candidate.get("action_id"), str) or not candidate.get("action_id"):
        raise RuntimeError("confirmed candidate 缺少 action_id。")
    if str(candidate.get("planet_id", confirmed_plan.get("planet_id"))) != str(confirmed_plan.get("planet_id")):
        raise RuntimeError("confirmed candidate planet_id 與 plan 不符。")
    eligible_key = "can_upgrade" if operation == OperationKind.UPGRADE else "can_apply"
    if candidate.get(eligible_key) is not True:
        raise RuntimeError(f"{candidate['action_id']} 未被 live state 確認為可執行。")

    if operation == OperationKind.FLEET_DISPATCH:
        return _assess_fleet_candidate(candidate, confirmed_plan, safety, now, constants)

    zero = {key: 0 for key in RESOURCE_KEYS}
    queue_key = candidate.get("queue")
    if not isinstance(queue_key, str) or not queue_key:
        raise RuntimeError("confirmed candidate queue 無效。")

    if operation == OperationKind.CANCEL_BUILDING:
        evidence = candidate.get("queue_evidence")
        if not isinstance(evidence, Mapping) or evidence.get("active") is not True:
            raise RuntimeError("取消建造缺少 active queue evidence。")
        if str(evidence.get("queue_token") or "") != str(candidate.get("queue_token") or ""):
            raise RuntimeError("取消建造 queue token 不符。")
        return CandidateAssessment(operation, queue_key, zero, zero, None)

    costs = _resource_vector(candidate.get("costs"), "costs")
    energy_delta: Optional[int] = None
    if operation == OperationKind.UPGRADE:
        if candidate.get("section") != "research":
            energy_delta = _plain_int(candidate.get("energy_delta"), "energy_delta")
    elif operation == OperationKind.PRODUCE:
        _plain_int(candidate.get("amount"), "amount", minimum=1)
        if str(candidate.get("component")) not in {"shipyard", "defenses"}:
            raise RuntimeError("production candidate component 無效。")
    elif operation == OperationKind.LIFEFORM_UPGRADE:
        if str(candidate.get("component")) not in {"lfbuildings", "lfresearch"}:
            raise RuntimeError("lifeform candidate component 無效。")
        if candidate.get("component") == "lfbuildings":
            if candidate.get("energy_delta_known") is not True:
                raise RuntimeError("Lifeform building 能源影響未知；已 fail closed。")
            energy_delta = _plain_int(candidate.get("energy_delta"), "energy_delta")

    storage_limited = costs
    if candidate.get("section") == "research":
        storage_limited = {key: 0 for key in RESOURCE_KEYS}

    return CandidateAssessment(operation, queue_key, costs, storage_limited, energy_delta)
