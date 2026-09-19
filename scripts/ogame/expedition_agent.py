"""Preset-driven, movement-aware expedition relay."""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import random
import re
import time
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from . import browser, execution, lifecycle
from .browser import require_confirmed_mutation
from .operations import resolve_expedition_preset
from .policy import DEFAULT_CONSTANTS_PATH, SAFETY_POLICY


STATE_FILE = os.path.join(lifecycle.MEMORY_DIR, "expedition-agent.json")
COORDINATE_RE = re.compile(r"\[?\s*(\d+)\s*:\s*(\d+)\s*:\s*(\d+)\s*\]?")


def _coordinates(raw: Any) -> Optional[Tuple[int, int, int]]:
    match = COORDINATE_RE.search(str(raw or ""))
    if not match:
        return None
    return tuple(int(match.group(index)) for index in range(1, 4))


def summarize_expeditions(movement: Mapping[str, Any]) -> Dict[str, Any]:
    """Use one scheduled return row as the canonical record for each expedition."""
    if movement.get("success") is not True or movement.get("coverage") != "verified":
        raise RuntimeError("movement expedition evidence 未驗證。")
    if movement.get("threat_status") != "none":
        raise RuntimeError("movement 尚有敵襲或不明方向；禁止遠征補位。")
    events = movement.get("events")
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        raise RuntimeError("movement events 格式無效。")

    fleets: Dict[str, Dict[str, Any]] = {}
    mission_rows = 0
    for event in events:
        if not isinstance(event, Mapping) or str(event.get("mission_type") or "") != "15":
            continue
        mission_rows += 1
        if event.get("direction") != "own" or not str(event.get("direction_evidence") or "").strip():
            raise RuntimeError("expedition movement 缺少己方方向證據。")
        if event.get("return_flight") is not True:
            continue
        fleet_id = str(event.get("fleet_id") or "").strip()
        event_id = str(event.get("id") or "").strip()
        logical_id = fleet_id or (f"return-row:{event_id}" if event_id else "")
        if not logical_id:
            raise RuntimeError("expedition return row 缺少 fleet_id 與 event id。")
        origin = _coordinates(event.get("origin_coords"))
        destination = _coordinates(event.get("dest_coords"))
        slot16 = [coords for coords in (origin, destination) if coords and coords[2] == 16]
        if len({coords for coords in slot16}) != 1:
            raise RuntimeError(f"expedition movement {logical_id} 無法唯一解析 position 16 座標。")
        expedition_coords = slot16[0]
        record = fleets.setdefault(
            logical_id,
            {"galaxy": expedition_coords[0], "system": expedition_coords[1], "return_epochs": []},
        )
        if (record["galaxy"], record["system"]) != expedition_coords[:2]:
            raise RuntimeError(f"expedition movement {logical_id} 座標互相矛盾。")
        end_epoch = event.get("end_epoch")
        if isinstance(end_epoch, bool) or not isinstance(end_epoch, (int, float)) or int(end_epoch) <= 0:
            raise RuntimeError(f"expedition movement {logical_id} 回程缺少 end_epoch。")
        record["return_epochs"].append(int(end_epoch))

    if mission_rows and not fleets:
        raise RuntimeError("expedition movement 有 mission 15，但缺少可驗證的 return rows。")

    system_counts: Dict[str, int] = {}
    return_epochs = []
    for record in fleets.values():
        key = f"{record['galaxy']}:{record['system']}"
        system_counts[key] = system_counts.get(key, 0) + 1
        unique_epochs = set(record["return_epochs"])
        if len(unique_epochs) > 1:
            raise RuntimeError("同一 expedition fleet 出現互相衝突的回程時間。")
        return_epochs.extend(unique_epochs)
    return {
        "active_count": len(fleets),
        "system_counts": system_counts,
        "earliest_return_epoch": min(return_epochs) if return_epochs else None,
        "fleet_ids": sorted(fleets),
    }


def adjacent_systems(system: int) -> Tuple[int, int, int]:
    if isinstance(system, bool) or not isinstance(system, int) or not 1 <= system <= 499:
        raise RuntimeError("來源 system 必須介於 1 與 499。")
    previous_system = 499 if system == 1 else system - 1
    next_system = 1 if system == 499 else system + 1
    return system, previous_system, next_system


