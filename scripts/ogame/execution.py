"""Execution, planning, mutation, verification, and workflow management.

Provides deterministic technology formulas, cost calculations, pre-validation,
verification gates, action plans, watches, applies, and typed workflows.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
import os
import random
import re
import secrets
import sys
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Set
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from scripts.ogame import browser as _browser
from scripts.ogame import lifecycle as _lifecycle
from scripts.ogame import operations as _operations
from scripts.ogame import atoms as _atoms
from scripts.ogame import matrix as _matrix
from scripts.ogame.matrix import calc_storage_capacity
from scripts.ogame.browser import (
    checked_js,
    game_url,
    require_confirmed_mutation,
)
from scripts.ogame.lifecycle import (
    MEMORY_DIR,
    patrol_contract_file,
    print_command_output,
)
from scripts.ogame.policy import (
    AccountConstants,
    DEFAULT_CONSTANTS_PATH,
    DEFAULT_STRATEGY_PATH,
    SAFETY_POLICY,
    StrategyPolicy,
    load_account_constants,
    load_strategy_policy,
)
from scripts.ogame.farming import evaluate_farming_targets, parse_farm_targets_md
from scripts.ogame.atoms import PlannedMutationCallbacks, read_lifeform_atom
from scripts.ogame.models import ActionResult, ActionStatus, Intent, IntentKind, WorkflowPlan
from scripts.ogame.operations import (
    FleetMission,
    build_fleet_candidate,
    build_patrol_fleet_candidates,
    resolve_expedition_preset,
)
from scripts.ogame.planning import build_workflow_plan, feasible_packages as build_feasible_packages

feasible_packages = build_feasible_packages
from scripts.ogame.workflow import (
    DecisionValidationError,
    WorkflowJournal,
    WorkflowRunner,
    bounded_text,
    candidate_block_reason,
    compact_results,
    format_compact_json,
    rotate_workflow_archives,
    select_candidates,
)


from scripts.ogame.resolver import get_dep, register_controller

_get_dep = get_dep


def set_dependency_resolver(resolver: Optional[Callable[[str, Any], Any]]) -> None:
    # Backward compatibility
    pass


PLAN_FILE = os.path.join(MEMORY_DIR, "patrol-plan.json")
NEXT_WAKE_FILE = os.path.join(MEMORY_DIR, "next_wake.txt")
RATES_FILE = os.path.join(MEMORY_DIR, "production-rates.json")
WORKFLOW_DIR = os.path.join(MEMORY_DIR, "workflows")
RESOURCE_KEYS = ("metal", "crystal", "deuterium")
PLAN_TTL_SECONDS = 120
MAX_ACTIONS_PER_PLAN = getattr(SAFETY_POLICY, "max_actions_per_run", 999)
MIN_ENERGY_SAFE = SAFETY_POLICY.min_safe_energy

def _plan_file() -> str:
    return _get_dep("PLAN_FILE", os.path.join(_get_dep("MEMORY_DIR", MEMORY_DIR), "patrol-plan.json"))


def _next_wake_file() -> str:
    return _get_dep("NEXT_WAKE_FILE", os.path.join(_get_dep("MEMORY_DIR", MEMORY_DIR), "next_wake.txt"))


def _rates_file() -> str:
    return _get_dep("RATES_FILE", os.path.join(_get_dep("MEMORY_DIR", MEMORY_DIR), "production-rates.json"))


def _workflow_dir() -> str:
    return _get_dep("WORKFLOW_DIR", os.path.join(_get_dep("MEMORY_DIR", MEMORY_DIR), "workflows"))


def _memory_dir() -> str:
    return _get_dep("MEMORY_DIR", MEMORY_DIR)


def execute_in_game_tab(js_code: str, target_url: Optional[str] = None, wait_after_nav: float = 0.5) -> Dict[str, Any]:
    fn = _get_dep("execute_in_game_tab")
    if fn and fn is not execute_in_game_tab:
        return fn(js_code, target_url=target_url, wait_after_nav=wait_after_nav)
    return _browser.execute_in_game_tab(js_code, target_url=target_url, wait_after_nav=wait_after_nav)


def execute_checked_component(component: str, planet_id: int, inner_expression: str, runner_fn: Optional[Callable[[str], Dict[str, Any]]] = None) -> Dict[str, Any]:
    fn = _get_dep("execute_checked_component")
    if fn and fn is not execute_checked_component:
        return fn(component, planet_id, inner_expression, runner_fn=runner_fn)
    return _browser.execute_checked_component(component, planet_id, inner_expression, runner_fn=runner_fn)


def execute_checked_component_followup(component: str, planet_id: int, inner_expression: str, **kwargs) -> Dict[str, Any]:
    fn = _get_dep("execute_checked_component_followup")
    if fn and fn is not execute_checked_component_followup:
        return fn(component, planet_id, inner_expression, **kwargs)
    return _browser.execute_checked_component_followup(component, planet_id, inner_expression, **kwargs)


def execute_checked_component_result(component: str, planet_id: int, inner_expression: str, runner_fn: Optional[Callable[[str], Dict[str, Any]]] = None) -> Dict[str, Any]:
    fn = _get_dep("execute_checked_component_result")
    if fn and fn is not execute_checked_component_result:
        return fn(component, planet_id, inner_expression, runner_fn=runner_fn)
    return _browser.execute_checked_component_result(component, planet_id, inner_expression, runner_fn=runner_fn)


def atomic_write_json(path: str, data: Any) -> None:
    fn = _get_dep("atomic_write_json")
    if fn and fn is not atomic_write_json:
        return fn(path, data)
    return _lifecycle.atomic_write_json(path, data)


def load_json_file(path: str) -> Optional[Dict[str, Any]]:
    fn = _get_dep("load_json_file")
    if fn and fn is not load_json_file:
        return fn(path)
    return _lifecycle.load_json_file(path)


def require_run_lease(run_id: str) -> None:
    fn = _get_dep("require_run_lease")
    if fn and fn is not require_run_lease:
        return fn(run_id)
    return _lifecycle.require_run_lease(run_id)


def release_run_lease(run_id: str) -> bool:
    fn = _get_dep("release_run_lease")
    if fn and fn is not release_run_lease:
        return fn(run_id)
    return _lifecycle.release_run_lease(run_id)



def normalize_number(value: Any) -> Optional[int]:
    fn = _get_dep("normalize_number")
    if fn and fn is not normalize_number:
        return fn(value)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^0-9]", "", str(value))
    return int(digits) if digits else None


def parse_costs(raw_costs: Any) -> Optional[Dict[str, int]]:
    fn = _get_dep("parse_costs")
    if fn and fn is not parse_costs:
        return fn(raw_costs)
    text = str(raw_costs or "")
    clean_text = re.sub(r"(?:升級\s+.*?|建造\s+.*?)?至\s*\d+\s*級", "", text)
    clean_text = re.sub(r"等級\s*\d+", "", clean_text)
    clean_text = re.sub(r"\(\s*\d+\s*\)", "", clean_text)
    labels = {"metal": "金屬", "crystal": "水晶", "deuterium": "重氫"}
    costs: Dict[str, int] = {}
    found_any = False
    for key, label in labels.items():
        match = re.search(rf"{label}[^0-9]*([0-9][0-9.,\s]*)", clean_text)
        if match:
            parsed = normalize_number(match.group(1))
            if parsed is not None:
                costs[key] = parsed
                found_any = True
            else:
                costs[key] = 0
        else:
            costs[key] = 0
    return costs if found_any else None


def resource_vector(value: Dict[str, Any]) -> Dict[str, int]:
    fn = _get_dep("resource_vector")
    if fn and fn is not resource_vector:
        return fn(value)
    result: Dict[str, int] = {}
    for key in RESOURCE_KEYS:
        parsed = normalize_number(value.get(key, 0))
        result[key] = parsed if parsed is not None else 0
    return result


def subtract_resources(resources: Dict[str, int], costs: Dict[str, int]) -> Dict[str, int]:
    return {key: resources.get(key, 0) - costs.get(key, 0) for key in RESOURCE_KEYS}


def can_afford(resources: Dict[str, int], costs: Dict[str, int]) -> bool:
    return all(resources.get(key, 0) >= costs.get(key, 0) for key in RESOURCE_KEYS)


def resource_shortfall(resources: Dict[str, int], costs: Dict[str, int]) -> Dict[str, int]:
    return {key: max(0, costs.get(key, 0) - resources.get(key, 0)) for key in RESOURCE_KEYS}


def sum_costs(actions: List[Dict[str, Any]]) -> Dict[str, int]:
    return {key: sum(int(action["costs"].get(key, 0)) for action in actions) for key in RESOURCE_KEYS}


def read_header_snapshot(component: str, planet_id: int) -> Dict[str, Any]:
    fn = _get_dep("read_header_snapshot")
    if fn and fn is not read_header_snapshot and (hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value")):
        return fn(component, planet_id)
    return _browser.read_header_snapshot(component, planet_id)


def read_technology_list(component: str, planet_id: int) -> Dict[str, Any]:
    fn = _get_dep("read_technology_list")
    if fn and fn is not read_technology_list and (hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value")):
        return fn(component, planet_id)
    return _browser.read_technology_list(component, planet_id)


def read_fleet_state(planet_id: int) -> Dict[str, Any]:
    fn = _get_dep("read_fleet_state")
    if fn and fn is not read_fleet_state and (hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value")):
        return fn(planet_id)
    return _browser.read_fleet_state(planet_id)


def read_events_state(planet_id: int) -> Dict[str, Any]:
    fn = _get_dep("read_events_state")
    if fn and fn is not read_events_state and (hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value")):
        return fn(planet_id)
    return _browser.read_events_state(planet_id)


def read_galaxy_target_evidence(planet_id: int, target: Mapping[str, int]) -> Dict[str, Any]:
    fn = _get_dep("read_galaxy_target_evidence")
    if fn and fn is not read_galaxy_target_evidence and (hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value")):
        return fn(planet_id, target)
    return _browser.read_galaxy_target_evidence(planet_id, target)


def read_owned_planets(*args, **kwargs) -> List[Dict[str, Any]]:
    fn = _get_dep("read_owned_planets")
    if fn and fn is not read_owned_planets and (hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value")):
        return fn(*args, **kwargs)
    return _matrix.read_owned_planets(*args, **kwargs)


def cache_rates(planet_id: int, rates: Dict[str, int], source: str) -> None:
    fn = _get_dep("cache_rates")
    if fn and fn is not cache_rates and (hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value")):
        return fn(planet_id, rates, source)
    rates_file = _get_dep("RATES_FILE", RATES_FILE)
    _lifecycle.atomic_write_json(rates_file, {
        "planet_id": str(planet_id),
        "rates": resource_vector(rates),
        "source": source,
        "updated_at": int(time.time()),
    })


def mark_rates_stale(planet_id: int) -> None:
    fn = _get_dep("mark_rates_stale")
    if fn and fn is not mark_rates_stale and (hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value")):
        return fn(planet_id)
    rates_file = _get_dep("RATES_FILE", RATES_FILE)
    data = _lifecycle.load_json_file(rates_file)
    if data and str(data.get("planet_id")) == str(planet_id):
        data["stale"] = True
        _lifecycle.atomic_write_json(rates_file, data)


def load_cached_rates(planet_id: int) -> Optional[Dict[str, int]]:
    fn = _get_dep("load_cached_rates")
    if fn and fn is not load_cached_rates and (hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value")):
        return fn(planet_id)
    rates_file = _get_dep("RATES_FILE", RATES_FILE)
    data = _lifecycle.load_json_file(rates_file)
    if not data or data.get("stale") or str(data.get("planet_id")) != str(planet_id):
        return None
    rates = data.get("rates")
    if not isinstance(rates, dict) or any(normalize_number(rates.get(key)) is None for key in RESOURCE_KEYS):
        return None
    return resource_vector(rates)


def execute_in_game_tab(*args, **kwargs) -> Any:
    fn = _get_dep("execute_in_game_tab")
    if fn and fn is not execute_in_game_tab and (hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value")):
        return fn(*args, **kwargs)
    return _browser.execute_in_game_tab(*args, **kwargs)


def execute_checked_component_result(*args, **kwargs) -> Dict[str, Any]:
    fn = _get_dep("execute_checked_component_result")
    if fn and fn is not execute_checked_component_result and (hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value")):
        return fn(*args, **kwargs)
    return _browser.execute_checked_component_result(*args, **kwargs)


def execute_checked_component(*args, **kwargs) -> Dict[str, Any]:
    fn = _get_dep("execute_checked_component")
    if fn and fn is not execute_checked_component and (hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value")):
        return fn(*args, **kwargs)
    return _browser.execute_checked_component(*args, **kwargs)


def execute_checked_component_followup(*args, **kwargs) -> Dict[str, Any]:
    fn = _get_dep("execute_checked_component_followup")
    if fn and fn is not execute_checked_component_followup and (hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value")):
        return fn(*args, **kwargs)
    return _browser.execute_checked_component_followup(*args, **kwargs)


def atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    if path == PLAN_FILE:
        path = _get_dep("PLAN_FILE", PLAN_FILE)
    elif path == RATES_FILE:
        path = _get_dep("RATES_FILE", RATES_FILE)
    elif path == NEXT_WAKE_FILE:
        path = _get_dep("NEXT_WAKE_FILE", NEXT_WAKE_FILE)
    fn = _get_dep("atomic_write_json", _lifecycle.atomic_write_json)
    return fn(path, data)


def load_json_file(path: str) -> Optional[Dict[str, Any]]:
    if path == PLAN_FILE:
        path = _get_dep("PLAN_FILE", PLAN_FILE)
    elif path == RATES_FILE:
        path = _get_dep("RATES_FILE", RATES_FILE)
    elif path == NEXT_WAKE_FILE:
        path = _get_dep("NEXT_WAKE_FILE", NEXT_WAKE_FILE)
    return _lifecycle.load_json_file(path)


def write_next_wake(epoch: int) -> None:
    next_wake_file = _get_dep("NEXT_WAKE_FILE", NEXT_WAKE_FILE)
    memory_dir = _get_dep("MEMORY_DIR", MEMORY_DIR)
    fn = _get_dep("write_next_wake")
    if fn and fn is not write_next_wake and _resolver._is_mock(fn):
        return fn(epoch)
    return _lifecycle.write_next_wake(epoch, next_wake_file=next_wake_file, memory_dir=memory_dir)


def require_run_lease(run_id: str) -> Dict[str, Any]:
    fn = _get_dep("require_run_lease", _lifecycle.require_run_lease)
    return fn(run_id)


def assess_workflow_candidate(*args, **kwargs):
    fn = _get_dep("assess_workflow_candidate", _operations.assess_workflow_candidate)
    if fn is assess_workflow_candidate:
        fn = _operations.assess_workflow_candidate
    return fn(*args, **kwargs)


def apply_planned_action_atom(*args, **kwargs):
    fn = _get_dep("apply_planned_action_atom", _atoms.apply_planned_action_atom)
    if fn is apply_planned_action_atom:
        fn = _atoms.apply_planned_action_atom
    return fn(*args, **kwargs)


TECH_FORMULAS: Dict[str, Dict[str, Any]] = {
    # Supplies
    "1": {"name": "金屬礦", "metal": 60, "crystal": 15, "deuterium": 0, "factor": 1.5, "energy_type": "mine_10"},
    "2": {"name": "晶體礦", "metal": 48, "crystal": 24, "deuterium": 0, "factor": 1.6, "energy_type": "mine_10"},
    "3": {"name": "重氫合成器", "metal": 225, "crystal": 75, "deuterium": 0, "factor": 1.5, "energy_type": "synthesizer_20"},
    "4": {"name": "太陽能發電廠", "metal": 75, "crystal": 30, "deuterium": 0, "factor": 1.5, "energy_type": "solar_plant"},
    "12": {"name": "核融合反應器", "metal": 900, "crystal": 360, "deuterium": 180, "factor": 1.8, "energy_type": "fusion"},
    "22": {"name": "金屬儲存器", "metal": 1000, "crystal": 0, "deuterium": 0, "factor": 2.0},
    "23": {"name": "晶體儲存器", "metal": 1000, "crystal": 500, "deuterium": 0, "factor": 2.0},
    "24": {"name": "重氫儲存槽", "metal": 1000, "crystal": 1000, "deuterium": 0, "factor": 2.0},

    # Facilities
    "14": {"name": "機器人工廠", "metal": 400, "crystal": 120, "deuterium": 200, "factor": 2.0},
    "15": {"name": "奈米機械工廠", "metal": 1000000, "crystal": 500000, "deuterium": 100000, "factor": 2.0},
    "21": {"name": "造船廠", "metal": 400, "crystal": 200, "deuterium": 100, "factor": 2.0},
    "31": {"name": "研究實驗室", "metal": 200, "crystal": 400, "deuterium": 200, "factor": 2.0},
    "33": {"name": "地形改造器", "metal": 0, "crystal": 50000, "deuterium": 100000, "factor": 2.0},
    "34": {"name": "飛彈發射井", "metal": 20000, "crystal": 20000, "deuterium": 1000, "factor": 2.0},
    "36": {"name": "宇宙港", "metal": 200, "crystal": 0, "deuterium": 50, "factor": 5.0},

    # Research
    "106": {"name": "間諜偵察技術", "metal": 200, "crystal": 1000, "deuterium": 200, "factor": 2.0},
    "108": {"name": "電腦技術", "metal": 0, "crystal": 400, "deuterium": 600, "factor": 2.0},
    "109": {"name": "武器技術", "metal": 800, "crystal": 200, "deuterium": 0, "factor": 2.0},
    "110": {"name": "防盾技術", "metal": 200, "crystal": 600, "deuterium": 0, "factor": 2.0},
    "111": {"name": "裝甲技術", "metal": 1000, "crystal": 0, "deuterium": 0, "factor": 2.0},
    "113": {"name": "能源技術", "metal": 0, "crystal": 800, "deuterium": 400, "factor": 2.0},
    "114": {"name": "超空間技術", "metal": 0, "crystal": 4000, "deuterium": 2000, "factor": 2.0},
    "115": {"name": "燃燒引擎", "metal": 400, "crystal": 0, "deuterium": 600, "factor": 2.0},
    "117": {"name": "脈衝引擎", "metal": 2000, "crystal": 4000, "deuterium": 600, "factor": 2.0},
    "118": {"name": "超空間引擎", "metal": 10000, "crystal": 20000, "deuterium": 6000, "factor": 2.0},
    "120": {"name": "雷射技術", "metal": 200, "crystal": 100, "deuterium": 0, "factor": 2.0},
    "121": {"name": "離子技術", "metal": 1000, "crystal": 300, "deuterium": 100, "factor": 2.0},
    "122": {"name": "電漿技術", "metal": 2000, "crystal": 4000, "deuterium": 1000, "factor": 2.0},
    "123": {"name": "跨星系研究網絡", "metal": 240000, "crystal": 400000, "deuterium": 160000, "factor": 2.0},
    "124": {"name": "天體物理學", "metal": 4000, "crystal": 8000, "deuterium": 4000, "factor": 1.75},
    "199": {"name": "重力子技術", "metal": 0, "crystal": 0, "deuterium": 0, "factor": 3.0},
}

PRODUCTION_SPECS: Dict[str, Dict[str, Any]] = {
    # Ships
    "202": {"name": "小型運輸艦", "metal": 2000, "crystal": 2000, "deuterium": 0},
    "203": {"name": "大型運輸艦", "metal": 6000, "crystal": 6000, "deuterium": 0},
    "204": {"name": "輕型戰鬥機", "metal": 3000, "crystal": 1000, "deuterium": 0},
    "205": {"name": "重型戰鬥機", "metal": 6000, "crystal": 4000, "deuterium": 0},
    "206": {"name": "巡洋艦", "metal": 20000, "crystal": 7000, "deuterium": 2000},
    "207": {"name": "戰列艦", "metal": 45000, "crystal": 15000, "deuterium": 0},
    "208": {"name": "殖民船", "metal": 10000, "crystal": 20000, "deuterium": 10000},
    "209": {"name": "回收船", "metal": 10000, "crystal": 6000, "deuterium": 2000},
    "210": {"name": "間諜探測器", "metal": 0, "crystal": 1000, "deuterium": 0},
    "211": {"name": "轟炸機", "metal": 50000, "crystal": 25000, "deuterium": 15000},
    "212": {"name": "太陽能衛星", "metal": 0, "crystal": 2000, "deuterium": 500},
    "213": {"name": "驅逐艦", "metal": 60000, "crystal": 50000, "deuterium": 15000},
    "214": {"name": "死星", "metal": 5000000, "crystal": 4000000, "deuterium": 1000000},
    "215": {"name": "戰鬥巡洋艦", "metal": 30000, "crystal": 40000, "deuterium": 15000},
    "218": {"name": "死神艦", "metal": 85000, "crystal": 55000, "deuterium": 20000},
    "219": {"name": "拓荒者", "metal": 8000, "crystal": 15000, "deuterium": 8000},

    # Defenses
    "401": {"name": "飛彈發射器", "metal": 2000, "crystal": 0, "deuterium": 0},
    "402": {"name": "輕型雷射炮", "metal": 1500, "crystal": 500, "deuterium": 0},
    "403": {"name": "重型雷射炮", "metal": 6000, "crystal": 2000, "deuterium": 0},
    "404": {"name": "高斯炮", "metal": 20000, "crystal": 15000, "deuterium": 2000},
    "405": {"name": "離子加農炮", "metal": 2000, "crystal": 6000, "deuterium": 0},
    "406": {"name": "等離子炮塔", "metal": 50000, "crystal": 50000, "deuterium": 30000},
    "407": {"name": "小型防護罩", "metal": 10000, "crystal": 10000, "deuterium": 0},
    "408": {"name": "大型防護罩", "metal": 50000, "crystal": 50000, "deuterium": 0},
    "502": {"name": "攔截飛彈", "metal": 8000, "crystal": 0, "deuterium": 2000},
    "503": {"name": "星際飛彈", "metal": 12500, "crystal": 2500, "deuterium": 10000},
}


def calculate_technology_cost(tech_id: str, target_level: int) -> Tuple[Optional[Dict[str, int]], Optional[int]]:
    """Deterministic calculation of tech upgrade cost & energy delta based on official OGame formula."""
    spec = TECH_FORMULAS.get(str(tech_id))
    if not spec or target_level < 1:
        return None, None
    factor = spec.get("factor", 2.0)
    multiplier = factor ** (target_level - 1)
    costs = {
        "metal": int(spec.get("metal", 0) * multiplier),
        "crystal": int(spec.get("crystal", 0) * multiplier),
        "deuterium": int(spec.get("deuterium", 0) * multiplier),
    }
    energy_delta = None
    energy_type = spec.get("energy_type")
    if energy_type == "mine_10":
        cur_e = math.floor(10 * (target_level - 1) * (1.1 ** (target_level - 1))) if target_level > 1 else 0
        tgt_e = math.floor(10 * target_level * (1.1 ** target_level))
        energy_delta = -(tgt_e - cur_e)
    elif energy_type == "synthesizer_20":
        cur_e = math.floor(20 * (target_level - 1) * (1.1 ** (target_level - 1))) if target_level > 1 else 0
        tgt_e = math.floor(20 * target_level * (1.1 ** target_level))
        energy_delta = -(tgt_e - cur_e)
    elif energy_type == "solar_plant":
        cur_e = math.floor(20 * (target_level - 1) * (1.1 ** (target_level - 1))) if target_level > 1 else 0
        tgt_e = math.floor(20 * target_level * (1.1 ** target_level))
        energy_delta = +(tgt_e - cur_e)
    elif energy_type == "fusion":
        cur_e = math.floor(30 * (target_level - 1) * ((1.05 + 0.01 * 3) ** (target_level - 1))) if target_level > 1 else 0
        tgt_e = math.floor(30 * target_level * ((1.05 + 0.01 * 3) ** target_level))
        energy_delta = +(tgt_e - cur_e)
    return costs, energy_delta


def estimate_action_duration(section: str, costs: Dict[str, int], robotics_level: int = 5, lab_level: int = 3, nanite_level: int = 0, universe_speed: int = 1) -> int:
    """Estimate construction/research duration in seconds based on OGame official formula."""
    total_cost = costs.get("metal", 0) + costs.get("crystal", 0)
    if total_cost <= 0:
        return 10
    if section in {"supplies", "facilities"}:
        hours = total_cost / (2500 * (1 + robotics_level) * (2 ** nanite_level) * universe_speed)
    else:
        hours = total_cost / (1000 * (1 + lab_level) * universe_speed)
    return max(10, int(hours * 3600))


def parse_signed_number(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    parsed = normalize_number(value)
    if parsed is None:
        return None
    return -parsed if "-" in str(value) or "−" in str(value) else parsed


def action_component(section: str) -> str:
    return {"supplies": "supplies", "facilities": "facilities", "research": "research"}[section]


def action_queue(section: str) -> str:
    return {"supplies": "building", "facilities": "building", "research": "research"}[section]


def action_from_item(section: str, tech_id: str, item: Dict[str, Any], resources: Dict[str, int], energy: Optional[int]) -> Optional[Dict[str, Any]]:
    target_level = int(item.get("level") or 0) + 1
    costs = parse_costs(item.get("costs_raw"))
    calculated_costs, calc_energy_delta = calculate_technology_cost(tech_id, target_level)
    if costs is None:
        costs = calculated_costs
    if costs is None:
        return None
    energy_delta = parse_signed_number(item.get("energy_raw"))
    if energy_delta is None:
        energy_delta = calc_energy_delta
    if energy_delta is None and section != "research" and str(tech_id) in TECH_FORMULAS:
        energy_delta = 0
    energy_safe = section == "research" or SAFETY_POLICY.energy_is_safe(energy, energy_delta)
    name = item.get("name") or (TECH_FORMULAS.get(str(tech_id), {}).get("name")) or f"Tech {tech_id}"
    duration_sec = estimate_action_duration(section, costs)
    return {
        "action_id": f"{section}:{tech_id}", "operation": "upgrade",
        "section": section, "component": action_component(section),
        "queue": action_queue(section), "tech_id": str(tech_id),
        "name": name, "level": int(item.get("level") or 0),
        "target_level": target_level, "costs": costs,
        "costs_raw": str(item.get("costs_raw") or ""), "duration_raw": str(item.get("duration_raw") or ""),
        "estimated_duration": duration_sec,
        "requirements_raw": str(item.get("requirements_raw") or ""), "energy_delta": energy_delta,
        "energy_raw": str(item.get("energy_raw") or ""), "can_upgrade": bool(item.get("can_upgrade")),
        "resource_shortfall": resource_shortfall(resources, costs), "energy_safe": energy_safe,
        "actionable_now": bool(item.get("can_upgrade")) and can_afford(resources, costs) and energy_safe,
    }


def lifeform_action_from_item(
    component: str,
    tech_id: str,
    item: Dict[str, Any],
    resources: Dict[str, int],
    energy: Optional[int],
    planet_id: int,
) -> Optional[Dict[str, Any]]:
    """Create an opaque confirmed candidate only from displayed Lifeform data."""
    if component not in {"lfbuildings", "lfresearch"}:
        raise ValueError("Lifeform component 無效。")
    costs = parse_costs(item.get("costs_raw"))
    if costs is None:
        return None
    level = int(item.get("level") or 0)
    energy_delta = parse_signed_number(item.get("energy_raw"))
    energy_known = component == "lfresearch" or energy_delta is not None
    if component == "lfresearch":
        energy_delta = None
    energy_safe = component == "lfresearch" or SAFETY_POLICY.energy_is_safe(energy, energy_delta)
    queue = "lifeform_building" if component == "lfbuildings" else "lifeform_research"
    material = json.dumps(
        {
            "planet_id": str(planet_id),
            "component": component,
            "tech_id": str(tech_id),
            "level": level,
            "costs": costs,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    action_id = f"lifeform:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"
    can_apply = bool(item.get("can_upgrade")) and energy_known and energy_safe and can_afford(resources, costs)
    return {
        "action_id": action_id,
        "operation": "lifeform_upgrade",
        "planet_id": str(planet_id),
        "section": "lifeform",
        "component": component,
        "queue": queue,
        "tech_id": str(tech_id),
        "name": item.get("name") or f"Lifeform {tech_id}",
        "level": level,
        "target_level": level + 1,
        "costs": costs,
        "costs_raw": str(item.get("costs_raw") or ""),
        "duration_raw": str(item.get("duration_raw") or ""),
        "estimated_duration": estimate_action_duration("research", costs),
        "energy_delta": energy_delta,
        "energy_delta_known": energy_known,
        "energy_safe": energy_safe,
        "can_upgrade": bool(item.get("can_upgrade")),
        "can_apply": can_apply,
        "actionable_now": can_apply,
        "resource_shortfall": resource_shortfall(resources, costs),
    }


def cancel_building_action_from_snapshot(
    supplies: Dict[str, Any],
    planet_id: int,
) -> Optional[Dict[str, Any]]:
    """Create an opaque cancellation candidate from one exact active queue."""
    queue = supplies.get("building_queue")
    if not isinstance(queue, dict) or queue.get("active") is not True:
        return None
    queue_token = str(queue.get("queue_token") or "")
    if not queue_token or queue.get("cancel_available") is not True:
        return None
    material = json.dumps(
        {"planet_id": str(planet_id), "queue_token": queue_token},
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "action_id": f"cancel:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}",
        "operation": "cancel_building",
        "planet_id": str(planet_id),
        "section": "supplies",
        "component": "supplies",
        "queue": "cancel_building",
        "queue_token": queue_token,
        "tech_id": str(queue.get("tech_id") or ""),
        "name": str(queue.get("summary") or "active building queue"),
        "costs": {key: 0 for key in RESOURCE_KEYS},
        "energy_delta": None,
        "energy_safe": True,
        "can_apply": True,
        "queue_evidence": dict(queue),
        "estimated_duration": 0,
    }


def production_action_from_item(
    component: str,
    tech_id: str,
    item: Dict[str, Any],
    resources: Dict[str, int],
    planet_id: int,
    amount: int,
) -> Optional[Dict[str, Any]]:
    """Build an opaque production candidate from displayed one-unit costs."""
    if component not in {"shipyard", "defenses"}:
        raise ValueError("production component 無效。")
    if isinstance(amount, bool) or amount <= 0:
        raise ValueError("production amount 必須為正整數。")
    unit_costs = parse_costs(item.get("costs_raw"))
    if unit_costs is None and str(tech_id) in PRODUCTION_SPECS:
        spec = PRODUCTION_SPECS[str(tech_id)]
        unit_costs = {key: spec.get(key, 0) for key in RESOURCE_KEYS}
    if unit_costs is None:
        return None
    costs = {key: unit_costs[key] * amount for key in RESOURCE_KEYS}
    current_amount = int(item.get("level") or 0)
    material = json.dumps(
        {
            "planet_id": str(planet_id),
            "component": component,
            "tech_id": str(tech_id),
            "amount": amount,
            "unit_costs": unit_costs,
            "current_amount": current_amount,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    can_upgrade = bool(item.get("can_upgrade")) or str(item.get("status") or "") == "on"
    can_apply = can_upgrade and can_afford(resources, costs)
    name = item.get("name") or PRODUCTION_SPECS.get(str(tech_id), {}).get("name") or f"Production {tech_id}"
    return {
        "action_id": f"produce:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}",
        "operation": "produce",
        "planet_id": str(planet_id),
        "section": "production",
        "component": component,
        "queue": "shipyard",
        "tech_id": str(tech_id),
        "name": name,
        "amount": amount,
        "level": current_amount,
        "target_level": current_amount + amount,
        "unit_costs": unit_costs,
        "costs": costs,
        "costs_raw": str(item.get("costs_raw") or ""),
        "estimated_duration": estimate_action_duration("research", costs),
        "energy_delta": None,
        "energy_safe": True,
        "can_upgrade": bool(item.get("can_upgrade")),
        "can_apply": can_apply,
        "actionable_now": can_apply,
        "resource_shortfall": resource_shortfall(resources, costs),
    }


def _known_resource_vector(value: Any, field: str) -> Dict[str, int]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{field} 缺少可信資源資料。")
    result: Dict[str, int] = {}
    for key in RESOURCE_KEYS:
        parsed = normalize_number(value.get(key))
        if parsed is None:
            raise RuntimeError(f"{field}.{key} 未知；已 fail closed。")
        result[key] = parsed
    return result


def _storage_capacities_from_supplies(supplies: Mapping[str, Any]) -> Dict[str, int]:
    items = supplies.get("items")
    if isinstance(items, Mapping):
        levels: Dict[str, int] = {}
        for resource, tech_id in (("metal", "22"), ("crystal", "23"), ("deuterium", "24")):
            item = items.get(tech_id)
            level = normalize_number(item.get("level")) if isinstance(item, Mapping) else None
            if level is not None:
                levels[resource] = level
        if len(levels) == 3:
            return {key: calc_storage_capacity(level) for key, level in levels.items()}
    # Fallback to scout-report.json if available
    try:
        scout = load_json_file(os.path.join(MEMORY_DIR, "scout-report.json"))
        if scout and "planets" in scout:
            planet_id = supplies.get("planet_id")
            for p in scout["planets"]:
                if str(p.get("planet_id")) == str(planet_id) and "storage" in p:
                    return {
                        "metal": int(p["storage"]["metal"]),
                        "crystal": int(p["storage"]["crystal"]),
                        "deuterium": int(p["storage"]["deuterium"]),
                    }
    except Exception:
        pass
    raise RuntimeError("storage capacities 無法解析；已 fail closed。")


def _coordinate_text(target: Mapping[str, int]) -> str:
    return f"[{int(target['galaxy'])}:{int(target['system'])}:{int(target['position'])}]"


def _local_raid_evidence(target: Mapping[str, int]) -> Dict[str, Any]:
    coords = _coordinate_text(target)
    matches = [item for item in parse_farm_targets_md() if item.get("coords") == coords]
    if len(matches) != 1:
        return {
            "defense_count": None,
            "fleet_count": None,
            "report_observed_at": None,
            "attacks_24h": None,
        }
    item = matches[0]
    return {
        "defense_count": item.get("defense_count"),
        "fleet_count": item.get("fleet_count"),
        "report_observed_at": item.get("report_observed_at"),
        "attacks_24h": item.get("attacks_24h"),
    }


def create_fleet_confirmed_plan(args: argparse.Namespace, mission: str) -> Dict[str, Any]:
    """Create one short-lived fleet candidate from live reads and local evidence."""
    if mission not in {"transport", "deploy", "colonize", "spy", "raid", "expedition"}:
        raise RuntimeError("fleet mission 無效。")
    planet_id = int(args.planet_id)
    target = {
        "galaxy": int(args.galaxy),
        "system": int(args.system),
        "position": int(args.position),
    }
    fleet_state = read_fleet_state(planet_id)
    if str(fleet_state.get("planet_id")) != str(planet_id):
        raise RuntimeError("Fleet state planet pin 不符。")
    slots = fleet_state.get("fleet_slots")
    if not isinstance(slots, dict) or slots.get("known") is not True:
        raise RuntimeError("Fleet Slot 無法可靠解析；已 fail closed。")
    ships_before_raw = fleet_state.get("ships")
    if not isinstance(ships_before_raw, Mapping):
        raise RuntimeError("Fleet state 缺少 stationed ships。")
    ships_before = {}
    for tech_id, val in ships_before_raw.items():
        if not str(tech_id).isdigit():
            continue
        amt = val.get("amount") if isinstance(val, Mapping) else val
        if isinstance(amt, int) and not isinstance(amt, bool) and amt >= 0:
            ships_before[str(tech_id)] = amt
    resources = _known_resource_vector(fleet_state.get("resources"), "origin resources")
    origin_supplies = read_technology_list("supplies", planet_id)
    storage_capacities = _storage_capacities_from_supplies(origin_supplies)

    target_evidence: Dict[str, Any]
    target_resources = {key: 0 for key in RESOURCE_KEYS}
    target_capacities = {key: 1 for key in RESOURCE_KEYS}
    payload = {
        "metal": int(getattr(args, "metal", 0) or 0),
        "crystal": int(getattr(args, "crystal", 0) or 0),
        "deuterium": int(getattr(args, "deuterium", 0) or 0),
    }
    if any(value < 0 for value in payload.values()):
        raise RuntimeError("fleet payload 不得為負數。")

    combat_tech = str(getattr(args, "combat_tech", "204") or "204")
    combat_amount = int(getattr(args, "combat_amount", 0) or 0)
    ship_composition: Optional[Dict[str, int]] = None
    preset_name: Optional[str] = None

    if mission in {"transport", "deploy"}:
        coords = _coordinate_text(target)
        owned = [item for item in read_owned_planets() if str(item.get("coords") or "") == coords]
        if len(owned) != 1 or not str(owned[0].get("id") or "").isdigit():
            raise RuntimeError("運輸／部署目標未唯一對應自有星球。")
        target_id = int(owned[0]["id"])
        target_supplies = read_technology_list("supplies", target_id)
        target_resources = _known_resource_vector(target_supplies.get("resources"), "target resources")
        target_capacities = _storage_capacities_from_supplies(target_supplies)
        target_evidence = {
            "owned_planet": True,
            "target_planet_id": str(target_id),
            "empty": False,
            "inactive": False,
            "destroyed": False,
            "vacation": False,
        }
    elif mission == "expedition":
        target_evidence = {
            "owned_planet": False,
            "empty": True,
            "inactive": False,
            "destroyed": False,
            "vacation": False,
            "galaxy_raw": "expedition slot 16",
        }
    else:
        observed_target = read_galaxy_target_evidence(planet_id, target)
        target_evidence = {
            "owned_planet": bool(observed_target.get("owned_planet")),
            "empty": bool(observed_target.get("empty")),
            "inactive": bool(observed_target.get("inactive")),
            "destroyed": bool(observed_target.get("destroyed")),
            "vacation": bool(observed_target.get("vacation")),
            "galaxy_raw": str(observed_target.get("raw") or ""),
        }
        if mission == "raid":
            target_evidence.update(_local_raid_evidence(target))

    if mission == "colonize":
        ship_tech, ship_amount = "208", 1
    elif mission == "spy":
        ship_tech, ship_amount = "210", int(getattr(args, "probes", 1) or 1)
    elif mission == "expedition":
        requested_preset = getattr(args, "preset_name", None)
        if requested_preset:
            preset = resolve_expedition_preset(
                fleet_state.get("expedition_templates"),
                str(requested_preset),
            )
            ship_composition = dict(preset["ships"])
            preset_name = str(preset["name"])
            ship_tech = "203" if int(ship_composition.get("203", 0) or 0) > 0 else "202"
            ship_amount = int(ship_composition.get(ship_tech, 0) or 0)
            if ship_amount <= 0:
                raise RuntimeError("agent expedition preset 必須包含大型或小型運輸艦。")
            combat_tech = ""
            combat_amount = 0
        else:
            ship_tech = str(getattr(args, "ship_tech", "203") or "203")
            ship_amount = int(getattr(args, "cargo_amount", getattr(args, "ship_amount", 5)) or 5)
            combat_tech = str(getattr(args, "combat_tech", "204") or "204")
            combat_amount = int(getattr(args, "combat_amount", 1) or 1)
            ship_composition = {ship_tech: ship_amount}
            if combat_amount > 0:
                ship_composition[combat_tech] = ship_composition.get(combat_tech, 0) + combat_amount
    else:
        ship_tech = str(getattr(args, "ship_tech", "202") or "202")
        ship_amount = int(getattr(args, "ship_amount", 1) or 1)
    candidate = build_fleet_candidate(
        planet_id=str(planet_id),
        mission=FleetMission(mission),
        target=target,
        ship_tech=ship_tech,
        ship_amount=ship_amount,
        ships_before=ships_before,
        fleet_slots={"free": int(slots["free"]), "used": slots.get("used"), "total": slots.get("total")},
        ship_composition=ship_composition,
        expedition_slots=fleet_state.get("expedition_slots") if mission == "expedition" else None,
        payload=payload,
        target_resources=target_resources if mission in {"transport", "deploy"} else None,
        target_storage_capacities=target_capacities if mission in {"transport", "deploy"} else None,
        owner_authorized_large_transport=bool(getattr(args, "confirm", False)),
        target_evidence=target_evidence,
    )
    if mission == "expedition":
        if preset_name is not None:
            candidate["preset_name"] = preset_name

    previous_plan = load_json_file(_plan_file())
    watch_costs = (
        resource_vector(previous_plan.get("watch_costs", {}))
        if previous_plan and str(previous_plan.get("planet_id")) == str(planet_id)
        else {key: 0 for key in RESOURCE_KEYS}
    )
    spendable = {key: max(0, resources[key] - watch_costs[key]) for key in RESOURCE_KEYS}
    now = int(time.time())
    snapshot_material = json.dumps(
        {"planet_id": str(planet_id), "resources": resources, "candidate": candidate},
        ensure_ascii=False,
        sort_keys=True,
    )
    plan = {
        "version": 1,
        "plan_id": secrets.token_urlsafe(12),
        "planet_id": str(planet_id),
        "run_id": str(args.run_id),
        "created_at": now,
        "expires_at": now + PLAN_TTL_SECONDS,
        "status": "active",
        "action_count": 0,
        "snapshot_hash": hashlib.sha256(snapshot_material.encode("utf-8")).hexdigest(),
        "resources": resources,
        "spendable_resources": spendable,
        "storage_capacities": storage_capacities,
        "energy": None,
        "rates": {key: 0 for key in RESOURCE_KEYS},
        "rate_source": "not_required_for_fleet",
        "queue_busy": {"fleet": False},
        "watch_action_id": previous_plan.get("watch_action_id") if previous_plan else None,
        "watch_costs": watch_costs,
        "candidates": [candidate],
        "packages": [],
    }
    constants = load_account_constants(getattr(args, "constants", DEFAULT_CONSTANTS_PATH))
    _get_dep('assess_workflow_candidate', assess_workflow_candidate)(candidate, plan, constants=constants, now=now)
    if not can_afford(spendable, candidate.get("payload", {})):
        raise RuntimeError("Fleet dispatch 會侵蝕 watch 保留或來源資源不足。")
    atomic_write_json(_plan_file(), plan)
    return plan


def active_watch(plan: Optional[Dict[str, Any]], candidates: List[Dict[str, Any]], planet_id: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    if not plan:
        return None
    if planet_id is not None and str(plan.get("planet_id")) != str(planet_id):
        return None
    return next((candidate for candidate in candidates if candidate["action_id"] == plan.get("watch_action_id")), None)


def feasible_packages(
    candidates: List[Dict[str, Any]],
    spendable: Dict[str, int],
    storage_capacities: Optional[Dict[str, int]] = None,
    initial_energy: Optional[int] = None,
    queue_busy: Optional[Dict[str, bool]] = None,
) -> List[Dict[str, Any]]:
    """Compatibility wrapper around the extracted pure planner."""
    return build_feasible_packages(
        candidates,
        spendable,
        storage_capacities=storage_capacities,
        initial_energy=initial_energy,
        queue_busy=queue_busy,
        safety=SAFETY_POLICY,
    )


RESOURCE_SETTINGS_PROBE_JS = """
(function() {
    var body = (document.body && document.body.innerText) || '';
    return JSON.stringify({success:true, text:body.slice(0, 12000), headings:Array.from(document.querySelectorAll('h1,h2,h3,.title,.resource_name')).slice(0,50).map(function(el) { return el.innerText.trim(); })});
})()
"""


def parse_resource_settings_rates(text: str) -> Optional[Dict[str, int]]:
    summary = re.search(
        r"(?:時產量|時産量|每小時|/h|hour)\s*:\s*([0-9][0-9.,]*)\s+([0-9][0-9.,]*)\s+([0-9][0-9.,]*)",
        text,
        re.IGNORECASE,
    )
    if summary:
        values = [normalize_number(summary.group(index)) for index in range(1, 4)]
        if all(value is not None for value in values):
            return dict(zip(RESOURCE_KEYS, values))
    labels = {"metal": "金屬", "crystal": "水晶", "deuterium": "重氫"}
    rates: Dict[str, int] = {}
    for key, label in labels.items():
        match = re.search(rf"{label}(?:(?!金屬|水晶|重氫).){{0,500}}?(?:每小時|/h|hour)[^0-9]*([0-9][0-9.,\s]*)", text, re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        parsed = normalize_number(match.group(1))
        if parsed is None:
            return None
        rates[key] = parsed
    return rates



def parse_header_rates(tooltips: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """Accept rates only when all three tooltip values expose an unambiguous hourly value."""
    fn = _get_dep("parse_header_rates")
    if fn and fn is not parse_header_rates:
        return fn(tooltips)
    rates: Dict[str, int] = {}
    for key in RESOURCE_KEYS:
        text = str(tooltips.get(key, ""))
        hourly = re.search(r"(?:每小時|hour|/h)[^0-9]*([0-9][0-9.,\s]*)", text, re.IGNORECASE)
        if not hourly:
            return None
        value = normalize_number(hourly.group(1))
        if value is None:
            return None
        rates[key] = value
    return rates


def cache_rates(planet_id: int, rates: Dict[str, int], source: str) -> None:
    fn = _get_dep("cache_rates")
    if fn and fn is not cache_rates:
        return fn(planet_id, rates, source)
    atomic_write_json(_rates_file(), {
        "planet_id": str(planet_id),
        "rates": resource_vector(rates),
        "source": source,
        "updated_at": int(time.time()),
    })


def mark_rates_stale(planet_id: int) -> None:
    fn = _get_dep("mark_rates_stale")
    if fn and fn is not mark_rates_stale:
        return fn(planet_id)
    data = load_json_file(_rates_file())
    if data and str(data.get("planet_id")) == str(planet_id):
        data["stale"] = True
        atomic_write_json(_rates_file(), data)


def load_cached_rates(planet_id: int) -> Optional[Dict[str, int]]:
    fn = _get_dep("load_cached_rates")
    if fn and fn is not load_cached_rates:
        return fn(planet_id)
    data = load_json_file(_rates_file())
    if not data or data.get("stale") or str(data.get("planet_id")) != str(planet_id):
        return None
    rates = data.get("rates")
    if not isinstance(rates, dict):
        return None
    clean = resource_vector(rates)
    return clean if len(clean) == 3 else None

def read_resource_settings_rates(planet_id: int) -> Optional[Dict[str, int]]:
    result = execute_checked_component("resourcesettings", planet_id, RESOURCE_SETTINGS_PROBE_JS)
    return parse_resource_settings_rates(str(result.get("text") or ""))


def get_rates_for_plan(planet_id: int, header_tooltips: Dict[str, Any]) -> Tuple[Dict[str, int], str]:
    header_rates = parse_header_rates(header_tooltips)
    if header_rates is not None:
        cache_rates(planet_id, header_rates, "header-tooltip")
        return header_rates, "header-tooltip"
    settings_rates = read_resource_settings_rates(planet_id)
    if settings_rates is None:
        raise RuntimeError("Header tooltip 與 Resource settings 都無法解析每小時產量，已停止計畫。")
    cache_rates(planet_id, settings_rates, "resourcesettings")
    return settings_rates, "resourcesettings"


def _parse_coordinate_label(value: Any) -> Optional[Dict[str, int]]:
    match = re.fullmatch(r"\[([0-9]+):([0-9]+):([0-9]+)\]", str(value or "").strip())
    if match is None:
        return None
    return {
        "galaxy": int(match.group(1)),
        "system": int(match.group(2)),
        "position": int(match.group(3)),
    }


def collect_patrol_fleet_candidates(
    planet_id: int,
    origin_resources: Dict[str, int],
    origin_storage_capacities: Dict[str, int],
    watch_costs: Dict[str, int],
    strategy: StrategyPolicy,
    constants: AccountConstants,
    *,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Read bounded fleet evidence, then delegate candidate construction to the domain layer."""
    now = int(time.time() if now is None else now)
    fleet_state = read_fleet_state(planet_id)
    if str(fleet_state.get("planet_id")) != str(planet_id):
        raise RuntimeError("Fleet candidate read 的 planet pin 不符。")
    raw_slots = fleet_state.get("fleet_slots")
    if not isinstance(raw_slots, Mapping) or raw_slots.get("known") is not True:
        raise RuntimeError("Fleet Slot 無法可靠解析；已 fail closed。")
    slots = {
        key: int(raw_slots[key])
        for key in ("free", "used", "total")
        if isinstance(raw_slots.get(key), int) and not isinstance(raw_slots.get(key), bool)
    }
    if "free" not in slots:
        raise RuntimeError("Fleet Slot free 未知；已 fail closed。")
    raw_ships = fleet_state.get("ships")
    if not isinstance(raw_ships, Mapping):
        raise RuntimeError("Fleet candidate read 缺少 stationed ships。")
    ships = {
        str(key): int(value)
        for key, value in raw_ships.items()
        if str(key).isdigit() and isinstance(value, int) and not isinstance(value, bool) and value >= 0
    }

    diagnostics: List[Dict[str, Any]] = []
    owned_planets = read_owned_planets()
    owned_targets: List[Dict[str, Any]] = []
    origin_coordinates: Optional[Dict[str, int]] = None
    for planet in owned_planets:
        coordinates = _parse_coordinate_label(planet.get("coords"))
        if str(planet.get("id")) == str(planet_id):
            origin_coordinates = coordinates
            continue
        if coordinates is None or not str(planet.get("id") or "").isdigit():
            diagnostics.append({"target_planet_id": planet.get("id"), "reason": "owned_planet_coordinates_unknown"})
            continue
        try:
            state = read_technology_list("supplies", int(planet["id"]))
            owned_targets.append({
                "planet_id": str(planet["id"]),
                "target": coordinates,
                "resources": _known_resource_vector(state.get("resources"), "target resources"),
                "storage_capacities": _storage_capacities_from_supplies(state),
            })
        except RuntimeError as exc:
            diagnostics.append({"target_planet_id": planet.get("id"), "reason": f"owned_target_read_failed:{exc}"})

    live_farming_evidence: Dict[str, Dict[str, Any]] = {}
    live_farming_targets: List[Dict[str, Any]] = []
    if strategy.farming_enabled:
        for target in parse_farm_targets_md()[:strategy.max_farming_targets]:
            coordinate = {key: target.get(key) for key in ("galaxy", "system", "position")}
            try:
                observed = read_galaxy_target_evidence(planet_id, coordinate)
            except (RuntimeError, TypeError, ValueError) as exc:
                diagnostics.append({"target": target.get("coords"), "reason": f"live_target_read_failed:{exc}"})
                continue
            coords = _coordinate_text(coordinate)
            live_farming_evidence[coords] = observed
            live_farming_targets.append({
                **target,
                "coords": coords,
                "is_inactive": observed.get("inactive") is True,
                "is_destroyed": observed.get("destroyed") is True,
                "is_vacation": observed.get("vacation") is True,
            })
    farming_suggestions = evaluate_farming_targets(
        live_farming_targets,
        available_fleet_slots=slots["free"],
        available_ships={
            "espionage_probe": int(ships.get("210", 0)),
            "small_cargo": int(ships.get("202", 0)),
            "large_cargo": int(ships.get("203", 0)),
        },
        min_loot_threshold=strategy.minimum_raid_loot,
        max_concurrent_raids=strategy.max_concurrent_raids,
        reserved_slots=SAFETY_POLICY.minimum_free_fleet_slots,
        cargo_capacities=constants.cargo_capacities,
        now=now,
    ) if strategy.farming_enabled else {
        "probes_to_send": [],
        "raids_to_launch": [],
        "skipped_targets": [],
    }

    empty_targets: List[Dict[str, int]] = []
    if strategy.colonization_cycle_enabled and origin_coordinates is not None and int(ships.get("208", 0)) >= 1:
        start = max(1, origin_coordinates["system"] - strategy.colony_scan_radius)
        end = min(499, origin_coordinates["system"] + strategy.colony_scan_radius)
        owned_coordinates = {str(planet.get("coords") or "") for planet in owned_planets}
        for system in range(start, end + 1):
            coordinate = {
                "galaxy": origin_coordinates["galaxy"],
                "system": system,
                "position": strategy.preferred_colony_position,
            }
            if _coordinate_text(coordinate) in owned_coordinates:
                continue
            try:
                observed = read_galaxy_target_evidence(planet_id, coordinate)
            except RuntimeError as exc:
                diagnostics.append({"target": _coordinate_text(coordinate), "reason": f"colony_read_failed:{exc}"})
                continue
            if observed.get("empty") is True and observed.get("destroyed") is not True:
                empty_targets.append(coordinate)
                if len(empty_targets) >= strategy.max_colony_candidates:
                    break

    built = build_patrol_fleet_candidates(
        planet_id=str(planet_id),
        origin_resources=origin_resources,
        origin_storage_capacities=origin_storage_capacities,
        watch_costs=watch_costs,
        ships_before=ships,
        fleet_slots=slots,
        owned_targets=owned_targets,
        farming_suggestions=farming_suggestions,
        live_farming_evidence=live_farming_evidence,
        empty_colony_targets=empty_targets,
        strategy=strategy,
        constants=constants,
        observed_at=now,
    )
    return {
        "candidates": built["candidates"],
        "diagnostics": diagnostics + built["diagnostics"] + list(farming_suggestions.get("skipped_targets", [])),
    }


