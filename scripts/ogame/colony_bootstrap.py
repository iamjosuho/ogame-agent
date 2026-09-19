"""Deterministic, fail-closed bootstrap controller for a new colony.

The pure planner converts OGame's transparent building formulae into one next
action.  The command runner then refreshes live evidence, sends a bounded
look-ahead resource budget, waits on exact queue timers, and replans.
"""

from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
import io
import math
import os
import random
import re
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .lifecycle import MEMORY_DIR, atomic_write_json, load_json_file, require_run_lease, write_next_wake
from .matrix import calc_storage_capacity
from .policy import DEFAULT_CONSTANTS_PATH, SAFETY_POLICY, load_account_constants


RESOURCE_KEYS = ("metal", "crystal", "deuterium")
CORE_TECH_IDS = ("1", "2", "3", "4", "14", "15", "22", "23", "24")
STORAGE_TECH_BY_RESOURCE = {"metal": "22", "crystal": "23", "deuterium": "24"}
TECH_NAMES = {
    "1": "金屬礦", "2": "晶體礦", "3": "重氫合成器", "4": "太陽能發電廠",
    "14": "機器人工廠", "15": "奈米機械工廠",
    "22": "金屬儲存器", "23": "晶體儲存器", "24": "重氫儲存槽",
}
TECH_SPECS: Dict[str, Tuple[Dict[str, int], float]] = {
    "1": ({"metal": 60, "crystal": 15, "deuterium": 0}, 1.5),
    "2": ({"metal": 48, "crystal": 24, "deuterium": 0}, 1.6),
    "3": ({"metal": 225, "crystal": 75, "deuterium": 0}, 1.5),
    "4": ({"metal": 75, "crystal": 30, "deuterium": 0}, 1.5),
    "14": ({"metal": 400, "crystal": 120, "deuterium": 200}, 2.0),
    "15": ({"metal": 1_000_000, "crystal": 500_000, "deuterium": 100_000}, 2.0),
    "22": ({"metal": 1000, "crystal": 0, "deuterium": 0}, 2.0),
    "23": ({"metal": 1000, "crystal": 500, "deuterium": 0}, 2.0),
    "24": ({"metal": 1000, "crystal": 1000, "deuterium": 0}, 2.0),
}
PRODUCTION_WEIGHTS = {"metal": 1.0, "crystal": 1.5, "deuterium": 3.0}


@dataclass(frozen=True)
class BootstrapPolicy:
    target_metal: int = 20
    target_crystal: int = 20
    target_deuterium: int = 17
    max_robotics: int = 10
    max_nanite: int = 1
    lookahead_steps: int = 6
    min_energy: int = SAFETY_POLICY.min_safe_energy

    @property
    def mine_targets(self) -> Dict[str, int]:
        return {"1": self.target_metal, "2": self.target_crystal, "3": self.target_deuterium}


def technology_cost(tech_id: str, target_level: int) -> Dict[str, int]:
    if tech_id not in TECH_SPECS or target_level < 1:
        raise ValueError("unsupported bootstrap technology or target level")
    base, factor = TECH_SPECS[tech_id]
    return {key: int(math.floor(base[key] * factor ** (target_level - 1))) for key in RESOURCE_KEYS}


def energy_delta(tech_id: str, target_level: int) -> int:
    if tech_id not in {"1", "2", "3", "4"}:
        return 0
    multiplier = 20 if tech_id in {"3", "4"} else 10
    previous = 0 if target_level <= 1 else math.floor(multiplier * (target_level - 1) * 1.1 ** (target_level - 1))
    current = math.floor(multiplier * target_level * 1.1 ** target_level)
    delta = current - previous
    return delta if tech_id == "4" else -delta


def production_delta(tech_id: str, target_level: int, deuterium_factor: float = 1.0) -> float:
    bases = {"1": 30.0, "2": 20.0, "3": 10.0 * deuterium_factor}
    if tech_id not in bases:
        return 0.0
    previous = 0.0 if target_level <= 1 else bases[tech_id] * (target_level - 1) * 1.1 ** (target_level - 1)
    current = bases[tech_id] * target_level * 1.1 ** target_level
    return current - previous


