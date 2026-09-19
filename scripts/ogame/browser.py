"""Private Chrome/Apple Events primitives.

Domain modules never import this module.  The compatibility CLI owns the only
adapter from these low-level operations to pinned, safety-gated domain reads.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import subprocess
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.parse import urlencode, urlparse
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


SERVER_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "server.toml")
SERVER_EXAMPLE_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "server.example.toml")


def load_server_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load server configuration from server.toml; auto-bootstrap from example or fail-closed."""
    target_path = path or SERVER_CONFIG_PATH
    if not os.path.isfile(target_path):
        if target_path == SERVER_CONFIG_PATH and os.path.isfile(SERVER_EXAMPLE_CONFIG_PATH):
            import shutil
            shutil.copyfile(SERVER_EXAMPLE_CONFIG_PATH, target_path)
        else:
            raise RuntimeError(
                f"找不到伺服器配置檔：{target_path}。\n"
                "請複製 scripts/ogame/config/server.example.toml 為 server.toml 並填入您的 OGame 伺服器資訊：\n"
                "  cp scripts/ogame/config/server.example.toml scripts/ogame/config/server.toml"
            )
    try:
        with open(target_path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        raise RuntimeError(f"無法解析伺服器配置檔 {target_path}：{exc}") from exc
    if not isinstance(data, dict) or "base_url" not in data or not data["base_url"]:
        raise RuntimeError(f"伺服器配置檔 {target_path} 格式無效，必須包含非空的 base_url。")
    return data


_SERVER_CONFIG = load_server_config()
GAME_BASE_URL: str = _SERVER_CONFIG["base_url"].rstrip("/")
GAME_HOST: str = urlparse(GAME_BASE_URL).netloc
UNIVERSE_NAME: Optional[str] = _SERVER_CONFIG.get("universe_name")


def _run_applescript(script: str) -> str:
    result = subprocess.run(["osascript", "-"], input=script, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript Error: {result.stderr.strip()}")
    return result.stdout.strip()


def _execute_in_game_tab(
    js_code: str,
    wait_after_nav: float = 4.0,
    target_url: Optional[str] = None,
    followup_js_code: Optional[str] = None,
    wait_after_js: float = 0.0,
    *,
    applescript_runner: Callable[[str], str] = _run_applescript,
) -> Any:
    def _make_nav_line(tab_var: str) -> str:
        if not target_url:
            return ""
        iterations = max(15 if ("component=empire" in target_url or "component=movement" in target_url) else 1, int(wait_after_nav * 5))
        if "component=empire" in target_url:
            ready_check = f'if (execute {tab_var} javascript "Boolean(document.querySelector(\'#empire .planet[id^=\\\"planet\\\"]\'))") is "true" then exit repeat'
        elif "component=movement" in target_url:
            ready_check = (
                f'if (execute {tab_var} javascript "(function() {{ '
                f"var c = new URL(window.location.href).searchParams.get('component'); "
                f"return (c === 'movement' || c === 'fleetdispatch') && "
                f"Boolean(document.querySelector('#eventContent, #eventHeader, #eventTable')); "
                f'}})()") is "true" then exit repeat'
            )
        else:
            ready_check = f'if (execute {tab_var} javascript "document.readyState") is "complete" then exit repeat'
        return (
            f'if (URL of {tab_var}) is not "{target_url}" then\n'
            f'    set URL of {tab_var} to "{target_url}"\n'
            f'    delay 1.0\n'
            f'    repeat with i from 1 to {iterations}\n'
            f'        delay 0.2\n'
            f'        try\n'
            f'            {ready_check}\n'
            f'        end try\n'
            f'    end repeat\n'
            f'    delay 0.2\n'
            f'end if'
        )


    nav_line = _make_nav_line("t")
    nav_line2 = _make_nav_line("t2")
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
            return;
        }}
