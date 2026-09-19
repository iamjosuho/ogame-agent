"""Empire matrix extraction, official accountInfo projection, and multi-planet synchronization.

Provides single-page Empire reading, accountInfo rate enrichment, and the global matrix CLI.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional

from scripts.ogame.browser import (
    checked_js,
    empire_url,
    execute_checked_component,
    execute_in_game_tab,
    read_active_planet_context,
    read_technology_list,
)
from scripts.ogame.empire import (
    EMPIRE_STANDALONE_JS,
    enrich_empire_with_official,
    normalize_empire_snapshot,
)
from scripts.ogame.lifecycle import MEMORY_DIR, atomic_write_json
from scripts.ogame.probes import classify_external_data_export_response

OFFICIAL_SNAPSHOT_SCHEMA_VERSION = 1
OFFICIAL_RESOURCE_BUILDING_IDS = frozenset({"1", "2", "3", "4", "12", "22", "23", "24"})
RESOURCE_KEYS = ("metal", "crystal", "deuterium")


from scripts.ogame.resolver import get_dep, register_controller

_get_dep = get_dep


class SafetyStopError(RuntimeError):
    """A browser safety signal that must never be converted into a source fallback."""


def calc_storage_capacity(level: int) -> int:
    """Calculate storage capacity based on official OGame formula."""
    if level <= 0:
        return 10000
    return int(5000 * math.floor(2.5 * math.exp(20 * level / 33)))


def official_integer(value: Any, field: str) -> int:
    """Normalize a numeric official-export field without locale-string guessing."""
    if isinstance(value, bool) or value is None:
        raise RuntimeError(f"official accountInfo 缺少數值欄位：{field}")
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError(f"official accountInfo 數值欄位格式不符：{field}") from exc


def official_optional_integer(value: Any, field: str) -> Optional[int]:
    """Keep documented optional IDs nullable while validating any present value."""
    if value is None:
        return None
    return official_integer(value, field)


def official_integer_map(value: Any, field: str) -> Dict[str, int]:
    if value == []:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError(f"official accountInfo 缺少物件欄位：{field}")
    return {
        str(key): official_integer(item, f"{field}.{key}")
        for key, item in value.items()
    }


def normalize_number(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    import re
    digits = re.sub(r"[^0-9]", "", str(value))
    return int(digits) if digits else None


def resource_vector(value: Dict[str, Any]) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for key in RESOURCE_KEYS:
        parsed = normalize_number(value.get(key, 0))
        result[key] = parsed if parsed is not None else 0
    return result


def normalize_official_account_info(
    data: Dict[str, Any],
    planet_metadata: Optional[List[Dict[str, Any]]] = None,
    captured_at: Optional[int] = None,
) -> Dict[str, Any]:
    """Convert accountInfo into the versioned controller/MCP read contract."""
    if not isinstance(data, dict):
        raise RuntimeError("official accountInfo 回應不是 JSON object。")
    raw_planets = data.get("planets")
    if not isinstance(raw_planets, dict) or not raw_planets:
        raise RuntimeError("official accountInfo 未提供 planets，拒絕建立空快照。")

    metadata_by_id = {
        str(item.get("id")): item
        for item in (planet_metadata or [])
        if isinstance(item, dict) and str(item.get("id") or "").isdigit()
    }
    researches = official_integer_map(data.get("researches"), "researches")
    normalized_planets: List[Dict[str, Any]] = []
    for raw_key, raw_planet in raw_planets.items():
        if not isinstance(raw_planet, dict):
            raise RuntimeError(f"official accountInfo planets.{raw_key} 不是 JSON object。")
        planet_id = official_integer(raw_planet.get("id", raw_key), f"planets.{raw_key}.id")
        if str(planet_id) != str(raw_key):
            raise RuntimeError(f"official accountInfo 星球 key/id 不一致：{raw_key}/{planet_id}")
        galaxy = official_integer(raw_planet.get("galaxy"), f"planets.{raw_key}.galaxy")
        system = official_integer(raw_planet.get("system"), f"planets.{raw_key}.system")
        position = official_integer(raw_planet.get("position"), f"planets.{raw_key}.position")
        resources_raw = raw_planet.get("resources")
        production_raw = raw_planet.get("production")
        base_production_raw = raw_planet.get("baseProduction")
        if not isinstance(resources_raw, dict) or not isinstance(production_raw, dict) or not isinstance(base_production_raw, dict):
            raise RuntimeError(f"official accountInfo 星球 {planet_id} 缺少資源或產速欄位。")
        resources = {
            key: official_integer(resources_raw.get(key), f"planets.{raw_key}.resources.{key}")
            for key in RESOURCE_KEYS
        }
        production = {
            key: official_integer(production_raw.get(key), f"planets.{raw_key}.production.{key}")
            for key in RESOURCE_KEYS
        }
        base_production = {
            key: official_integer(base_production_raw.get(key), f"planets.{raw_key}.baseProduction.{key}")
            for key in RESOURCE_KEYS
        }
        metadata = metadata_by_id.get(str(planet_id), {})
        normalized_planets.append({
            "planet_id": str(planet_id),
            "name": metadata.get("name"),
            "coords": metadata.get("coords") or f"[{galaxy}:{system}:{position}]",
            "coordinates": {"galaxy": galaxy, "system": system, "position": position},
            "resources": resources,
            "energy": official_integer(resources_raw.get("energy"), f"planets.{raw_key}.resources.energy"),
            "production": production,
            "base_production": base_production,
            "buildings": official_integer_map(raw_planet.get("buildings"), f"planets.{raw_key}.buildings"),
            "ships": official_integer_map(raw_planet.get("ships"), f"planets.{raw_key}.ships"),
            "defenses": official_integer_map(raw_planet.get("defenses"), f"planets.{raw_key}.defenses"),
            "species_buildings": official_integer_map(raw_planet.get("speciesBuildings", {}), f"planets.{raw_key}.speciesBuildings"),
            "species_researches": official_integer_map(raw_planet.get("speciesResearches", {}), f"planets.{raw_key}.speciesResearches"),
        })

    normalized_planets.sort(key=lambda item: int(item["planet_id"]))
    return {
        "schema_version": OFFICIAL_SNAPSHOT_SCHEMA_VERSION,
        "source": "official.accountInfo",
        "captured_at": int(captured_at if captured_at is not None else time.time()),
        "account": {
            "player_id": str(official_integer(data.get("playerId"), "playerId")),
            "character_class_id": official_optional_integer(data.get("characterClassId"), "characterClassId"),
            "alliance_class_id": official_optional_integer(data.get("allianceClassId"), "allianceClassId"),
            "officers": {
                key: bool((data.get("officers") or {}).get(key, False))
                for key in ("commander", "admiral", "engineer", "geologist", "technocrat")
            },
            "researches": researches,
        },
        "planet_count": len(normalized_planets),
        "planets": normalized_planets,
        "queue_coverage": "not_provided",
    }


def external_data_export_fetch_js(action: str) -> str:
    path_json = json.dumps(f"/game/index.php?page=standalone&component=externaldataexport&action={action}&asJson=1")
    return f"""
    (function() {{
        window.__ogameExternalExportRead = {{done:false, started_at:Date.now(), response:null}};
        var requestUrl = new URL({path_json}, window.location.origin);
        var startedAt = Date.now();
        fetch(requestUrl.href, {{
            method: 'GET',
            credentials: 'same-origin',
            headers: {{'X-Requested-With':'XMLHttpRequest', 'Accept':'application/json'}}
        }}).then(function(response) {{
            return response.text().then(function(body) {{
                window.__ogameExternalExportRead = {{
                    done: true,
                    started_at: startedAt,
                    response: {{
                        status: response.status,
                        response_url: response.url,
                        content_type: response.headers.get('content-type') || '',
                        body: body
                    }}
                }};
            }});
        }}).catch(function(error) {{
            window.__ogameExternalExportRead = {{
                done: true,
                started_at: startedAt,
                response: {{error: String(error)}}
            }};
        }});
        return JSON.stringify({{success:true, started:true}});
    }})()
    """


EXTERNAL_DATA_EXPORT_READ_EXTRACT_JS = """
(function() {
    var read = window.__ogameExternalExportRead;
    if (!read || !read.done) {
        return JSON.stringify({success:false, reason:"official export read 尚未完成"});
    }
    return JSON.stringify({success:true, export_read:read});
})()
"""


def read_official_account_snapshot(
    planet_metadata: Optional[List[Dict[str, Any]]] = None,
    *,
    execute_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Read accountInfo in the active official tab without changing the selected planet."""
    _execute = execute_fn or _get_dep("execute_in_game_tab", execute_in_game_tab)
    result = _execute(
        checked_js(external_data_export_fetch_js("accountInfo")),
        followup_js_code=checked_js(EXTERNAL_DATA_EXPORT_READ_EXTRACT_JS),
        wait_after_js=2.0,
    )
    if not isinstance(result, dict):
        raise RuntimeError(f"official accountInfo 沒有回傳結構化資料：{result}")
    if result.get("safety_stop"):
        raise SafetyStopError(f"安全守衛已停止：{result.get('reason', '未知原因')}")
    if not result.get("success"):
        raise RuntimeError(f"official accountInfo 查詢失敗：{result.get('reason', result)}")
    export_read = result.get("export_read")
    response = export_read.get("response") if isinstance(export_read, dict) else None
    if not isinstance(response, dict):
        raise RuntimeError("official accountInfo 未回傳 response。")
    classification = classify_external_data_export_response(
        int(response.get("status") or 0),
        str(response.get("content_type") or ""),
        str(response.get("body") or ""),
    )
    if not classification.get("available"):
        raise RuntimeError(f"official accountInfo 不可用：{classification.get('reason')}")
    data = classification.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("official accountInfo JSON 不是 object。")
    return normalize_official_account_info(data, planet_metadata=planet_metadata)