def command_plan(args: argparse.Namespace) -> Dict[str, Any]:
    """Create the compact, short-lived candidate set used by the Agent's ROI decision."""
    run_id = getattr(args, "run_id", None)
    if run_id:
        require_run_lease(run_id)
    planet_id = int(args.planet_id)
    overview = read_header_snapshot("overview", planet_id)
    resources = resource_vector(overview.get("resources", {}))
    energy = parse_signed_number(overview.get("energy"))
    rates, rate_source = _get_dep('get_rates_for_plan', get_rates_for_plan)(planet_id, overview.get("rate_tooltips", {}))

    supplies = read_technology_list("supplies", planet_id)
    facilities = read_technology_list("facilities", planet_id)
    research = read_technology_list("research", planet_id)
    lifeforms: Optional[Dict[str, Any]] = None
    if getattr(args, "include_lifeforms", False):
        lifeforms = read_lifeform_atom(planet_id, read_technology_list)
        if lifeforms.get("success") is not True:
            raise RuntimeError(f"Lifeform plan 讀取失敗：{lifeforms.get('reason', 'unknown')}。")
    production: Optional[Dict[str, Dict[str, Any]]] = None
    production_request = getattr(args, "production_request", None)
    if getattr(args, "include_production", False) or production_request is not None:
        production = {
            component: read_technology_list(component, planet_id)
            for component in ("shipyard", "defenses")
        }

    storage_capacities = _storage_capacities_from_supplies(supplies)

    queue_busy = supplies.get("queue_busy", {})
    if not queue_busy:
        queue_busy = {
            "building": False,
            "research": False,
        }
    if lifeforms is not None:
        queue_busy.update(lifeforms["lfbuildings"].get("queue_busy", {}))
        queue_busy.update(lifeforms["lfresearch"].get("queue_busy", {}))
    if production is not None:
        for state in production.values():
            queue_busy.update(state.get("queue_busy", {}))

    candidates: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    for section, data in (("supplies", supplies), ("facilities", facilities), ("research", research)):
        for tech_id, item in data.get("items", {}).items():
            candidate = action_from_item(section, str(tech_id), item, resources, energy)
            if candidate is not None:
                candidates.append(candidate)
            elif getattr(args, "diagnose", False) and item.get("can_upgrade"):
                diagnostics.append({"section": section, "tech_id": str(tech_id), "name": item.get("name"), "can_upgrade": item.get("can_upgrade"), "costs_raw": item.get("costs_raw"), "energy_raw": item.get("energy_raw"), "debug": item.get("debug", {})})
    if lifeforms is not None:
        for component in ("lfbuildings", "lfresearch"):
            for tech_id, item in lifeforms[component].get("items", {}).items():
                candidate = lifeform_action_from_item(
                    component,
                    str(tech_id),
                    item,
                    resources,
                    energy,
                    planet_id,
                )
                if candidate is not None:
                    candidates.append(candidate)
                elif getattr(args, "diagnose", False) and item.get("can_upgrade"):
                    diagnostics.append(
                        {
                            "section": component,
                            "tech_id": str(tech_id),
                            "name": item.get("name"),
                            "reason": "displayed_costs_unparseable",
                            "costs_raw": item.get("costs_raw"),
                            "energy_raw": item.get("energy_raw"),
                        }
                    )
    if getattr(args, "include_cancel", False):
        cancellation = cancel_building_action_from_snapshot(supplies, planet_id)
        if cancellation is not None:
            candidates.append(cancellation)
    if production is not None:
        requested_tech = str(production_request[0]) if production_request is not None else None
        requested_amount = int(production_request[1]) if production_request is not None else 1
        for component, state in production.items():
            for tech_id, item in state.get("items", {}).items():
                if requested_tech is not None and str(tech_id) != requested_tech:
                    continue
                candidate = production_action_from_item(
                    component,
                    str(tech_id),
                    item,
                    resources,
                    planet_id,
                    requested_amount,
                )
                if candidate is not None:
                    candidates.append(candidate)
                elif getattr(args, "diagnose", False) and item.get("can_upgrade"):
                    diagnostics.append(
                        {
                            "section": component,
                            "tech_id": str(tech_id),
                            "reason": "displayed_unit_costs_unparseable",
                            "costs_raw": item.get("costs_raw"),
                        }
                    )

    previous_plan = load_json_file(_plan_file())
    watch = active_watch(previous_plan, candidates, planet_id=planet_id)
    watch_costs = watch["costs"] if watch else {key: 0 for key in RESOURCE_KEYS}
    spendable = {key: max(0, resources.get(key, 0) - watch_costs.get(key, 0)) for key in RESOURCE_KEYS}

    fleet_diagnostics: List[Dict[str, Any]] = []
    if getattr(args, "include_fleet", False):
        strategy = load_strategy_policy(getattr(args, "strategy", DEFAULT_STRATEGY_PATH))
        constants = load_account_constants(getattr(args, "constants", DEFAULT_CONSTANTS_PATH))
        fleet_plan = _get_dep('collect_patrol_fleet_candidates', collect_patrol_fleet_candidates)(
            planet_id,
            resources,
            storage_capacities,
            watch_costs,
            strategy,
            constants,
        )
        provisional_plan = {
            "planet_id": str(planet_id),
            "resources": resources,
            "spendable_resources": spendable,
            "storage_capacities": storage_capacities,
        }
        for candidate in fleet_plan["candidates"]:
            try:
                _get_dep('assess_workflow_candidate', assess_workflow_candidate)(
                    candidate,
                    provisional_plan,
                    constants=constants,
                )
                if not can_afford(spendable, candidate.get("payload", {})):
                    raise RuntimeError("fleet payload 會侵蝕 watch reserve。")
                candidates.append(candidate)
            except RuntimeError as exc:
                fleet_diagnostics.append({"action_id": candidate.get("action_id"), "reason": str(exc)})
        fleet_diagnostics.extend(fleet_plan["diagnostics"])
        queue_busy.setdefault("fleet", False)

    packages = feasible_packages(
        [candidate for candidate in candidates if not watch or candidate["action_id"] != watch["action_id"]],
        spendable,
        storage_capacities=storage_capacities,
        initial_energy=energy,
        queue_busy=queue_busy,
    )
    now = int(time.time())
    material = json.dumps({"planet_id": planet_id, "resources": resources, "energy": energy, "candidates": candidates}, ensure_ascii=False, sort_keys=True)
    plan = {
        "version": 1, "plan_id": secrets.token_urlsafe(12), "planet_id": str(planet_id), "created_at": now,
        "expires_at": now + PLAN_TTL_SECONDS, "action_count": 0,
        "snapshot_hash": hashlib.sha256(material.encode("utf-8")).hexdigest(), "resources": resources,
        "energy": energy, "rates": rates, "rate_source": rate_source,
        "storage_capacities": storage_capacities,
        "queue_busy": queue_busy,
        "building_queue": {
            key: (supplies.get("building_queue") or {}).get(key)
            for key in ("active", "tech_id", "start_epoch", "end_epoch", "queue_token", "summary")
        },
        "watch_action_id": watch["action_id"] if watch else None, "watch_costs": watch_costs,
        "spendable_resources": spendable, "candidates": candidates, "packages": packages,
    }
    if run_id:
        plan["run_id"] = run_id
    if getattr(args, "diagnose", False):
        plan["diagnostics"] = diagnostics
        plan["fleet_diagnostics"] = fleet_diagnostics
    atomic_write_json(_plan_file(), plan)
    print_command_output(
        args,
        plan,
        f"plan {plan['plan_id']}: planet {plan['planet_id']}, "
        f"{len(plan['candidates'])} candidates, {len(plan['packages'])} packages",
    )
    return plan