"""
    js_play = f"""
        var allBtns = Array.from(document.querySelectorAll('button, a'));
{univ_search}
        var primaryBtn = allBtns.find(el => {{
            var txt = (el.innerText || '').trim();
            var cls = el.className || '';
            return (cls.includes('btn-primary') || cls.includes('button-primary')) && (txt.includes('暢玩') || txt.includes('Play') || txt.includes('馬上暢玩') || txt.includes('開始'));
        }}) || document.querySelector('button.btn-primary, button.button-primary, button[class*="btn-primary"], button[class*="button-primary"]');
        if (primaryBtn) {{
            primaryBtn.click();
        }}
    """
    b64_play = base64.b64encode(js_play.encode("utf-8")).decode("utf-8")
    b64_payload = base64.b64encode(js_code.encode("utf-8")).decode("utf-8")
    followup_line = ""
    if followup_js_code:
        b64_followup = base64.b64encode(followup_js_code.encode("utf-8")).decode("utf-8")
        followup_line = f'delay {wait_after_js}\nset res to (execute t javascript "eval(decodeURIComponent(escape(window.atob(\'{b64_followup}\'))))")'
    followup_line2 = followup_line.replace("execute t javascript", "execute t2 javascript")
    apple_script = f'''
    tell application "Google Chrome"
        if (count of windows) is 0 then return "NO_WINDOWS"
        repeat with w in windows
            repeat with t in tabs of w
                if (URL of t) contains "{GAME_HOST}" and (((URL of t) contains "page=ingame") or (((URL of t) contains "page=standalone") and ((URL of t) contains "component=empire"))) then
                    {nav_line}
                    set res to (execute t javascript "eval(decodeURIComponent(escape(window.atob('{b64_payload}'))))")
                    {followup_line}
                    return res
                end if
            end repeat
        end repeat
        repeat with w in windows
            repeat with t in tabs of w
                if (URL of t) contains "lobby.ogame.gameforge.com" then
                    execute t javascript "eval(decodeURIComponent(escape(window.atob('{b64_play}'))))"
                    repeat 4 times
                        delay 2
                        repeat with w2 in windows
                            repeat with t2 in tabs of w2
                                if (URL of t2) contains "{GAME_HOST}" and (((URL of t2) contains "page=ingame") or (((URL of t2) contains "page=standalone") and ((URL of t2) contains "component=empire"))) then
                                    {nav_line2}
                                    set res to (execute t2 javascript "eval(decodeURIComponent(escape(window.atob('{b64_payload}'))))")
                                    {followup_line2}
                                    return res
                                end if
                            end repeat
                        end repeat
                    end repeat
                    return "NO_OGAME_TAB"
                end if
            end repeat
        end repeat
        return "NO_OGAME_TAB"
    end tell
    '''
    raw = applescript_runner(apple_script)
    if raw == "NO_WINDOWS":
        raise RuntimeError("Chrome 沒有開啟任何視窗。")
    if raw == "NO_OGAME_TAB":
        raise RuntimeError("Chrome 中找不到 OGame 分頁（請先開啟 Lobby 頁面）。")
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return raw


execute_in_game_tab = _execute_in_game_tab
run_applescript = _run_applescript


def game_url(component: str, planet_id: Optional[int] = None, **params: Any) -> str:
    """Build an in-game URL, optionally pinned to one owned planet by cp ID."""
    from urllib.parse import urlencode
    query: Dict[str, Any] = {"page": "ingame", "component": component}
    if planet_id is not None:
        query["cp"] = int(planet_id)
    query.update({key: value for key, value in params.items() if value is not None})
    return f"{GAME_BASE_URL}?{urlencode(query)}"


def empire_url() -> str:
    """Build the fixed, same-origin, read-only Empire standalone URL."""
    from urllib.parse import urlencode
    return f"{GAME_BASE_URL}?{urlencode({'page': 'standalone', 'component': 'empire'})}"


def require_confirmed_mutation(args: Any) -> None:
    """Fail closed unless a state-changing command names its planet and is explicit."""
    if getattr(args, "planet_id", None) is None:
        raise RuntimeError("變更動作必須提供 --planet-id，避免在錯誤星球執行。")
    if not getattr(args, "confirm", False):
        raise RuntimeError("變更動作必須提供 --confirm；先以 sync/sync-all 確認即時狀態。")


def checked_js(inner_expression: str, expected_planet_id: Optional[int] = None) -> str:
    """Wrap a read/click expression in the fixed OGame safety gate."""
    planet_gate = ""
    if expected_planet_id is not None:
        planet_gate = f"""
        var expectedCp = {json.dumps(str(expected_planet_id))};
        var metaCp = document.querySelector('meta[name="ogame-planet-id"]');
        var pinnedCp = url.searchParams.get("cp") || (metaCp ? metaCp.getAttribute("content") : null);
        if (pinnedCp !== expectedCp) {{
            return JSON.stringify({{success:false, safety_stop:true, reason:"星球 pin 驗證失敗", expected_planet_id:expectedCp, observed_planet_id:pinnedCp, url:window.location.href}});
        }}
        """
    return f"""
    (function() {{
        var url;
        try {{ url = new URL(window.location.href); }} catch (_) {{
            return JSON.stringify({{success:false, safety_stop:true, reason:"無法驗證目前頁面 URL"}});
        }}
        var page = url.searchParams.get("page");
        var component = url.searchParams.get("component");
        var official = url.protocol === "https:" && url.hostname.endsWith("ogame.gameforge.com") &&
            (page === "ingame" || (page === "standalone" && component === "empire"));
        if (!official) {{
            return JSON.stringify({{success:false, safety_stop:true, reason:"目前不是官方 OGame 遊戲內頁面", url:window.location.href}});
        }}
        {planet_gate}
        var text = (document.body && document.body.innerText || "").toLowerCase();
        var blocked = ["captcha", "recaptcha", "hcaptcha", "驗證碼", "封號", "帳號凍結", "suspension", "banned", "anti-bot", "異常活動"];
        var signal = blocked.find(function(item) {{ return text.includes(item.toLowerCase()); }});
        if (signal) {{
            return JSON.stringify({{success:false, safety_stop:true, reason:"偵測到安全訊號: " + signal}});
        }}
        return ({inner_expression});
    }})()
    """


def execute_checked_component_result(
    component: str, planet_id: int, inner_expression: str, *, runner_fn: Optional[Callable] = None
) -> Dict[str, Any]:
    """Navigate to a pinned component and return its structured result, including known blocks."""
    call_exec = runner_fn or _execute_in_game_tab
    result = call_exec(
        checked_js(inner_expression, planet_id), target_url=game_url(component, planet_id)
    )
    if not isinstance(result, dict):
        raise RuntimeError(f"{component} 沒有回傳結構化資料，已停止：{result}")
    if result.get("safety_stop"):
        raise RuntimeError(f"安全守衛已停止：{result.get('reason', '未知原因')} (expected={result.get('expected_planet_id')}, observed={result.get('observed_planet_id')}, url={result.get('url')})")
    return result


def execute_checked_component(
    component: str, planet_id: int, inner_expression: str, *, runner_fn: Optional[Callable] = None
) -> Dict[str, Any]:
    """Navigate to one pinned component and require its common safety gate to pass."""
    result = execute_checked_component_result(component, planet_id, inner_expression, runner_fn=runner_fn)
    if not result.get("success"):
        raise RuntimeError(f"{component} 查詢失敗：{result.get('reason', result)}")
    return result


def execute_checked_component_followup(
    component: str,
    planet_id: int,
    interaction_expression: str,
    followup_expression: str,
    wait_after_js: float = 2.0,
    *,
    runner_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Run a fixed UI-only interaction then read its result on the same pinned page."""
    call_exec = runner_fn or _execute_in_game_tab
    result = call_exec(
        checked_js(interaction_expression, planet_id),
        target_url=game_url(component, planet_id),
        followup_js_code=checked_js(followup_expression, planet_id),
        wait_after_js=wait_after_js,
    )
    if not isinstance(result, dict):
        raise RuntimeError(f"{component} 詳情沒有回傳結構化資料，已停止：{result}")
    if result.get("safety_stop"):
        raise RuntimeError(f"安全守衛已停止：{result.get('reason', '未知原因')} (expected={result.get('expected_planet_id')}, observed={result.get('observed_planet_id')}, url={result.get('url')})")
    if not result.get("success"):
        raise RuntimeError(f"{component} 詳情查詢失敗：{result.get('reason', result)} | diag: {result}")
    return result


