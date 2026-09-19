"""Pure contracts and DOM extraction for OGame's read-only Empire page."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, Optional


SCHEMA_VERSION = 1
RESOURCE_KEYS = ("metal", "crystal", "deuterium")
STORAGE_KEYS = ("metalStorage", "crystalStorage", "deuteriumStorage")


EMPIRE_STANDALONE_JS = r"""
(function() {
    function compactText(el) {
        return ((el && el.innerText) || '').replace(/\s+/g, ' ').trim();
    }
    function integerText(value) {
        var match = String(value || '').replace(/[,.\s]/g, '').match(/-?\d+/);
        return match ? Number(match[0]) : null;
    }
    function classKey(el) {
        return Array.from((el && el.classList) || []).find(function(name) {
            return /^\d+$/.test(name) || [
                'equipment', 'metal', 'crystal', 'deuterium', 'food', 'population',
                'metalStorage', 'crystalStorage', 'deuteriumStorage',
                'foodStorage', 'populationStorage'
            ].indexOf(name) >= 0;
        }) || '';
    }
    function groupKey(el) {
        var marker = Array.from((el && el.classList) || []).find(function(name) {
            return name.indexOf('group') === 0;
        }) || '';
        return marker.replace(/^group/, '');
    }
    function baseValue(el) {
        var clone = el.cloneNode(true);
        clone.querySelectorAll('img, .active, .loop').forEach(function(node) { node.remove(); });
        return integerText(compactText(clone));
    }
    function queueEntry(group, el) {
        var active = el.querySelector('.active');
        var loops = Array.from(el.querySelectorAll('.loop'));
        var image = el.querySelector('img');
        if (!active && !image && loops.length === 0) return null;
        return {
            group: group,
            technology_id: classKey(el),
            current: baseValue(el),
            active_target: integerText(compactText(active)),
            queued_targets: loops.map(function(node) { return integerText(compactText(node)); }).filter(function(value) { return value !== null; }),
            summary: (image && (image.getAttribute('data-tooltip-title') || image.getAttribute('title'))) || compactText(el).slice(0, 240)
        };
    }

    var root = document.querySelector('#empire');
    if (!root) return JSON.stringify({success:false, reason:'Empire root not found'});
    var planets = Array.from(root.querySelectorAll('.planet[id^="planet"]')).filter(function(planet) {
        return planet.id !== 'planet0' && !planet.classList.contains('summary');
    }).map(function(planet) {
        var idMatch = planet.id.match(/^planet(\d+)$/);
        var groups = {};
        var queues = [];
        Array.from(planet.querySelectorAll(':scope > .values')).forEach(function(groupEl) {
            var group = groupKey(groupEl);
            if (!group) return;
            var values = {};
            Array.from(groupEl.children).forEach(function(item) {
                var key = classKey(item);
                if (key) values[key] = baseValue(item);
                var queued = queueEntry(group, item);
                if (queued) queues.push(queued);
            });
            groups[group] = values;
        });
        var coords = compactText(planet.querySelector('.planetHead .coords a'));
        var fieldsText = compactText(planet.querySelector('.planetHead .fields.textRight'));
        var fieldsMatch = fieldsText.match(/(\d+)\s*\/\s*(\d+)/);
        var temperatureText = compactText(planet.querySelector('.planetDataBottom .fields'));
        var temperatures = temperatureText.match(/-?\d+/g) || [];
        return {
            planet_id: idMatch ? idMatch[1] : null,
            name: compactText(planet.querySelector('.planetname')),
            coords: coords,
            equipment: Array.from(planet.querySelectorAll(':scope > .values.groupitems > *')).map(function(item) {
                return compactText(item);
            }).filter(Boolean),
            fields: {
                used: fieldsMatch ? Number(fieldsMatch[1]) : null,
                total: fieldsMatch ? Number(fieldsMatch[2]) : null
            },
            energy: integerText(compactText(planet.querySelector('.energyRow li.textRight'))),
            temperature: {
                min: temperatures.length > 0 ? Number(temperatures[0]) : null,
                max: temperatures.length > 1 ? Number(temperatures[1]) : null
            },
            groups: groups,
            queues: queues
        };
    });
    if (!planets.length) return JSON.stringify({success:false, reason:'Empire planets not found'});
    return JSON.stringify({success:true, planets:planets});
})()
"""


def _required_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or value is None:
        raise RuntimeError(f"Empire standalone 缺少數值欄位：{field}")
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError(f"Empire standalone 數值欄位格式不符：{field}") from exc


def _integer_map(value: Any, field: str) -> Dict[str, int]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"Empire standalone 缺少物件欄位：{field}")
    return {str(key): _required_integer(item, f"{field}.{key}") for key, item in value.items()}


def _queue_flags(entries: List[Dict[str, Any]]) -> Dict[str, bool]:
    groups = {str(entry.get("group") or "") for entry in entries}
    return {
        "building": bool(groups.intersection({"supply", "station"})),
        "research": "research" in groups,
        "shipyard": bool(groups.intersection({"ships", "defence"})),
        "lifeform_building": any(group.startswith("lifeform") and group.endswith("buildings") for group in groups),
        "lifeform_research": any(group.startswith("lifeform") and group.endswith("research") for group in groups),
    }


def normalize_empire_snapshot(raw: Dict[str, Any], captured_at: Optional[int] = None) -> Dict[str, Any]:
    """Validate the browser result and expose a stable controller snapshot."""
    if not isinstance(raw, dict) or raw.get("success") is not True:
        raise RuntimeError(f"Empire standalone 沒有成功回傳：{raw}")
    raw_planets = raw.get("planets")
    if not isinstance(raw_planets, list) or not raw_planets:
        raise RuntimeError("Empire standalone 未提供任何星球。")

    planets: List[Dict[str, Any]] = []
    seen_ids = set()
    for index, raw_planet in enumerate(raw_planets):
        if not isinstance(raw_planet, Mapping):
            raise RuntimeError(f"Empire standalone planets.{index} 不是物件。")
        planet_id = str(raw_planet.get("planet_id") or "")
        if not planet_id.isdigit() or planet_id == "0" or planet_id in seen_ids:
            raise RuntimeError(f"Empire standalone 星球 ID 無效或重複：{planet_id!r}")
        seen_ids.add(planet_id)
        groups = raw_planet.get("groups")
        if not isinstance(groups, Mapping):
            raise RuntimeError(f"Empire standalone 星球 {planet_id} 缺少 groups。")

        resources_all = _integer_map(groups.get("resources"), f"planets.{planet_id}.resources")
        storage_all = _integer_map(groups.get("storage"), f"planets.{planet_id}.storage")
        resources = {key: _required_integer(resources_all.get(key), f"planets.{planet_id}.resources.{key}") for key in RESOURCE_KEYS}
        storage = {
            resource: _required_integer(storage_all.get(storage_key), f"planets.{planet_id}.storage.{storage_key}")
            for resource, storage_key in zip(RESOURCE_KEYS, STORAGE_KEYS)
        }
        supplies = _integer_map(groups.get("supply"), f"planets.{planet_id}.supply")
        facilities = _integer_map(groups.get("station"), f"planets.{planet_id}.station")
        researches = _integer_map(groups.get("research"), f"planets.{planet_id}.research")
        ships = _integer_map(groups.get("ships"), f"planets.{planet_id}.ships")
        defenses = _integer_map(groups.get("defence"), f"planets.{planet_id}.defence")
        queues_raw = raw_planet.get("queues")
        if not isinstance(queues_raw, list):
            raise RuntimeError(f"Empire standalone 星球 {planet_id} 缺少 queues。")
        queues = [dict(item) for item in queues_raw if isinstance(item, Mapping)]

        lifeform_buildings: Dict[str, int] = {}
        lifeform_researches: Dict[str, int] = {}
        for group_name, group_value in groups.items():
            name = str(group_name)
            if name.startswith("lifeform") and name.endswith("buildings"):
                lifeform_buildings.update(_integer_map(group_value, f"planets.{planet_id}.{name}"))
            elif name.startswith("lifeform") and name.endswith("research"):
                lifeform_researches.update(_integer_map(group_value, f"planets.{planet_id}.{name}"))

        fields = raw_planet.get("fields") if isinstance(raw_planet.get("fields"), Mapping) else {}
        temperature = raw_planet.get("temperature") if isinstance(raw_planet.get("temperature"), Mapping) else {}
        equipment_raw = raw_planet.get("equipment", [])
        if not isinstance(equipment_raw, list):
            raise RuntimeError(f"Empire standalone 星球 {planet_id} equipment 格式不符。")
        coords = str(raw_planet.get("coords") or "")
        if not coords:
            raise RuntimeError(f"Empire standalone 星球 {planet_id} 缺少座標。")
        planets.append({
            "planet_id": planet_id,
            "name": str(raw_planet.get("name") or f"Planet {planet_id}"),
            "coords": coords,
            "equipment": [str(item) for item in equipment_raw if str(item).strip()],
            "fields": {
                "used": _required_integer(fields.get("used"), f"planets.{planet_id}.fields.used"),
                "total": _required_integer(fields.get("total"), f"planets.{planet_id}.fields.total"),
            },
            "temperature": {
                "min": _required_integer(temperature.get("min"), f"planets.{planet_id}.temperature.min"),
                "max": _required_integer(temperature.get("max"), f"planets.{planet_id}.temperature.max"),
            },
            "resources": resources,
            "lifeform_resources": {
                key: resources_all[key] for key in ("food", "population") if key in resources_all
            },
            "storage": storage,
            "lifeform_storage": {
                key: storage_all[key] for key in ("foodStorage", "populationStorage") if key in storage_all
            },
            "energy": _required_integer(raw_planet.get("energy"), f"planets.{planet_id}.energy"),
            "buildings": {**supplies, **facilities},
            "supplies": supplies,
            "facilities": facilities,
            "researches": researches,
            "ships": ships,
            "defenses": defenses,
            "species_buildings": lifeform_buildings,
            "species_researches": lifeform_researches,
            "queues": queues,
            "queue_busy": _queue_flags(queues),
        })

    account_research_busy = any(planet["queue_busy"]["research"] for planet in planets)
    for planet in planets:
        planet["queue_busy"]["research"] = account_research_busy
    planets.sort(key=lambda item: int(item["planet_id"]))
    account_researches = dict(planets[0]["researches"])
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "empire.standalone",
        "captured_at": int(captured_at if captured_at is not None else time.time()),
        "planet_count": len(planets),
        "account": {"researches": account_researches},
        "planets": planets,
        "queue_coverage": "empire.standalone",
        "rates_coverage": "not_provided",
    }


def enrich_empire_with_official(empire: Dict[str, Any], official: Dict[str, Any]) -> Dict[str, Any]:
    """Add hourly production/account data without replacing Empire display truth."""
    official_by_id = {str(item.get("planet_id")): item for item in official.get("planets", [])}
    empire_ids = {str(item.get("planet_id")) for item in empire.get("planets", [])}
    if set(official_by_id) != empire_ids:
        raise RuntimeError("Empire standalone 與 official accountInfo 星球集合不一致。")

    for planet in empire["planets"]:
        official_planet = official_by_id[planet["planet_id"]]
        if str(official_planet.get("coords") or "") != str(planet.get("coords") or ""):
            raise RuntimeError(f"Empire standalone 與 official accountInfo 座標不一致：{planet['planet_id']}")
        planet["production"] = dict(official_planet.get("production") or {})
        planet["base_production"] = dict(official_planet.get("base_production") or {})
    empire["source"] = "empire.standalone+official.accountInfo"
    empire["rates_coverage"] = "official.accountInfo"
    empire["account"] = dict(official.get("account") or empire.get("account") or {})
    empire["captured_at"] = max(int(empire.get("captured_at") or 0), int(official.get("captured_at") or 0))
    return empire
