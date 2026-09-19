"""Legacy CLI command handlers for OGame Agent.

Provides compatibility commands:
  sync, build, research, produce, scan, transport, auto-transport, colonize,
  spy, raid, expedition, lifeform, lifeform-build, cancel-building,
  find-colonies, spy-reports, roi, events, messages, ships, storage,
  debug-page, planet-info, list-planets, lobby, list-tabs, patrol
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import random
import re
import sys
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Set
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from scripts.ogame import browser as _browser
from scripts.ogame import lifecycle as _lifecycle
from scripts.ogame import matrix as _matrix
from scripts.ogame import probes as _probes
from scripts.ogame import execution as _execution
from scripts.ogame import operations as _operations
from scripts.ogame import atoms as _atoms

from scripts.ogame.policy import (
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
from scripts.ogame.operations import FleetMission, build_fleet_candidate, build_patrol_fleet_candidates
from scripts.ogame.browser import (
    GAME_BASE_URL,
    GAME_HOST,
    UNIVERSE_NAME,
    checked_js,
    game_url,
    require_confirmed_mutation,
)

from scripts.ogame.resolver import get_dep, register_controller

_get_dep = get_dep

# Import commonly used symbols from other modules
MEMORY_DIR = _lifecycle.MEMORY_DIR
PLAN_FILE = _execution.PLAN_FILE
NEXT_WAKE_FILE = _lifecycle.NEXT_WAKE_FILE
RATES_FILE = _execution.RATES_FILE
RESOURCE_KEYS = _execution.RESOURCE_KEYS
RUN_LEASE_FILE = _lifecycle.RUN_LEASE_FILE
RUN_LEASE_GUARD_FILE = _lifecycle.RUN_LEASE_GUARD_FILE
RUN_LEASE_TTL_SECONDS = _lifecycle.RUN_LEASE_TTL_SECONDS
SafetyStopError = _matrix.SafetyStopError

load_json_file = _lifecycle.load_json_file
atomic_write_json = _lifecycle.atomic_write_json
write_next_wake = _lifecycle.write_next_wake
load_next_wake = _lifecycle.load_next_wake
require_run_lease = _lifecycle.require_run_lease
release_run_lease = _lifecycle.release_run_lease
print_command_output = _lifecycle.print_command_output

execute_in_game_tab = _browser.execute_in_game_tab
run_applescript = _browser.run_applescript
execute_checked_component = _browser.execute_checked_component
execute_checked_component_followup = _browser.execute_checked_component_followup
execute_checked_component_result = _browser.execute_checked_component_result
read_active_planet_context = _browser.read_active_planet_context
execute_checked_component = _browser.execute_checked_component

read_owned_planets = _matrix.read_owned_planets
read_empire_snapshot = _matrix.read_empire_snapshot
read_official_account_snapshot = _matrix.read_official_account_snapshot
enrich_empire_with_official = _matrix.enrich_empire_with_official
enrich_official_snapshot_planet_metadata = _matrix.enrich_official_snapshot_planet_metadata
cmd_matrix_empire = _matrix.cmd_matrix_empire
cmd_matrix_official = _matrix.cmd_matrix_official
cmd_matrix = _matrix.cmd_matrix
cmd_sync_all = _matrix.cmd_sync_all

TECH_FORMULAS = _execution.TECH_FORMULAS
calculate_technology_cost = _execution.calculate_technology_cost
create_fleet_confirmed_plan = _execution.create_fleet_confirmed_plan
command_plan = _execution.command_plan
command_apply = _execution.command_apply
command_watch = _execution.command_watch
require_active_plan = _execution.require_active_plan
parse_header_rates = _execution.parse_header_rates
cache_rates = _execution.cache_rates
mark_rates_stale = _execution.mark_rates_stale
load_cached_rates = _execution.load_cached_rates
normalize_number = _execution.normalize_number
parse_costs = _execution.parse_costs
resource_vector = _execution.resource_vector
read_technology_list = _execution.read_technology_list
read_fleet_state = _execution.read_fleet_state
calc_storage_capacity = _matrix.calc_storage_capacity

# ----------------- Subcommands -----------------

def cmd_sync(args) -> Dict[str, Any]:
    """Synchronize one planet. With --planet-id, every read is pinned to that planet."""
    planet_id = getattr(args, "planet_id", None)
    planet_label = f"cp={planet_id}" if planet_id is not None else "目前作用中星球"
    print(f"📡 同步 {planet_label}")
    print("📡 [1/6] 讀取基本資源與概況...")
    js_overview = """
    (function() {
        function getNum(sel) {
            var el = document.querySelector(sel);
            if (!el) return 0;
            var raw = el.getAttribute('data-raw') || el.innerText.replace(/,/g, '').replace(/\\./g, '').trim();
            var v = parseInt(raw, 10);
            return isNaN(v) ? 0 : v;
        }
        function getText(sel) {
            var el = document.querySelector(sel);
            return el ? el.innerText.trim() : null;
        }
        function getStorageLimit(sel) {
            var el = document.querySelector(sel);
            if (!el) return '';
            return el.getAttribute('title') || el.getAttribute('data-tooltip-title') || '';
        }
        return JSON.stringify({
            metal: getNum('#resources_metal'),
            crystal: getNum('#resources_crystal'),
            deuterium: getNum('#resources_deuterium'),
            metal_limit_tooltip: getStorageLimit('#resources_metal'),
            crystal_limit_tooltip: getStorageLimit('#resources_crystal'),
            deuterium_limit_tooltip: getStorageLimit('#resources_deuterium'),
            energy: getText('#resources_energy'),
            darkmatter: getNum('#resources_darkmatter'),
            planetId: new URLSearchParams(window.location.search).get('cp'),
            coords: getText('.planet-koords') || getText('.planetlink.active .planet-koords') || '',
            planetName: getText('.planet-name') || getText('.planetlink.active .planet-name') || ''
        });
    })()
    """
    overview = _get_dep('execute_in_game_tab', execute_in_game_tab)(js_overview, target_url=game_url("overview", planet_id))

    print("⛏️ [2/6] 掃描資源礦山與儲存槽 (Supplies)...")
    js_supplies = """
    (function() {
        var list = document.querySelectorAll("li.technology");
        var res = {};
        for (var i = 0; i < list.length; i++) {
            var el = list[i];
            var id = el.getAttribute("data-technology");
            var name = el.getAttribute("aria-label") || el.getAttribute("title") || "";
            var lvl = el.querySelector(".level") || el.querySelector(".amount");
            var btn = el.querySelector("button.upgrade");
            if (id) {
                res[id] = {
                    name: name,
                    level: lvl ? parseInt(lvl.innerText.trim(), 10) || 0 : 0,
                    canUpgrade: btn ? !btn.disabled : false,
                    costs: (el.querySelector(".costs") || el.querySelector(".technology_costs")) ? (el.querySelector(".costs") || el.querySelector(".technology_costs")).innerText.trim() : ""
                };
            }
        }
        return JSON.stringify(res);
    })()
    """
    supplies = _get_dep('execute_in_game_tab', execute_in_game_tab)(js_supplies, target_url=game_url("supplies", planet_id))

    print("🏭 [3/6] 掃描設施 (Facilities)...")
    facilities = _get_dep('execute_in_game_tab', execute_in_game_tab)(js_supplies, target_url=game_url("facilities", planet_id))

    print("🔬 [4/6] 掃描科技研究 (Research)...")
    research = _get_dep('execute_in_game_tab', execute_in_game_tab)(js_supplies, target_url=game_url("research", planet_id))

    print("🚀 [5/6] 掃描造船廠 (Shipyard)...")
    js_fleet = """
    (function() {
        var list = document.querySelectorAll("li.technology");
        var res = {};
        for (var i = 0; i < list.length; i++) {
            var el = list[i];
            var id = el.getAttribute("data-technology");
            var name = el.getAttribute("aria-label") || el.getAttribute("title") || "";
            var amountEl = el.querySelector(".amount") || el.querySelector(".level");
            if (id) {
                res[id] = {
                    name: name,
                    amount: amountEl ? parseInt(amountEl.innerText.trim(), 10) || 0 : 0
                };
            }
        }
        return JSON.stringify(res);
    })()
    """
    shipyard = _get_dep('execute_in_game_tab', execute_in_game_tab)(js_fleet, target_url=game_url("shipyard", planet_id))
    print("🛡️ [6/6] 掃描防禦 (Defense)...")
    defense = _get_dep('execute_in_game_tab', execute_in_game_tab)(js_fleet, target_url=game_url("defenses", planet_id))

    # Calculate storage levels
    m_storage_lvl = supplies.get("22", {}).get("level", 0)
    c_storage_lvl = supplies.get("23", {}).get("level", 0)
    d_storage_lvl = supplies.get("24", {}).get("level", 0)

    storage_info = {
        "metal": {"level": m_storage_lvl, "capacity": calc_storage_capacity(m_storage_lvl), "current": overview.get("metal", 0)},
        "crystal": {"level": c_storage_lvl, "capacity": calc_storage_capacity(c_storage_lvl), "current": overview.get("crystal", 0)},
        "deuterium": {"level": d_storage_lvl, "capacity": calc_storage_capacity(d_storage_lvl), "current": overview.get("deuterium", 0)},
    }

    state = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "planet_id": overview.get("planetId") or planet_id,
        "overview": overview,
        "supplies": supplies,
        "facilities": facilities,
        "research": research,
        "shipyard": shipyard,
        "defense": defense,
        "storage": storage_info
    }

    print("\n✅ 全面狀態同步完成！")
    print(f"💰 資源: 金屬 {overview.get('metal', 0):,} (容量 {calc_storage_capacity(m_storage_lvl):,}) / 水晶 {overview.get('crystal', 0):,} (容量 {calc_storage_capacity(c_storage_lvl):,}) / 重氫 {overview.get('deuterium', 0):,} (容量 {calc_storage_capacity(d_storage_lvl):,})")
    print(f"📦 倉庫等級: 金屬儲存槽 Lv.{m_storage_lvl} | 水晶儲存槽 Lv.{c_storage_lvl} | 重氫儲存槽 Lv.{d_storage_lvl}")
    return state


def read_owned_planets() -> List[Dict[str, Any]]:
    """Read owned-planet labels from the current UI without printing or navigation."""
    js_code = """
    (function() {
        var seen = {};
        var planets = [];
        document.querySelectorAll('a.planetlink[href*="cp="]').forEach(function(el) {
            var href = el.href || '';
            var match = href.match(/[?&]cp=(\\d+)/);
            if (!match || seen[match[1]]) return;
            seen[match[1]] = true;
            var coords = (el.innerText.match(/\\[\\d+:\\d+:\\d+\\]/) || [null])[0];
            planets.push({ id: Number(match[1]), name: (el.querySelector('.planet-name') || el).innerText.trim(), coords: coords, href: href });
        });
        return JSON.stringify({ success: true, planets: planets });
    })()
    """
    result = _get_dep('execute_in_game_tab', execute_in_game_tab)(js_code)
    if not isinstance(result, dict) or not result.get("success"):
        raise RuntimeError(f"無法讀取星球清單：{result}")
    planets = result.get("planets")
    if not isinstance(planets, list):
        raise RuntimeError(f"星球清單格式不符：{result}")
    return planets


def cmd_list_planets(args) -> Dict[str, Any]:
    """List owned planets from the current OGame UI without changing game state."""
    result = {"success": True, "planets": _get_dep('read_owned_planets', read_owned_planets)()}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def enrich_official_snapshot_planet_metadata(
    snapshot: Dict[str, Any], planet_metadata: List[Dict[str, Any]]
) -> Dict[str, Any]:
    metadata_by_id = {
        str(item.get("id")): item
        for item in planet_metadata
        if isinstance(item, dict) and str(item.get("id") or "").isdigit()
    }
    for planet in snapshot.get("planets", []):
        metadata = metadata_by_id.get(str(planet.get("planet_id")), {})
        if metadata.get("name"):
            planet["name"] = metadata["name"]
        if metadata.get("coords"):
            planet["coords"] = metadata["coords"]
    return snapshot


def cmd_sync_all_html(args) -> Dict[str, Any]:
    """Historical page-by-page fallback for servers without official accountInfo."""
    planets = _get_dep('read_owned_planets', read_owned_planets)()
    if not planets:
        raise RuntimeError("未在目前遊戲頁找到任何可同步的星球。")
    snapshots = []
    for planet in planets:
        planet_args = argparse.Namespace(planet_id=planet["id"])
        snapshots.append(cmd_sync(planet_args))
    result = {
        "success": True,
        "schema_version": OFFICIAL_SNAPSHOT_SCHEMA_VERSION,
        "source": "html.pages",
        "planet_count": len(snapshots),
        "planets": snapshots,
    }
    print(f"✅ 已用 HTML fallback 依序同步 {len(snapshots)} 顆星球；之後的變更必須逐筆重新確認。")
    return result


def cmd_sync_all(args) -> Dict[str, Any]:
    """Read Empire standalone first, enriching rates through accountInfo when available."""
    fn = _get_dep('cmd_sync_all')
    if fn and fn is not cmd_sync_all and (hasattr(fn, 'assert_called') or hasattr(fn, '_mock_return_value')):
        return fn(args)
    return _matrix.cmd_sync_all(args)


def cmd_matrix_html(args) -> Dict[str, Any]:
    """Historical multi-page matrix fallback."""
    quiet = getattr(args, "output", "human") == "json"
    planets = _get_dep('read_owned_planets', read_owned_planets)()
    if not planets:
        raise RuntimeError("未在目前遊戲頁找到任何星球。")

    matrix = []
    total_resources = {"metal": 0, "crystal": 0, "deuterium": 0}
    total_rates = {"metal": 0, "crystal": 0, "deuterium": 0}

    if not quiet:
        print("\n🌐 ==================== 【全帝國全局資源與佇列監控矩陣】 ====================")
    for p in planets:
        cp = p["id"]
        coords = p["coords"]
        name = p["name"]

        overview = _get_dep('read_header_snapshot', read_header_snapshot)("supplies", cp)
        res = resource_vector(overview.get("resources", {}))
        energy_val = parse_signed_number(overview.get("energy")) or 0
        rates = parse_header_rates(overview.get("rate_tooltips", {})) or {}

        supplies_data = _get_dep('read_technology_list', read_technology_list)("supplies", cp)
        m_storage = calc_storage_capacity(supplies_data.get("items", {}).get("22", {}).get("level", 0))
        c_storage = calc_storage_capacity(supplies_data.get("items", {}).get("23", {}).get("level", 0))
        d_storage = calc_storage_capacity(supplies_data.get("items", {}).get("24", {}).get("level", 0))

        b_busy = bool(supplies_data.get("active_production") or supplies_data.get("queue_busy", {}).get("building"))

        for k in RESOURCE_KEYS:
            total_resources[k] += res.get(k, 0)
            total_rates[k] += rates.get(k, 0)

        m_pct = (res.get("metal", 0) / m_storage * 100) if m_storage else 0
        c_pct = (res.get("crystal", 0) / c_storage * 100) if c_storage else 0
        d_pct = (res.get("deuterium", 0) / d_storage * 100) if d_storage else 0

        status_str = f"🪐 {name} {coords} (cp={cp}):"
        res_str = f"  🪙 M: {res.get('metal',0):>7,} ({m_pct:4.1f}%/{m_storage//1000}k) | 💎 C: {res.get('crystal',0):>7,} ({c_pct:4.1f}%/{c_storage//1000}k) | 🧪 D: {res.get('deuterium',0):>6,} ({d_pct:4.1f}%/{d_storage//1000}k) | ⚡ {energy_val:+d}"
        rate_str = f"  📈 產速: +{rates.get('metal',0):,}/h M | +{rates.get('crystal',0):,}/h C | +{rates.get('deuterium',0):,}/h D"
        queue_str = f"  🏗️ 建築佇列: {'⏳ 建造中' if b_busy else '⚠️ 空閒 (需立即排定)'}"

        if not quiet:
            print(status_str)
            print(res_str)
            print(rate_str)
            print(queue_str)
            print("-" * 75)

        matrix.append({
            "planet_id": cp,
            "name": name,
            "coords": coords,
            "resources": res,
            "rates": rates,
            "storage": {"metal": m_storage, "crystal": c_storage, "deuterium": d_storage},
            "storage_pct": {"metal": m_pct, "crystal": c_pct, "deuterium": d_pct},
            "energy": energy_val,
            "building_busy": b_busy
        })

    if not quiet:
        print(f"👑 【全帝國總產能彙總】: +{total_rates['metal']:,} M/h | +{total_rates['crystal']:,} C/h | +{total_rates['deuterium']:,} D/h （總產速: +{sum(total_rates.values()):,}/h）")
        print(f"💰 【全帝國總儲備彙總】: {total_resources['metal']:,} M | {total_resources['crystal']:,} C | {total_resources['deuterium']:,} D")
        print("=================================================================================\n")
    return {
        "success": True,
        "schema_version": OFFICIAL_SNAPSHOT_SCHEMA_VERSION,
        "source": "html.pages",
        "queue_source": "html.supplies",
        "planets": matrix,
        "totals": {"resources": total_resources, "rates": total_rates},
    }


def cmd_matrix_empire(snapshot: Dict[str, Any], quiet: bool = False) -> Dict[str, Any]:
    """Build the matrix from one Empire page; accountInfo may already have enriched rates."""
    matrix = []
    total_resources = {key: 0 for key in RESOURCE_KEYS}
    total_rates = {key: 0 for key in RESOURCE_KEYS}
    rates_known = snapshot.get("rates_coverage") == "official.accountInfo"

    if not quiet:
        print("\n🌐 ==================== 【Empire 單頁全帝國矩陣】 ====================")
    for planet in snapshot["planets"]:
        cp = int(planet["planet_id"])
        resources = resource_vector(planet["resources"])
        storage = resource_vector(planet["storage"])
        rates = resource_vector(planet.get("production", {})) if rates_known else {key: None for key in RESOURCE_KEYS}
        queue_busy = dict(planet.get("queue_busy") or {})
        storage_pct = {
            key: (resources[key] / storage[key] * 100) if storage[key] else 0
            for key in RESOURCE_KEYS
        }
        for key in RESOURCE_KEYS:
            total_resources[key] += resources[key]
            if rates_known:
                total_rates[key] += int(rates[key] or 0)

        if not quiet:
            print(f"🪐 {planet['name']} {planet['coords']} (cp={cp}):")
            print(f"  🪙 M: {resources['metal']:>7,} ({storage_pct['metal']:4.1f}%/{storage['metal']//1000}k) | 💎 C: {resources['crystal']:>7,} ({storage_pct['crystal']:4.1f}%/{storage['crystal']//1000}k) | 🧪 D: {resources['deuterium']:>6,} ({storage_pct['deuterium']:4.1f}%/{storage['deuterium']//1000}k) | ⚡ {int(planet['energy']):+d}")
            if rates_known:
                print(f"  📈 產速: +{rates['metal']:,}/h M | +{rates['crystal']:,}/h C | +{rates['deuterium']:,}/h D")
            else:
                print("  📈 產速: 未提供（Empire standalone 不含可靠時產；未以 0 代填）")
            print(
                "  🏗️ 佇列: "
                f"建築={'忙碌' if queue_busy.get('building') else '空閒'} | "
                f"研究={'忙碌' if queue_busy.get('research') else '空閒'} | "
                f"造船={'忙碌' if queue_busy.get('shipyard') else '空閒'} | "
                f"生命建築={'忙碌' if queue_busy.get('lifeform_building') else '空閒'} | "
                f"生命研究={'忙碌' if queue_busy.get('lifeform_research') else '空閒'}"
            )
            print("-" * 75)

        matrix.append({
            "planet_id": cp,
            "name": planet["name"],
            "coords": planet["coords"],
            "fields": planet.get("fields"),
            "temperature": planet.get("temperature"),
            "resources": resources,
            "lifeform_resources": dict(planet.get("lifeform_resources") or {}),
            "equipment": list(planet.get("equipment") or []),
            "rates": rates,
            "storage": storage,
            "storage_pct": storage_pct,
            "energy": int(planet["energy"]),
            "building_busy": bool(queue_busy.get("building")),
            "research_busy": bool(queue_busy.get("research")),
            "shipyard_busy": bool(queue_busy.get("shipyard")),
            "lifeform_building_busy": bool(queue_busy.get("lifeform_building")),
            "lifeform_research_busy": bool(queue_busy.get("lifeform_research")),
            "queues": list(planet.get("queues") or []),
            "buildings": {k: v for k, v in (planet.get("buildings") or {}).items() if v},
            "researches": {k: v for k, v in (planet.get("researches") or {}).items() if v},
            "ships": {k: v for k, v in (planet.get("ships") or {}).items() if v},
            "defenses": {k: v for k, v in (planet.get("defenses") or {}).items() if v},
            "species_buildings": {k: v for k, v in (planet.get("species_buildings") or {}).items() if v},
            "species_researches": {k: v for k, v in (planet.get("species_researches") or {}).items() if v},
        })

    rendered_rates = total_rates if rates_known else {key: None for key in RESOURCE_KEYS}
    if not quiet:
        if rates_known:
            print(f"👑 【全帝國總產能彙總】: +{total_rates['metal']:,} M/h | +{total_rates['crystal']:,} C/h | +{total_rates['deuterium']:,} D/h （總產速: +{sum(total_rates.values()):,}/h）")
        print(f"💰 【全帝國總儲備彙總】: {total_resources['metal']:,} M | {total_resources['crystal']:,} C | {total_resources['deuterium']:,} D")
        print("=================================================================================\n")
    return {
        "success": True,
        "schema_version": snapshot["schema_version"],
        "source": snapshot["source"],
        "queue_source": "empire.standalone",
        "queue_coverage": snapshot["queue_coverage"],
        "rates_coverage": snapshot.get("rates_coverage", "not_provided"),
        "captured_at": snapshot["captured_at"],
        "account": snapshot.get("account", {}),
        "planets": matrix,
        "totals": {"resources": total_resources, "rates": rendered_rates},
    }


def cmd_matrix_official(snapshot: Dict[str, Any], quiet: bool = False) -> Dict[str, Any]:
    """Build the matrix from one accountInfo read plus one queue-only read per planet."""
    matrix = []
    total_resources = {key: 0 for key in RESOURCE_KEYS}
    total_rates = {key: 0 for key in RESOURCE_KEYS}

    if not quiet:
        print("\n🌐 ==================== 【全帝國全局資源與佇列監控矩陣】 ====================")
    for planet in snapshot["planets"]:
        cp = int(planet["planet_id"])
        coords = planet["coords"]
        name = planet.get("name") or f"Planet {cp}"
        resources = resource_vector(planet["resources"])
        rates = resource_vector(planet["production"])
        energy_value = int(planet["energy"])
        buildings = planet["buildings"]
        storage = {
            "metal": calc_storage_capacity(int(buildings.get("22", 0))),
            "crystal": calc_storage_capacity(int(buildings.get("23", 0))),
            "deuterium": calc_storage_capacity(int(buildings.get("24", 0))),
        }

        queue_data = _get_dep('read_technology_list', read_technology_list)("supplies", cp)
        queue_busy = queue_data.get("queue_busy") or {}
        building_busy = bool(queue_data.get("active_production") or queue_busy.get("building"))
        research_busy = bool(queue_busy.get("research"))

        for key in RESOURCE_KEYS:
            total_resources[key] += resources[key]
            total_rates[key] += rates[key]
        storage_pct = {
            key: (resources[key] / storage[key] * 100) if storage[key] else 0
            for key in RESOURCE_KEYS
        }

        if not quiet:
            print(f"🪐 {name} {coords} (cp={cp}):")
            print(f"  🪙 M: {resources['metal']:>7,} ({storage_pct['metal']:4.1f}%/{storage['metal']//1000}k) | 💎 C: {resources['crystal']:>7,} ({storage_pct['crystal']:4.1f}%/{storage['crystal']//1000}k) | 🧪 D: {resources['deuterium']:>6,} ({storage_pct['deuterium']:4.1f}%/{storage['deuterium']//1000}k) | ⚡ {energy_value:+d}")
            print(f"  📈 產速: +{rates['metal']:,}/h M | +{rates['crystal']:,}/h C | +{rates['deuterium']:,}/h D")
            print(f"  🏗️ 建築佇列: {'⏳ 建造中' if building_busy else '⚠️ 空閒 (需立即排定)'}")
            print("-" * 75)

        matrix.append({
            "planet_id": cp,
            "name": name,
            "coords": coords,
            "resources": resources,
            "rates": rates,
            "storage": storage,
            "storage_pct": storage_pct,
            "energy": energy_value,
            "building_busy": building_busy,
            "research_busy": research_busy,
        })

    if not quiet:
        print(f"👑 【全帝國總產能彙總】: +{total_rates['metal']:,} M/h | +{total_rates['crystal']:,} C/h | +{total_rates['deuterium']:,} D/h （總產速: +{sum(total_rates.values()):,}/h）")
        print(f"💰 【全帝國總儲備彙總】: {total_resources['metal']:,} M | {total_resources['crystal']:,} C | {total_resources['deuterium']:,} D")
        print("=================================================================================\n")
    return {
        "success": True,
        "schema_version": snapshot["schema_version"],
        "source": snapshot["source"],
        "queue_source": "html.supplies",
        "captured_at": snapshot["captured_at"],
        "planets": matrix,
        "totals": {"resources": total_resources, "rates": total_rates},
    }


def cmd_matrix(args) -> Dict[str, Any]:
    """Prefer one Empire page, using accountInfo only to enrich hourly production."""
    fn = _get_dep('cmd_matrix')
    if fn and fn is not cmd_matrix and (hasattr(fn, 'assert_called') or hasattr(fn, '_mock_return_value')):
        return fn(args)
    return _matrix.cmd_matrix(args)


def cmd_list_tabs(args) -> Dict[str, Any]:
    """List all open Chrome windows and tabs (read-only diagnostic)."""
    as_code = """
    tell application "Google Chrome"
        if (count of windows) is 0 then
            return "NO_WINDOWS"
        end if
        set tabList to {}
        repeat with w in windows
            repeat with t in tabs of w
                set end of tabList to (title of t & "|||" & URL of t)
            end repeat
        end repeat
        set AppleScript's text item delimiters to "%%%"
        return tabList as text
    end tell
    """
    raw = run_applescript(as_code)
    if raw == "NO_WINDOWS":
        print("❌ Chrome 沒有開啟任何視窗。")
        return {"success": False, "reason": "NO_WINDOWS"}
    items = raw.split("%%%")
    tabs = []
    for item in items:
        if "|||" in item:
            title, url = item.split("|||", 1)
            tabs.append({"title": title, "url": url})
    print(f"📋 Chrome 當前開啟的 {len(tabs)} 個分頁：")
    for idx, t in enumerate(tabs):
        print(f"  [{idx+1}] {t['title']} -> {t['url']}")
    return {"success": True, "tabs": tabs}


def cmd_lobby(args) -> Dict[str, Any]:
    """Inspect or enter game from Lobby."""
    if getattr(args, "enter", False):
        print("🎮 正在從 Lobby 點擊「暢玩」進入遊戲...")
        univ_search = ""
        if UNIVERSE_NAME:
            univ_search = f"""
            var targetUniverse = {json.dumps(UNIVERSE_NAME)};
            var universeBtn = allBtns.find(function(b) {{
                var cur = b;
                for (var i = 0; i < 8; i++) {{
                    if (!cur || cur === document.body) break;
                    var txt = cur.innerText || '';
                    if (txt.indexOf(targetUniverse) !== -1) {{
                        return true;
                    }}
                    cur = cur.parentElement;
                }}
                return false;
            }});
            if (universeBtn) {{
                universeBtn.click();
                return JSON.stringify({{ success: true, clicked: (universeBtn.innerText || '').trim(), account: targetUniverse }});
            }}