ACTIVE_PLANET_CONTEXT_JS = """
(function() {
    function cpFromHref(href) {
        if (!href) return null;
        var match = href.match(/[?&]cp=(\\d+)/);
        return match ? match[1] : null;
    }
    var selected = document.querySelector('a.planetlink.active, a.planetlink.selected, a.planetlink[class*="active"], a.planetlink[class*="selected"], .planetlink.current');
    var selectedCp = selected ? cpFromHref(selected.href) : null;
    var meta = document.querySelector('meta[name="ogame-planet-id"]');
    var metaCp = meta ? meta.getAttribute('content') : null;
    var urlCp = new URLSearchParams(window.location.search).get('cp');
    var links = Array.from(document.querySelectorAll('a.planetlink[href*="cp="]'));
    return JSON.stringify({
        success: Boolean(selectedCp || metaCp || urlCp),
        planet_id: selectedCp || metaCp || urlCp || null,
        selected_cp: selectedCp,
        meta_cp: metaCp,
        url_cp: urlCp,
        owned_planet_ids: links.map(function(el) { return cpFromHref(el.href); })
            .filter(function(value, index, values) { return /^\\d+$/.test(String(value || '')) && values.indexOf(value) === index; }),
        url: window.location.href
    });
})()
"""


def read_active_planet_context(*, runner_fn: Optional[Callable] = None) -> Dict[str, Any]:
    """Read the selected planet before a pinned probe so it can be restored."""
    call_exec = runner_fn or _execute_in_game_tab
    result = call_exec(checked_js(ACTIVE_PLANET_CONTEXT_JS))
    if not isinstance(result, dict):
        raise RuntimeError(f"目前星球狀態沒有回傳結構化資料，已停止：{result}")
    if result.get("safety_stop"):
        raise RuntimeError(f"安全守衛已停止：{result.get('reason', '未知原因')}")
    if not result.get("success") or not str(result.get("planet_id") or "").isdigit():
        raise RuntimeError(f"無法確認目前作用中星球，為避免 Session 漂移已停止：{result}")
    return result


HEADER_SNAPSHOT_JS = """
(function() {
    function num(selector) {
        var el = document.querySelector(selector);
        if (!el) return null;
        var raw = el.getAttribute('data-raw') || el.innerText || '';
        var digits = raw.replace(/[^0-9]/g, '');
        return digits ? Number(digits) : null;
    }
    function attr(selector) {
        var el = document.querySelector(selector);
        return el ? (el.getAttribute('title') || el.getAttribute('data-tooltip-title') || el.getAttribute('aria-label') || '') : '';
    }
    return JSON.stringify({
        success: true,
        resources: {
            metal: num('#resources_metal'),
            crystal: num('#resources_crystal'),
            deuterium: num('#resources_deuterium')
        },
        energy: (document.querySelector('#resources_energy') || {}).innerText || '',
        rate_tooltips: {
            metal: attr('#resources_metal'),
            crystal: attr('#resources_crystal'),
            deuterium: attr('#resources_deuterium')
        },
        planet_id: new URLSearchParams(window.location.search).get('cp'),
        url: window.location.href
    });
})()
"""