def require_active_plan(plan_id: str, run_id: Optional[str] = None) -> Dict[str, Any]:
    plan = load_json_file(_plan_file())
    if not plan or plan.get("plan_id") != plan_id:
        raise RuntimeError("找不到相符的有效 plan_id。")
    if int(plan.get("expires_at", 0)) < int(time.time()):
        raise RuntimeError("plan_id 已逾時；請先重新執行 plan。")
    if plan.get("status") in {"uncertain", "cancelled"}:
        raise RuntimeError(f"目前計畫狀態為 {plan.get('status')}，禁止再執行。")
    plan_run_id = plan.get("run_id")
    if plan_run_id:
        if run_id != plan_run_id:
            raise RuntimeError("--run-id 與 plan 綁定的巡邏租約不符。")
        require_run_lease(str(run_id))
    return plan


def estimated_wake_epoch(resources: Dict[str, int], costs: Dict[str, int], rates: Dict[str, int]) -> int:
    seconds = 0
    for key, shortfall in resource_shortfall(resources, costs).items():
        if shortfall == 0:
            continue
        rate = rates.get(key, 0)
        if rate <= 0:
            return int(time.time()) + 3600
        seconds = max(seconds, math.ceil(shortfall * 3600 / rate))
    return int(time.time()) + seconds + 120