def read_empire_snapshot(*, execute_fn: Optional[Callable] = None) -> Dict[str, Any]:
    """Read all owned planets from the fixed Empire standalone page in one navigation."""
    _execute = execute_fn or _get_dep("execute_in_game_tab", execute_in_game_tab)
    result = _execute(checked_js(EMPIRE_STANDALONE_JS), target_url=empire_url())
    if not isinstance(result, dict):
        raise RuntimeError(f"Empire standalone 沒有回傳結構化資料：{result}")
    if result.get("safety_stop"):
        raise SafetyStopError(f"安全守衛已停止：{result.get('reason', '未知原因')}")
    return normalize_empire_snapshot(result)


def official_planet_to_sync_state(snapshot: Dict[str, Any], planet: Dict[str, Any]) -> Dict[str, Any]:
    """Project the normalized official contract onto the historical sync state shape."""
    from scripts.ogame_ctl import TECH_FORMULAS
    resources = resource_vector(planet.get("resources", {}))
    buildings = planet.get("buildings") if isinstance(planet.get("buildings"), dict) else {}
    supplies = {
        tech_id: {
            "name": TECH_FORMULAS.get(tech_id, {}).get("name", ""),
            "level": int(level),
            "canUpgrade": None,
            "costs": "",
        }
        for tech_id, level in buildings.items()
        if tech_id in OFFICIAL_RESOURCE_BUILDING_IDS
    }
    facilities = {
        tech_id: {
            "name": TECH_FORMULAS.get(tech_id, {}).get("name", ""),
            "level": int(level),
            "canUpgrade": None,
            "costs": "",
        }
        for tech_id, level in buildings.items()
        if tech_id not in OFFICIAL_RESOURCE_BUILDING_IDS
    }
    researches = (snapshot.get("account") or {}).get("researches") or {}
    research = {
        tech_id: {
            "name": TECH_FORMULAS.get(tech_id, {}).get("name", ""),
            "level": int(level),
            "canUpgrade": None,
            "costs": "",
        }
        for tech_id, level in researches.items()
    }
    shipyard = {
        tech_id: {"name": "", "amount": int(amount)}
        for tech_id, amount in (planet.get("ships") or {}).items()
    }
    defense = {
        tech_id: {"name": "", "amount": int(amount)}
        for tech_id, amount in (planet.get("defenses") or {}).items()
    }
    storage_info = {}
    for key, tech_id in (("metal", "22"), ("crystal", "23"), ("deuterium", "24")):
        level = int(buildings.get(tech_id, 0))
        storage_info[key] = {
            "level": level,
            "capacity": calc_storage_capacity(level),
            "current": resources[key],
        }
    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(snapshot["captured_at"]))),
        "source": snapshot.get("source"),
        "schema_version": snapshot.get("schema_version"),
        "planet_id": planet.get("planet_id"),
        "overview": {
            **resources,
            "energy": planet.get("energy"),
            "darkmatter": 0,
            "planetId": planet.get("planet_id"),
            "coords": planet.get("coords"),
            "planetName": planet.get("name"),
            "production": resource_vector(planet.get("production", {})),
            "base_production": resource_vector(planet.get("base_production", {})),
        },
        "supplies": supplies,
        "facilities": facilities,
        "research": research,
        "shipyard": shipyard,
        "defense": defense,
        "storage": storage_info,
        "queue_busy": {"known": False, "building": None, "research": None},
    }