TECHNOLOGY_LIST_JS = """
(function() {
    function text(el) { return el ? el.innerText.trim() : ''; }
    function safeUpgradeButton(el) {
        var controls = Array.from(el.querySelectorAll('button.upgrade, button.build, [data-action="upgrade"]'));
        return controls.find(function(control) {
            var marker = ((control.innerText || '') + ' ' + (control.outerHTML || '')).toLowerCase();
            return !marker.includes('darkmatter') && !marker.includes('dark_matter') &&
                !marker.includes('dark-matter') && !marker.includes('暗物質') &&
                !marker.includes('premium') && !marker.includes('item_shop');
        }) || null;
    }
    function num(selector) {
        var el = document.querySelector(selector);
        if (!el) return null;
        var raw = el.getAttribute('data-raw') || el.innerText || '';
        var digits = raw.replace(/[^0-9]/g, '');
        return digits ? Number(digits) : null;
    }
    function attr(selector) {
        var el = document.querySelector(selector);
        return el ? (el.getAttribute('title') || el.getAttribute('data-tooltip-title') || el.getAttribute('aria-label') || '') : '';
    }
    function buildingQueue() {
        var container = document.querySelector('#productionboxbuildingcomponent, #b_building, .queue-building');
        if (!container) return {active:false, queue_token:'', cancel_available:false};
        var active = Boolean(document.querySelector('#countdownBuilding, #productionboxbuildingcomponent .countdown, #productionboxbuildingcomponent .queueItem, #b_building .countdown, .queue-building .countdown, [data-component="building"] .countdown, #productionboxbuildingcomponent [data-end]'));
        if (!active) {
            return {
                active: false,
                queue_token: '',
                tech_id: '',
                start_epoch: null,
                end_epoch: null,
                summary: '',
                cancel_available: false
            };
        }
        var item = container.querySelector('[data-technology], .queueItem') || container;
        var techId = item.getAttribute('data-technology') || container.getAttribute('data-technology') || '';
        var start = item.getAttribute('data-start') || container.getAttribute('data-start') || '';
        var end = item.getAttribute('data-end') || container.getAttribute('data-end') || '';
        var summary = text(item).replace(/\\s+/g, ' ').slice(0, 160);
        var cancel = container.querySelector('a.abort, button.abort, a.cancel, button.cancel, [data-overlay="cancelProduction"]');
        return {
            active: true,
            queue_token: [techId, start, end, summary].join('|'),
            tech_id: techId,
            start_epoch: Number(start) || null,
            end_epoch: Number(end) || null,
            summary: summary,
            cancel_available: Boolean(cancel && !cancel.disabled)
        };
    }
    function productionQueue() {
        var containers = Array.from(document.querySelectorAll('#pqueue, #productionboxshipyardcomponent, .production_queue, .queue.shipyard'));
        var entries = [];
        containers.forEach(function(container) {
            container.querySelectorAll('[data-technology], .queueItem, li').forEach(function(item) {
                var raw = text(item).replace(/\\s+/g, ' ').slice(0, 160);
                var amountMatch = raw.match(/(?:x|×)\\s*([0-9]+)/i) || raw.match(/([0-9]+)\\s*(?:艘|個|units?)/i);
                entries.push({
                    tech_id: item.getAttribute('data-technology') || '',
                    amount: amountMatch ? Number(amountMatch[1]) : null,
                    end_epoch: Number(item.getAttribute('data-end')) || null,
                    summary: raw
                });
            });
        });
        return {active: entries.length > 0, entries: entries};
    }
    var items = {};
    document.querySelectorAll('li.technology[data-technology]').forEach(function(el) {
        var id = el.getAttribute('data-technology');
        var level = el.querySelector('.level, .amount');
        var button = safeUpgradeButton(el);
        var costs = el.querySelector('.costs, .technology_costs');
        var duration = el.querySelector('.build_duration, .time, [data-time]');
        var requirements = el.querySelector('.requirements, .technology_requirements, .requirements-list');
        var energy = el.querySelector('.energy, .technology_energy, [data-energy]');
        var costsRaw = text(costs);
        if (!costsRaw && button) {
            costsRaw = button.getAttribute('data-tooltip-title') || button.getAttribute('data-tooltip-content') || button.getAttribute('title') || '';
        }
        if (!costsRaw) {
            costsRaw = el.getAttribute('data-tooltip-title') || el.getAttribute('data-tooltip-content') || el.getAttribute('title') || '';
        }
        items[id] = {
            name: el.getAttribute('aria-label') || el.getAttribute('title') || text(el.querySelector('.name')),
            level: level ? Number((text(level).match(/\\d+/) || ['0'])[0]) : 0,
            can_upgrade: Boolean(button && !button.disabled) || el.getAttribute('data-status') === 'on' || el.classList.contains('on'),
            costs_raw: costsRaw,
            duration_raw: text(duration) || (duration && duration.getAttribute('data-time')) || '',
            requirements_raw: text(requirements),
            energy_raw: text(energy) || (energy && energy.getAttribute('data-energy')) || '',
            status: el.getAttribute('data-status') || '',
            start_epoch: Number(el.getAttribute('data-start')) || null,
            end_epoch: Number(el.getAttribute('data-end')) || null,
            total_time: Number(el.getAttribute('data-total')) || null,
            debug: {
                text: text(el),
                attributes: Array.from(el.attributes).map(function(attr) { return [attr.name, attr.value]; }),
                button_attributes: button ? Array.from(button.attributes).map(function(attr) { return [attr.name, attr.value]; }) : [],
                cost_nodes: Array.from(el.querySelectorAll('[data-cost], [data-raw], [data-resource], [title], [class*="cost"], [class*="resource"]')).slice(0, 40).map(function(node) {
                    return {tag:node.tagName, className:node.className || '', text:text(node), dataRaw:node.getAttribute('data-raw') || '', title:node.getAttribute('title') || '', attributes:Array.from(node.attributes).map(function(attr) { return [attr.name, attr.value]; })};
                })
            }
        };
    });
    return JSON.stringify({
        success:true,
        items:items,
        resources:{metal:num('#resources_metal'), crystal:num('#resources_crystal'), deuterium:num('#resources_deuterium')},
        energy:(document.querySelector('#resources_energy') || {}).innerText || '',
        rate_tooltips:{metal:attr('#resources_metal'), crystal:attr('#resources_crystal'), deuterium:attr('#resources_deuterium')},
        queue_busy:{
            building:Boolean(document.querySelector('#countdownBuilding, #productionboxbuildingcomponent .countdown, #productionboxbuildingcomponent .queueItem, #b_building .countdown, .queue-building .countdown, [data-component="building"] .countdown')),
            research:Boolean(document.querySelector('#countdownResearch, #productionboxresearchcomponent .countdown, #productionboxresearchcomponent .queueItem, #b_research .countdown, .queue-research .countdown, [data-component="research"] .countdown')),
            shipyard:Boolean(document.querySelector('#pqueue [data-technology], #productionboxshipyardcomponent .queueItem, .production_queue .queueItem, .queue.shipyard .queueItem'))
        },
        building_queue:buildingQueue(),
        production_queue:productionQueue()
    });
})()
"""