def command_watch(args: argparse.Namespace) -> Dict[str, Any]:
    plan = _get_dep('require_active_plan', require_active_plan)(args.plan_id, getattr(args, "run_id", None))
    candidate = next((item for item in plan.get("candidates", []) if item.get("action_id") == args.action_id), None)
    if candidate is None:
        raise RuntimeError("watch_action_id 不在目前計畫候選中。")
    plan["watch_action_id"] = candidate["action_id"]
    plan["watch_costs"] = candidate["costs"]
    plan["spendable_resources"] = {key: max(0, plan["resources"].get(key, 0) - candidate["costs"].get(key, 0)) for key in RESOURCE_KEYS}
    plan["expires_at"] = int(time.time()) + PLAN_TTL_SECONDS
    plan["next_wake"] = estimated_wake_epoch(plan["resources"], candidate["costs"], plan["rates"])
    atomic_write_json(_plan_file(), plan)
    write_next_wake(plan["next_wake"])
    output = {"plan_id": plan["plan_id"], "watch_action_id": candidate["action_id"], "next_wake": plan["next_wake"]}
    print_command_output(
        args,
        output,
        f"plan {plan['plan_id']}: watching {candidate['action_id']} until {plan['next_wake']}",
    )
    return output


def apply_action_js(candidate: Dict[str, Any], reserve_costs: Dict[str, int]) -> str:
    expected_costs = json.dumps(candidate["costs"], ensure_ascii=False)
    return f"""
    (function() {{
        function value(selector) {{ var el=document.querySelector(selector); var raw=el && (el.getAttribute('data-raw') || el.innerText) || ''; var digits=raw.replace(/[^0-9]/g,''); return digits ? Number(digits) : 0; }}
        var expected={expected_costs}; var reserve={json.dumps(reserve_costs, ensure_ascii=False)};
        var el=document.querySelector("li.technology[data-technology='{candidate['tech_id']}'], [data-technology='{candidate['tech_id']}']");
        if (!el) return JSON.stringify({{success:false,mutation_submitted:false,reason:"找不到計畫中的科技項目"}});
        var button=el.querySelector('button.upgrade, button.build, [data-action="upgrade"]');
        var marker=button && (((button.innerText || '') + ' ' + (button.outerHTML || '')).toLowerCase()) || '';
        if (marker.includes('darkmatter') || marker.includes('dark_matter') || marker.includes('dark-matter') || marker.includes('暗物質') || marker.includes('premium') || marker.includes('item_shop'))
            return JSON.stringify({{success:false,mutation_submitted:false,reason:"premium_control_rejected"}});
        if (!button || button.disabled) return JSON.stringify({{success:false,mutation_submitted:false,reason:"目前按鈕不可用或佇列已變更"}});
        var current={{metal:value('#resources_metal'),crystal:value('#resources_crystal'),deuterium:value('#resources_deuterium')}};
        for (var key of ['metal','crystal','deuterium']) {{
            if (current[key] < (expected[key] || 0) + Math.min(current[key], (reserve[key] || 0))) return JSON.stringify({{success:false,mutation_submitted:false,reason:"資源不足或會侵蝕 watch 保留"}});
        }}
        button.click(); return JSON.stringify({{success:true,mutation_submitted:true,action_id:{json.dumps(candidate['action_id'])},resources_before:current,clicked_at:Math.floor(Date.now()/1000)}});
    }})()
    """