def empire_planet_to_sync_state(snapshot: Dict[str, Any], planet: Dict[str, Any]) -> Dict[str, Any]:
    """Project the richer Empire snapshot onto the historical per-planet sync shape."""
    from scripts.ogame_ctl import TECH_FORMULAS
    resources = resource_vector(planet.get("resources", {}))
    production_raw = planet.get("production") if isinstance(planet.get("production"), dict) else None
    base_production_raw = planet.get("base_production") if isinstance(planet.get("base_production"), dict) else None
    production = resource_vector(production_raw) if production_raw else {key: None for key in RESOURCE_KEYS}
    base_production = resource_vector(base_production_raw) if base_production_raw else {key: None for key in RESOURCE_KEYS}

    supplies_raw = planet.get("supplies") if isinstance(planet.get("supplies"), dict) else {}
    facilities_raw = planet.get("facilities") if isinstance(planet.get("facilities"), dict) else {}
    storage = planet.get("storage") if isinstance(planet.get("storage"), dict) else {}
    storage_info = {}
    for key, tech_id in (("metal", "22"), ("crystal", "23"), ("deuterium", "24")):
        storage_info[key] = {
            "level": int(supplies_raw.get(tech_id, 0)),
            "capacity": int(storage.get(key, 0)),
            "current": resources[key],
        }
    queue_busy = dict(planet.get("queue_busy") or {})
    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(snapshot["captured_at"]))),
        "source": snapshot.get("source"),
        "schema_version": snapshot.get("schema_version"),
        "planet_id": planet.get("planet_id"),
        "overview": {
            **resources,
            "energy": planet.get("energy"),
            "darkmatter": None,
            "planetId": planet.get("planet_id"),
            "coords": planet.get("coords"),
            "planetName": planet.get("name"),
            "fields": planet.get("fields"),
            "temperature": planet.get("temperature"),
            "lifeform_resources": planet.get("lifeform_resources", {}),
            "production": production,
            "base_production": base_production,
        },
        "supplies": {
            str(tech_id): {
                "name": TECH_FORMULAS.get(str(tech_id), {}).get("name", ""),
                "level": int(level),
                "canUpgrade": None,
                "costs": "",
            }
            for tech_id, level in supplies_raw.items()
        },
        "facilities": {
            str(tech_id): {
                "name": TECH_FORMULAS.get(str(tech_id), {}).get("name", ""),
                "level": int(level),
                "canUpgrade": None,
                "costs": "",
            }
            for tech_id, level in facilities_raw.items()
        },
        "research": {
            str(tech_id): {
                "name": TECH_FORMULAS.get(str(tech_id), {}).get("name", ""),
                "level": int(level),
                "canUpgrade": None,
                "costs": "",
            }
            for tech_id, level in (planet.get("researches") or {}).items()
        },
        "shipyard": {str(k): {"name": "", "amount": int(v)} for k, v in (planet.get("ships") or {}).items()},
        "defense": {str(k): {"name": "", "amount": int(v)} for k, v in (planet.get("defenses") or {}).items()},
        "storage": storage_info,
        "queue_busy": {
            "known": True,
            "building": bool(queue_busy.get("building")),
            "research": bool(queue_busy.get("research")),
            "shipyard": bool(queue_busy.get("shipyard")),
            "lifeform_building": bool(queue_busy.get("lifeform_building")),
            "lifeform_research": bool(queue_busy.get("lifeform_research")),
        },
        "queues": list(planet.get("queues") or []),
    }


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
    result = _get_dep("execute_in_game_tab", execute_in_game_tab)(js_code)
    if not isinstance(result, dict) or not result.get("success"):
        raise RuntimeError(f"無法讀取星球清單：{result}")
    planets = result.get("planets")
    if not isinstance(planets, list):
        raise RuntimeError(f"星球清單格式不符：{result}")
    return planets


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