def read_header_snapshot(component: str, planet_id: int) -> Dict[str, Any]:
    return execute_checked_component(component, planet_id, HEADER_SNAPSHOT_JS)


def read_technology_list(component: str, planet_id: int) -> Dict[str, Any]:
    result = execute_checked_component(component, planet_id, TECHNOLOGY_LIST_JS)
    result["planet_id"] = str(planet_id)
    if component in {"lfbuildings", "lfresearch"}:
        queue_key = "lifeform_building" if component == "lfbuildings" else "lifeform_research"
        result.setdefault("queue_busy", {})[queue_key] = any(
            str(item.get("status") or "").lower() == "active" or bool(item.get("end_epoch"))
            for item in result.get("items", {}).values()
            if isinstance(item, dict)
        )
    return result


FLEET_STATE_JS = r"""
(function() {
    function number(selector) {
        var el = document.querySelector(selector);
        if (!el) return null;
        var raw = el.getAttribute('data-raw') || el.innerText || '';
        var digits = raw.replace(/[^0-9]/g, '');
        return digits ? Number(digits) : null;
    }
    var ships = {};
    document.querySelectorAll('#shipsForm li.technology[data-technology], #fleet1 li.technology[data-technology], li.technology[data-technology]').forEach(function(el) {
        var techId = el.getAttribute('data-technology');
        var amountEl = el.querySelector('.amount, .stockAmount');
        var raw = amountEl ? (amountEl.getAttribute('data-value') || amountEl.innerText || '') : '';
        var digits = raw.replace(/[^0-9]/g, '');
        if (techId && digits) ships[techId] = Number(digits);
    });
    var slotEl = document.querySelector('#slots, #fleetSlots, .fleetSlots, [data-fleet-slots]');
    var slotText = slotEl ? (slotEl.getAttribute('data-fleet-slots') || slotEl.innerText || '') : '';
    var slotMatch = slotText.match(/([0-9]+)\s*\/\s*([0-9]+)/);
    var used = slotMatch ? Number(slotMatch[1]) : null;
    var total = slotMatch ? Number(slotMatch[2]) : null;
    function finiteInt(value) {
        var parsed = Number(value);
        return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
    }
    function templateShips(template) {
        var source = template && (template.ships || template.fleet || template.shipData || template.ship_data);
        var result = {};
        if (Array.isArray(source)) {
            source.forEach(function(item) {
                var tech = item && (item.technologyId || item.techId || item.shipId || item.id);
                var amount = item && finiteInt(item.amount !== undefined ? item.amount : item.count);
                if (String(tech || '').match(/^\d+$/) && amount > 0) result[String(tech)] = amount;
            });
        } else if (source && typeof source === 'object') {
            Object.keys(source).forEach(function(key) {
                var value = source[key];
                var amount = finiteInt(value && typeof value === 'object' ? (value.amount !== undefined ? value.amount : value.count) : value);
                if (String(key).match(/^\d+$/) && amount > 0) result[String(key)] = amount;
            });
        }
        return result;
    }
    var rawTemplates = (typeof expeditionFleetTemplates !== 'undefined' && Array.isArray(expeditionFleetTemplates))
        ? expeditionFleetTemplates : [];
    var expeditionTemplates = rawTemplates.map(function(template) {
        return {
            name: String(template && (template.name || template.templateName || template.label || template.title) || '').trim(),
            ships: templateShips(template)
        };
    }).filter(function(template) { return template.name && Object.keys(template.ships).length > 0; });
    var expeditionTemplateRows = Array.from(document.querySelectorAll('a.changeExpeditionFleet')).map(function(link) {
        var descCell = link.closest('td.fleetDesc');
        var actionsCell = descCell ? descCell.nextElementSibling : null;
        var editLink = actionsCell ? actionsCell.querySelector('a[onclick*="setExpeditionFleetTemplateShips"]') : null;
        return {
            name: String(link.innerText || link.getAttribute('data-tooltip-title') || '').trim(),
            template_id: String(link.getAttribute('rel') || '').trim(),
            edit_onclick: editLink ? String(editLink.getAttribute('onclick') || '') : ''
        };
    }).filter(function(row) { return row.name && row.edit_onclick; });
    var expeditionSlotEl = document.querySelector('#expeditionSlots, .expeditionSlots, [data-expedition-slots]');
    var expeditionSlotText = expeditionSlotEl ? (expeditionSlotEl.getAttribute('data-expedition-slots') || expeditionSlotEl.innerText || '') : '';
    var expeditionSlotMatch = expeditionSlotText.match(/([0-9]+)\s*\/\s*([0-9]+)/);
    var expeditionUsed = typeof expeditionCount !== 'undefined' ? finiteInt(expeditionCount) : null;
    var expeditionTotal = typeof maxExpeditionCount !== 'undefined' ? finiteInt(maxExpeditionCount) : null;
    if (expeditionUsed === null && expeditionSlotMatch) expeditionUsed = Number(expeditionSlotMatch[1]);
    if (expeditionTotal === null && expeditionSlotMatch) expeditionTotal = Number(expeditionSlotMatch[2]);
    var expeditionKnown = expeditionUsed !== null && expeditionTotal !== null && expeditionTotal >= expeditionUsed;
    var originCoords = '';
    if (typeof apiCommonData !== 'undefined' && apiCommonData && apiCommonData.coords) originCoords = String(apiCommonData.coords);
    if (!originCoords && typeof apiDataJson !== 'undefined' && apiDataJson && apiDataJson.coords) originCoords = String(apiDataJson.coords);
    if (!originCoords) {
        var coordsMeta = document.querySelector('meta[name="ogame-planet-coordinates"]');
        originCoords = coordsMeta ? String(coordsMeta.content || '') : '';
    }
    return JSON.stringify({
        success: true,
        planet_id: new URLSearchParams(window.location.search).get('cp') || (document.querySelector('meta[name="ogame-planet-id"]') ? document.querySelector('meta[name="ogame-planet-id"]').content : null),
        ships: ships,
        fleet_slots: {
            known: Boolean(slotMatch && total >= used),
            used: used,
            total: total,
            free: slotMatch && total >= used ? total - used : null,
            raw: slotText.replace(/\s+/g, ' ').trim()
        },
        expedition_slots: {
            known: expeditionKnown,
            used: expeditionUsed,
            total: expeditionTotal,
            free: expeditionKnown ? expeditionTotal - expeditionUsed : null,
            raw: expeditionSlotText.replace(/\s+/g, ' ').trim()
        },
        expedition_templates: expeditionTemplates,
        expedition_template_rows: expeditionTemplateRows,
        origin_coords: originCoords,
        resources: {
            metal: number('#resources_metal'),
            crystal: number('#resources_crystal'),
            deuterium: number('#resources_deuterium')
        }
    });
})()
"""