def cancel_building_action_js(candidate: Dict[str, Any]) -> str:
    expected = json.dumps(str(candidate["queue_token"]), ensure_ascii=False)
    return f"""
    (function() {{
        function text(el) {{ return el ? el.innerText.trim() : ''; }}
        var container=document.querySelector('#productionboxbuildingcomponent, #b_building, .queue-building');
        if (!container) return JSON.stringify({{success:false,mutation_submitted:false,reason:'building_queue_missing'}});
        var item=container.querySelector('[data-technology], .queueItem, .construction') || container;
        var techId=item.getAttribute('data-technology') || container.getAttribute('data-technology') || '';
        var start=item.getAttribute('data-start') || container.getAttribute('data-start') || '';
        var end=item.getAttribute('data-end') || container.getAttribute('data-end') || '';
        var summary=text(item).replace(/\\s+/g, ' ').slice(0, 160);
        var token=[techId,start,end,summary].join('|');
        if (token !== {expected}) return JSON.stringify({{success:false,mutation_submitted:false,reason:'queue_token_mismatch',observed_queue_token:token}});
        var cancel=container.querySelector('a.abort, button.abort, a.cancel, button.cancel, [data-overlay="cancelProduction"]');
        if (!cancel || cancel.disabled) return JSON.stringify({{success:false,mutation_submitted:false,reason:'cancel_control_unavailable'}});
        cancel.click();
        setTimeout(function() {{
            var dialog=document.querySelector('#decisionOK, .decisionOK, button.btn_blue.ok');
            if (dialog && !dialog.disabled) dialog.click();
        }}, 300);
        return JSON.stringify({{success:true,mutation_submitted:true,queue_token:token,clicked_at:Math.floor(Date.now()/1000)}});
    }})()
    """


def prevalidate_cancel_building(candidate: Dict[str, Any], pinned: Dict[str, Any]) -> Dict[str, Any]:
    queue = (pinned.get("technology") or {}).get("building_queue")
    if not isinstance(queue, dict) or queue.get("active") is not True:
        return {"ok": False, "skip": True, "reason": "building_queue_already_clear"}
    if str(queue.get("queue_token") or "") != str(candidate.get("queue_token") or ""):
        return {"ok": False, "reason": "building_queue_token_changed", "observed": queue}
    if queue.get("cancel_available") is not True:
        return {"ok": False, "reason": "cancel_control_unavailable", "observed": queue}
    return {"ok": True, "queue": queue}


def verify_cancel_building(
    candidate: Dict[str, Any],
    execution: Dict[str, Any],
    after: Dict[str, Any],
) -> Dict[str, Any]:
    queue = after.get("building_queue")
    cleared = isinstance(queue, dict) and queue.get("active") is False
    reasons: List[str] = []
    if not execution.get("success"):
        reasons.append(str(execution.get("reason") or "cancel_click_failed"))
    if not cleared:
        reasons.append("building_queue_not_cleared")
    return {
        "success": bool(execution.get("success") and cleared),
        "reasons": reasons,
        "evidence": {
            "expected_queue_token": candidate.get("queue_token"),
            "observed_queue": queue,
            "queue_cleared": cleared,
        },
    }


def production_open_detail_js(candidate: Dict[str, Any]) -> str:
    return f"""
    (function() {{
        var item=document.querySelector("li.technology[data-technology='{candidate['tech_id']}']");
        if (!item) return JSON.stringify({{success:false,mutation_submitted:false,reason:'production_target_missing'}});
        var target=item.querySelector('.icon') || item;
        target.click();
        return JSON.stringify({{success:true,mutation_submitted:false,detail_opened:true}});
    }})()
    """


def production_submit_js(candidate: Dict[str, Any], reserve: Dict[str, int]) -> str:
    expected_costs = json.dumps(candidate["costs"], ensure_ascii=False)
    reserve_json = json.dumps(reserve, ensure_ascii=False)
    return f"""
    (function() {{
        function value(selector) {{
            var el=document.querySelector(selector);
            var raw=el && (el.getAttribute('data-raw') || el.innerText) || '';
            var digits=raw.replace(/[^0-9]/g,'');
            return digits ? Number(digits) : 0;
        }}
        var expected={expected_costs};
        var reserve={reserve_json};
        var current={{metal:value('#resources_metal'),crystal:value('#resources_crystal'),deuterium:value('#resources_deuterium')}};
        for (var key of ['metal','crystal','deuterium']) {{
            if (current[key] < (expected[key] || 0) + (reserve[key] || 0))
                return JSON.stringify({{success:false,mutation_submitted:false,reason:'resource_or_watch_reserve_shortfall'}});
        }}
        var input=document.querySelector('#build_amount, input[name="build_amount"], input[name="menge"], input#amount, input.amount');
        if (!input) return JSON.stringify({{success:false,mutation_submitted:false,reason:'production_amount_input_missing'}});
        input.value={int(candidate['amount'])};
        ['input','change','blur'].forEach(function(eventName) {{ input.dispatchEvent(new Event(eventName, {{bubbles:true}})); }});
        var button=document.querySelector('button.upgrade, .build-it_wrap button, button.build, button.btn_build, [data-action="build"], a.build-it');
        var marker=button && (((button.innerText || '') + ' ' + (button.outerHTML || '')).toLowerCase()) || '';
        if (marker.includes('darkmatter') || marker.includes('dark_matter') || marker.includes('dark-matter') || marker.includes('暗物質') || marker.includes('premium') || marker.includes('item_shop'))
            return JSON.stringify({{success:false,mutation_submitted:false,reason:'premium_control_rejected'}});
        if (!button || button.disabled) return JSON.stringify({{success:false,mutation_submitted:false,reason:'production_submit_unavailable'}});
        button.click();
        return JSON.stringify({{
            success:true,
            mutation_submitted:true,
            action_id:{json.dumps(candidate['action_id'])},
            resources_before:current,
            clicked_at:Math.floor(Date.now()/1000)
        }});
    }})()
    """


def prevalidate_production(
    candidate: Dict[str, Any],
    pinned: Dict[str, Any],
    plan: Dict[str, Any],
    reserve: Dict[str, int],
) -> Dict[str, Any]:
    technology = pinned.get("technology") or {}
    item = technology.get("items", {}).get(str(candidate.get("tech_id")))
    if not isinstance(item, dict):
        return {"ok": False, "reason": "production_target_missing"}
    observed_amount = normalize_number(item.get("level"))
    if observed_amount != int(candidate.get("level") or 0):
        if observed_amount is not None and observed_amount >= int(candidate.get("target_level") or 0):
            return {"ok": False, "skip": True, "reason": "production_already_satisfied"}
        return {"ok": False, "reason": "production_amount_changed", "observed_amount": observed_amount}
    if bool((technology.get("queue_busy") or {}).get("shipyard")):
        return {"ok": False, "reason": "production_queue_became_busy"}
    if not bool(item.get("can_upgrade")) and str(item.get("status") or "") != "on":
        return {"ok": False, "reason": "production_control_unavailable"}
    unit_costs = parse_costs(item.get("costs_raw"))
    if unit_costs is None and str(candidate.get("tech_id")) in PRODUCTION_SPECS:
        spec = PRODUCTION_SPECS[str(candidate.get("tech_id"))]
        unit_costs = {key: spec.get(key, 0) for key in RESOURCE_KEYS}
    expected_unit_costs = resource_vector(candidate.get("unit_costs") or {})
    if unit_costs is None or resource_vector(unit_costs) != expected_unit_costs:
        return {
            "ok": False,
            "reason": "production_unit_cost_changed",
            "observed_unit_costs": unit_costs,
        }
    expected_costs = resource_vector(candidate.get("costs") or {})
    if expected_costs != {key: expected_unit_costs[key] * int(candidate["amount"]) for key in RESOURCE_KEYS}:
        return {"ok": False, "reason": "production_total_cost_invalid"}
    capacities = plan.get("storage_capacities") or {}
    if any(normalize_number(capacities.get(key)) in {None, 0} for key in RESOURCE_KEYS):
        return {"ok": False, "reason": "storage_capacity_unknown"}
    if not SAFETY_POLICY.storage_cost_is_safe(expected_costs, resource_vector(capacities)):
        return {"ok": False, "reason": "storage_90_percent_limit"}
    resources = resource_vector(technology.get("resources") or {})
    for key in RESOURCE_KEYS:
        required = expected_costs[key] + int(reserve.get(key, 0) or 0)
        if resources[key] < required:
            return {"ok": False, "reason": "resource_or_watch_reserve_shortfall", "resource": key}
    return {"ok": True, "observed_amount": observed_amount, "costs": expected_costs, "resources": resources}


def verify_production(
    candidate: Dict[str, Any],
    execution: Dict[str, Any],
    after: Dict[str, Any],
    rates: Dict[str, int],
    now: Optional[int] = None,
) -> Dict[str, Any]:
    now = int(time.time() if now is None else now)
    item = after.get("items", {}).get(str(candidate.get("tech_id")))
    observed_amount = normalize_number(item.get("level")) if isinstance(item, dict) else None
    amount_advanced = observed_amount is not None and observed_amount >= int(candidate.get("target_level") or 0)
    queue_entries = (after.get("production_queue") or {}).get("entries", [])
    target_queued = any(
        str(entry.get("tech_id") or "") == str(candidate.get("tech_id"))
        and isinstance(entry.get("amount"), int)
        and entry["amount"] >= int(candidate.get("amount") or 0)
        for entry in queue_entries
        if isinstance(entry, dict)
    )
    if not target_queued and isinstance(item, dict):
        if item.get("status") == "active" or item.get("start_epoch") is not None or item.get("end_epoch") is not None:
            target_queued = True
    before = execution.get("resources_before")
    after_resources = after.get("resources")
    resource_checks: Dict[str, Any] = {}
    resources_ok = isinstance(before, dict) and isinstance(after_resources, dict)
    clicked_at = normalize_number(execution.get("clicked_at"))
    observation_seconds = max(30, now - clicked_at + 15) if clicked_at is not None else 30
    for key in RESOURCE_KEYS:
        expected = int(candidate.get("costs", {}).get(key, 0) or 0)
        if expected <= 0:
            resource_checks[key] = {"expected": expected, "checked": False}
            continue
        before_value = normalize_number(before.get(key)) if isinstance(before, dict) else None
        after_value = normalize_number(after_resources.get(key)) if isinstance(after_resources, dict) else None
        tolerance = math.ceil(max(0, int(rates.get(key, 0) or 0)) * observation_seconds / 3600) + 2
        observed = before_value - after_value if before_value is not None and after_value is not None else None
        matched = observed is not None and abs(observed - expected) <= tolerance
        resource_checks[key] = {"expected": expected, "observed": observed, "tolerance": tolerance, "matched": matched}
        resources_ok = resources_ok and matched
    action_evidence = amount_advanced or target_queued
    reasons: List[str] = []
    if not execution.get("success"):
        reasons.append(str(execution.get("reason") or "production_submit_failed"))
    if not action_evidence:
        reasons.append("production_target_not_queued_or_completed")
    if not resources_ok:
        reasons.append("resource_deduction_mismatch")
    return {
        "success": bool(execution.get("success") and action_evidence and resources_ok),
        "reasons": reasons,
        "evidence": {
            "observed_amount": observed_amount,
            "amount_advanced": amount_advanced,
            "target_queued": target_queued,
            "resource_checks": resource_checks,
        },
    }


def _fleet_mission_number(mission: str) -> int:
    return {"raid": 1, "transport": 3, "deploy": 4, "spy": 6, "colonize": 7, "expedition": 15}[mission]


def fleet_prepare_js(candidate: Dict[str, Any]) -> str:
    target = candidate["target"]
    mission_number = _fleet_mission_number(str(candidate["mission"]))
    raw_composition = candidate.get("ship_composition") or {
        str(candidate["ship_tech"]): int(candidate["ship_amount"]),
    }
    composition = {
        str(key): int(value)
        for key, value in dict(raw_composition).items()
    }
    composition_json = json.dumps(composition, ensure_ascii=False, sort_keys=True)
    tg = int(target["galaxy"])
    ts = int(target["system"])
    tp = int(target["position"])
    return f"""
    (function() {{
        var composition = {composition_json};
        var selected = [];
        document.querySelectorAll('#shipsForm li.technology[data-technology] input, #fleet1 li.technology[data-technology] input, input[name^="am"]').forEach(function(input) {{
            input.value = '0';
            ['input', 'change', 'blur', 'keyup'].forEach(function(name) {{
                input.dispatchEvent(new Event(name, {{bubbles: true}}));
            }});
        }});
        for (var tech in composition) {{
            if (!Object.prototype.hasOwnProperty.call(composition, tech)) continue;
            var ship = document.querySelector('li.technology[data-technology="' + tech + '"] input, input[name="am' + tech + '"]');
            if (!ship) return JSON.stringify({{success:false, mutation_submitted:false, reason:'fleet_ship_missing:' + tech}});
            ship.value = String(composition[tech]);
            ['input', 'change', 'blur', 'keyup'].forEach(function(name) {{
                ship.dispatchEvent(new Event(name, {{bubbles: true}}));
            }});
            selected.push(tech);
        }}
        if (selected.length === 0) return JSON.stringify({{success:false, mutation_submitted:false, reason:'fleet_composition_empty'}});
        var continue2 = document.querySelector('#continueToFleet2');
        if (!continue2) return JSON.stringify({{success:false, mutation_submitted:false, reason:'fleet_continue_2_missing'}});

        setTimeout(function() {{
            var btn2 = document.querySelector('#continueToFleet2');
            if (btn2) btn2.click();

            setTimeout(function() {{
                var g = document.getElementById('galaxy') || document.querySelector('input[name="galaxy"]');
                var s = document.getElementById('system') || document.querySelector('input[name="system"]');
                var p = document.getElementById('position') || document.querySelector('input[name="position"]');
                if (g && s && p) {{
                    g.value = '{tg}';
                    s.value = '{ts}';
                    p.value = '{tp}';
                    ['input', 'change', 'blur', 'keyup'].forEach(function(name) {{
                        g.dispatchEvent(new Event(name, {{bubbles: true}}));
                        s.dispatchEvent(new Event(name, {{bubbles: true}}));
                        p.dispatchEvent(new Event(name, {{bubbles: true}}));
                    }});
                }}
                setTimeout(function() {{
                    var mBtn = document.getElementById('missionButton{mission_number}') || document.querySelector('#missions a[data-mission="{mission_number}"]');
                    if (mBtn) mBtn.click();
                }}, 500);
            }}, 800);
        }}, 400);

        return JSON.stringify({{success:true, mutation_submitted:false, preparation_scheduled:true}});
    }})()
    """


