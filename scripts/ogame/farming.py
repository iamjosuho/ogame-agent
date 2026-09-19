"""Pure, fail-closed evaluation of inactive farming targets.

This module never dispatches a fleet. It normalizes local memory evidence and
returns suggestions which still have to become confirmed typed candidates.
"""

from __future__ import annotations

import math
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional


REPORT_MAX_AGE_SECONDS = 2 * 60 * 60
COORDINATE_PATTERN = re.compile(r"\[([0-9]+):([0-9]+):([0-9]+)\]")


def _parse_timestamp(value: str) -> Optional[int]:
    text = value.strip()
    if not text or text in {"-", "—", "無", "未知", "N/A"}:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
    ):
        try:
            return int(datetime.strptime(text, fmt).timestamp())
        except ValueError:
            continue
    return None


def _parse_optional_count(text: str, labels: tuple[str, ...]) -> Optional[int]:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*[:：]?\s*([0-9][0-9,]*)", text, re.IGNORECASE)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def parse_farm_targets_md(filepath: str = "runtime/memory/farm_targets.md") -> List[Dict[str, Any]]:
    """Parse local target memory without inventing missing combat evidence."""
    if not os.path.exists(filepath):
        return []
    targets: List[Dict[str, Any]] = []
    with open(filepath, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line.startswith("|") or re.search(r"\|\s*:?-{3,}", line):
                continue
            coordinate = COORDINATE_PATTERN.search(line)
            if coordinate is None:
                continue
            galaxy, system, position = (int(coordinate.group(index)) for index in range(1, 4))
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            status_text = " ".join(cells[1:3]) if len(cells) >= 3 else line
            status_lower = status_text.lower()
            destroyed = any(token in status_lower for token in ("已毀滅", "destroyed", "détruite"))
            vacation = "(v)" in status_lower or "假期" in status_text
            inactive = ("(i)" in status_text or "(I)" in status_text) and not destroyed and not vacation
            attacks_match = re.search(r"([0-9]+)\s*/\s*6", line)
            attacks_24h = int(attacks_match.group(1)) if attacks_match else None
            total_match = re.search(
                r"(?:總資源|total(?:\s+resources)?)\s*[:：]?\s*\*\*?([0-9,]+)",
                line,
                re.IGNORECASE,
            )
            total_resources = int(total_match.group(1).replace(",", "")) if total_match else None
            report_time = next(
                (
                    parsed
                    for cell in cells
                    for parsed in [_parse_timestamp(cell)]
                    if parsed is not None
                ),
                None,
            )
            targets.append(
                {
                    "coords": f"[{galaxy}:{system}:{position}]",
                    "galaxy": galaxy,
                    "system": system,
                    "position": position,
                    "is_inactive": inactive,
                    "is_destroyed": destroyed,
                    "is_vacation": vacation,
                    "report_observed_at": report_time,
                    "attacks_24h": attacks_24h,
                    "total_resources": total_resources,
                    "defense_count": _parse_optional_count(line, ("Defense", "防禦", "防御")),
                    "fleet_count": _parse_optional_count(line, ("Fleet", "艦隊", "舰队")),
                }
            )
    return targets


def _skip(skipped: List[Dict[str, Any]], coords: Any, reason: str) -> None:
    skipped.append({"coords": coords, "reason": reason})


def evaluate_farming_targets(
    scanned_targets: Optional[List[Dict[str, Any]]],
    available_fleet_slots: int,
    available_ships: Mapping[str, int],
    bashing_limits: Optional[Mapping[str, int]] = None,
    min_loot_threshold: int = 5000,
    max_concurrent_raids: int = 2,
    reserved_slots: int = 1,
    *,
    cargo_capacities: Mapping[str, int],
    memory_file: str = "runtime/memory/farm_targets.md",
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Return safe probe and raid suggestions from explicit live capability."""
    now = int(time.time() if now is None else now)
    if scanned_targets is None:
        scanned_targets = parse_farm_targets_md(memory_file)
    if isinstance(available_fleet_slots, bool) or not isinstance(available_fleet_slots, int) or available_fleet_slots < 0:
        raise ValueError("available_fleet_slots 必須是非負整數。")
    if reserved_slots < 1:
        raise ValueError("reserved_slots 不得低於 1。")
    if max_concurrent_raids < 0:
        raise ValueError("max_concurrent_raids 不得小於 0。")

    bashing_limits = bashing_limits or {}
    usable_slots = max(0, available_fleet_slots - int(reserved_slots))
    normalized_ships: Dict[str, int] = {}
    for key in ("espionage_probe", "small_cargo", "large_cargo"):
        value = available_ships.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"available_ships.{key} 必須是非負整數。")
        normalized_ships[key] = value
    probes_available = normalized_ships["espionage_probe"]
    small_available = normalized_ships["small_cargo"]
    large_available = normalized_ships["large_cargo"]
    probes_to_send: List[Dict[str, Any]] = []
    raids_to_launch: List[Dict[str, Any]] = []
    skipped_targets: List[Dict[str, Any]] = []

    for target in scanned_targets:
        coords = target.get("coords")
        if usable_slots <= 0:
            _skip(skipped_targets, coords, "no_usable_fleet_slot")
            continue
        if target.get("is_destroyed") is True:
            _skip(skipped_targets, coords, "destroyed_target")
            continue
        if target.get("is_vacation") is True:
            _skip(skipped_targets, coords, "vacation_target")
            continue
        if target.get("is_inactive") is not True:
            _skip(skipped_targets, coords, "target_not_confirmed_inactive")
            continue

        attacks = target.get("attacks_24h")
        if attacks is None:
            attacks = bashing_limits.get(str(coords))
        if not isinstance(attacks, int) or isinstance(attacks, bool):
            attacks = 0

        observed_at = target.get("report_observed_at")
        report_fresh = (
            isinstance(observed_at, int)
            and not isinstance(observed_at, bool)
            and 0 <= now - observed_at <= REPORT_MAX_AGE_SECONDS
        )
        defense = target.get("defense_count")
        fleet = target.get("fleet_count")
        report_complete = (
            isinstance(defense, int)
            and not isinstance(defense, bool)
            and isinstance(fleet, int)
            and not isinstance(fleet, bool)
        )
        if not report_fresh or not report_complete:
            if probes_available > 0:
                probes_to_send.append(
                    {
                        "coords": coords,
                        "galaxy": target.get("galaxy"),
                        "system": target.get("system"),
                        "position": target.get("position"),
                        "probes": 1,
                        "reason": "report_stale" if not report_fresh else "combat_evidence_incomplete",
                    }
                )
                probes_available -= 1
                usable_slots -= 1
            else:
                _skip(skipped_targets, coords, "report_unusable_and_no_probe")
            continue
        if defense != 0 or fleet != 0:
            _skip(skipped_targets, coords, "target_has_defense_or_fleet")
            continue

        resources = target.get("resources")
        if isinstance(resources, Mapping):
            values = [resources.get(key) for key in ("metal", "crystal", "deuterium")]
            total_resources = (
                sum(values)
                if all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in values)
                else None
            )
        else:
            total_resources = target.get("total_resources")
        if isinstance(total_resources, bool) or not isinstance(total_resources, int) or total_resources < 0:
            _skip(skipped_targets, coords, "resource_evidence_unknown")
            continue
        expected_loot = total_resources // 2
        if expected_loot < min_loot_threshold:
            _skip(skipped_targets, coords, "loot_below_threshold")
            continue
        if len(raids_to_launch) >= max_concurrent_raids:
            _skip(skipped_targets, coords, "raid_concurrency_limit")
            continue

        sc_cap = int(cargo_capacities.get("202", 0) or 0)
        lc_cap = int(cargo_capacities.get("203", 0) or 0)
        needed_small = max(1, math.ceil(expected_loot / sc_cap)) if sc_cap > 0 else None
        needed_large = max(1, math.ceil(expected_loot / lc_cap)) if lc_cap > 0 else None
        ship_tech: Optional[str] = None
        ship_amount = 0
        if needed_small is not None and small_available >= needed_small:
            ship_tech, ship_amount = "202", needed_small
            small_available -= needed_small
        elif needed_large is not None and large_available >= needed_large:
            ship_tech, ship_amount = "203", needed_large
            large_available -= needed_large
        if ship_tech is None:
            _skip(skipped_targets, coords, "cargo_capacity_unavailable")
            continue

        raids_to_launch.append(
            {
                "coords": coords,
                "galaxy": target.get("galaxy"),
                "system": target.get("system"),
                "position": target.get("position"),
                "ship_tech": ship_tech,
                "ship_amount": ship_amount,
                "expected_loot": expected_loot,
                "evidence": {
                    "inactive": True,
                    "defense_count": defense,
                    "fleet_count": fleet,
                    "report_observed_at": observed_at,
                    "attacks_24h": attacks,
                },
            }
        )
        usable_slots -= 1

    return {
        "usable_slots_remaining": usable_slots,
        "probes_to_send": probes_to_send,
        "raids_to_launch": raids_to_launch,
        "skipped_targets": skipped_targets,
    }