EVENTS_STATE_JS = r"""
(function() {
    var events = [];
    document.querySelectorAll('#eventTable tr.eventFleet, #eventContent tr.eventFleet, .eventFleet').forEach(function(row) {
        var missionType = row.getAttribute('data-mission-type') || '';
        var missionClass = Array.from(row.querySelectorAll('.missionFleet, [class*="mission"]')).map(el => el.className + ' ' + (el.title || '')).join(' ');
        var text = (row.innerText || '').replace(/\\s+/g, ' ').trim() + ' ' + missionType + ' ' + missionClass;
        var countdown = row.querySelector('[data-end], [data-arrival-time], .countdown');
        var end = row.getAttribute('data-arrival-time') || row.getAttribute('data-arrival') || row.getAttribute('data-end') || (countdown ? (countdown.getAttribute('data-arrival-time') || countdown.getAttribute('data-arrival') || countdown.getAttribute('data-end')) : '');
        var fleetNode = row.querySelector('[data-fleet-id], [data-fleetid], [data-movement-id]');
        var fleetId = row.getAttribute('data-fleet-id') || row.getAttribute('data-fleetid') || row.getAttribute('data-movement-id') || (fleetNode ? (fleetNode.getAttribute('data-fleet-id') || fleetNode.getAttribute('data-fleetid') || fleetNode.getAttribute('data-movement-id')) : '') || '';
        var originCoordsEl = row.querySelector('.coordsOrigin');
        var destCoordsEl = row.querySelector('.destCoords');
        events.push({
            id: row.id || '',
            fleet_id: fleetId,
            text: text.trim(),
            mission_type: missionType,
            return_flight: row.getAttribute('data-return-flight') === 'true',
            origin_coords: originCoordsEl ? originCoordsEl.innerText.replace(/\s+/g, ' ').trim() : '',
            dest_coords: destCoordsEl ? destCoordsEl.innerText.replace(/\s+/g, ' ').trim() : '',
            end_epoch: Number(end) || null
        });
    });
    return JSON.stringify({
        success: true,
        planet_id: new URLSearchParams(window.location.search).get('cp') || (document.querySelector('meta[name="ogame-planet-id"]') ? document.querySelector('meta[name="ogame-planet-id"]').content : null),
        events: events
    });
})()
"""


def _parse_expedition_template_rows(rows: Any) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    templates: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("name") or "").strip()
        onclick = html.unescape(str(row.get("edit_onclick") or ""))
        match = re.search(r"setExpeditionFleetTemplateShips\(\s*(\{.*?\})\s*,", onclick)
        if not name or not match:
            continue
        try:
            raw_ships = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(raw_ships, dict):
            continue
        ships: Dict[str, int] = {}
        for tech, raw_amount in raw_ships.items():
            tech_id = str(tech).strip()
            if not tech_id.isdigit() or isinstance(raw_amount, bool):
                continue
            try:
                amount = int(raw_amount)
            except (TypeError, ValueError):
                continue
            if amount > 0:
                ships[tech_id] = amount
        if ships:
            templates.append({"name": name, "ships": ships})
    return templates