"""
        js_enter = f"""
        (function() {{
            var allBtns = Array.from(document.querySelectorAll('button, a'));
{univ_search}
            var primaryBtn = allBtns.find(function(el) {{
                var txt = (el.innerText || '').trim();
                var cls = el.className || '';
                return (cls.includes('btn-primary') || cls.includes('button-primary')) && (txt.includes('暢玩') || txt.includes('Play') || txt.includes('馬上暢玩') || txt.includes('開始'));
            }}) || document.querySelector('button.btn-primary, button.button-primary, button[class*="btn-primary"], button[class*="button-primary"]');
            if (primaryBtn) {{
                primaryBtn.click();
                return JSON.stringify({{ success: true, clicked: (primaryBtn.innerText || '').trim(), type: 'btn-primary' }});
            }}
            return JSON.stringify({{ success: false, reason: "找不到暢玩或開始按鈕" }});
        }})()
        """
        b64_enter = base64.b64encode(js_enter.encode('utf-8')).decode('utf-8')
        overview_url = game_url("overview")
        as_code = f'''
        tell application "Google Chrome"
            repeat with w in windows
                repeat with t in tabs of w
                    if (URL of t) contains "{GAME_HOST}" then
                        set URL of t to "{overview_url}"
                        return "{{\\"success\\":true,\\"action\\":\\"navigated_existing_game_tab\\"}}"
                    end if
                end repeat
            end repeat
            repeat with w in windows
                repeat with t in tabs of w
                    if (URL of t) contains "lobby.ogame.gameforge.com" and (URL of t) contains "accounts" then
                        set res to (execute t javascript "eval(decodeURIComponent(escape(window.atob('{b64_enter}'))))")
                        return res
                    end if
                end repeat
            end repeat
            repeat with w in windows
                repeat with t in tabs of w
                    if (URL of t) contains "lobby.ogame.gameforge.com" then
                        set res to (execute t javascript "eval(decodeURIComponent(escape(window.atob('{b64_enter}'))))")
                        return res
                    end if
                end repeat
            end repeat
            return "NO_LOBBY_TAB"
        end tell
        '''
        raw = run_applescript(as_code)
        print("點擊結果:", raw)
        time.sleep(5)
        return cmd_list_tabs(args)

    js_inspect = """
    (function() {
        var buttons = Array.from(document.querySelectorAll('button, a')).map(function(b) {
            var parentTxt = (b.parentElement && b.parentElement.parentElement ? b.parentElement.parentElement.innerText : '').replace(/\\s+/g, ' ').trim();
            return {
                tag: b.tagName,
                text: (b.innerText || '').trim(),
                className: b.className || '',
                context: parentTxt.substring(0, 80)
            };
        }).filter(function(b) { return b.text.length > 0 && b.text.length < 50; });
        return JSON.stringify({
            success: true,
            url: window.location.href,
            title: document.title,
            buttons: buttons
        });
    })()
    """
    b64_inspect = base64.b64encode(js_inspect.encode('utf-8')).decode('utf-8')
    as_code = f'''
    tell application "Google Chrome"
        repeat with w in windows
            repeat with t in tabs of w
                if (URL of t) contains "lobby.ogame.gameforge.com" then
                    set res to (execute t javascript "eval(atob('{b64_inspect}'))")
                    return res
                end if
            end repeat
        end repeat
        return "NO_LOBBY_TAB"
    end tell
    '''
    raw = run_applescript(as_code)
    if raw == "NO_LOBBY_TAB":
        print("❌ 找不到 Lobby 分頁")
        return {"success": False, "reason": "NO_LOBBY_TAB"}
    try:
        data = json.loads(raw)
        print("Lobby 狀態:", data.get("title"), data.get("url"))
        print("按鈕清單:")
        for b in data.get("buttons", []):
            ctx = f" | ctx: {b.get('context')}" if b.get('context') else ""
            print(f"  [{b['tag']}] {b['text']} (class: {b['className']}){ctx}")
        return data
    except Exception as e:
        print("Raw output:", raw)
        return {"success": False, "raw": raw}


def cmd_inspect(args) -> Dict[str, Any]:
    """Print the live level, availability, and displayed costs for named tech IDs."""
    state = cmd_sync(args)
    requested = [str(tech_id) for tech_id in args.tech_ids]
    sections = {
        "supplies": state["supplies"],
        "facilities": state["facilities"],
        "research": state["research"],
    }
    overview = state["overview"]
    result: Dict[str, Any] = {
        "planet_id": state["planet_id"],
        "resources": {
            "metal": overview.get("metal", 0),
            "crystal": overview.get("crystal", 0),
            "deuterium": overview.get("deuterium", 0),
            "energy": overview.get("energy"),
        },
        "items": {},
    }
    for tech_id in requested:
        for section_name, section in sections.items():
            if tech_id in section:
                result["items"][tech_id] = {"section": section_name, **section[tech_id]}
                break
    print("🔎 即時技術明細:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result

def cmd_build(args) -> Any:
    """Compatibility wrapper: resolve a fresh confirmed plan, then use apply."""
    require_confirmed_mutation(args)
    tech_id = str(args.tech_id)
    plan = _get_dep('command_plan', command_plan)(argparse.Namespace(
        planet_id=args.planet_id,
        run_id=args.run_id,
        diagnose=False,
        silent=True,
    ))
    action_ids = [f"supplies:{tech_id}", f"facilities:{tech_id}"]
    candidate = next(
        (item for item in plan.get("candidates", []) if item.get("action_id") in action_ids),
        None,
    )
    if candidate is None:
        raise RuntimeError("build 指定項目不在 fresh confirmed plan；未執行變更。")
    return _get_dep('command_apply', command_apply)(argparse.Namespace(
        plan_id=plan["plan_id"],
        action_id=candidate["action_id"],
        planet_id=args.planet_id,
        run_id=args.run_id,
        confirm=True,
        output=getattr(args, "output", "human"),
    ))

def cmd_research(args) -> Any:
    """Compatibility wrapper: resolve a fresh confirmed plan, then use apply."""
    require_confirmed_mutation(args)
    tech_id = str(args.tech_id)
    plan = _get_dep('command_plan', command_plan)(argparse.Namespace(
        planet_id=args.planet_id,
        run_id=args.run_id,
        diagnose=False,
        silent=True,
    ))
    action_id = f"research:{tech_id}"
    if not any(item.get("action_id") == action_id for item in plan.get("candidates", [])):
        raise RuntimeError("research 指定項目不在 fresh confirmed plan；未執行變更。")
    return _get_dep('command_apply', command_apply)(argparse.Namespace(
        plan_id=plan["plan_id"],
        action_id=action_id,
        planet_id=args.planet_id,
        run_id=args.run_id,
        confirm=True,
        output=getattr(args, "output", "human"),
    ))


def cmd_lifeform(args) -> Dict[str, Any]:
    """Compatibility read wrapper for both planet-pinned Lifeform domains."""
    planet_id = int(args.planet_id)
    result = read_lifeform_atom(planet_id, _get_dep('read_technology_list', read_technology_list))
    print_command_output(
        args,
        result,
        f"lifeform planet {planet_id}: "
        f"{len(result.get('lfbuildings', {}).get('items', {}))} buildings, "
        f"{len(result.get('lfresearch', {}).get('items', {}))} researches"
        if result.get("success")
        else f"lifeform planet {planet_id}: blocked ({result.get('reason')})",
    )
    return result


def cmd_lifeform_build(args) -> Dict[str, Any]:
    """Compatibility wrapper: resolve a fresh Lifeform candidate, then use apply."""
    require_confirmed_mutation(args)
    tech_id = str(args.tech_id)
    component = getattr(args, "component", None)
    plan = _get_dep('command_plan', command_plan)(
        argparse.Namespace(
            planet_id=args.planet_id,
            run_id=args.run_id,
            diagnose=False,
            include_lifeforms=True,
            silent=True,
        )
    )
    matches = [
        item
        for item in plan.get("candidates", [])
        if item.get("operation") == "lifeform_upgrade"
        and item.get("tech_id") == tech_id
        and (component is None or item.get("component") == component)
    ]
    if len(matches) != 1:
        raise RuntimeError("lifeform-build 指定項目未唯一對應 fresh confirmed candidate；未執行變更。")
    candidate = matches[0]
    if candidate.get("can_apply") is not True:
        raise RuntimeError("lifeform-build 缺少成本、佇列或能源的可信證據；未執行變更。")
    return _get_dep('command_apply', command_apply)(
        argparse.Namespace(
            plan_id=plan["plan_id"],
            action_id=candidate["action_id"],
            planet_id=args.planet_id,
            run_id=args.run_id,
            confirm=True,
            output=getattr(args, "output", "human"),
        )
    )


def cmd_cancel_building(args) -> Dict[str, Any]:
    """Compatibility wrapper for one queue-token-bound cancellation workflow."""
    require_confirmed_mutation(args)
    plan = _get_dep('command_plan', command_plan)(
        argparse.Namespace(
            planet_id=args.planet_id,
            run_id=args.run_id,
            diagnose=False,
            include_lifeforms=False,
            include_cancel=True,
            silent=True,
        )
    )
    matches = [
        item
        for item in plan.get("candidates", [])
        if item.get("operation") == "cancel_building"
    ]
    if len(matches) != 1:
        raise RuntimeError("目前沒有可由 exact queue token 確認的 building cancellation；未執行變更。")
    return _get_dep('command_apply', command_apply)(
        argparse.Namespace(
            plan_id=plan["plan_id"],
            action_id=matches[0]["action_id"],
            planet_id=args.planet_id,
            run_id=args.run_id,
            confirm=True,
            output=getattr(args, "output", "human"),
        )
    )


def cmd_produce(args) -> Any:
    require_confirmed_mutation(args)
    tech_id = str(args.tech_id)
    amount = int(args.amount)
    planet_id = int(args.planet_id)
    if amount <= 0:
        raise RuntimeError("produce amount 必須大於 0。")
    plan = _get_dep('command_plan', command_plan)(
        argparse.Namespace(
            planet_id=planet_id,
            run_id=args.run_id,
            diagnose=False,
            include_lifeforms=False,
            include_cancel=False,
            include_production=True,
            production_request=(tech_id, amount),
            silent=True,
        )
    )
    matches = [
        item
        for item in plan.get("candidates", [])
        if item.get("operation") == "produce"
        and item.get("tech_id") == tech_id
        and item.get("amount") == amount
    ]
    if len(matches) != 1 or matches[0].get("can_apply") is not True:
        raise RuntimeError("produce 指定項目未唯一對應可執行的 fresh confirmed candidate；未執行變更。")
    return _get_dep('command_apply', command_apply)(
        argparse.Namespace(
            plan_id=plan["plan_id"],
            action_id=matches[0]["action_id"],
            planet_id=planet_id,
            run_id=args.run_id,
            confirm=True,
            output=getattr(args, "output", "human"),
        )
    )

def cmd_colonize(args) -> Dict[str, Any]:
    require_confirmed_mutation(args)
    planet_id = int(args.planet_id)
    plan = _get_dep('create_fleet_confirmed_plan', create_fleet_confirmed_plan)(args, "colonize")
    candidate = plan["candidates"][0]
    return _get_dep('command_apply', command_apply)(
        argparse.Namespace(
            plan_id=plan["plan_id"],
            action_id=candidate["action_id"],
            planet_id=planet_id,
            run_id=args.run_id,
            confirm=True,
            output=getattr(args, "output", "human"),
        )
    )


def cmd_auto_transport(args) -> Dict[str, Any]:
    """Compatibility wrapper selecting one Python-confirmed transport candidate."""
    origin_id = int(args.origin_id)
    target_id = str(args.target_id)
    target = {
        "galaxy": int(args.galaxy),
        "system": int(args.system),
        "position": int(args.position),
    }
    plan = _get_dep('command_plan', command_plan)(
        argparse.Namespace(
            planet_id=origin_id,
            run_id=args.run_id,
            diagnose=False,
            include_lifeforms=False,
            include_cancel=False,
            include_production=False,
            include_fleet=True,
            strategy=getattr(args, "strategy", DEFAULT_STRATEGY_PATH),
            constants=getattr(args, "constants", DEFAULT_CONSTANTS_PATH),
            silent=True,
        )
    )
    matches = [
        candidate
        for candidate in plan.get("candidates", [])
        if candidate.get("operation") == "fleet_dispatch"
        and candidate.get("mission") == "transport"
        and candidate.get("target") == target
        and str((candidate.get("target_evidence") or {}).get("target_planet_id")) == target_id
    ]
    if len(matches) != 1:
        raise RuntimeError("auto-transport 未唯一對應 fresh typed transport candidate；未執行變更。")
    candidate = matches[0]
    preview = {
        "success": True,
        "status": "calculated",
        "plan_id": plan["plan_id"],
        "action_id": candidate["action_id"],
        "planet_id": plan["planet_id"],
        "target_planet_id": target_id,
        "payload": candidate["payload"],
        "ship_tech": candidate["ship_tech"],
        "ship_amount": candidate["ship_amount"],
    }
    if getattr(args, "dry_run", False) or not getattr(args, "confirm", False):
        print_command_output(args, preview, f"auto-transport {candidate['action_id']}: calculated only")
        return preview
    return _get_dep('command_apply', command_apply)(
        argparse.Namespace(
            plan_id=plan["plan_id"],
            action_id=candidate["action_id"],
            planet_id=origin_id,
            run_id=args.run_id,
            constants=getattr(args, "constants", DEFAULT_CONSTANTS_PATH),
            confirm=True,
            output=getattr(args, "output", "human"),
        )
    )



def cmd_planet_info(args: argparse.Namespace) -> Dict[str, Any]:
    """Read full overview information for a planet: name, coords, diameter, fields, temperature, points."""
    planet_id = getattr(args, "planet_id", None)
    planet_label = f"cp={planet_id}" if planet_id is not None else "目前作用中星球"
    print(f"🪐 讀取星球概況資訊 ({planet_label})...")

    js_code = """
    (function() {
        function getText(sel) {
            var el = document.querySelector(sel);
            return el ? el.innerText.trim() : "";
        }

        var diameterEl = document.querySelector('#diameterContentField') || document.querySelector('.diameterContentField');
        var tempEl = document.querySelector('#temperatureContentField') || document.querySelector('.temperatureContentField');
        var posEl = document.querySelector('#positionContentField') || document.querySelector('.planet-koords');
        var nameEl = document.querySelector('#planetNameHeader') || document.querySelector('.planet-name');

        // Parse all table / planet-data rows
        var rows = [];
        document.querySelectorAll('#planetData tr, #planet tr, .content-box-s tr, #planetTable tr').forEach(function(tr) {
            var txt = tr.innerText.replace(/\\s+/g, ' ').trim();
            if (txt) rows.push(txt);
        });

        var rawBox = document.querySelector('#planetData') || document.querySelector('#planet') || document.querySelector('.content-box-s');

        return JSON.stringify({
            success: true,
            planet_id: new URLSearchParams(window.location.search).get('cp'),
            planet_name: nameEl ? nameEl.innerText.trim() : getText('.planetlink.active .planet-name'),
            coords: posEl ? posEl.innerText.trim() : getText('.planetlink.active .planet-koords'),
            diameter_raw: diameterEl ? diameterEl.innerText.trim() : "",
            temperature_raw: tempEl ? tempEl.innerText.trim() : "",
            table_rows: rows,
            box_text: rawBox ? rawBox.innerText.replace(/\\n+/g, ' | ').trim() : ""
        });
    })()
    """
    res = _get_dep('execute_in_game_tab', execute_in_game_tab)(js_code, target_url=game_url("overview", planet_id))
    if not isinstance(res, dict):
        print(f"無法取得星球資料: {res}")
        return {"success": False, "error": str(res)}

    print("\n🪐 【星球基本資訊】")
    print(f"  🔹 名稱: {res.get('planet_name')}")
    print(f"  🔹 座標: {res.get('coords')} (ID: {res.get('planet_id')})")
    print(f"  🔹 直徑與方格: {res.get('diameter_raw')}")
    print(f"  🔹 溫度: {res.get('temperature_raw')}")
    if res.get('table_rows'):
        print(f"  🔹 詳細欄位: {', '.join(res.get('table_rows'))}")
    elif res.get('box_text'):
        print(f"  🔹 概況文字: {res.get('box_text')}")
    return res


def cmd_open_abandon_dialog(args: argparse.Namespace) -> Dict[str, Any]:
    """Navigate to planet overview and open Abandon Colony confirmation dialog in Chrome."""
    planet_id = getattr(args, "planet_id", None)
    if not planet_id:
        raise ValueError("必須提供 --planet-id 才能開啟放棄殖民星確認視窗。")
    url = game_url("overview", planet_id)
    js_code = """
    (function() {
        var btn = document.querySelector('.openPlanetRenameGiveupBox');
        if (btn) {
            btn.click();
            return JSON.stringify({opened: true});
        }
        return JSON.stringify({opened: false, error: "button_not_found"});
    })()
    """
    res = _get_dep('execute_in_game_tab', execute_in_game_tab)(
        js_code,
        target_url=url,
        wait_after_nav=2.0,
    )
    try:
        subprocess.run(["osascript", "-e", 'tell application "Google Chrome" to activate'], check=False)
    except Exception:
        pass
    print(f"🪐 已為您在 Chrome 瀏覽器切換至 cp={planet_id} 並打開「放棄殖民星」對話框。")
    print("⚠️ 請在瀏覽器彈出的對話框中輸入帳號密碼，並點擊確認刪除該星球。")
    return {"success": True, "planet_id": planet_id, "dialog_opened": True}


def cmd_transport(args) -> Dict[str, Any]:
    """Transport resources from origin planet to target coordinates using cargo ships."""
    require_confirmed_mutation(args)
    planet_id = int(args.planet_id)
    mission = int(getattr(args, "mission", 3) or 3)
    plan = _get_dep('create_fleet_confirmed_plan', create_fleet_confirmed_plan)(args, "deploy" if mission == 4 else "transport")
    candidate = plan["candidates"][0]
    return _get_dep('command_apply', command_apply)(
        argparse.Namespace(
            plan_id=plan["plan_id"],
            action_id=candidate["action_id"],
            planet_id=planet_id,
            run_id=args.run_id,
            confirm=True,
            output=getattr(args, "output", "human"),
        )
    )

def cmd_scan(args) -> Dict[str, Any]:
    galaxy = int(args.galaxy)
    system_start = int(args.system)
    system_end = int(getattr(args, "system_end", 0) or system_start)
    planet_id = getattr(args, "planet_id", None)

    print(f"🌌 掃描銀河系 [{galaxy}:{system_start}] ~ [{galaxy}:{system_end}]...")

    all_systems = []
    inactive_targets = []

    for sys_num in range(system_start, system_end + 1):
        print(f"📡 正在掃描系統 [{galaxy}:{sys_num}]...")
        js_code = """
        (function() {
            var parsedRows = [];
            var contentRows = document.querySelectorAll('#galaxyContent tr.ctContentRow, .galaxyRow.ctContentRow');
            contentRows.forEach(function(r, idx) {
                var pos = r.id.replace('galaxyRow', '').trim() || String(idx + 1);
                var text = r.innerText.replace(/\\s+/g, ' ').trim();
                var isEmpty = r.className.includes('empty_filter') || text === pos || text === '';
                var isNewbie = r.className.includes('newbie_filter') || text.includes('(n)');
                var isInactive = r.className.includes('inactive_filter') || text.includes('(i)');
                var isLongInactive = r.className.includes('longinactive_filter') || text.includes('(I)');
                var isVacation = r.className.includes('vacation_filter') || text.includes('(v)');
                var isStrong = r.className.includes('strong_filter') || text.includes('(s)');
                var isBanned = text.includes('(b)');
                var myPlayerName = (document.querySelector('meta[name="ogame-player-name"]') ? document.querySelector('meta[name="ogame-player-name"]').content : '') || (document.querySelector('#bar #playerName, .playerName') ? document.querySelector('#bar #playerName, .playerName').innerText.trim() : '');
                var isSelf = Boolean(myPlayerName && text.includes(myPlayerName)) || r.classList.contains('my_planets') || (r.querySelector('.cellPlayerName .self, .playername .self') !== null);

                var planetEl = r.querySelector('.planetname, [data-planet-id], .cellPlanetName');
                var playerEl = r.querySelector('.playername, .cellPlayerName');
                var allyEl = r.querySelector('.allytag, .cellAlliance');
                var debrisEl = r.querySelector('.debris, .cellDebris');
                var planetName = planetEl ? planetEl.innerText.trim() : (isEmpty ? '（空位）' : '');
                var playerName = playerEl ? playerEl.innerText.trim() : '';

                var isDestroyed = text.includes('已毀滅') || planetName.includes('已毀滅');

                var statusLabel = "🪐 活躍玩家";
                if (isEmpty) statusLabel = "🌱 空位";
                else if (isSelf) statusLabel = "🏠 自有星球";
                else if (isDestroyed) statusLabel = "💥 已毀滅行星";
                else if (isVacation) statusLabel = "🏖️ 假期模式 (v)";
                else if (isLongInactive) statusLabel = "💀 長期死羊 (I)";
                else if (isInactive) statusLabel = "🐑 閒置死羊 (i)";
                else if (isNewbie) statusLabel = "🛡️ 新手保護 (n)";
                else if (isStrong) statusLabel = "⚔️ 強保護 (s)";

                parsedRows.push({
                    position: parseInt(pos, 10),
                    raw: text,
                    is_empty: isEmpty,
                    is_newbie: isNewbie,
                    is_inactive: isInactive,
                    is_long_inactive: isLongInactive,
                    is_vacation: isVacation,
                    is_strong: isStrong,
                    is_self: isSelf,
                    is_destroyed: isDestroyed,
                    is_farmable_sheep: (isInactive || isLongInactive) && !isVacation && !isSelf && !isDestroyed,
                    status_label: statusLabel,
                    planet: planetName,
                    player: playerName,
                    alliance: allyEl ? allyEl.innerText.trim() : '',
                    debris: debrisEl ? debrisEl.innerText.trim() : ''
                });
            });

            return JSON.stringify({
                count: parsedRows.length,
                rows: parsedRows
            });
        })()
        """
        url = game_url("galaxy", planet_id, galaxy=galaxy, system=sys_num)
        res = _get_dep('execute_in_game_tab', execute_in_game_tab)(js_code, target_url=url)
        rows = res.get("rows", []) if isinstance(res, dict) else []
        all_systems.append({"system": sys_num, "rows": rows})

        for r in rows:
            if r.get("is_farmable_sheep"):
                target_coord = f"[{galaxy}:{sys_num}:{r.get('position')}]"
                inactive_targets.append({
                    "coords": target_coord,
                    "galaxy": galaxy,
                    "system": sys_num,
                    "position": r.get("position"),
                    "player": r.get("player"),
                    "status": r.get("status_label"),
                    "planet": r.get("planet"),
                    "debris": r.get("debris")
                })
                print(f"🎯 發現死羊目標: {target_coord} | 玩家: {r.get('player')} | 狀態: {r.get('status_label')}")

        if sys_num < system_end:
            time.sleep(1.5)

    print(f"\n=======================================================")
    print(f"🌌 【銀河系 [{galaxy}:{system_start}] ~ [{galaxy}:{system_end}] 掃描結算】")
    print(f"📊 掃描系統數: {len(all_systems)} | 發現閒置死羊數: {len(inactive_targets)}")
    print(f"{'目標座標':<12} | {'玩家名稱':<16} | {'狀態標籤':<16} | {'星球名稱'}")
    print("-" * 65)
    for t in inactive_targets:
        print(f"{t['coords']:<12} | {t['player']:<16} | {t['status']:<16} | {t['planet']}")
    if not inactive_targets:
        print("（目前周邊系統無 (i)/(I) 標籤之閒置死羊）")
    print("=======================================================\n")

    return {
        "success": True,
        "galaxy": galaxy,
        "system_start": system_start,
        "system_end": system_end,
        "inactive_targets": inactive_targets,
        "all_systems": all_systems
    }


def cmd_find_colonies(args) -> Dict[str, Any]:
    """Scan and list available 8th position (or specified position) colony slots in given range."""
    galaxy = int(getattr(args, "galaxy", 1) or 1)
    system_start = int(getattr(args, "system", 1) or 1)
    system_end = int(getattr(args, "system_end", None) or system_start)
    target_pos = int(getattr(args, "position", 8) or 8)
    planet_id = int(args.planet_id)

    ref_sys = system_start
    try:
        from .browser import read_planets
        for p in read_planets():
            if int(p.get("id", 0)) == planet_id:
                m = re.search(r"\[?\d+:(\d+):\d+\]?", str(p.get("coords", "")))
                if m:
                    ref_sys = int(m.group(1))
                break
    except Exception:
        pass

    print(f"🔭 搜尋可殖民第 {target_pos} 號位：銀河系 [{galaxy}:{system_start}] ~ [{galaxy}:{system_end}]...")

    results = []

    for sys_num in range(system_start, system_end + 1):
        js_code = f"""
        (function() {{
            var contentRows = Array.from(document.querySelectorAll('#galaxyContent tr.ctContentRow, .galaxyRow.ctContentRow'));
            var targetRow = contentRows.find(function(r, idx) {{
                var pos = r.id.replace('galaxyRow', '').trim() || String(idx + 1);
                return parseInt(pos, 10) === {target_pos};
            }});

            var totalPlanets = contentRows.filter(function(r) {{
                return !r.className.includes('empty_filter') && r.innerText.trim().length > 3;
            }}).length;

            if (!contentRows.length || !targetRow) {{
                return JSON.stringify({{ success: false, exists: false, is_empty: false, colonizable: false, reason: 'target_row_missing', total_planets: totalPlanets }});
            }}

            var text = targetRow.innerText.replace(/\\s+/g, ' ').trim();
            var isEmpty = targetRow.className.includes('empty_filter') || text === '{target_pos}' || text === '';
            var isDestroyed = text.includes('已毀滅') || text.includes('détruite');
            var isInactive = targetRow.className.includes('inactive_filter') || text.includes('(i)');
            var isLongInactive = targetRow.className.includes('longinactive_filter') || text.includes('(I)');
            var isNewbie = targetRow.className.includes('newbie_filter') || text.includes('(n)');
            var isVacation = targetRow.className.includes('vacation_filter') || text.includes('(v)');
            var myPlayerName = (document.querySelector('meta[name="ogame-player-name"]') ? document.querySelector('meta[name="ogame-player-name"]').content : '') || (document.querySelector('#bar #playerName, .playerName') ? document.querySelector('#bar #playerName, .playerName').innerText.trim() : '');
            var isSelf = Boolean(myPlayerName && text.includes(myPlayerName)) || targetRow.classList.contains('my_planets') || (targetRow.querySelector('.cellPlayerName .self, .playername .self') !== null);

            var planetEl = targetRow.querySelector('.planetname, [data-planet-id], .cellPlanetName');
            var playerEl = targetRow.querySelector('.playername, .cellPlayerName');
            var planetName = planetEl ? planetEl.innerText.trim() : (isEmpty ? '（空位）' : '');
            var playerName = playerEl ? playerEl.innerText.trim() : '';

            var status = "🌱 完全空位 (可立即殖民)";
            var colonizable = true;
            if (isSelf) {{ status = "🏠 自有星球"; colonizable = false; }}
            else if (isDestroyed) {{ status = "💥 已毀滅行星 (暫不可殖民)"; colonizable = false; }}
            else if (!isEmpty) {{ status = "🪐 已被佔領 (" + playerName + ")"; colonizable = false; }}

            return JSON.stringify({{
                exists: true,
                is_empty: isEmpty,
                is_destroyed: isDestroyed,
                colonizable: colonizable,
                status: status,
                planet: planetName,
                player: playerName,
                total_planets: totalPlanets,
                raw: text
            }});
        }})()
        """
        url = game_url("galaxy", planet_id, galaxy=galaxy, system=sys_num)
        res = _get_dep('execute_in_game_tab', execute_in_game_tab)(js_code, target_url=url, wait_after_nav=1.2)
        if isinstance(res, dict):
            status = res.get("status", "🌱 完全空位 (可立即殖民)" if res.get("is_empty") else "🪐 已被佔領")
            colonizable = bool(
                res.get("success", True)
                and res.get("colonizable", False)
                and res.get("is_empty") is True
                and not res.get("is_destroyed", False)
            )
            total_planets = res.get("total_planets", 0)
            dist = abs(sys_num - ref_sys)
            results.append({
                "coords": f"[{galaxy}:{sys_num}:{target_pos}]",
                "system": sys_num,
                "position": target_pos,
                "status": status,
                "colonizable": colonizable,
                "total_planets": total_planets,
                "distance": dist,
                "player": res.get("player", "")
            })

    print(f"\n=======================================================")
    print(f"🎯 【銀河系 [{galaxy}:{system_start}] ~ [{galaxy}:{system_end}] 第 {target_pos} 號位殖民點排查總結】")
    print(f"{'目標座標':<12} | {'距離來源星':<8} | {'8號位狀態':<26} | {'該系總行星數':<10} | {'推薦指數'}")
    print("-" * 75)
    for r in results:
        rec = "⭐⭐⭐⭐⭐ 首選" if r.get("colonizable") and r.get("total_planets", 0) <= 2 else ("⭐⭐⭐⭐ 推薦" if r.get("colonizable") else "❌ 不可殖民")
        print(f"{r.get('coords'):<12} | {r.get('distance'):<6} 系統 | {r.get('status'):<26} | {r.get('total_planets', 0):<8} 顆 | {rec}")
    print("=======================================================\n")

    return {"success": True, "target_position": target_pos, "results": results}


def cmd_spy(args) -> Dict[str, Any]:
    """Dispatch 1 espionage probe to target coordinates."""
    require_confirmed_mutation(args)
    planet_id = int(args.planet_id)
    plan = _get_dep('create_fleet_confirmed_plan', create_fleet_confirmed_plan)(args, "spy")
    candidate = plan["candidates"][0]
    return _get_dep('command_apply', command_apply)(
        argparse.Namespace(
            plan_id=plan["plan_id"],
            action_id=candidate["action_id"],
            planet_id=planet_id,
            run_id=args.run_id,
            confirm=True,
            output=getattr(args, "output", "human"),
        )
    )


def cmd_raid(args) -> Dict[str, Any]:
    """Dispatch cargo ships to attack/harvest an inactive target."""
    require_confirmed_mutation(args)
    planet_id = int(args.planet_id)
    plan = _get_dep('create_fleet_confirmed_plan', create_fleet_confirmed_plan)(args, "raid")
    candidate = plan["candidates"][0]
    return _get_dep('command_apply', command_apply)(
        argparse.Namespace(
            plan_id=plan["plan_id"],
            action_id=candidate["action_id"],
            planet_id=planet_id,
            run_id=args.run_id,
            confirm=True,
            output=getattr(args, "output", "human"),
        )
    )


def cmd_expedition(args) -> Dict[str, Any]:
    """Dispatch expedition fleet to position 16 (Slot 16 deep space)."""
    require_confirmed_mutation(args)
    planet_id = int(args.planet_id)
    args.position = 16
    plan = _get_dep('create_fleet_confirmed_plan', create_fleet_confirmed_plan)(args, "expedition")
    candidate = plan["candidates"][0]
    return _get_dep('command_apply', command_apply)(
        argparse.Namespace(
            plan_id=plan["plan_id"],
            action_id=candidate["action_id"],
            planet_id=planet_id,
            run_id=args.run_id,
            confirm=True,
            output=getattr(args, "output", "human"),
        )
    )


def cmd_lifeform_explore(args) -> Dict[str, Any]:
    """Dispatch lifeform discovery mission to target coordinates via Galaxy view."""
    require_confirmed_mutation(args)
    planet_id = int(args.planet_id)
    galaxy = int(args.galaxy)
    system = int(args.system)
    position = int(args.position)

    target_url = game_url("galaxy", planet_id, galaxy=galaxy, system=system)
    discovery_url = game_url("fleetdispatch", action="sendDiscoveryFleet", asJson=1)
    js_code = f"""
    (function() {{
        var script = document.createElement('script');
        script.textContent = `
            (function() {{
                var targetPos = {position};
                var btn = document.querySelector('.planetDiscover.position' + targetPos);
                if (btn && !btn.classList.contains('disabled') && !btn.classList.contains('cooldown') && !btn.classList.contains('gray')) {{
                    btn.click();
                    document.documentElement.setAttribute('data-explore-res', JSON.stringify({{success: true, dispatched: true, target_pos: targetPos}}));
                }} else if (typeof discoverPlanet === 'function' && typeof token !== 'undefined') {{
                    var url = '{discovery_url}';
                    discoverPlanet(url, {{galaxy: {galaxy}, system: {system}, position: targetPos, token: token}});
                    document.documentElement.setAttribute('data-explore-res', JSON.stringify({{success: true, dispatched: true, target_pos: targetPos}}));
                }} else {{
                    document.documentElement.setAttribute('data-explore-res', JSON.stringify({{success: false, reason: 'button_or_func_not_found', target_pos: targetPos}}));
                }}
            }})();
        `;
        document.documentElement.appendChild(script);
        script.remove();
        return document.documentElement.getAttribute('data-explore-res');
    }})()
    """
    res = _get_dep('execute_in_game_tab', execute_in_game_tab)(js_code, target_url=target_url, wait_after_nav=3.0)
    if isinstance(res, str):
        try:
            res = json.loads(res)
        except Exception:
            pass
    if not isinstance(res, dict) or not res.get("success"):
        return {"success": False, "reason": res.get("reason", "dispatch_failed") if isinstance(res, dict) else "execution_error"}

    time.sleep(1.5)
    # Check for daily cap Toast
    check_toast_js = """
    (function() {
        var toasts = Array.from(document.querySelectorAll('.fadeBox, .toast, .ui-dialog-content, #errorBoxNotify'));
        var toastText = toasts.map(function(t) { return t.innerText || ''; }).join(' ');
        var limitReached = toastText.includes('上限') || toastText.includes('limit reached') || toastText.includes('額度已滿');
        return JSON.stringify({limit_reached: limitReached, raw_toast: toastText.trim()});
    })()
    """
    toast_res = _get_dep('execute_in_game_tab', execute_in_game_tab)(check_toast_js)
    if isinstance(toast_res, dict) and toast_res.get("limit_reached"):
        return {"success": False, "reason": "daily_limit_reached", "detail": toast_res.get("raw_toast")}

    return {"success": True, "target": f"[{galaxy}:{system}:{position}]", "mission": "lifeform_explore"}


def cmd_auto_fill_slots(args) -> Dict[str, Any]:
    """Auto-fill remaining fleet slots using Lifeform Discoveries via Galaxy header '發現' button or single dispatch."""
    require_confirmed_mutation(args)
    planet_id = int(args.planet_id)

    # 1. Read current fleet slots
    fleet_state = read_fleet_state(planet_id)
    slots = fleet_state.get("fleet_slots") or {}
    free_slots = int(slots.get("free", 0) or 0)
    slots_to_fill = free_slots - 1  # Always preserve 1 slot for Fleetsave

    if slots_to_fill <= 0:
        print(f"✅ 艦隊槽位已達極致滿載狀態（可用槽位: {free_slots}，保留 1 槽避難，無需補位）。")
        return {"success": True, "filled": 0, "free_slots": free_slots, "message": "all_slots_utilized"}

    # 2. Deuterium safeguard check (Empire deut < 50,000 or source planet < 5,000)
    res = fleet_state.get("resources") or {}
    deut = int(res.get("deuterium", 0) or 0)
    empire_deut = 0
    try:
        scout_path = Path(__file__).resolve().parent.parent / "runtime" / "memory" / "scout-report.json"
        if scout_path.exists():
            with open(scout_path, "r", encoding="utf-8") as f:
                sdata = json.load(f)
                empire_deut = int(sdata.get("totals", {}).get("resources", {}).get("deuterium", 0) or 0)
    except Exception:
        pass

    if empire_deut > 0 and empire_deut < 50000:
        print(f"⚠️ 全帝國重氫為 {empire_deut} < 50,000，觸發重氫蓄水保衛機制，暫緩自動探索補滿。")
        return {"success": True, "filled": 0, "free_slots": free_slots, "reason": "empire_deuterium_below_safeguard"}
    if deut < 5000:
        print(f"⚠️ 來源星重氫為 {deut} < 5,000，重氫不足以支應探索，暫緩自動探索補滿。")
        return {"success": True, "filled": 0, "free_slots": free_slots, "reason": "planet_deuterium_insufficient"}

    print(f"🚀 啟動結尾槽位動態收斂閘門：當前可用槽位 {free_slots}，需補滿 {slots_to_fill} 隊生命形式探索...")

    center_sys = 1
    try:
        from .browser import read_planets
        planets = read_planets()
        for p in planets:
            if int(p.get("id", 0)) == planet_id:
                coords = p.get("coords", "")
                m = re.search(r"\[?\d+:(\d+):\d+\]?", str(coords))
                if m:
                    center_sys = int(m.group(1))
                break
    except Exception:
        pass

    search_systems = [center_sys]
    for d in range(1, 11):
        if center_sys - d >= 1:
            search_systems.append(center_sys - d)
        if center_sys + d <= 499:
            search_systems.append(center_sys + d)

    filled = 0
    for sys_num in search_systems:
        # Re-check current fleet slots dynamically before searching next system
        curr_fleet = read_fleet_state(planet_id)
        curr_slots = curr_fleet.get("fleet_slots") or {}
        curr_free = int(curr_slots.get("free", 0) or 0)
        if curr_free <= 1:
            print(f"🎯 艦隊槽位已收斂至極致滿載（剩餘可用: {curr_free}，保留 1 槽避難）。")
            break

        galaxy_url = game_url("galaxy", planet_id, galaxy=1, system=sys_num)

        # Try Galaxy header '發現' button (#discoverSystemBtn) in main world
        try_sys_btn_js = """
        (function() {
            var script = document.createElement('script');
            script.textContent = `
                (function() {
                    window.__sys_disc_res = null;
                    $(document).one('ajaxSuccess', function(event, xhr, settings) {
                        if (settings.url && settings.url.includes('sendSystemDiscoveryFleet')) {
                            try {
                                window.__sys_disc_res = JSON.parse(xhr.responseText);
                            } catch(e) {
                                window.__sys_disc_res = {raw: xhr.responseText};
                            }
                        }
                    });
                    var btn = document.querySelector('#discoverSystemBtn');
                    if (btn && !btn.getAttribute('disabled')) {
                        btn.click();
                    } else if (typeof sendSystemDiscoveryMission === 'function') {
                        sendSystemDiscoveryMission();
                    } else {
                        window.__sys_disc_res = {skipped: true, reason: 'btn_disabled_or_unavailable'};
                    }
                })();
            `;
            document.documentElement.appendChild(script);
            script.remove();
            return JSON.stringify({triggered: true});
        })()
        """
        _get_dep('execute_in_game_tab', execute_in_game_tab)(try_sys_btn_js, target_url=galaxy_url, wait_after_nav=3.0)
        time.sleep(2.5)

        read_res_js = """
        (function() {
            var script = document.createElement('script');
            script.textContent = `
                document.documentElement.setAttribute('data-sys-disc-res', JSON.stringify(window.__sys_disc_res));
            `;
            document.documentElement.appendChild(script);
            script.remove();
            return document.documentElement.getAttribute('data-sys-disc-res');
        })()
        """
        disc_raw = _get_dep('execute_in_game_tab', execute_in_game_tab)(read_res_js)
        disc_data = {}
        if isinstance(disc_raw, str):
            try:
                disc_data = json.loads(disc_raw)
            except Exception:
                pass
        elif isinstance(disc_raw, dict):
            disc_data = disc_raw

        resp_obj = disc_data.get("response") if isinstance(disc_data, dict) else {}
        ships_sent = resp_obj.get("shipsSent", 0) if isinstance(resp_obj, dict) else 0

        if ships_sent > 0:
            filled += ships_sent
            print(f"✨ 星系 [1:{sys_num}] 一鍵【發現】成功派遣 {ships_sent} 隊生命形式探索！")
            time.sleep(2.0)
            continue
        elif disc_data.get("skipped"):
            print(f"⏩ 星系 [1:{sys_num}] 【發現】按鈕冷卻中或無可用探索點，嘗試下一個星系。")
            continue

    print(f"🎯 槽位收斂結算完畢：本輪共補發 {filled} 隊生命形式探索！")
    return {"success": True, "filled": filled, "slots_to_fill": slots_to_fill}



def cmd_spy_reports(args) -> Dict[str, Any]:
    """Read and parse all espionage reports from OGame messages tab."""
    planet_id = int(args.planet_id)
    target_msg_id = getattr(args, "msg_id", None)
    print(f"📬 正在讀取並解析間諜偵察報告 (Messages Espionage, target_msg_id={target_msg_id})...")

    constants = load_account_constants(getattr(args, "constants", DEFAULT_CONSTANTS_PATH))
    SMALL_CARGO_CAPACITY = constants.cargo_capacity("202")
    LARGE_CARGO_CAPACITY = constants.cargo_capacity("203")

    ajax_messages_url = f"{GAME_BASE_URL}?page=ajax&component=messages&tab=20&subtab=20"
    ajax_details_url = f"{GAME_BASE_URL}?page=ajax&component=messagedetails&messageId="

    js_code = r"""
    (function() {
        var targetMsgId = %s;
        var msgIds = [];
        if (targetMsgId) {
            msgIds = [targetMsgId];
        } else {
            var tabs = Array.from(document.querySelectorAll('.subtabs li, .tabs_bb li, [data-tab-id], .tabItem, [data-subtab-id]')).map(function(el) {
            return {
                text: el.innerText.trim(),
                tabId: el.getAttribute('data-tab-id'),
                subtabId: el.getAttribute('data-subtab-id'),
                className: el.className
            };
        });
        var raw = Array.from(document.querySelectorAll('[data-msg-id]'))
            .map(function(r) { return parseInt(r.getAttribute('data-msg-id'), 10); })
            .filter(function(id) { return id && !isNaN(id); });
        if (!raw.length) {
            try {
                var listXhr = new XMLHttpRequest();
                listXhr.open('GET', %s, false);
                listXhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
                listXhr.send();
                var listDiv = document.createElement('div');
                listDiv.innerHTML = listXhr.responseText;
                raw = Array.from(listDiv.querySelectorAll('[data-msg-id]'))
                    .map(function(r) { return parseInt(r.getAttribute('data-msg-id'), 10); })
                    .filter(function(id) { return id && !isNaN(id); });
            } catch(e) {}
        }
        msgIds = Array.from(new Set(raw)).sort(function(a, b) { return b - a; }).slice(0, 8);
        }

        var parsedReports = [];

        msgIds.forEach(function(msgId) {
            // Synchronously fetch full report details
            try {
                var xhr = new XMLHttpRequest();
                xhr.open('GET', %s + msgId, false);
                xhr.send();

                var tempDiv = document.createElement('div');
                tempDiv.innerHTML = xhr.responseText;
                var text = tempDiv.innerText.replace(/\s+/g, ' ').trim();

                var coordsMatch = text.match(/\[([0-9]+:[0-9]+:[0-9]+)\]/);
                var coords = coordsMatch ? '[' + coordsMatch[1] + ']' : '';
                var targetNameMatch = text.match(/間諜偵察報告\s+([^\[\]]+)/) || text.match(/報告\s+([^\[\]]+)/) || text.match(/來自\s+([^\[\]]+)/);
                var targetName = targetNameMatch ? targetNameMatch[1].trim() : '';

                var dateMatch = text.match(/([0-9]{2}\.[0-9]{2}\.[0-9]{4}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})/);
                var reportDate = dateMatch ? dateMatch[1] : '';

                // Extract resources via regex on text
                var mMatch = text.match(/金屬\s*([0-9.,]+)/) || text.match(/Metal\s*([0-9.,]+)/i);
                var cMatch = text.match(/晶體\s*([0-9.,]+)/) || text.match(/Crystal\s*([0-9.,]+)/i);
                var dMatch = text.match(/重氫\s*([0-9.,]+)/) || text.match(/Deuterium\s*([0-9.,]+)/i);

                var metal = mMatch ? parseInt(mMatch[1].replace(/[^0-9]/g, ''), 10) || 0 : 0;
                var crystal = cMatch ? parseInt(cMatch[1].replace(/[^0-9]/g, ''), 10) || 0 : 0;
                var deuterium = dMatch ? parseInt(dMatch[1].replace(/[^0-9]/g, ''), 10) || 0 : 0;

                var totalRes = metal + crystal + deuterium;
                var lootM = Math.floor(metal / 2);
                var lootC = Math.floor(crystal / 2);
                var lootD = Math.floor(deuterium / 2);
                var totalLoot = lootM + lootC + lootD;

                // Defense check
                var hasDefense = false;
                var defenseCount = 0;
                var defDetails = [];
                var defKeywords = ['火箭發射器', '輕型雷射', '重型雷射', '高斯砲', '離子砲', '等離子砲', '小型防護罩', '大型防護罩', '飛彈發射器'];
                defKeywords.forEach(function(kw) {
                    var reg = new RegExp(kw + '\\s*([0-9]+)', 'i');
                    var m = text.match(reg);
                    if (m) {
                        var count = parseInt(m[1], 10) || 0;
                        if (count > 0) {
                            hasDefense = true;
                            defenseCount += count;
                            defDetails.push(kw + ' x' + count);
                        }
                    }
                });

                // Fleet check
                var hasFleet = false;
                var fleetCount = 0;
                var fleetDetails = [];
                var shipKeywords = ['小型運輸艦', '大型運輸艦', '輕型戰鬥機', '重型戰鬥機', '巡洋艦', '戰列艦', '殖民船', '回收船', '間諜探測機', '轟炸機', '太陽能衛星', '驅逐艦', '死星', '戰鬥巡洋艦', '收割者', '探路者'];
                shipKeywords.forEach(function(kw) {
                    var reg = new RegExp(kw + '\\s*([0-9]+)', 'i');
                    var m = text.match(reg);
                    if (m) {
                        var count = parseInt(m[1], 10) || 0;
                        if (count > 0 && kw !== '太陽能衛星') {
                            hasFleet = true;
                            fleetCount += count;
                            fleetDetails.push(kw + ' x' + count);
                        }
                    }
                });

                // Mine building levels
                var metalMineMatch = text.match(/金屬礦\s*([0-9]+)/);
                var crystalMineMatch = text.match(/晶體礦\s*([0-9]+)/);
                var deutSynthMatch = text.match(/重氫合成器\s*([0-9]+)/);
                var metalMineLvl = metalMineMatch ? parseInt(metalMineMatch[1], 10) : 0;
                var crystalMineLvl = crystalMineMatch ? parseInt(crystalMineMatch[1], 10) : 0;
                var deutSynthLvl = deutSynthMatch ? parseInt(deutSynthMatch[1], 10) : 0;
                var hasBuildingsScanned = (metalMineLvl > 0 || crystalMineLvl > 0 || deutSynthLvl > 0 || /建築物/.test(text));

                // Explicit zero or scan level proof:
                // If buildings were scanned (diff >= 5), fleet (diff 2) & defense (diff 3) are guaranteed scanned
                var defenseExplicitZero = /(?:防禦|Defense)\s*(?:[:：]|總數|Total)?\s*0(?:\D|$)/i.test(text) || (hasBuildingsScanned && !hasDefense);
                var fleetExplicitZero = /(?:艦隊|Fleet)\s*(?:[:：]|總數|Total)?\s*0(?:\D|$)/i.test(text) || (hasBuildingsScanned && !hasFleet);
                var defenseEvidenceComplete = hasDefense || defenseExplicitZero;
                var fleetEvidenceComplete = hasFleet || fleetExplicitZero;

                parsedReports.push({
                    msg_id: String(msgId),
                    coords: coords,
                    target_name: targetName,
                    date: reportDate,
                    metal: metal,
                    crystal: crystal,
                    deuterium: deuterium,
                    total_resources: totalRes,
                    loot_metal: lootM,
                    loot_crystal: lootC,
                    loot_deuterium: lootD,
                    total_loot: totalLoot,
                    sc_needed: Math.ceil(totalLoot / %d) || 1,
                    lc_needed: Math.ceil(totalLoot / %d) || 1,
                    has_defense: hasDefense,
                    defense_count: defenseCount,
                    defense_details: defDetails.join(', ') || (defenseExplicitZero ? '明確為 0' : '未知'),
                    defense_evidence_complete: defenseEvidenceComplete,
                    has_fleet: hasFleet,
                    fleet_count: fleetCount,
                    fleet_details: fleetDetails.join(', ') || (fleetExplicitZero ? '明確為 0' : '未知'),
                    fleet_evidence_complete: fleetEvidenceComplete,
                    has_buildings_scanned: hasBuildingsScanned,
                    metal_mine: metalMineLvl,
                    crystal_mine: crystalMineLvl,
                    deut_synth: deutSynthLvl,
                    is_safe_to_farm: !hasDefense && !hasFleet && (defenseExplicitZero || hasBuildingsScanned),
                    raw: text.slice(0, 600)
                });
            } catch(err) {
                parsedReports.push({
                    msg_id: String(msgId),
                    error: err.toString()
                });
            }
        });

        return JSON.stringify({
            success: true,
            url: window.location.href,
            tabs: typeof tabs !== 'undefined' ? tabs : [],
            count: parsedReports.length,
            reports: parsedReports
        });
    })()
    """ % (json.dumps(target_msg_id), json.dumps(ajax_messages_url), json.dumps(ajax_details_url), int(SMALL_CARGO_CAPACITY), int(LARGE_CARGO_CAPACITY))

    url = game_url("messages", planet_id, tab=20)
    res = _get_dep('execute_in_game_tab', execute_in_game_tab)(
        js_code,
        target_url=url,
        wait_after_nav=2.0
    )
    if isinstance(res, dict) and "reports" in res:
        print(f"\n=======================================================")
        print(f"📋 【最新間諜報告總覽】(解析到 {res.get('count', 0)} 份報告)")
        print(f"{'目標座標':<12} | {'總資源':<8} | {'50%掠奪 (M/C/D)':<28} | {'防禦':<8} | {'艦隊':<8} | {'安全性'}")
        print("-" * 85)
        for r in res.get("reports", []):
            safe_str = "✅ 已確認 0 防禦/0 艦隊" if r.get("is_safe_to_farm") else "⛔ 證據不足或有防禦/艦隊"
            loot_str = f"{r.get('total_loot', 0):,} (M:{r.get('loot_metal', 0):,} C:{r.get('loot_crystal', 0):,} D:{r.get('loot_deuterium', 0):,})"
            print(f"{r.get('coords', 'N/A'):<12} | {r.get('total_resources', 0):<8} | {loot_str:<28} | {r.get('defense_details', '0'):<8} | {r.get('fleet_details', '0'):<8} | {safe_str}")
    if isinstance(res, dict):
        print(f"URL: {res.get('url')}")
        print(f"Tabs: {json.dumps(res.get('tabs', []))}")
        print("Top Reports:")
        for r in res.get("reports", []):
            print(f"  {r.get('coords')} | {r.get('date')} | loot: {r.get('total_loot')} | def: {r.get('defense_count')} | fleet: {r.get('fleet_count')} | safe: {r.get('is_safe_to_farm')}")
    return res


def cmd_events(args) -> Dict[str, Any]:
    """Read active fleet movements / event list from the OGame UI."""
    js_code = """
    (function() {
        var events = [];
        var rows = document.querySelectorAll('#eventTable tr.eventFleet, #eventContent tr.eventFleet, .eventFleet');
        rows.forEach(function(row) {
            events.push({
                id: row.id || '',
                text: row.innerText.replace(/\\s+/g, ' ').trim()
            });
        });

        var countEl = document.querySelector('#js_eventDetailsClosed, #eventboxContent');
        var summary = countEl ? countEl.innerText.replace(/\\s+/g, ' ').trim() : '';

        return JSON.stringify({
            success: true,
            summary: summary,
            count: events.length,
            events: events
        });
    })()
    """
    url = game_url("movement", getattr(args, "planet_id", None))
    res = _get_dep('execute_in_game_tab', execute_in_game_tab)(js_code, target_url=url)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return res


def cmd_messages(args) -> Dict[str, Any]:
    """Read recent messages and combat/espionage reports from OGame."""
    js_code = """
    (function() {
        var msgs = [];
        var rows = document.querySelectorAll('li.msg[data-msg-id], tr[data-msg-id], .msg[data-msg-id], .message_item');
        rows.forEach(function(row) {
            var msgId = row.getAttribute('data-msg-id') || row.id || '';
            var titleEl = row.querySelector('.msg_title, .subject, .msgHead');
            var title = titleEl ? titleEl.innerText.replace(/\\s+/g, ' ').trim() : '';
            var dateEl = row.querySelector('.msg_date, .date');
            var date = dateEl ? dateEl.innerText.replace(/\\s+/g, ' ').trim() : '';
            var content = row.innerText.replace(/\\s+/g, ' ').trim().slice(0, 200);
            msgs.push({
                msg_id: msgId,
                title: title,
                date: date,
                summary: content
            });
        });
        return JSON.stringify({
            success: true,
            count: msgs.length,
            messages: msgs
        });
    })()
    """
    url = game_url("messages", getattr(args, "planet_id", None))
    res = _get_dep('execute_in_game_tab', execute_in_game_tab)(js_code, target_url=url)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return res


def cmd_ships(args) -> Dict[str, Any]:
    """Read currently stationed ships and fleet slots from the fleetdispatch page."""
    js_code = r"""
    (function() {
        var ships = {};
        document.querySelectorAll('#shipsForm li.technology, #fleet1 li.technology, .military_fleet li.technology, .civil_fleet li.technology, li.technology').forEach(function(el) {
            var techId = el.getAttribute('data-technology');
            var amountEl = el.querySelector('.amount');
            var amount = amountEl ? parseInt(amountEl.innerText.replace(/[^0-9]/g, ''), 10) || 0 : 0;
            if (techId) {
                ships[techId] = {
                    tech_id: techId,
                    amount: amount
                };
            }
        });
        var slotEl = document.querySelector('#slots, #fleetSlots, .fleetSlots, [data-fleet-slots]');
        var slotText = slotEl ? (slotEl.getAttribute('data-fleet-slots') || slotEl.innerText || '') : '';
        var slotMatch = slotText.match(/([0-9]+)\s*\/\s*([0-9]+)/);
        var used = slotMatch ? Number(slotMatch[1]) : null;
        var total = slotMatch ? Number(slotMatch[2]) : null;
        return JSON.stringify({
            success: true,
            ships: ships,
            fleet_slots: {
                known: Boolean(slotMatch && total !== null && total >= used),
                used: used,
                total: total,
                free: (slotMatch && total !== null && total >= used) ? total - used : null,
                raw: slotText.replace(/\\s+/g, ' ').trim()
            }
        });
    })()
    """
    url = game_url("fleetdispatch", getattr(args, "planet_id", None))
    res = _get_dep('execute_in_game_tab', execute_in_game_tab)(js_code, target_url=url)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return res


def cmd_debug_page(args) -> Dict[str, Any]:
    """Inspect technology page on specified planet."""
    component = getattr(args, "component", "shipyard") or "shipyard"
    planet_id = getattr(args, "planet_id", None)
    js_code = """
    (function() {
        var satEl = document.querySelector('li.technology[data-technology="212"]');
        var satAmount = 0;
        if (satEl) {
            var amtEl = satEl.querySelector('.amount');
            satAmount = amtEl ? parseInt(amtEl.innerText.replace(/[^0-9]/g, ''), 10) || 0 : 0;
        }

        var queueBox = document.querySelector('#productionboxshipyardcomponent');
        var activeItem = null;
        var queueEntries = [];

        if (queueBox) {
            var activeTh = queueBox.querySelector('.construction.active th');
            var activeSum = queueBox.querySelector('.construction.active #shipSum, .construction.active .amount, .construction.active td.first');
            if (activeTh) {
                var sumMatch = (activeSum ? activeSum.innerText : '').match(/\\d+/);
                activeItem = {
                    name: activeTh.innerText.trim(),
                    amount: sumMatch ? parseInt(sumMatch[0], 10) : 0
                };
            }

            queueBox.querySelectorAll('tr:not(.data) td.tooltip, tr:not(.data) td').forEach(function(td) {
                var img = td.querySelector('img');
                var title = (img ? (img.getAttribute('title') || img.getAttribute('alt') || '') : '') || td.getAttribute('title') || '';
                var txt = td.innerText.replace(/[^0-9]/g, '');
                if (txt && title) {
                    queueEntries.push({
                        title: title,
                        amount: parseInt(txt, 10)
                    });
                }
            });
        }

        return JSON.stringify({
            existing_satellites: satAmount,
            active_item: activeItem,
            queue_entries: queueEntries
        });
    })()
    """
    res = _get_dep('execute_in_game_tab', execute_in_game_tab)(js_code, target_url=game_url(component, planet_id))
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return res







































def cmd_roi(args, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Provide objective candidate data and feasible knapsack bundles.
    Per architecture rules, Python performs NO subjective ROI scoring;
    all strategic prioritization is evaluated by the Agent.
    """
    planet_id = getattr(args, "planet_id", None)
    if planet_id is None:
        planets_data = cmd_list_planets(args)
        planets = planets_data.get("planets", [])
        if not planets:
            raise RuntimeError("找不到任何可用星球。")
        planet_id = planets[0]["id"]
    plan_args = argparse.Namespace(
        planet_id=planet_id,
        run_id=args.run_id,
        diagnose=getattr(args, "diagnose", False),
        output=getattr(args, "output", "human"),
    )
    print("\n💡 【0/1 背包可行組合與候選清單（Python 客觀計算，無 ROI 偏見）】")
    plan = _get_dep('command_plan', command_plan)(plan_args)
    return plan