def cmd_matrix_official(snapshot: Dict[str, Any], quiet: bool = False, read_tech_list_fn: Optional[Callable] = None) -> Dict[str, Any]:
    """Build the matrix from one accountInfo read plus one queue-only read per planet."""
    read_tech_fn = read_tech_list_fn or _get_dep("read_technology_list", read_technology_list)
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

        queue_data = read_tech_fn("supplies", cp)
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


def cmd_matrix(
    args,
    *,
    memory_dir: str = MEMORY_DIR,
    read_active_planet_context_fn: Optional[Callable] = None,
    read_empire_snapshot_fn: Optional[Callable] = None,
    read_official_account_snapshot_fn: Optional[Callable] = None,
    enrich_empire_with_official_fn: Optional[Callable] = None,
    enrich_official_snapshot_planet_metadata_fn: Optional[Callable] = None,
    read_owned_planets_fn: Optional[Callable] = None,
    cmd_matrix_empire_fn: Optional[Callable] = None,
    cmd_matrix_official_fn: Optional[Callable] = None,
    cmd_matrix_html_fn: Optional[Callable] = None,
    execute_checked_component_fn: Optional[Callable] = None,
    atomic_write_json_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Prefer one Empire page, using accountInfo only to enrich hourly production."""
    _read_active = _get_dep("read_active_planet_context", read_active_planet_context_fn or read_active_planet_context)
    _read_empire = _get_dep("read_empire_snapshot", read_empire_snapshot_fn or read_empire_snapshot)
    _read_official = _get_dep("read_official_account_snapshot", read_official_account_snapshot_fn or read_official_account_snapshot)
    _enrich_empire = _get_dep("enrich_empire_with_official", enrich_empire_with_official_fn or enrich_empire_with_official)
    _enrich_meta = _get_dep("enrich_official_snapshot_planet_metadata", enrich_official_snapshot_planet_metadata_fn or enrich_official_snapshot_planet_metadata)
    _read_planets = _get_dep("read_owned_planets", read_owned_planets_fn or read_owned_planets)
    _matrix_empire = _get_dep("cmd_matrix_empire", cmd_matrix_empire_fn or cmd_matrix_empire)
    _matrix_official = _get_dep("cmd_matrix_official", cmd_matrix_official_fn or cmd_matrix_official)
    _matrix_html = cmd_matrix_html_fn or _get_dep("cmd_matrix_html")
    if _matrix_html is None:
        from scripts.ogame.legacy_commands import cmd_matrix_html as _default_matrix_html
        _matrix_html = _default_matrix_html
    _exec_checked = _get_dep("execute_checked_component", execute_checked_component_fn or execute_checked_component)
    _write_json = _get_dep("atomic_write_json", atomic_write_json_fn or atomic_write_json)

    before = _read_active()
    before_id = int(before["planet_id"])
    source = getattr(args, "source", "auto")
    quiet = getattr(args, "output", "human") == "json"
    try:
        if source == "html":
            result = _matrix_html(args)
        elif source == "official":
            snapshot = _read_official()
            try:
                _enrich_meta(snapshot, _read_planets())
            except RuntimeError:
                pass
            result = _matrix_official(snapshot, quiet=quiet)
        else:
            try:
                snapshot = _read_empire()
            except SafetyStopError:
                raise
            except RuntimeError as empire_exc:
                if source in {"empire", "patrol"}:
                    raise
                if not quiet:
                    print(f"⚠️ Empire standalone 不可用，切換 official accountInfo：{empire_exc}")
                try:
                    _exec_checked("overview", before_id, "JSON.stringify({success:true})")
                except Exception:
                    pass
                try:
                    official = _read_official()
                    try:
                        _enrich_meta(official, _read_planets())
                    except RuntimeError:
                        pass
                except SafetyStopError:
                    raise
                except RuntimeError as official_exc:
                    if not quiet:
                        print(f"⚠️ official accountInfo 亦不可用，切換逐星 HTML fallback：{official_exc}")
                    result = _matrix_html(args)
                else:
                    result = _matrix_official(official, quiet=quiet)
            else:
                if source in {"auto", "patrol"}:
                    metadata = [
                        {"id": int(planet["planet_id"]), "name": planet.get("name"), "coords": planet.get("coords")}
                        for planet in snapshot["planets"]
                    ]
                    try:
                        snapshot = _enrich_empire(
                            snapshot, _read_official(planet_metadata=metadata)
                        )
                    except SafetyStopError:
                        raise
                    except RuntimeError as exc:
                        if not quiet:
                            print(f"⚠️ Empire standalone 已取得；official accountInfo 產速補充不可用：{exc}")
                result = _matrix_empire(snapshot, quiet=quiet)
    except Exception:
        # A safety stop or unexpected page error ends browser I/O immediately.
        # The caller aborts the run rather than navigating again to restore cp.
        raise
    else:
        restored = _exec_checked(
            "overview",
            before_id,
            "JSON.stringify({success:true, planet_id:(document.querySelector('meta[name=\"ogame-planet-id\"]') ? document.querySelector('meta[name=\"ogame-planet-id\"]').getAttribute('content') : new URL(window.location.href).searchParams.get('cp'))})",
        )
        if str(restored.get("planet_id") or "") != str(before_id):
            raise RuntimeError(f"matrix 後無法恢復原作用中星球 cp={before_id}，已停止。")
    result["active_planet_before"] = str(before_id)
    result["active_planet_restored"] = True
    run_id = getattr(args, "run_id", None) or os.environ.get("OGAME_RUN_ID") or ""
    if run_id:
        result["run_id"] = run_id
    if "timestamp" not in result:
        result["timestamp"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    if "alarms" not in result:
        result["alarms"] = []
    _write_json(os.path.join(memory_dir, "scout-report.json"), result)
    if quiet:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def cmd_sync_all(
    args,
    *,
    read_active_planet_context_fn: Optional[Callable] = None,
    read_empire_snapshot_fn: Optional[Callable] = None,
    read_official_account_snapshot_fn: Optional[Callable] = None,
    enrich_empire_with_official_fn: Optional[Callable] = None,
    enrich_official_snapshot_planet_metadata_fn: Optional[Callable] = None,
    read_owned_planets_fn: Optional[Callable] = None,
    execute_checked_component_fn: Optional[Callable] = None,
    cmd_sync_all_html_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Read Empire standalone first, enriching rates through accountInfo when available."""
    _read_active = _get_dep("read_active_planet_context", read_active_planet_context_fn or read_active_planet_context)
    _read_empire = _get_dep("read_empire_snapshot", read_empire_snapshot_fn or read_empire_snapshot)
    _read_official = _get_dep("read_official_account_snapshot", read_official_account_snapshot_fn or read_official_account_snapshot)
    _enrich_empire = _get_dep("enrich_empire_with_official", enrich_empire_with_official_fn or enrich_empire_with_official)
    _enrich_meta = _get_dep("enrich_official_snapshot_planet_metadata", enrich_official_snapshot_planet_metadata_fn or enrich_official_snapshot_planet_metadata)
    _read_planets = _get_dep("read_owned_planets", read_owned_planets_fn or read_owned_planets)
    _exec_checked = _get_dep("execute_checked_component", execute_checked_component_fn or execute_checked_component)
    _sync_html = cmd_sync_all_html_fn or _get_dep("cmd_sync_all_html")

    source = getattr(args, "source", "auto")
    if source == "html":
        return _sync_html(args)

    if source == "official":
        snapshot = _read_official()
        try:
            _enrich_meta(snapshot, _read_planets())
        except RuntimeError:
            pass
        states = [official_planet_to_sync_state(snapshot, planet) for planet in snapshot["planets"]]
        result = {
            "success": True,
            "schema_version": snapshot["schema_version"],
            "source": snapshot["source"],
            "captured_at": snapshot["captured_at"],
            "planet_count": len(states),
            "queue_coverage": snapshot["queue_coverage"],
            "account": snapshot["account"],
            "planets": states,
        }
        print(f"✅ official accountInfo 一次同步 {len(states)} 顆星球；佇列狀態未包含，變更前仍須由 plan 重新驗證。")
        return result

    before = _read_active()
    before_id = int(before["planet_id"])
    try:
        snapshot = _read_empire()
        if source == "auto":
            metadata = [
                {"id": int(planet["planet_id"]), "name": planet.get("name"), "coords": planet.get("coords")}
                for planet in snapshot["planets"]
            ]
            try:
                snapshot = _enrich_empire(
                    snapshot, _read_official(planet_metadata=metadata)
                )
            except SafetyStopError:
                raise
            except RuntimeError as exc:
                print(f"⚠️ Empire standalone 已取得；official accountInfo 產速補充不可用：{exc}")
    except SafetyStopError:
        raise
    except RuntimeError as empire_exc:
        if source == "empire":
            raise
        print(f"⚠️ Empire standalone 不可用，切換 official accountInfo：{empire_exc}")
        try:
            snapshot = _read_official()
        except SafetyStopError:
            raise
        except RuntimeError as official_exc:
            print(f"⚠️ official accountInfo 亦不可用，切換逐星 HTML fallback：{official_exc}")
            return _sync_html(args)
    finally:
        restored = _exec_checked(
            "overview",
            before_id,
            "JSON.stringify({success:true, planet_id:(document.querySelector('meta[name=\"ogame-planet-id\"]') ? document.querySelector('meta[name=\"ogame-planet-id\"]').getAttribute('content') : new URL(window.location.href).searchParams.get('cp'))})",
        )
        if str(restored.get("planet_id") or "") != str(before_id):
            raise RuntimeError(f"sync-all 後無法恢復原作用中星球 cp={before_id}，已停止。")

    projector = empire_planet_to_sync_state if str(snapshot.get("source") or "").startswith("empire.") else official_planet_to_sync_state
    states = [projector(snapshot, planet) for planet in snapshot["planets"]]
    result = {
        "success": True,
        "schema_version": snapshot["schema_version"],
        "source": snapshot["source"],
        "captured_at": snapshot["captured_at"],
        "planet_count": len(states),
        "queue_coverage": snapshot["queue_coverage"],
        "rates_coverage": snapshot.get("rates_coverage", "official.accountInfo"),
        "account": snapshot["account"],
        "planets": states,
    }
    if str(snapshot.get("source") or "").startswith("empire."):
        print(f"✅ Empire 單頁同步 {len(states)} 顆星球；佇列={result['queue_coverage']}，產速={result['rates_coverage']}。")
    else:
        print(f"✅ official accountInfo fallback 同步 {len(states)} 顆星球；佇列未包含，變更前仍須由 plan 重新驗證。")
    return result