def read_fleet_state(planet_id: int) -> Dict[str, Any]:
    result = execute_checked_component("fleetdispatch", planet_id, FLEET_STATE_JS)
    if not isinstance(result, dict):
        raise RuntimeError("fleetdispatch 沒有回傳結構化資料。")
    expedition_slots = result.get("expedition_slots")
    if not isinstance(expedition_slots, dict) or expedition_slots.get("known") is not True:
        fleet_slots = result.get("fleet_slots")
        raw = " ".join(
            str(value or "")
            for value in (
                expedition_slots.get("raw") if isinstance(expedition_slots, dict) else "",
                fleet_slots.get("raw") if isinstance(fleet_slots, dict) else "",
            )
        )
        match = re.search(
            r"(?:遠征艦隊|遠征|expedition(?:\s+fleet)?s?)[^0-9]*(\d+)\s*/\s*(\d+)",
            raw,
            flags=re.IGNORECASE,
        )
        if match:
            used, total = (int(match.group(1)), int(match.group(2)))
            if total >= used:
                result["expedition_slots"] = {
                    "known": True,
                    "used": used,
                    "total": total,
                    "free": total - used,
                    "raw": match.group(0).strip(),
                }
    templates = result.get("expedition_templates")
    if not isinstance(templates, list) or not templates:
        result["expedition_templates"] = _parse_expedition_template_rows(
            result.get("expedition_template_rows")
        )
    return result


def read_events_state(planet_id: int) -> Dict[str, Any]:
    return execute_checked_component("movement", planet_id, EVENTS_STATE_JS)


GLOBAL_MOVEMENT_EVIDENCE_JS = r"""
(function() {
    var url = new URL(window.location.href);
    var comp = url.searchParams.get('component');
    if (url.searchParams.get('page') !== 'ingame' || (comp !== 'movement' && comp !== 'fleetdispatch')) {
        return JSON.stringify({success:false, safety_stop:true, reason:'movement component mismatch'});
    }
    var eventContent = document.querySelector('#eventContent');
    var eventHeader = document.querySelector('#eventHeader');
    var eventTable = document.querySelector('#eventTable');
    var rootVerified = Boolean(eventContent || eventHeader || eventTable);
    if (!rootVerified) {
        return JSON.stringify({
            success: false,
            scope: 'account_unverified',
            coverage: 'unverified',
            reason: 'movement root not found'
        });
    }

    var rows = Array.from(document.querySelectorAll('#eventTable tr.eventFleet, #eventContent tr.eventFleet, .eventFleet'));
    var events = [];
    var hostileIds = [];
    var hasUnknown = false;

    rows.forEach(function(row) {
        var fleetNode = row.querySelector('[data-fleet-id], [data-fleetid], [data-movement-id]');
        var fleetId = row.getAttribute('data-fleet-id') || row.getAttribute('data-fleetid') || row.getAttribute('data-movement-id') || (fleetNode ? (fleetNode.getAttribute('data-fleet-id') || fleetNode.getAttribute('data-fleetid') || fleetNode.getAttribute('data-movement-id')) : '') || '';
        var id = row.id || fleetId;
        var missionType = row.getAttribute('data-mission-type') || '';
        var returnFlight = row.getAttribute('data-return-flight') === 'true';
        var text = (row.innerText || '').replace(/\s+/g, ' ').trim();
        var tooltipEl = row.querySelector('.missionFleet [data-tooltip-title], .missionFleet .tooltipHTML, [data-tooltip-title]');
        var tooltipTitle = tooltipEl ? (tooltipEl.getAttribute('data-tooltip-title') || '') : '';
        var originCoordsEl = row.querySelector('.coordsOrigin');
        var originCoords = originCoordsEl ? originCoordsEl.innerText.replace(/\s+/g, ' ').trim() : '';
        var destCoordsEl = row.querySelector('.destCoords');
        var destCoords = destCoordsEl ? destCoordsEl.innerText.replace(/\s+/g, ' ').trim() : '';
        var iconMovement = row.querySelector('[class*="icon_movement"]');
        var iconClass = iconMovement ? iconMovement.className : '';
        var countdown = row.querySelector('[data-end], [data-arrival-time], .countdown');
        var end = row.getAttribute('data-arrival-time') || row.getAttribute('data-arrival') || row.getAttribute('data-end') || (countdown ? (countdown.getAttribute('data-arrival-time') || countdown.getAttribute('data-arrival') || countdown.getAttribute('data-end')) : '');

        var direction = 'unknown';
        var directionEvidence = '';

        if (tooltipTitle.includes('己方') || tooltipTitle.toLowerCase().includes('own') || returnFlight || iconClass.includes('icon_movement_reserve')) {
            direction = 'own';
            directionEvidence = 'own_fleet:' + (tooltipTitle || (returnFlight ? 'return_flight' : iconClass));
        } else if (tooltipTitle.includes('敵方') || tooltipTitle.toLowerCase().includes('hostile') || text.includes('敵方') || row.className.includes('hostile')) {
            direction = 'incoming_hostile';
            directionEvidence = 'hostile_fleet:' + (tooltipTitle || text);
        } else if (tooltipTitle.includes('友好') || tooltipTitle.toLowerCase().includes('friendly')) {
            direction = 'neutral';
            directionEvidence = 'friendly_fleet:' + tooltipTitle;
        } else if (missionType === '8' || missionType === '15' || missionType === '18' || missionType === '7') {
            direction = 'own';
            directionEvidence = 'peaceful_mission_type:' + missionType;
        } else if (missionType === '1' || missionType === '2' || missionType === '9') {
            direction = 'incoming_hostile';
            directionEvidence = 'attack_mission_type:' + missionType;
        } else {
            direction = 'unknown';
            directionEvidence = 'ambiguous_row:' + text;
            hasUnknown = true;
        }

        if (direction === 'incoming_hostile') {
            hostileIds.push(id);
        }

        var rawAttrs = {};
        for (var ai = 0; ai < row.attributes.length; ai++) {
            rawAttrs[row.attributes[ai].name] = row.attributes[ai].value;
        }
        var recallLink = row.querySelector('a[onclick*="recall"], a[href*="recall"], a[class*="icon_movement_reserve"]');
        var recallInfo = recallLink ? (recallLink.getAttribute('onclick') || recallLink.getAttribute('href') || recallLink.className) : '';

        events.push({
            id: id,
            fleet_id: fleetId,
            raw_attrs: rawAttrs,
            recall_info: recallInfo,
            html_snippet: row.innerHTML.slice(0, 1000),
            text: text,
            mission_type: missionType,
            return_flight: returnFlight,
            origin_coords: originCoords,
            dest_coords: destCoords,
            end_epoch: Number(end) || null,
            direction: direction,
            direction_evidence: directionEvidence
        });
    });

    var threatStatus = 'none';
    if (hostileIds.length > 0) {
        threatStatus = 'hostile';
    } else if (hasUnknown) {
        threatStatus = 'unknown';
    } else {
        threatStatus = 'none';
    }

    var emptyStateVerified = (events.length === 0) && rootVerified;

    var result = {
        success: true,
        scope: 'account',
        coverage: 'verified',
        page_evidence: {
            root_verified: rootVerified,
            empty_state_verified: emptyStateVerified
        },
        threat_status: threatStatus,
        events: events
    };

    if (threatStatus === 'hostile') {
        result.hostile_event_ids = hostileIds;
    }

    return JSON.stringify(result);
})()
"""