def fleet_submit_js(candidate: Dict[str, Any]) -> str:
    target = candidate["target"]
    payload = candidate["payload"]
    mission_number = _fleet_mission_number(str(candidate["mission"]))
    tg = int(target["galaxy"])
    ts = int(target["system"])
    tp = int(target["position"])
    expected_composition = json.dumps(
        {
            str(key): int(value)
            for key, value in dict(candidate.get("ship_composition") or {
                str(candidate["ship_tech"]): int(candidate["ship_amount"]),
            }).items()
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"""
    (function() {{
        function value(selector) {{
            var el = document.querySelector(selector);
            var raw = el && (el.getAttribute('data-raw') || el.innerText) || '';
            var digits = raw.replace(/[^0-9]/g, '');
            return digits ? Number(digits) : 0;
        }}
        var galaxy = document.querySelector('#galaxy, input[name="galaxy"]');
        var system = document.querySelector('#system, input[name="system"]');
        var position = document.querySelector('#position, input[name="position"]');
        if (!galaxy || !system || !position) {{
            return JSON.stringify({{success:false, mutation_submitted:false, reason:'fleet_target_inputs_missing'}});
        }}
        if (Number(galaxy.value) !== {tg}) {{
            galaxy.value = '{tg}';
            ['input','change','blur','keyup'].forEach(function(n) {{ galaxy.dispatchEvent(new Event(n, {{bubbles:true}})); }});
        }}
        if (Number(system.value) !== {ts}) {{
            system.value = '{ts}';
            ['input','change','blur','keyup'].forEach(function(n) {{ system.dispatchEvent(new Event(n, {{bubbles:true}})); }});
        }}
        if (Number(position.value) !== {tp}) {{
            position.value = '{tp}';
            ['input','change','blur','keyup'].forEach(function(n) {{ position.dispatchEvent(new Event(n, {{bubbles:true}})); }});
        }}

        var mBtn = document.getElementById('missionButton{mission_number}') || document.querySelector('#missions a[data-mission="{mission_number}"]');
        if (mBtn) {{
            mBtn.click();
        }}

        var payload = {{metal:{int(payload['metal'])}, crystal:{int(payload['crystal'])}, deuterium:{int(payload['deuterium'])}}};
        if (payload.metal > 0 || payload.crystal > 0 || payload.deuterium > 0) {{
            for (var key of ['metal','crystal','deuterium']) {{
                var field = document.querySelector('#' + key + ', input[name="' + key + '"]');
                if (field) {{
                    field.value = payload[key];
                    ['input','change','blur','keyup'].forEach(function(name) {{ field.dispatchEvent(new Event(name, {{bubbles:true}})); }});
                }} else if (payload[key] !== 0) {{
                    return JSON.stringify({{success:false, mutation_submitted:false, reason:'fleet_payload_input_missing', resource:key}});
                }}
            }}
        }}

        var send = document.getElementById('sendFleet');
        if (!send || send.disabled || send.classList.contains('off')) {{
            return JSON.stringify({{success:false, mutation_submitted:false, reason:'fleet_send_missing_or_disabled', className: send ? send.className : 'null'}});
        }}
        var expectedComposition = {expected_composition};
        var selectedComposition = {{}};
        function addSelected(tech, rawAmount) {{
            var amount = Number(rawAmount);
            if (String(tech || '').match(/^\\d+$/) && Number.isInteger(amount) && amount > 0) selectedComposition[String(tech)] = amount;
        }}
        var selectedSource = typeof shipsToSend !== 'undefined' ? shipsToSend : null;
        if (Array.isArray(selectedSource)) {{
            selectedSource.forEach(function(item) {{
                if (Array.isArray(item)) addSelected(item[0], item[1]);
                else if (item && typeof item === 'object') addSelected(item.technologyId || item.techId || item.shipId || item.id, item.amount !== undefined ? item.amount : item.count);
            }});
        }} else if (selectedSource && typeof selectedSource === 'object') {{
            Object.keys(selectedSource).forEach(function(key) {{
                var value = selectedSource[key];
                addSelected(key, value && typeof value === 'object' ? (value.amount !== undefined ? value.amount : value.count) : value);
            }});
        }}
        if (Object.keys(selectedComposition).length === 0) {{
            document.querySelectorAll('#shipsForm li.technology[data-technology] input, #fleet1 li.technology[data-technology] input, input[name^="am"]').forEach(function(input) {{
                var holder = input.closest('li.technology[data-technology]');
                var nameMatch = String(input.getAttribute('name') || '').match(/^am(\\d+)$/);
                var tech = holder ? holder.getAttribute('data-technology') : (nameMatch ? nameMatch[1] : '');
                addSelected(tech, input.value || 0);
            }});
        }}
        if (JSON.stringify(Object.keys(selectedComposition).sort().map(function(key) {{ return [key, selectedComposition[key]]; }})) !==
            JSON.stringify(Object.keys(expectedComposition).sort().map(function(key) {{ return [key, expectedComposition[key]]; }}))) {{
            return JSON.stringify({{success:false, mutation_submitted:false, reason:'fleet_composition_mismatch', selected:selectedComposition}});
        }}
        var resourcesBefore = {{
            metal: value('#resources_metal'),
            crystal: value('#resources_crystal'),
            deuterium: value('#resources_deuterium')
        }};

        send.click();

        return JSON.stringify({{
            success: true,
            mutation_submitted: true,
            action_id: {json.dumps(candidate['action_id'])},
            target: {json.dumps(_coordinate_text(target))},
            mission: {json.dumps(candidate['mission'])},
            resources_before: resourcesBefore,
            clicked_at: Math.floor(Date.now() / 1000)
        }});
    }})()
    """


def galaxy_spy_shortcut_js(candidate: Mapping[str, Any]) -> str:
    """Use the Galaxy row's native mini-fleet action for one espionage probe."""
    if str(candidate.get("mission")) != "spy" or int(candidate.get("ship_amount", 0) or 0) != 1:
        raise RuntimeError("Galaxy 快捷偵察只允許一架間諜探測機。")
    target = candidate["target"]
    galaxy = int(target["galaxy"])
    system = int(target["system"])
    position = int(target["position"])
    return f"""
    (function() {{
        var rows = Array.from(document.querySelectorAll('#galaxyContent tr.ctContentRow, .galaxyRow.ctContentRow'));
        var row = rows.find(function(item, index) {{
            var raw = item.getAttribute('data-position') || (item.id || '').replace('galaxyRow', '').trim() || String(index + 1);
            return Number(raw) === {position};
        }});
        if (!row) return JSON.stringify({{success:false,mutation_submitted:false,reason:'galaxy_spy_target_row_missing'}});

        var text = (row.innerText || '').replace(/\\s+/g, ' ').trim();
        var classes = row.className || '';
        var destroyed = text.includes('已毀滅') || text.toLowerCase().includes('destroyed') || text.toLowerCase().includes('détruite');
        var vacation = classes.includes('vacation_filter') || text.includes('(v)');
        var inactive = classes.includes('inactive_filter') || classes.includes('longinactive_filter') || text.includes('(i)') || text.includes('(I)');
        if (!inactive || destroyed || vacation)
            return JSON.stringify({{success:false,mutation_submitted:false,reason:'galaxy_spy_target_no_longer_safe'}});

        var quick = row.querySelector('a.espionage, button.espionage, [data-mission="6"], [data-action="spy"], [data-action="espionage"], [onclick*="sendShips(6"]');
        if (!quick) {{
            var icon = row.querySelector('.icon_eye, .icon_eye_blue, [class*="espionage"]');
            quick = icon ? icon.closest('a,button') : null;
        }}
        if (!quick || quick.disabled || quick.classList.contains('disabled') || quick.getAttribute('aria-disabled') === 'true')
            return JSON.stringify({{success:false,mutation_submitted:false,reason:'galaxy_spy_shortcut_unavailable'}});
        var dispatched = false;
        try {{
            if (typeof window.sendShips === 'function') {{
                window.sendShips(6, {galaxy}, {system}, {position}, 1, 1);
                dispatched = true;
            }} else if (typeof sendShips === 'function') {{
                sendShips(6, {galaxy}, {system}, {position}, 1, 1);
                dispatched = true;
            }} else if (quick) {{
                quick.click();
                try {{
                    quick.dispatchEvent(new MouseEvent('click', {{bubbles: true, cancelable: true}}));
                }} catch (e) {{}}
                dispatched = true;
            }}
        }} catch (error) {{
            return JSON.stringify({{success:false,mutation_submitted:false,reason:'galaxy_spy_shortcut_error',detail:String(error)}});
        }}
        if (!dispatched)
            return JSON.stringify({{success:false,mutation_submitted:false,reason:'galaxy_sendShips_unavailable'}});

        return JSON.stringify({{
            success:true,
            mutation_submitted:true,
            action_id:{json.dumps(str(candidate.get('action_id') or ''))},
            target:{json.dumps(_coordinate_text(target))},
            mission:'spy',
            ship_tech:'210',
            ship_amount:1,
            dispatch_path:'galaxy_quick_spy',
            clicked_at:Math.floor(Date.now()/1000)
        }});
    }})()
    """


def execute_galaxy_spy_shortcut(candidate: Mapping[str, Any], planet_id: int) -> Dict[str, Any]:
    """Navigate directly to the target Galaxy system and invoke its one-probe shortcut."""
    target = candidate["target"]
    result = execute_in_game_tab(
        checked_js(galaxy_spy_shortcut_js(candidate), planet_id),
        target_url=game_url(
            "galaxy",
            planet_id,
            galaxy=int(target["galaxy"]),
            system=int(target["system"]),
        ),
        wait_after_nav=2.0,
    )
    if not isinstance(result, dict):
        raise RuntimeError(f"galaxy 快捷偵察沒有回傳結構化資料：{result}")
    if result.get("safety_stop"):
        raise RuntimeError(f"安全守衛已停止：{result.get('reason', '未知原因')}")
    return result


def _read_target_for_fleet_candidate(candidate: Mapping[str, Any], origin_planet_id: int) -> Dict[str, Any]:
    mission = str(candidate["mission"])
    target = candidate["target"]
    if mission in {"transport", "deploy"}:
        coords = _coordinate_text(target)
        owned = [item for item in read_owned_planets() if str(item.get("coords") or "") == coords]
        if len(owned) != 1 or not str(owned[0].get("id") or "").isdigit():
            raise RuntimeError("運輸／部署目標不再唯一對應自有星球。")
        target_id = int(owned[0]["id"])
        supplies = read_technology_list("supplies", target_id)
        return {
            "target_evidence": {
                "owned_planet": True,
                "target_planet_id": str(target_id),
                "empty": False,
                "inactive": False,
                "destroyed": False,
                "vacation": False,
            },
            "target_resources": _known_resource_vector(supplies.get("resources"), "target resources"),
            "target_storage_capacities": _storage_capacities_from_supplies(supplies),
        }
    elif mission == "expedition":
        return {
            "target_evidence": {
                "owned_planet": False,
                "empty": True,
                "inactive": False,
                "destroyed": False,
                "vacation": False,
                "galaxy_raw": "expedition slot 16",
            },
            "target_resources": {key: 0 for key in RESOURCE_KEYS},
            "target_storage_capacities": {key: 1 for key in RESOURCE_KEYS},
        }
    observed = read_galaxy_target_evidence(origin_planet_id, target)
    evidence = {
        "owned_planet": bool(observed.get("owned_planet")),
        "empty": bool(observed.get("empty")),
        "inactive": bool(observed.get("inactive")),
        "destroyed": bool(observed.get("destroyed")),
        "vacation": bool(observed.get("vacation")),
        "galaxy_raw": str(observed.get("raw") or ""),
    }
    if mission == "raid":
        evidence.update(_local_raid_evidence(target))
    return {
        "target_evidence": evidence,
        "target_resources": {key: 0 for key in RESOURCE_KEYS},
        "target_storage_capacities": {key: 1 for key in RESOURCE_KEYS},
    }


def read_fleet_precondition(candidate: Mapping[str, Any], planet_id: int) -> Dict[str, Any]:
    fn = _get_dep("read_fleet_precondition")
    if fn and fn is not read_fleet_precondition and (hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value")):
        return fn(candidate, planet_id)
    fleet_state = read_fleet_state(planet_id)
    target_state = _read_target_for_fleet_candidate(candidate, planet_id)
    origin_supplies = read_technology_list("supplies", planet_id)
    return {
        "planet_id": str(fleet_state.get("planet_id") or planet_id),
        "fleet_state": fleet_state,
        "origin_storage_capacities": _storage_capacities_from_supplies(origin_supplies),
        **target_state,
    }


def prevalidate_fleet_dispatch(
    candidate: Dict[str, Any],
    pinned: Dict[str, Any],
    plan: Dict[str, Any],
    reserve: Dict[str, int],
    constants: AccountConstants,
) -> Dict[str, Any]:
    fleet_state = pinned.get("fleet_state")
    if not isinstance(fleet_state, dict):
        return {"ok": False, "reason": "fleet_state_missing"}
    if str(pinned.get("planet_id")) != str(plan.get("planet_id")):
        return {"ok": False, "reason": "fleet_planet_pin_mismatch"}
    slots = fleet_state.get("fleet_slots")
    if not isinstance(slots, dict) or slots.get("known") is not True:
        return {"ok": False, "reason": "fleet_slots_unknown"}
    confirmed_ships = dict(candidate.get("ships_before") or {})
    observed_ships = dict(fleet_state.get("ships") or {})
    if confirmed_ships != observed_ships:
        return {
            "ok": False,
            "reason": "stationed_ship_state_changed",
            "confirmed": confirmed_ships,
            "observed": observed_ships,
        }
    live = dict(candidate)
    live["ships_before"] = observed_ships
    live["fleet_slots"] = {"free": slots.get("free"), "used": slots.get("used"), "total": slots.get("total")}
    if str(candidate.get("mission")) == "expedition":
        expedition_slots = fleet_state.get("expedition_slots")
        if not isinstance(expedition_slots, dict) or expedition_slots.get("known") is not True:
            return {"ok": False, "reason": "expedition_slots_unknown"}
        live["expedition_slots"] = {
            "free": expedition_slots.get("free"),
            "used": expedition_slots.get("used"),
            "total": expedition_slots.get("total"),
        }
        preset_name = candidate.get("preset_name")
        if preset_name:
            try:
                live_preset = resolve_expedition_preset(
                    fleet_state.get("expedition_templates"),
                    str(preset_name),
                )
            except RuntimeError as exc:
                return {"ok": False, "reason": f"expedition_preset_invalid: {exc}"}
            if dict(live_preset["ships"]) != dict(candidate.get("ship_composition") or {}):
                return {"ok": False, "reason": "expedition_preset_changed"}
    live["target_evidence"] = dict(pinned.get("target_evidence") or {})
    live["target_resources"] = dict(pinned.get("target_resources") or {})
    live["target_storage_capacities"] = dict(pinned.get("target_storage_capacities") or {})
    live_resources = _known_resource_vector(fleet_state.get("resources"), "live origin resources")
    live_plan = {
        **plan,
        "resources": live_resources,
        "spendable_resources": {
            key: max(0, live_resources[key] - int(reserve.get(key, 0) or 0))
            for key in RESOURCE_KEYS
        },
        "storage_capacities": dict(pinned.get("origin_storage_capacities") or {}),
    }
    try:
        _get_dep('assess_workflow_candidate', assess_workflow_candidate)(
            live,
            live_plan,
            constants=constants,
        )
    except RuntimeError as exc:
        return {"ok": False, "reason": f"fleet_policy_blocked: {exc}"}
    payload = resource_vector(live.get("payload") or {})
    for key in RESOURCE_KEYS:
        if live_resources[key] < payload[key] + int(reserve.get(key, 0) or 0):
            return {"ok": False, "reason": "resource_or_watch_reserve_shortfall", "resource": key}
    return {
        "ok": True,
        "fleet_state": fleet_state,
        "target_evidence": live["target_evidence"],
        "target_resources": live["target_resources"],
    }


def read_fleet_postcondition(candidate: Mapping[str, Any], planet_id: int) -> Dict[str, Any]:
    fn = _get_dep("read_fleet_postcondition")
    if fn and fn is not read_fleet_postcondition and (hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value")):
        return fn(candidate, planet_id)
    time.sleep(3.5)
    return {
        "planet_id": str(planet_id),
        "fleet_state": read_fleet_state(planet_id),
        "events": read_events_state(planet_id),
    }


def read_technology_postcondition(selected: Mapping[str, Any], selected_planet_id: int) -> Dict[str, Any]:
    fn = _get_dep("read_technology_postcondition")
    if fn and fn is not read_technology_postcondition and (hasattr(fn, "assert_called") or hasattr(fn, "_mock_return_value")):
        return fn(selected, selected_planet_id)
    time.sleep(3.0)
    return read_technology_list(str(selected.get("component") or "supplies"), selected_planet_id)



def verify_fleet_dispatch(
    candidate: Dict[str, Any],
    execution: Dict[str, Any],
    after: Dict[str, Any],
) -> Dict[str, Any]:
    raw_composition = candidate.get("ship_composition") or {
        str(candidate.get("ship_tech")): int(candidate.get("ship_amount") or 0),
    }
    composition = {
        str(key): int(value)
        for key, value in dict(raw_composition).items()
    }
    before_ships = dict(candidate.get("ships_before") or {})
    after_ships = dict(((after.get("fleet_state") or {}).get("ships") or {}))
    checked_techs = sorted(set(str(key) for key in before_ships) | set(composition))
    ship_deltas = {
        tech: {
            "requested": int(composition.get(tech, 0) or 0),
            "before": int(before_ships.get(tech, 0) or 0),
            "after": int(after_ships.get(tech, 0) or 0),
            "deducted": int(before_ships.get(tech, 0) or 0) - int(after_ships.get(tech, 0) or 0),
            "observed_after": tech in after_ships,
        }
        for tech in checked_techs
    }
    ship_deducted = bool(ship_deltas) and all(
        item["observed_after"] and item["deducted"] == item["requested"]
        for item in ship_deltas.values()
    )
    coordinate = _coordinate_text(candidate["target"])
    mission = str(candidate["mission"])
    mission_keywords = {
        "transport": ("transport", "運輸"),
        "deploy": ("deployment", "deploy", "部署", "駐留"),
        "colonize": ("colonize", "colonisation", "殖民"),
        "spy": ("espionage", "spy", "間諜", "偵察", "6"),
        "raid": ("attack", "攻擊", "1"),
        "expedition": ("expedition", "外太空", "遠征", "15"),
    }[mission]

    def matching_event(item: Mapping[str, Any]) -> bool:
        text = str(item.get("text") or "")
        coordinates = " ".join((
            text,
            str(item.get("origin_coords") or ""),
            str(item.get("dest_coords") or ""),
        ))
        mission_matches = (
            str(item.get("mission_type") or "") == str(_fleet_mission_number(mission))
            or any(keyword.lower() in text.lower() for keyword in mission_keywords)
        )
        return coordinate in coordinates and mission_matches

    event_items = [
        item for item in (after.get("events") or {}).get("events", [])
        if isinstance(item, Mapping)
    ]
    event_texts = [str(item.get("text") or "") for item in event_items]
    event_match = any(matching_event(item) for item in event_items)
    expedition_slot_advanced = True
    if mission == "expedition":
        before_expedition = candidate.get("expedition_slots") or {}
        after_expedition = (after.get("fleet_state") or {}).get("expedition_slots") or {}
        before_used = before_expedition.get("used")
        after_used = after_expedition.get("used")
        expedition_slot_advanced = (
            isinstance(before_used, int) and not isinstance(before_used, bool)
            and isinstance(after_used, int) and not isinstance(after_used, bool)
            and after_expedition.get("known") is True
            and after_used == before_used + 1
        )
    if not event_match and execution.get("success") and ship_deducted:
        time.sleep(3.0)
        target_planet = int(candidate.get("planet_id", 0) or after.get("planet_id", 0))
        if target_planet > 0:
            retry_events = read_events_state(target_planet)
            retry_items = [
                item for item in (retry_events.get("events") or [])
                if isinstance(item, Mapping)
            ]
            retry_texts = [str(item.get("text") or "") for item in retry_items]
            if any(matching_event(item) for item in retry_items):
                event_match = True
                event_texts = retry_texts
                if isinstance(after.get("events"), dict):
                    after["events"]["events"] = retry_events.get("events", [])
    reasons: List[str] = []
    if not execution.get("success"):
        reasons.append(str(execution.get("reason") or "fleet_submit_failed"))
    if not ship_deducted:
        reasons.append("stationed_ship_count_not_deducted")
    if not event_match:
        reasons.append("target_mission_event_not_found")
    if not expedition_slot_advanced:
        reasons.append("expedition_slot_not_advanced")
    return {
        "success": bool(execution.get("success") and ship_deducted and event_match and expedition_slot_advanced),
        "reasons": reasons,
        "evidence": {
            "ship_composition": composition,
            "ship_deltas": ship_deltas,
            "ship_deducted": ship_deducted,
            "target": coordinate,
            "event_match": event_match,
            "expedition_slot_advanced": expedition_slot_advanced,
            "events": event_texts,
        },
    }


def verify_applied_action(
    candidate: Dict[str, Any],
    click_result: Dict[str, Any],
    verification: Dict[str, Any],
    rates: Dict[str, int],
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Require target-specific state evidence and a matching resource deduction."""
    now = int(now if now is not None else time.time())
    tech_id = str(candidate.get("tech_id"))
    verified_item = verification.get("items", {}).get(tech_id)
    if not isinstance(verified_item, dict):
        verified_item = {}

    target_level = int(candidate.get("target_level") or (int(candidate.get("level") or 0) + 1))
    verified_level = normalize_number(verified_item.get("level"))
    end_epoch = normalize_number(verified_item.get("end_epoch"))
    level_advanced = verified_level is not None and verified_level >= target_level
    target_timed = end_epoch is not None and end_epoch > now
    queue_name = str(candidate.get("queue") or "")
    queue_started = bool(verification.get("queue_busy", {}).get(queue_name))
    button_locked = "can_upgrade" in verified_item and not bool(verified_item.get("can_upgrade"))
    target_status = str(verified_item.get("status") or "").lower()
    target_status_evidence = target_status in {"active", "queued"} or end_epoch is not None
    action_evidence = level_advanced or target_timed or (
        queue_started and (button_locked or target_status_evidence)
    )

    before_raw = click_result.get("resources_before")
    after_raw = verification.get("resources")
    resource_checks: Dict[str, Any] = {}
    resources_ok = isinstance(before_raw, dict) and isinstance(after_raw, dict)
    clicked_at = normalize_number(click_result.get("clicked_at"))
    observation_seconds = max(1, now - clicked_at + 5) if clicked_at is not None else 30
    for key in RESOURCE_KEYS:
        expected = int(candidate.get("costs", {}).get(key, 0) or 0)
        if expected <= 0:
            resource_checks[key] = {"expected": expected, "checked": False}
            continue
        before = normalize_number(before_raw.get(key)) if isinstance(before_raw, dict) else None
        after = normalize_number(after_raw.get(key)) if isinstance(after_raw, dict) else None
        rate = max(0, int(rates.get(key, 0) or 0))
        tolerance = math.ceil(rate * observation_seconds / 3600) + 2
        observed = before - after if before is not None and after is not None else None
        matched = observed is not None and abs(observed - expected) <= tolerance
        resource_checks[key] = {
            "expected": expected,
            "observed": observed,
            "tolerance": tolerance,
            "matched": matched,
        }
        resources_ok = resources_ok and matched

    reasons: List[str] = []
    if not click_result.get("success"):
        reasons.append(str(click_result.get("reason") or "click_failed"))
    if not verified_item:
        reasons.append("target_missing_after_click")
    if not action_evidence:
        reasons.append("no_target_level_or_queue_evidence")
    if not resources_ok:
        reasons.append("resource_deduction_mismatch")
    return {
        "success": bool(click_result.get("success") and verified_item and action_evidence and resources_ok),
        "reasons": reasons,
        "evidence": {
            "target_level": target_level,
            "verified_level": verified_level,
            "level_advanced": level_advanced,
            "target_timed": target_timed,
            "queue": queue_name,
            "queue_started": queue_started,
            "button_locked": button_locked,
            "target_status": target_status,
            "target_status_evidence": target_status_evidence,
            "resource_checks": resource_checks,
        },
    }


def prevalidate_planned_action(
    candidate: Dict[str, Any],
    pinned: Dict[str, Any],
    plan: Dict[str, Any],
    reserve: Dict[str, int],
) -> Dict[str, Any]:
    """Repeat level, queue, cost, resource, storage, and energy checks before click."""
    technology = pinned.get("technology") or {}
    header = pinned.get("header") or {}
    item = technology.get("items", {}).get(str(candidate.get("tech_id")))
    if not isinstance(item, dict):
        return {"ok": False, "reason": "target_missing_during_prevalidation"}
    observed_level = normalize_number(item.get("level"))
    target_level = int(candidate.get("target_level") or 0)
    planned_level = int(candidate.get("level") or 0)
    if observed_level is not None and observed_level >= target_level:
        return {"ok": False, "skip": True, "reason": "target_already_satisfied", "observed_level": observed_level}
    if observed_level != planned_level:
        return {"ok": False, "reason": "target_level_changed", "observed_level": observed_level}
    queue = str(candidate.get("queue") or "")
    if bool((technology.get("queue_busy") or {}).get(queue)):
        return {"ok": False, "reason": "queue_became_busy"}
    if not item.get("can_upgrade"):
        return {"ok": False, "reason": "upgrade_control_unavailable"}

    expected_costs = resource_vector(candidate.get("costs") or {})
    observed_costs = parse_costs(item.get("costs_raw"))
    if observed_costs is None and candidate.get("operation", "upgrade") == "upgrade":
        observed_costs, _ = calculate_technology_cost(str(candidate.get("tech_id")), target_level)
    if observed_costs is None or resource_vector(observed_costs) != expected_costs:
        return {
            "ok": False,
            "reason": "cost_revalidation_mismatch",
            "expected_costs": expected_costs,
            "observed_costs": observed_costs,
        }
    capacities = plan.get("storage_capacities") or {}
    if any(normalize_number(capacities.get(key)) in {None, 0} for key in RESOURCE_KEYS):
        return {"ok": False, "reason": "storage_capacity_unknown"}
    if candidate.get("section") != "research":
        if not SAFETY_POLICY.storage_cost_is_safe(expected_costs, resource_vector(capacities)):
            return {"ok": False, "reason": "storage_90_percent_limit"}
    live_resources = resource_vector(technology.get("resources") or header.get("resources") or {})
    for resource in RESOURCE_KEYS:
        required = expected_costs[resource] + int(reserve.get(resource, 0) or 0)
        if live_resources[resource] < required:
            return {
                "ok": False,
                "reason": "resource_or_watch_reserve_shortfall",
                "resource": resource,
                "available": live_resources[resource],
                "required": required,
            }
    live_energy = parse_signed_number(header.get("energy"))
    energy_delta = candidate.get("energy_delta")
    requires_energy = (
        candidate.get("operation", "upgrade") == "upgrade" and candidate.get("section") != "research"
    ) or (
        candidate.get("operation") == "lifeform_upgrade" and candidate.get("component") == "lfbuildings"
    )
    if requires_energy and not SAFETY_POLICY.energy_is_safe(
        live_energy, int(energy_delta) if energy_delta is not None else None
    ):
        return {
            "ok": False,
            "reason": "energy_below_safety_floor_or_unknown",
            "energy": live_energy,
            "energy_delta": energy_delta,
        }
    return {
        "ok": True,
        "observed_level": observed_level,
        "costs": observed_costs,
        "resources": live_resources,
        "energy": live_energy,
    }


def command_apply(args: argparse.Namespace) -> Dict[str, Any]:
    require_confirmed_mutation(args)
    if not getattr(args, "mutation_lock_held", False):
        locked_args = vars(args).copy()
        locked_args["mutation_lock_held"] = True
        with WorkflowJournal(_workflow_dir()).mutation_lock():
            return _command_apply_body(argparse.Namespace(**locked_args))
    return _command_apply_body(args)


def _command_apply_body(args: argparse.Namespace) -> Dict[str, Any]:
    plan = _get_dep('require_active_plan', require_active_plan)(args.plan_id, getattr(args, "run_id", None))
    if str(args.planet_id) != str(plan.get("planet_id")):
        raise RuntimeError("--planet-id 與 plan 綁定星球不符。")
    if int(plan.get("action_count", 0)) >= MAX_ACTIONS_PER_PLAN:
        raise RuntimeError("此計畫已達每輪 5 個動作上限。")
    candidate = next((item for item in plan.get("candidates", []) if item.get("action_id") == args.action_id), None)
    if candidate is None:
        raise RuntimeError("action_id 不在計畫中。")
    operation = str(candidate.get("operation", "upgrade"))
    if operation == "upgrade" and candidate.get("energy_safe") is not True:
        raise RuntimeError("action_id 能源影響尚未通過安全驗證。")
    if operation != "upgrade" and candidate.get("can_apply") is not True:
        raise RuntimeError("action_id 未被 confirmed live state 確認為可執行。")
    if operation != "upgrade":
        constants = load_account_constants(getattr(args, "constants", DEFAULT_CONSTANTS_PATH))
        _get_dep('assess_workflow_candidate', assess_workflow_candidate)(
            candidate,
            plan,
            constants=constants,
        )
    reserve = {key: 0 for key in RESOURCE_KEYS} if candidate["action_id"] == plan.get("watch_action_id") else resource_vector(plan.get("watch_costs", {}))
    time.sleep(random.uniform(5, 10))
    planet_id = int(plan["planet_id"])

    def pin_and_read(selected: Dict[str, Any], selected_planet_id: int) -> Dict[str, Any]:
        return {
            "planet_id": str(selected_planet_id),
            "technology": read_technology_list(selected["component"], selected_planet_id),
            "header": read_header_snapshot(selected["component"], selected_planet_id),
        }

    if operation == "cancel_building":
        callbacks = PlannedMutationCallbacks(
            pin_and_read=pin_and_read,
            prevalidate=prevalidate_cancel_building,
            execute=lambda selected, selected_planet_id: execute_checked_component_result(
                "supplies", selected_planet_id, cancel_building_action_js(selected)
            ),
            read_postcondition=lambda _selected, selected_planet_id: read_technology_list(
                "supplies", selected_planet_id
            ),
            verify_postcondition=verify_cancel_building,
        )
    elif operation == "produce":
        callbacks = PlannedMutationCallbacks(
            pin_and_read=pin_and_read,
            prevalidate=lambda selected, pinned: prevalidate_production(selected, pinned, plan, reserve),
            execute=lambda selected, selected_planet_id: execute_checked_component_followup(
                selected["component"],
                selected_planet_id,
                production_open_detail_js(selected),
                production_submit_js(selected, reserve),
                wait_after_js=2.0,
            ),
            read_postcondition=lambda selected, selected_planet_id: read_technology_list(
                selected["component"], selected_planet_id
            ),
            verify_postcondition=lambda selected, execution, after: verify_production(
                selected, execution, after, plan.get("rates", {})
            ),
        )
    elif operation == "fleet_dispatch":
        use_galaxy_spy_shortcut = (
            str(candidate.get("mission")) == "spy"
            and int(candidate.get("ship_amount", 0) or 0) == 1
        )
        callbacks = PlannedMutationCallbacks(
            pin_and_read=lambda *a, **kw: _get_dep("read_fleet_precondition", read_fleet_precondition)(*a, **kw),
            prevalidate=lambda selected, pinned: prevalidate_fleet_dispatch(
                selected,
                pinned,
                plan,
                reserve,
                constants,
            ),
            execute=(
                (lambda *a, **kw: _get_dep("execute_galaxy_spy_shortcut", execute_galaxy_spy_shortcut)(*a, **kw))
                if use_galaxy_spy_shortcut
                else lambda selected, selected_planet_id: _get_dep("execute_checked_component_followup", execute_checked_component_followup)(
                    "fleetdispatch",
                    selected_planet_id,
                    fleet_prepare_js(selected),
                    fleet_submit_js(selected),
                    wait_after_js=6.0,
                )
            ),
            read_postcondition=lambda *a, **kw: _get_dep("read_fleet_postcondition", read_fleet_postcondition)(*a, **kw),
            verify_postcondition=verify_fleet_dispatch,
        )
    else:
        callbacks = PlannedMutationCallbacks(
            pin_and_read=pin_and_read,
            prevalidate=lambda selected, pinned: prevalidate_planned_action(selected, pinned, plan, reserve),
            execute=lambda selected, selected_planet_id: execute_checked_component_result(
                selected["component"], selected_planet_id, apply_action_js(selected, reserve)
            ),
            read_postcondition=lambda *a, **kw: _get_dep("read_technology_postcondition", read_technology_postcondition)(*a, **kw),
            verify_postcondition=lambda selected, execution, after: verify_applied_action(
                selected, execution, after, plan.get("rates", {})
            ),
        )
    action_result = _get_dep('apply_planned_action_atom', _atoms.apply_planned_action_atom)(candidate, planet_id, callbacks)
    typed_result = {**action_result.to_dict(), "success": action_result.status == ActionStatus.APPLIED}
    if action_result.status == ActionStatus.UNCERTAIN:
        plan["status"] = "uncertain"
        plan["last_action_attempt"] = {
            "action_id": candidate["action_id"],
            "action_result": typed_result,
        }
        atomic_write_json(_plan_file(), plan)
        print_command_output(args, typed_result, f"action {candidate['action_id']}: uncertain ({action_result.reason})")
        return typed_result
    if action_result.status in {ActionStatus.BLOCKED, ActionStatus.SKIPPED}:
        plan["last_action_attempt"] = {"action_id": candidate["action_id"], "action_result": typed_result}
        atomic_write_json(_plan_file(), plan)
        print_command_output(
            args,
            typed_result,
            f"action {candidate['action_id']}: {action_result.status.value} ({action_result.reason})",
        )
        return typed_result

    postcondition = typed_result["evidence"]["postcondition"]
    verification = typed_result["evidence"]["post_state"]
    if operation == "cancel_building":
        plan["action_count"] = int(plan.get("action_count", 0)) + 1
        plan["expires_at"] = int(time.time()) + PLAN_TTL_SECONDS
        next_wake_epoch = int(time.time()) + 120
        plan["next_wake"] = next_wake_epoch
        plan["last_action"] = {
            "action_id": candidate["action_id"],
            "action_result": typed_result,
            "postcondition": postcondition,
        }
        write_next_wake(next_wake_epoch)
        atomic_write_json(_plan_file(), plan)
        output = {
            **typed_result,
            "action_count": plan["action_count"],
            "next_wake": next_wake_epoch,
            "postcondition": postcondition,
        }
        print_command_output(
            args,
            output,
            f"action {candidate['action_id']}: applied; building queue cleared",
        )
        return output
    verified_item = verification.get("items", {}).get(candidate["tech_id"], {})
    plan["action_count"] = int(plan.get("action_count", 0)) + 1
    plan["expires_at"] = int(time.time()) + PLAN_TTL_SECONDS
    plan["last_action"] = {
        "action_id": candidate["action_id"],
        "action_result": typed_result,
        "verification": verified_item,
        "postcondition": postcondition,
    }
    if candidate["section"] == "supplies":
        mark_rates_stale(int(plan["planet_id"]))

    end_epoch = verified_item.get("end_epoch")
    if not end_epoch:
        for attr_name, attr_val in verified_item.get("debug", {}).get("attributes", []):
            if attr_name == "data-end" and str(attr_val).isdigit():
                end_epoch = int(attr_val)
                break

    if end_epoch and end_epoch > int(time.time()):
        next_wake_epoch = end_epoch + 120
    else:
        duration_sec = candidate.get("estimated_duration") or estimate_action_duration(candidate["section"], candidate["costs"])
        next_wake_epoch = int(time.time()) + duration_sec + 120

    write_next_wake(next_wake_epoch)
    plan["next_wake"] = next_wake_epoch

    atomic_write_json(_plan_file(), plan)
    output = {
        **typed_result,
        "action_count": plan["action_count"],
        "next_wake": next_wake_epoch,
        "verification": verified_item,
        "postcondition": postcondition,
    }
    print_command_output(
        args,
        output,
        f"action {candidate['action_id']}: applied; next wake {next_wake_epoch}",
    )
    return output


def _workflow_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    plan = WorkflowPlan.from_dict(state["plan"])
    return {
        "workflow_id": state["workflow_id"],
        "status": state["status"],
        "state_certainty": state["state_certainty"],
        "in_flight_step_id": state.get("in_flight_step_id"),
        "active_run_id": state["active_run_id"],
        "plan_hash": state["plan_hash"],
        "confirmed_plan_id": plan.confirmed_plan_id,
        "expires_at": plan.expires_at,
        "steps_total": len(plan.steps),
        "steps_finished": len(state.get("results", [])),
        "steps": [
            {
                "step_id": step.step_id,
                "kind": step.kind.value,
                "action_id": step.action_id,
                "planet_id": step.planet_id,
            }
            for step in plan.steps
        ],
        "results": state.get("results", []),
    }


def command_workflow_plan(args: argparse.Namespace) -> Dict[str, Any]:
    """Turn one strict typed Intent into an immutable, journaled WorkflowPlan."""
    require_run_lease(args.run_id)
    raw_intent = load_json_file(args.intent_file)
    if raw_intent is None:
        raise RuntimeError("Intent 檔案不存在、不是 JSON object，或 JSON 無效。")
    try:
        intent = Intent.from_dict(raw_intent)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Intent schema 無效：{exc}") from exc
    confirmed_plan = require_active_plan(intent.confirmed_plan_id, args.run_id)
    strategy = load_strategy_policy(args.strategy)
    constants = load_account_constants(getattr(args, "constants", DEFAULT_CONSTANTS_PATH))
    workflow_plan = build_workflow_plan(intent, confirmed_plan, args.run_id, strategy, constants)
    state = WorkflowJournal(_workflow_dir()).create(workflow_plan)
    return _workflow_summary(state)


def command_execute_decision(args: argparse.Namespace) -> None:
    """Execute one minimal patrol intent in-process without Subprocess loop."""
    try:
        if getattr(args, "kind", "apply") == "apply" and not getattr(args, "confirm", False):
            raise DecisionValidationError("confirmation_required")
        amount = getattr(args, "amount", None)
        inc_prod = getattr(args, "include_production", False)
        if amount is not None and (not inc_prod or amount <= 0):
            raise DecisionValidationError("amount_requires_positive_production_request")
        if inc_prod and amount is None:
            raise DecisionValidationError("production_amount_required")
        if getattr(args, "target_name", None) and not getattr(args, "component", None):
            raise DecisionValidationError("target_component_required")
        if not inc_prod and getattr(args, "target_name", None) and getattr(args, "target_level", None) is None:
            raise DecisionValidationError("target_level_required")

        delay = float(getattr(args, "delay", 0.0) or 0.0)
        if delay > 0:
            time.sleep(delay)

        strategy_path = getattr(args, "strategy", DEFAULT_STRATEGY_PATH)
        constants_path = getattr(args, "constants", DEFAULT_CONSTANTS_PATH)
        plan_ns = argparse.Namespace(
            command="plan",
            planet_id=args.planet_id,
            run_id=args.run_id,
            include_lifeforms=getattr(args, "include_lifeforms", False),
            include_production=inc_prod,
            strategy=strategy_path,
            constants=constants_path,
            output="json",
        )
        plan = _get_dep('command_plan', command_plan)(plan_ns)
        plan_id = plan.get("plan_id")
        if not plan_id:
            raise DecisionValidationError("plan_id_missing")

        matches = select_candidates(
            plan,
            action_ids=getattr(args, "action_ids", None),
            target_name=getattr(args, "target_name", None),
            component=getattr(args, "component", None),
            target_level=getattr(args, "target_level", None),
        )
        valid_actions = []
        skipped_reasons = []

        if getattr(args, "target_name", None) and len(matches) != 1:
            skipped_reasons.append({"code": "target_not_unique", "matches": len(matches)})
        else:
            matched_ids = {str(item.get("action_id") or "") for item in matches}
            if getattr(args, "action_ids", None):
                for action_id in args.action_ids:
                    if action_id not in matched_ids:
                        skipped_reasons.append({"code": "action_not_found", "action_id": action_id})
            for candidate in matches:
                reason = candidate_block_reason(candidate)
                if reason:
                    skipped_reasons.append({"action_id": candidate.get("action_id"), **reason})
                elif candidate.get("action_id"):
                    valid_actions.append(str(candidate["action_id"]))

        pretty = getattr(args, "pretty", False)
        if not valid_actions:
            result = {
                "planet_id": args.planet_id,
                "status": "blocked",
                "reason": skipped_reasons,
                "plan_id": plan_id,
                "global_stop": False,
            }
            print(format_compact_json(result, pretty))
            return

        if amount is not None:
            candidate = matches[0]
            if candidate.get("operation") != "produce" or not candidate.get("tech_id"):
                raise DecisionValidationError("production_target_invalid")
            prod_ns = argparse.Namespace(
                command="produce",
                tech_id=int(candidate["tech_id"]),
                amount=amount,
                planet_id=args.planet_id,
                run_id=args.run_id,
                confirm=True,
                output="json",
            )
            produced = cmd_produce(prod_ns)
            status = str(produced.get("status") or "unknown")
            out = {
                "planet_id": args.planet_id,
                "status": status,
                "plan_id": produced.get("plan_id"),
                "action_id": produced.get("action_id"),
                "amount": amount,
                "reason": produced.get("reason"),
                "global_stop": status == "uncertain",
                "evidence_ref": "runtime/memory/patrol-plan.json",
            }
            print(format_compact_json(out, pretty))
            return

        intent_file = getattr(args, "intent_file", None) or os.path.join(MEMORY_DIR, f"workflow-intent-{args.planet_id}.json")
        intent = {
            "schema_version": 1,
            "kind": getattr(args, "kind", "apply"),
            "planet_id": str(args.planet_id),
            "confirmed_plan_id": str(plan_id),
            "action_ids": valid_actions,
            "source": "ogame-patrol-multiagent",
        }
        with open(intent_file, "w", encoding="utf-8") as handle:
            json.dump(intent, handle, ensure_ascii=False, separators=(",", ":"))

        try:
            wf_plan_ns = argparse.Namespace(
                workflow_command="plan",
                intent_file=intent_file,
                run_id=args.run_id,
                strategy=strategy_path,
                constants=constants_path,
                output="json",
            )
            wf_plan = _get_dep('command_workflow_plan', command_workflow_plan)(wf_plan_ns)
            wf_id = wf_plan.get("workflow_id")
            if not wf_id:
                raise DecisionValidationError("workflow_id_missing")

            wf_run_ns = argparse.Namespace(
                workflow_command="run",
                workflow_id=wf_id,
                run_id=args.run_id,
                confirm=(getattr(args, "kind", "apply") == "apply"),
                output="json",
            )
            wf_result = _get_dep('command_workflow_run', command_workflow_run)(wf_run_ns)
            out = {
                "planet_id": args.planet_id,
                "status": wf_result.get("status", "unknown"),
                "workflow_id": wf_id,
                "plan_id": plan_id,
                "actions": valid_actions,
                "results": compact_results(wf_result.get("results", [])),
                "global_stop": (
                    wf_result.get("status") == "uncertain"
                    or wf_result.get("state_certainty") == "uncertain"
                ),
                "evidence_ref": (
                    f"runtime/memory/workflows/{'archive' if wf_result.get('status') == 'completed' else 'active'}/{wf_id}.json"
                ),
            }
            print(format_compact_json(out, pretty))
        finally:
            if os.path.exists(intent_file):
                try:
                    os.remove(intent_file)
                except OSError:
                    pass
            rotate_workflow_archives(os.path.join(MEMORY_DIR, "workflows"), max_age_days=7, keep_latest=10)

    except DecisionValidationError as exc:
        print(format_compact_json({"status": "blocked", "reason": bounded_text(exc), "global_stop": False}, getattr(args, "pretty", False)))
        raise SystemExit(1)
    except Exception as exc:
        print(format_compact_json({"status": "uncertain", "reason": bounded_text(exc), "global_stop": True}, getattr(args, "pretty", False)))
        raise SystemExit(1)


def _prepare_workflow_legacy_plan(state: Dict[str, Any], run_id: str) -> None:
    """Validate the confirmed plan and only rebind a certain interrupted run."""
    workflow_plan = WorkflowPlan.from_dict(state["plan"])
    legacy_plan = load_json_file(_plan_file())
    if legacy_plan is None:
        raise RuntimeError("找不到 WorkflowPlan 綁定的 confirmed plan。")
    if str(legacy_plan.get("plan_id")) != workflow_plan.confirmed_plan_id:
        raise RuntimeError("目前 confirmed plan_id 已變更；禁止續跑。")
    if str(legacy_plan.get("snapshot_hash")) != workflow_plan.confirmed_plan_hash:
        raise RuntimeError("confirmed plan snapshot hash 已變更；禁止續跑。")
    planet_ids_match = all(step.planet_id == str(legacy_plan.get("planet_id")) for step in workflow_plan.steps)
    if not planet_ids_match:
        raise RuntimeError("confirmed plan 星球綁定已變更；禁止續跑。")

    old_run_id = str(legacy_plan.get("run_id") or "")
    if old_run_id and old_run_id != run_id:
        resumable = (
            state.get("status") in {"interrupted", "running"}
            and state.get("state_certainty") == "certain"
            and not state.get("in_flight_step_id")
            and not any(item.get("status") == ActionStatus.UNCERTAIN.value for item in state.get("results", []))
        )
        if not resumable:
            raise RuntimeError("只有狀態確定的 interrupted workflow 可換新 lease。")
        legacy_plan["run_id"] = run_id
        atomic_write_json(_plan_file(), legacy_plan)
    require_active_plan(workflow_plan.confirmed_plan_id, run_id)


def command_workflow_run(args: argparse.Namespace) -> Dict[str, Any]:
    require_run_lease(args.run_id)
    journal = WorkflowJournal(_workflow_dir())
    state = journal.load(args.workflow_id)
    workflow_plan = WorkflowPlan.from_dict(state["plan"])
    if any(step.mutation for step in workflow_plan.steps) and not args.confirm:
        raise RuntimeError("包含 mutation 的 workflow run 必須提供 --confirm。")
    _prepare_workflow_legacy_plan(state, args.run_id)

    def executor(step: Any, run_id: str) -> ActionResult:
        if step.kind == IntentKind.APPLY:
            result = _get_dep('command_apply', command_apply)(argparse.Namespace(
                plan_id=workflow_plan.confirmed_plan_id,
                action_id=step.action_id,
                planet_id=int(step.planet_id),
                run_id=run_id,
                confirm=True,
                silent=True,
                mutation_lock_held=True,
            ))
            return ActionResult.from_dict(result)
        if step.kind == IntentKind.WATCH:
            result = command_watch(argparse.Namespace(
                plan_id=workflow_plan.confirmed_plan_id,
                action_id=step.action_id,
                run_id=run_id,
                silent=True,
            ))
            return ActionResult(
                ActionStatus.APPLIED,
                step.action_id,
                step.planet_id,
                evidence={"watch": result},
            )
        candidate = step.payload.get("candidate", {})
        observed = read_technology_list(str(candidate.get("component")), int(step.planet_id))
        if not isinstance(observed, dict) or observed.get("success") is False:
            return ActionResult(
                ActionStatus.BLOCKED,
                step.action_id,
                step.planet_id,
                "read_failed_or_unconfirmed",
                {"observed": observed},
            )
        return ActionResult(
            ActionStatus.APPLIED,
            step.action_id,
            step.planet_id,
            evidence={"observed": observed},
        )

    final_state = WorkflowRunner(journal, executor).run(args.workflow_id, args.run_id)
    return _workflow_summary(final_state)


def command_workflow_status(args: argparse.Namespace) -> Dict[str, Any]:
    return _workflow_summary(WorkflowJournal(_workflow_dir()).load(args.workflow_id))


def print_workflow_output(result: Dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(
        f"workflow {result['workflow_id']}: {result['status']} "
        f"({result['steps_finished']}/{result['steps_total']} steps, "
        f"certainty={result['state_certainty']})"
    )