def choose_target_system(
    *,
    galaxy: int,
    origin_system: int,
    system_counts: Mapping[str, int],
    cursor: int,
) -> Tuple[int, int]:
    """Choose the least-loaded adjacent system, rotating ties across rounds."""
    systems = adjacent_systems(origin_system)
    start = int(cursor) % len(systems)
    ordered = systems[start:] + systems[:start]
    loads = {system: int(system_counts.get(f"{galaxy}:{system}", 0) or 0) for system in systems}
    minimum = min(loads.values())
    chosen = next(system for system in ordered if loads[system] == minimum)
    return chosen, (systems.index(chosen) + 1) % len(systems)


def _load_cursor(state_file: str) -> int:
    state = lifecycle.load_json_file(state_file) or {}
    value = state.get("cursor", 0)
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _save_cursor(state_file: str, cursor: int) -> None:
    lifecycle.atomic_write_json(state_file, {"cursor": int(cursor), "updated_at": int(time.time())})


def _quiet_call(function, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return function(*args, **kwargs)


def _write_earliest_next_wake(epoch: int, baseline_wake: Optional[int]) -> int:
    now = int(time.time())
    candidates = [int(epoch)]
    if isinstance(baseline_wake, int) and not isinstance(baseline_wake, bool) and baseline_wake > now:
        candidates.append(baseline_wake)
    selected = min(candidates)
    lifecycle.write_next_wake(selected)
    return selected


def _defer_or_wait(
    *,
    run_id: str,
    return_epoch: int,
    started_at: int,
    max_wait_seconds: int,
    baseline_wake: Optional[int],
    sleep_fn=time.sleep,
) -> Optional[int]:
    buffered = int(return_epoch) + random.randint(5, 10)
    while int(time.time()) < buffered:
        now = int(time.time())
        if buffered - now > max_wait_seconds or now - started_at >= max_wait_seconds:
            return _write_earliest_next_wake(buffered, baseline_wake)
        lifecycle.require_run_lease(run_id)
        sleep_fn(min(30, max(1, buffered - now)))
    return None


def _validated_cycle_state(planet_id: int) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    movement = browser.read_global_movement_evidence()
    lifecycle.atomic_write_json(os.path.join(lifecycle.MEMORY_DIR, "movement-events.json"), movement)
    summary = summarize_expeditions(movement)
    fleet_state = browser.read_fleet_state(planet_id)
    if str(fleet_state.get("planet_id")) != str(planet_id):
        raise RuntimeError("expedition-agent planet pin 不符。")
    fleet_slots = fleet_state.get("fleet_slots")
    expedition_slots = fleet_state.get("expedition_slots")
    if not isinstance(fleet_slots, Mapping) or fleet_slots.get("known") is not True:
        raise RuntimeError("Fleet Slot 無法可靠解析；已 fail closed。")
    if not isinstance(expedition_slots, Mapping) or expedition_slots.get("known") is not True:
        raise RuntimeError("Expedition Slot 無法可靠解析；已 fail closed。")
    used = expedition_slots.get("used")
    if isinstance(used, bool) or not isinstance(used, int) or used != summary["active_count"]:
        raise RuntimeError("movement 與 live Expedition Slot 數量不一致；已 fail closed。")
    return movement, summary, fleet_state


def _command_expedition_agent(
    args: argparse.Namespace,
    dispatched: list,
    baseline_wake: Optional[int],
) -> Dict[str, Any]:
    """Fill live expedition vacancies, then wait briefly or persist an exact wake."""
    require_confirmed_mutation(args)
    lifecycle.require_run_lease(args.run_id)
    planet_id = int(args.planet_id)
    max_wait_seconds = int(args.max_wait_seconds)
    if not 0 <= max_wait_seconds <= 900:
        raise RuntimeError("expedition-agent max-wait-seconds 必須介於 0 與 900。")
    max_cycles = int(args.max_cycles)
    if not 1 <= max_cycles <= 8:
        raise RuntimeError("expedition-agent max-cycles 必須介於 1 與 8。")

    started_at = int(time.time())
    cursor = _load_cursor(args.state_file)
    completed_waits = 0

    while True:
        lifecycle.require_run_lease(args.run_id)
        _movement, summary, fleet_state = _validated_cycle_state(planet_id)
        preset = resolve_expedition_preset(fleet_state.get("expedition_templates"), args.preset)
        origin = _coordinates(fleet_state.get("origin_coords"))
        if origin is None or origin[2] == 16:
            raise RuntimeError("來源星座標無法可靠解析。")
        fleet_slots = fleet_state["fleet_slots"]
        expedition_slots = fleet_state["expedition_slots"]
        usable_general = max(0, int(fleet_slots["free"]) - SAFETY_POLICY.minimum_free_fleet_slots)
        available = min(int(expedition_slots["free"]), usable_general)

        if available > 0:
            target_system, next_cursor = choose_target_system(
                galaxy=origin[0],
                origin_system=origin[1],
                system_counts=summary["system_counts"],
                cursor=cursor,
            )
            dispatch_args = argparse.Namespace(
                planet_id=planet_id,
                galaxy=origin[0],
                system=target_system,
                position=16,
                preset_name=preset["name"],
                metal=0,
                crystal=0,
                deuterium=0,
                run_id=args.run_id,
                confirm=True,
                constants=args.constants,
                output="json",
            )
            plan = execution.create_fleet_confirmed_plan(dispatch_args, "expedition")
            candidate = plan["candidates"][0]
            result = _quiet_call(
                execution.command_apply,
                argparse.Namespace(
                    plan_id=plan["plan_id"],
                    action_id=candidate["action_id"],
                    planet_id=planet_id,
                    run_id=args.run_id,
                    confirm=True,
                    output="json",
                ),
            )
            if result.get("status") != "applied":
                output = {
                    "status": result.get("status", "blocked"),
                    "reason": result.get("reason"),
                    "dispatched": dispatched,
                }
                lifecycle.print_command_output(
                    args,
                    output,
                    f"expedition-agent stopped: {result.get('reason', 'dispatch failed')}",
                )
                return output
            cursor = next_cursor
            _save_cursor(args.state_file, cursor)
            dispatched.append({
                "target": f"[{origin[0]}:{target_system}:16]",
                "preset": preset["name"],
                "ship_composition": preset["ships"],
                "action_id": candidate["action_id"],
            })
            time.sleep(random.randint(5, 10))
            continue

        return_epoch = summary.get("earliest_return_epoch")
        if not isinstance(return_epoch, int) or return_epoch <= 0:
            raise RuntimeError("沒有可派空槽，且無法確認最早 expedition 回程時間。")
        if completed_waits >= max_cycles - 1:
            buffered = int(return_epoch) + random.randint(5, 10)
            next_wake = _write_earliest_next_wake(buffered, baseline_wake)
            output = {"status": "deferred", "dispatched": dispatched, "next_wake": next_wake}
            lifecycle.print_command_output(args, output, f"expedition-agent deferred until {next_wake}")
            return output
        deferred = _defer_or_wait(
            run_id=args.run_id,
            return_epoch=return_epoch,
            started_at=started_at,
            max_wait_seconds=max_wait_seconds,
            baseline_wake=baseline_wake,
        )
        if deferred is not None:
            output = {"status": "deferred", "dispatched": dispatched, "next_wake": deferred}
            lifecycle.print_command_output(args, output, f"expedition-agent deferred until {deferred}")
            return output
        completed_waits += 1


def command_expedition_agent(args: argparse.Namespace) -> Dict[str, Any]:
    """Run one safe relay and preserve evidence after any partial mutation."""
    dispatched = []
    baseline_wake = lifecycle.load_next_wake()
    try:
        return _command_expedition_agent(args, dispatched, baseline_wake)
    except RuntimeError as exc:
        if not dispatched:
            raise
        output: Dict[str, Any] = {
            "status": "uncertain",
            "global_stop": True,
            "reason": str(exc),
            "dispatched": dispatched,
        }
        try:
            _movement, summary, _fleet_state = _validated_cycle_state(int(args.planet_id))
            return_epoch = summary.get("earliest_return_epoch")
            if isinstance(return_epoch, int) and return_epoch > 0:
                output["next_wake"] = _write_earliest_next_wake(
                    return_epoch + random.randint(5, 10),
                    baseline_wake,
                )
        except RuntimeError as recovery_exc:
            output["recovery_reason"] = str(recovery_exc)
        lifecycle.print_command_output(
            args,
            output,
            f"expedition-agent uncertain after partial dispatch: {exc}",
        )
        return output