def read_global_movement_evidence() -> Dict[str, Any]:
    """Read the official no-cp movement page once, without asserting DOM coverage.

    HANDOFF FOR THE MOVEMENT DOM AGENT: The owner observes that this page lists
    all account events. Verify that against the live page; identify a durable
    movement root and empty-state marker, extract direction/owner/hostile cues,
    and only then return scope='account', coverage='verified'. A matching URL or
    zero selected rows is not proof of zero incoming fleets. Keep ambiguous rows
    as threat_status='unknown'; never classify raw 'attack' text alone because
    our own raids also say attack. Preserve the checked_js safety gate and the
    no-cp official URL. patrol-start rejects this provisional evidence until
    the DOM contract is implemented and verified.
    """
    before_id = int(read_active_planet_context()["planet_id"])
    result = _execute_in_game_tab(
        checked_js(GLOBAL_MOVEMENT_EVIDENCE_JS),
        target_url=game_url("movement"),
    )
    if not isinstance(result, dict):
        raise RuntimeError("movement 沒有回傳結構化資料。")
    if result.get("safety_stop") or not result.get("success"):
        raise RuntimeError(f"movement 安全守衛已停止：{result.get('reason', 'unknown')}")
    # Only restore after a safe, structured read. A captcha/ban/page anomaly
    # must stop further browser operations immediately.
    restored = execute_checked_component(
        "overview", before_id,
        "JSON.stringify({success:true, planet_id:new URL(window.location.href).searchParams.get('cp')})",
    )
    if str(restored.get("planet_id") or "") != str(before_id):
        raise RuntimeError(f"movement 後無法恢復原作用中星球 cp={before_id}。")
    return result


def read_galaxy_target_evidence(planet_id: int, target: Mapping[str, int]) -> Dict[str, Any]:
    position = int(target["position"])
    js_code = f"""
    (function() {{
        var rows=Array.from(document.querySelectorAll('#galaxyContent tr.ctContentRow, .galaxyRow.ctContentRow'));
        var row=rows.find(function(item, index) {{
            var value=(item.id || '').replace('galaxyRow','').trim() || String(index + 1);
            return Number(value) === {position};
        }});
        if (!rows.length || !row) return JSON.stringify({{success:false,reason:'target_row_missing',position:{position}}});
        var text=(row.innerText || '').replace(/\\s+/g,' ').trim();
        var classes=row.className || '';
        var empty=classes.includes('empty_filter') || text === '' || text === String({position});
        var destroyed=text.includes('已毀滅') || text.toLowerCase().includes('destroyed') || text.toLowerCase().includes('détruite');
        var vacation=classes.includes('vacation_filter') || text.includes('(v)');
        var inactive=(classes.includes('inactive_filter') || classes.includes('longinactive_filter') || text.includes('(i)') || text.includes('(I)')) && !destroyed && !vacation;
        var owned=Boolean(row.querySelector('.own, .playername.own, [data-player-is-own="true"]'));
        return JSON.stringify({{
            success:true,
            position:{position},
            empty:empty,
            inactive:inactive,
            destroyed:destroyed,
            vacation:vacation,
            owned_planet:owned,
            raw:text
        }});
    }})()
    """
    result = _execute_in_game_tab(
        checked_js(js_code, planet_id),
        target_url=game_url(
            "galaxy",
            planet_id,
            galaxy=int(target["galaxy"]),
            system=int(target["system"]),
        ),
        wait_after_nav=2.0,
    )
    if not isinstance(result, dict) or result.get("success") is not True:
        raise RuntimeError(f"無法確認 fleet target live evidence：{result}")
    result["planet_id"] = str(planet_id)
    return result