def equivalent_cost(costs: Mapping[str, int]) -> float:
    return sum(float(costs.get(key, 0)) * PRODUCTION_WEIGHTS[key] for key in RESOURCE_KEYS)


def minimum_standard_solar_level(policy: BootstrapPolicy) -> int:
    consumption = (
        math.floor(10 * policy.target_metal * 1.1 ** policy.target_metal)
        + math.floor(10 * policy.target_crystal * 1.1 ** policy.target_crystal)
        + math.floor(20 * policy.target_deuterium * 1.1 ** policy.target_deuterium)
    )
    level = 0
    while math.floor(20 * level * 1.1 ** level) + policy.min_energy < consumption:
        level += 1
    return level


def required_storage_levels(
    levels: Mapping[str, int],
    policy: BootstrapPolicy,
    *,
    robotics_target: Optional[int] = None,
    nanite_target: Optional[int] = None,
) -> Dict[str, int]:
    maximum = {key: 0 for key in RESOURCE_KEYS}
    targets = {
        **policy.mine_targets,
        "4": minimum_standard_solar_level(policy),
        "14": policy.max_robotics if robotics_target is None else robotics_target,
        "15": policy.max_nanite if nanite_target is None else nanite_target,
    }
    for tech_id, target in targets.items():
        for level in range(int(levels.get(tech_id, 0)) + 1, target + 1):
            costs = technology_cost(tech_id, level)
            for key in RESOURCE_KEYS:
                maximum[key] = max(maximum[key], costs[key])
    result: Dict[str, int] = {}
    for resource, storage_tech in STORAGE_TECH_BY_RESOURCE.items():
        level = int(levels.get(storage_tech, 0))
        while maximum[resource] > calc_storage_capacity(level) * SAFETY_POLICY.max_storage_spend_fraction:
            level += 1
        result[storage_tech] = level
    return result


def optimal_infrastructure(levels: Mapping[str, int], policy: BootstrapPolicy) -> Tuple[int, int]:
    """Minimise remaining build work across Robotics and Nanite end levels."""
    current_robotics = int(levels.get("14", 0))
    current_nanite = int(levels.get("15", 0))
    choices: List[Tuple[float, int, int, int]] = []
    for final_robotics in range(current_robotics, policy.max_robotics + 1):
        for final_nanite in range(current_nanite, policy.max_nanite + 1):
            if final_nanite > current_nanite and final_robotics < 10:
                continue
            storage_targets = required_storage_levels(
                levels,
                policy,
                robotics_target=final_robotics,
                nanite_target=final_nanite,
            )
            non_infrastructure_work = 0
            targets = {
                **policy.mine_targets,
                "4": minimum_standard_solar_level(policy),
                **storage_targets,
            }
            for tech_id, target in targets.items():
                for level in range(int(levels.get(tech_id, 0)) + 1, target + 1):
                    costs = technology_cost(tech_id, level)
                    non_infrastructure_work += costs["metal"] + costs["crystal"]
            work = 0.0
            infrastructure_cost = 0
            for target_level in range(current_robotics + 1, final_robotics + 1):
                costs = technology_cost("14", target_level)
                summed = costs["metal"] + costs["crystal"]
                work += summed / target_level / (2 ** current_nanite)
                infrastructure_cost += int(equivalent_cost(costs))
            for target_level in range(current_nanite + 1, final_nanite + 1):
                costs = technology_cost("15", target_level)
                summed = costs["metal"] + costs["crystal"]
                work += summed / (1 + final_robotics) / (2 ** (target_level - 1))
                infrastructure_cost += int(equivalent_cost(costs))
            work += non_infrastructure_work / (1 + final_robotics) / (2 ** final_nanite)
            choices.append((work, infrastructure_cost, final_robotics, final_nanite))
    best = min(choices)
    return best[2], best[3]