def cmd_patrol(args):
    """Legacy read-only patrol wrapper; mutations require an external typed Intent."""
    gate = command_check_wake(argparse.Namespace(force=getattr(args, "force", False), acquire=True))
    run_id = str(gate["run_id"])
    try:
        if getattr(args, "all_planets", False):
            multi_state = cmd_sync_all(args)
            planets = multi_state.get("planets", [])
            if not planets:
                raise RuntimeError("patrol 沒有可規劃的星球。")
            planet_id = int(planets[0]["planet_id"])
        else:
            state = cmd_sync(args)
            planet_id = int(state["planet_id"])
        plan = _get_dep('command_plan', command_plan)(
            argparse.Namespace(
                planet_id=planet_id,
                run_id=run_id,
                diagnose=False,
                include_lifeforms=False,
                include_cancel=False,
                include_production=False,
                include_fleet=True,
                strategy=DEFAULT_STRATEGY_PATH,
                constants=DEFAULT_CONSTANTS_PATH,
                output="json",
                silent=True,
            )
        )
        result = {
            "success": True,
            "status": "read_only_plan_created",
            "plan_id": plan["plan_id"],
            "planet_id": plan["planet_id"],
            "candidate_count": len(plan.get("candidates", [])),
            "note": "legacy patrol 不會自行產生 Intent 或執行 mutation",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    finally:
        release_run_lease(run_id)

def calc_storage_capacity(level: int) -> int:
    """Calculate storage capacity based on official OGame formula."""
    import math
    if level <= 0:
        return 10000
    return int(5000 * math.floor(2.5 * math.exp(20 * level / 33)))

def cmd_storage(args):
    """Check storage capacity and usage percentages."""
    print("📦 正在查詢各資源儲存槽狀態與容量上限...")
    js_storage = """
    (function() {
        function getNum(sel) {
            var el = document.querySelector(sel);
            if (!el) return 0;
            var raw = el.getAttribute('data-raw') || el.innerText.replace(/,/g, '').replace(/\\./g, '').trim();
            var v = parseInt(raw, 10);
            return isNaN(v) ? 0 : v;
        }
        function getStorageLvl(id) {
            var el = document.querySelector("li.technology[data-technology='" + id + "'] .level, li.technology[data-technology='" + id + "'] .amount");
            return el ? parseInt(el.innerText.trim(), 10) || 0 : 0;
        }
        function getTooltip(sel) {
            var el = document.querySelector(sel);
            if (!el) return '';
            return el.getAttribute('title') || el.getAttribute('data-tooltip-title') || el.getAttribute('aria-label') || '';
        }
        return JSON.stringify({
            metal: getNum('#resources_metal'),
            crystal: getNum('#resources_crystal'),
            deuterium: getNum('#resources_deuterium'),
            metal_tip: getTooltip('#resources_metal'),
            crystal_tip: getTooltip('#resources_crystal'),
            deuterium_tip: getTooltip('#resources_deuterium'),
            m_lvl: getStorageLvl('22'),
            c_lvl: getStorageLvl('23'),
            d_lvl: getStorageLvl('24')
        });
    })()
    """
    res = _get_dep('execute_in_game_tab', execute_in_game_tab)(js_storage, target_url=game_url("supplies", getattr(args, "planet_id", None)))
    if not isinstance(res, dict):
        print("無法取得儲存槽資料:", res)
        return res

    m_cap = calc_storage_capacity(res.get('m_lvl', 0))
    c_cap = calc_storage_capacity(res.get('c_lvl', 0))
    d_cap = calc_storage_capacity(res.get('d_lvl', 0))

    m_pct = (res.get('metal', 0) / m_cap) * 100 if m_cap else 0
    c_pct = (res.get('crystal', 0) / c_cap) * 100 if c_cap else 0
    d_pct = (res.get('deuterium', 0) / d_cap) * 100 if d_cap else 0

    print(f"\n📦 【儲存槽與容量狀況】(標準 OGame 公式)")
    print(f"  🔹 金屬儲存槽 Lv.{res.get('m_lvl', 0):2d}: {res.get('metal', 0):>8,} / {m_cap:>8,} ({m_pct:5.1f}%) {'⚠️ 接近爆倉(>90%)' if m_pct >= 90 else '✅ 安全'}")
    print(f"  🔹 水晶儲存槽 Lv.{res.get('c_lvl', 0):2d}: {res.get('crystal', 0):>8,} / {c_cap:>8,} ({c_pct:5.1f}%) {'⚠️ 接近爆倉(>90%)' if c_pct >= 90 else '✅ 安全'}")
    print(f"  🔹 重氫儲存槽 Lv.{res.get('d_lvl', 0):2d}: {res.get('deuterium', 0):>8,} / {d_cap:>8,} ({d_pct:5.1f}%) {'⚠️ 接近爆倉(>90%)' if d_pct >= 90 else '✅ 安全'}")
    if res.get('metal_tip'):
        print(f"  ℹ️ 頂部資訊提示: 金屬提示={res.get('metal_tip')} | 水晶提示={res.get('crystal_tip')} | 重氫提示={res.get('deuterium_tip')}")
    return res