def optimal_robotics_level(levels: Mapping[str, int], policy: BootstrapPolicy) -> int:
    """Compatibility helper for callers interested only in Robotics."""
    return optimal_infrastructure(levels, policy)[0]


def levels_from_plan(plan: Mapping[str, Any]) -> Dict[str, int]:
    levels: Dict[str, int] = {}
    for candidate in plan.get("candidates", []):
        tech_id = str(candidate.get("tech_id") or "")
        if tech_id in CORE_TECH_IDS and candidate.get("operation") == "upgrade":
            levels[tech_id] = int(candidate.get("level", 0) or 0)
    missing = set(CORE_TECH_IDS) - set(levels)
    if missing:
        raise RuntimeError("bootstrap live plan 缺少核心建築：" + ",".join(sorted(missing)))
    return levels


def _candidate_map(plan: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(item.get("tech_id")): dict(item) for item in plan.get("candidates", [])
            if item.get("operation") == "upgrade" and str(item.get("tech_id")) in CORE_TECH_IDS}


def _storage_gate(candidate: Mapping[str, Any], plan: Mapping[str, Any], candidates: Mapping[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    capacities = plan.get("storage_capacities") or {}
    costs = candidate.get("costs") or {}
    violations = []
    for key in RESOURCE_KEYS:
        capacity = int(capacities.get(key, 0) or 0)
        cost = int(costs.get(key, 0) or 0)
        if cost and (capacity <= 0 or cost > capacity * SAFETY_POLICY.max_storage_spend_fraction):
            violations.append((cost / max(1, capacity), key))
    if not violations:
        return None
    resource = max(violations)[1]
    storage = candidates.get(STORAGE_TECH_BY_RESOURCE[resource])
    if storage is None:
        raise RuntimeError(f"bootstrap 缺少 {resource} storage candidate")
    return storage


def choose_next_action(plan: Mapping[str, Any], policy: BootstrapPolicy) -> Dict[str, Any]:
    queue = plan.get("building_queue") or {}
    if bool(queue.get("active")) or bool((plan.get("queue_busy") or {}).get("building")):
        return {"status": "waiting", "reason": "building_queue_busy",
                "end_epoch": int(queue["end_epoch"]) if queue.get("end_epoch") else None}
    levels = levels_from_plan(plan)
    candidates = _candidate_map(plan)
    optimal_robotics, optimal_nanite = optimal_infrastructure(levels, policy)
    if levels["14"] < optimal_robotics:
        selected = candidates["14"]
    elif levels["15"] < optimal_nanite:
        selected = candidates["15"]
    else:
        mine_options = []
        for tech_id, target in policy.mine_targets.items():
            if levels[tech_id] >= target:
                continue
            candidate = candidates[tech_id]
            resource = {"1": "metal", "2": "crystal", "3": "deuterium"}[tech_id]
            score = production_delta(tech_id, int(candidate["target_level"])) * PRODUCTION_WEIGHTS[resource]
            score /= max(1.0, equivalent_cost(candidate.get("costs") or {}))
            mine_options.append((-score, tech_id, candidate))
        if not mine_options:
            return {"status": "complete", "reason": "mine_targets_reached",
                    "levels": levels, "optimal_robotics": optimal_robotics, "optimal_nanite": optimal_nanite}
        selected = min(mine_options)[2]
        if selected.get("energy_safe") is not True:
            selected = candidates["4"]
    storage = _storage_gate(selected, plan, candidates)
    if storage is not None:
        selected = storage
    return {
        "status": "planned", "reason": "formula_optimized", "action_id": selected["action_id"],
        "tech_id": str(selected["tech_id"]), "name": selected.get("name") or TECH_NAMES[str(selected["tech_id"])],
        "target_level": int(selected["target_level"]),
        "costs": {key: int((selected.get("costs") or {}).get(key, 0)) for key in RESOURCE_KEYS},
        "resource_shortfall": {key: int((selected.get("resource_shortfall") or {}).get(key, 0)) for key in RESOURCE_KEYS},
        "actionable_now": bool(selected.get("actionable_now")), "optimal_robotics": optimal_robotics,
        "optimal_nanite": optimal_nanite,
    }


def forecast_budget(plan: Mapping[str, Any], policy: BootstrapPolicy) -> Dict[str, int]:
    levels = levels_from_plan(plan)
    energy = int(plan.get("energy", 0) or 0)
    capacities = {key: int((plan.get("storage_capacities") or {}).get(key, 0)) for key in RESOURCE_KEYS}
    total = {key: 0 for key in RESOURCE_KEYS}
    for _ in range(policy.lookahead_steps):
        candidates = []
        for tech_id in CORE_TECH_IDS:
            target = levels[tech_id] + 1
            costs = technology_cost(tech_id, target)
            delta = energy_delta(tech_id, target)
            candidates.append({"action_id": f"bootstrap:{tech_id}:{target}", "operation": "upgrade",
                               "tech_id": tech_id, "level": levels[tech_id], "target_level": target,
                               "name": TECH_NAMES[tech_id], "costs": costs,
                               "energy_safe": energy + delta >= policy.min_energy, "actionable_now": True,
                               "resource_shortfall": {key: 0 for key in RESOURCE_KEYS}})
        simulated = {"candidates": candidates, "queue_busy": {"building": False},
                     "building_queue": {"active": False}, "storage_capacities": capacities,
                     "resources": {key: 10**18 for key in RESOURCE_KEYS}, "energy": energy}
        decision = choose_next_action(simulated, policy)
        if decision["status"] != "planned":
            break
        tech_id = decision["tech_id"]
        for key in RESOURCE_KEYS:
            total[key] += int(decision["costs"][key])
        levels[tech_id] += 1
        energy += energy_delta(tech_id, levels[tech_id])
        if tech_id in STORAGE_TECH_BY_RESOURCE.values():
            resource = next(key for key, value in STORAGE_TECH_BY_RESOURCE.items() if value == tech_id)
            capacities[resource] = calc_storage_capacity(levels[tech_id])
    return total


def delivery_need(plan: Mapping[str, Any], policy: BootstrapPolicy, pending: Optional[Mapping[str, int]] = None) -> Dict[str, int]:
    budget = forecast_budget(plan, policy)
    resources = plan.get("resources") or {}
    capacities = plan.get("storage_capacities") or {}
    pending = pending or {}
    result = {}
    for key in RESOURCE_KEYS:
        missing = max(0, budget[key] - int(resources.get(key, 0)) - int(pending.get(key, 0)))
        headroom = max(0, int(capacities.get(key, 0)) - int(resources.get(key, 0)) - int(pending.get(key, 0)))
        result[key] = min(missing, headroom)
    return result


def allocate_transport(
    need: Mapping[str, int],
    source: Mapping[str, Any],
    reserve: Mapping[str, int],
    *,
    cargo_capacities: Mapping[str, int],
) -> Optional[Dict[str, Any]]:
    ships = source.get("ships") or {}
    source_resources = source.get("resources") or {}
    payload = {key: min(int(need.get(key, 0)),
                        max(0, int(source_resources.get(key, 0)) - int(reserve.get(key, 0))),
                        max(0, int(source_resources.get(key, 0)) // 2)) for key in RESOURCE_KEYS}
    if sum(payload.values()) <= 0:
        return None
    options = []
    for tech_id in ("203", "202"):
        available = int(ships.get(tech_id, 0) or 0)
        capacity = int(cargo_capacities.get(tech_id, 0) or 0)
        if available > 0 and capacity > 0:
            options.append((available * capacity, tech_id, available, capacity))
    if not options:
        return None
    total_capacity, tech_id, available, unit_capacity = max(options)
    remaining = min(sum(payload.values()), total_capacity)
    fitted = {key: 0 for key in RESOURCE_KEYS}
    for key in ("crystal", "metal", "deuterium"):
        fitted[key] = min(payload[key], remaining)
        remaining -= fitted[key]
    fitted_total = sum(fitted.values())
    if fitted_total <= 0:
        return None
    return {"payload": fitted, "ship_tech": tech_id,
            "ship_amount": min(available, math.ceil(fitted_total / unit_capacity))}


def _parse_coordinates(raw: Any) -> Dict[str, int]:
    match = re.search(r"\[?\s*(\d+)\s*:\s*(\d+)\s*:\s*(\d+)\s*\]?", str(raw or ""))
    if not match:
        raise RuntimeError(f"無法解析新星座標：{raw}")
    return {"galaxy": int(match.group(1)), "system": int(match.group(2)), "position": int(match.group(3))}


def _quiet_call(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def _timer_wait(run_id: str, wake_epoch: int, *, max_wait_seconds: int, started_at: int) -> Optional[int]:
    """Wait inside the current lease, or return the exact deferred wake epoch."""
    buffered = int(wake_epoch) + random.randint(5, 10)
    if buffered - int(time.time()) > max_wait_seconds:
        write_next_wake(buffered)
        return buffered
    while int(time.time()) < buffered:
        if int(time.time()) - started_at >= max_wait_seconds:
            write_next_wake(buffered)
            return buffered
        require_run_lease(run_id)
        time.sleep(min(30, max(1, buffered - int(time.time()))))
    return None


def _transport_arrival_epoch(result: Mapping[str, Any], target_text: str) -> Optional[int]:
    post_state = ((result.get("evidence") or {}).get("post_state") or {})
    events = ((post_state.get("events") or {}).get("events") or [])
    epochs = [int(item["end_epoch"]) for item in events if isinstance(item, Mapping)
              and target_text in str(item.get("text") or "") and item.get("end_epoch")]
    return min(epochs) if epochs else None


def command_colony_bootstrap(args: argparse.Namespace) -> Dict[str, Any]:
    """Run a bounded same-lease bootstrap loop using existing safe mutations."""
    from . import execution, legacy_commands, matrix

    require_run_lease(args.run_id)
    if args.mode == "run" and not args.confirm:
        raise RuntimeError("colony-bootstrap run 必須明示 --confirm。")
    numeric_values = (
        args.target_metal, args.target_crystal, args.target_deuterium, args.max_robotics, args.max_nanite,
        args.lookahead_steps, args.max_wait_seconds, args.max_steps, args.min_fields,
        args.source_reserve_metal, args.source_reserve_crystal, args.source_reserve_deuterium,
    )
    if any(isinstance(value, bool) or int(value) < 0 for value in numeric_values):
        raise RuntimeError("colony-bootstrap 數值參數不得為負數。")
    if args.lookahead_steps < 1 or args.max_wait_seconds < 1 or args.max_steps < 1:
        raise RuntimeError("lookahead/max-wait/max-steps 必須大於 0。")
    policy = BootstrapPolicy(
        target_metal=args.target_metal,
        target_crystal=args.target_crystal,
        target_deuterium=args.target_deuterium,
        max_robotics=args.max_robotics,
        max_nanite=args.max_nanite,
        lookahead_steps=args.lookahead_steps,
    )
    constants = load_account_constants(getattr(args, "constants", DEFAULT_CONSTANTS_PATH))
    state_path = os.path.join(MEMORY_DIR, f"colony-bootstrap-{int(args.planet_id)}.json")
    state = load_json_file(state_path) or {"version": 1, "planet_id": str(args.planet_id), "pending": []}
    started_at = int(time.time())
    applied: List[Dict[str, Any]] = []
    initial_empire = _quiet_call(matrix.cmd_matrix, argparse.Namespace(
        source="auto", output="human", run_id=args.run_id
    ))
    accepted = [
        item for item in initial_empire.get("planets", [])
        if str(item.get("planet_id")) == str(args.planet_id)
    ]
    if len(accepted) != 1:
        raise RuntimeError("Empire matrix 未唯一找到 bootstrap target planet。")
    fields = accepted[0].get("fields") or {}
    total_fields = fields.get("total") if isinstance(fields, Mapping) else None
    if total_fields is None or int(total_fields) < int(args.min_fields):
        raise RuntimeError(
            f"bootstrap target 未通過方格驗收：fields.total={total_fields}, required={args.min_fields}。"
        )

    for _ in range(args.max_steps):
        require_run_lease(args.run_id)
        now = int(time.time())
        pending_entries = [item for item in state.get("pending", []) if int(item.get("ready_at", 0)) > now]
        state["pending"] = pending_entries
        if any(item.get("eta_confirmed") is not True for item in pending_entries):
            result = {"status": "blocked", "reason": "transport_eta_unknown", "applied": applied}
            atomic_write_json(state_path, {**state, "last_result": result, "updated_at": now})
            return result
        pending = {key: sum(int((item.get("payload") or {}).get(key, 0)) for item in pending_entries)
                   for key in RESOURCE_KEYS}
        plan = _quiet_call(execution.command_plan, argparse.Namespace(
            planet_id=args.planet_id, run_id=args.run_id, diagnose=False, include_lifeforms=False,
            include_cancel=False, include_production=False, include_fleet=False,
            strategy=args.strategy, silent=True, output="human"))
        decision = choose_next_action(plan, policy)
        need = delivery_need(plan, policy, pending)

        if args.mode == "plan":
            result = {"status": decision["status"], "decision": decision, "delivery_need": need}
            atomic_write_json(state_path, {**state, "last_result": result, "updated_at": now})
            return result

        if sum(need.values()) > 0 and args.source_id and not pending_entries:
            empire = _quiet_call(matrix.cmd_matrix, argparse.Namespace(source="auto", output="human", run_id=args.run_id))
            planets = {str(item["planet_id"]): item for item in empire.get("planets", [])}
            target = planets.get(str(args.planet_id))
            if target is None:
                raise RuntimeError("Empire matrix 未唯一找到 bootstrap target planet。")
            coordinates = _parse_coordinates(target.get("coords"))
            reserve = {"metal": args.source_reserve_metal, "crystal": args.source_reserve_crystal,
                       "deuterium": args.source_reserve_deuterium}
            for source_id in args.source_id:
                source = planets.get(str(source_id))
                if source is None or str(source_id) == str(args.planet_id):
                    continue
                allocation = allocate_transport(
                    need,
                    source,
                    reserve,
                    cargo_capacities=constants.cargo_capacities,
                )
                if allocation is None:
                    continue
                transport = _quiet_call(legacy_commands.cmd_transport, argparse.Namespace(
                    galaxy=coordinates["galaxy"], system=coordinates["system"], position=coordinates["position"],
                    planet_id=int(source_id), run_id=args.run_id,
                    metal=allocation["payload"]["metal"], crystal=allocation["payload"]["crystal"],
                    deuterium=allocation["payload"]["deuterium"], ship_tech=allocation["ship_tech"],
                    ship_amount=allocation["ship_amount"], mission=3, confirm=True, silent=True, output="human"))
                status = str(transport.get("status") or "unknown")
                if status == "uncertain":
                    result = {"status": "uncertain", "global_stop": True, "reason": transport.get("reason")}
                    atomic_write_json(state_path, {**state, "last_result": result, "updated_at": int(time.time())})
                    return result
                if status != "applied":
                    continue
                target_text = f"[{coordinates['galaxy']}:{coordinates['system']}:{coordinates['position']}]"
                ready_at = _transport_arrival_epoch(transport, target_text)
                if ready_at is None:
                    entry = {"source_id": str(source_id), "payload": allocation["payload"],
                             "sent_at": int(time.time()), "ready_at": int(time.time()) + 86400,
                             "eta_confirmed": False}
                    state.setdefault("pending", []).append(entry)
                    applied.append({"kind": "transport", **entry})
                    result = {"status": "blocked", "reason": "transport_eta_unknown", "applied": applied}
                    atomic_write_json(state_path, {**state, "last_result": result, "updated_at": int(time.time())})
                    return result
                entry = {"source_id": str(source_id), "payload": allocation["payload"],
                         "sent_at": int(time.time()), "ready_at": ready_at, "eta_confirmed": True}
                state.setdefault("pending", []).append(entry)
                atomic_write_json(state_path, {**state, "updated_at": int(time.time())})
                applied.append({"kind": "transport", **entry})
                pending_entries = list(state["pending"])
                break
            else:
                result = {"status": "blocked", "reason": "no_safe_transport_source",
                          "delivery_need": need, "applied": applied}
                atomic_write_json(state_path, {**state, "last_result": result, "updated_at": int(time.time())})
                return result

        next_arrival = min(
            (int(item["ready_at"]) for item in pending_entries if item.get("eta_confirmed") is True),
            default=None,
        )

        if decision["status"] == "waiting":
            end_epoch = decision.get("end_epoch")
            if not end_epoch:
                result = {"status": "blocked", "reason": "building_queue_end_unknown", "applied": applied}
                atomic_write_json(state_path, {**state, "last_result": result, "updated_at": int(time.time())})
                return result
            event_epoch = min(int(end_epoch), next_arrival) if next_arrival else int(end_epoch)
            deferred_until = _timer_wait(
                args.run_id, event_epoch, max_wait_seconds=args.max_wait_seconds, started_at=started_at
            )
            if deferred_until is not None:
                reason = "transport_in_flight" if next_arrival and next_arrival <= int(end_epoch) else "building_timer_outside_window"
                return {"status": "waiting", "reason": reason,
                        "next_wake": deferred_until, "applied": applied}
            continue
        if decision["status"] == "complete":
            result = {"status": "complete", "decision": decision, "applied": applied}
            atomic_write_json(state_path, {**state, "last_result": result, "updated_at": int(time.time())})
            return result
        if not decision.get("actionable_now") and next_arrival:
            deferred_until = _timer_wait(
                args.run_id, next_arrival, max_wait_seconds=args.max_wait_seconds, started_at=started_at
            )
            if deferred_until is not None:
                return {"status": "waiting", "reason": "transport_in_flight",
                        "next_wake": deferred_until, "applied": applied}
            continue
        if not decision.get("actionable_now"):
            result = {"status": "blocked", "reason": "resources_not_ready", "decision": decision,
                      "delivery_need": need, "applied": applied}
            atomic_write_json(state_path, {**state, "last_result": result, "updated_at": int(time.time())})
            return result

        action = _quiet_call(execution.command_apply, argparse.Namespace(
            plan_id=plan["plan_id"], action_id=decision["action_id"], planet_id=args.planet_id,
            run_id=args.run_id, confirm=True, silent=True, output="human"))
        status = str(action.get("status") or "unknown")
        applied.append({"kind": "build", "status": status, "action_id": decision["action_id"],
                        "name": decision["name"], "target_level": decision["target_level"]})
        if status == "uncertain":
            result = {"status": "uncertain", "global_stop": True, "reason": action.get("reason"), "applied": applied}
            atomic_write_json(state_path, {**state, "last_result": result, "updated_at": int(time.time())})
            return result
        if status not in {"applied", "skipped"}:
            result = {"status": "blocked", "reason": action.get("reason") or status, "applied": applied}
            atomic_write_json(state_path, {**state, "last_result": result, "updated_at": int(time.time())})
            return result

    result = {"status": "waiting", "reason": "max_steps_reached", "applied": applied}
    atomic_write_json(state_path, {**state, "last_result": result, "updated_at": int(time.time())})
    return result
