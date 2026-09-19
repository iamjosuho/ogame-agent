"""Diagnostic and inspection probes (rates, detail, query, export).

Supports both individual probe commands and the unified `probe <type>` command.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from scripts.ogame.browser import (
    checked_js,
    execute_checked_component,
    execute_checked_component_followup,
    execute_in_game_tab,
    game_url,
    read_active_planet_context,
)
from scripts.ogame.lifecycle import (
    MEMORY_DIR,
    atomic_write_json,
    load_json_file,
    require_run_lease,
)
from scripts.ogame.resolver import get_dep

QUERY_TRACE_FILE = os.path.join(MEMORY_DIR, "api-query-samples.json")
EXPORT_PROBE_FILE = os.path.join(MEMORY_DIR, "api-export-probe.json")

SENSITIVE_TRACE_KEY = re.compile(
    r"(?:authorization|cookie|csrf(?:[_-]?token)?|session(?:[_-]?id)?|token|api[_-]?key|(?:^|[_-])sid$)",
    re.IGNORECASE,
)


def redact_sensitive_text(value: str) -> str:
    """Remove credential-bearing values while retaining request/response structure."""
    text = str(value)
    text = re.sub(
        r"(?im)^(set-cookie|cookie|authorization|x-csrf-token|x-request-token)\s*:\s*.*$",
        lambda match: f"{match.group(1)}: [REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)((?:csrf(?:[_-]?token)?|session(?:[_-]?id)?|token|api[_-]?key)"
        r"[\"']?\s*(?:=|:)\s*[\"']?)([^\"'&\s<>]+)",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)(name=[\"'](?:csrf(?:[_-]?token)?|session(?:[_-]?id)?|token|api[_-]?key)[\"']"
        r"[^>]*value=[\"'])([^\"']*)([\"'])",
        r"\1[REDACTED]\3",
        text,
    )
    return text


def sanitize_trace_url(value: str) -> str:
    """Redact sensitive query parameter values from one URL."""
    try:
        parsed = urlsplit(str(value))
        query = []
        for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
            query.append((key, "[REDACTED]" if SENSITIVE_TRACE_KEY.search(key) else item_value))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
    except ValueError:
        return redact_sensitive_text(str(value))


RESOURCE_KEYS = ("metal", "crystal", "deuterium")


def normalize_number(value: Any) -> Optional[int]:
    if value is None:
        return None
    cleaned = re.sub(r"[,\s+]", "", str(value).strip())
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        try:
            return int(float(cleaned))
        except ValueError:
            return None


def sanitize_query_trace(value: Any, key: str = "") -> Any:
    """Recursively scrub authorization, cookies, and tokens from request/response structures."""
    if SENSITIVE_TRACE_KEY.search(str(key)):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): sanitize_query_trace(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [sanitize_query_trace(item) for item in value]
    if isinstance(value, str):
        if str(key).lower() in {"url", "response_url"}:
            return sanitize_trace_url(value)
        return redact_sensitive_text(value)
    return value


def response_schema(body: str, content_type: str = "") -> Dict[str, Any]:
    """Describe a response body without needing to infer game semantics."""
    text = str(body or "")
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        tags = sorted(set(re.findall(r"<\s*([a-zA-Z][a-zA-Z0-9:-]*)", text)))[:20]
        return {
            "kind": "html" if "html" in content_type.lower() or tags else "text",
            "length": len(text),
            "tags": tags,
        }
    if isinstance(parsed, dict):
        shape = {str(item_key): type(item_value).__name__ for item_key, item_value in parsed.items()}
    elif isinstance(parsed, list):
        shape = {"items": len(parsed), "first_type": type(parsed[0]).__name__ if parsed else None}
    else:
        shape = {"type": type(parsed).__name__}
    return {"kind": "json", "length": len(text), "shape": shape}


def is_safe_query_replay(record: Dict[str, Any]) -> bool:
    """Allow replay only for observed same-origin GET read pages/detail queries."""
    request = record.get("request") if isinstance(record, dict) else None
    if not isinstance(request, dict) or str(request.get("method") or "").upper() != "GET":
        return False
    try:
        parsed = urlsplit(str(request.get("url") or ""))
    except ValueError:
        return False
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    page = str(params.get("page") or "").lower()
    component = str(params.get("component") or "").lower()
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.hostname.endswith("ogame.gameforge.com")
        and (
            (page == "ajax" and component in {"technologydetails", "technologydetail"})
            or (
                page == "ingame"
                and component in {"supplies", "facilities", "research"}
                and str(params.get("cp") or "").isdigit()
            )
        )
    )


RESOURCE_SETTINGS_PROBE_JS = """
(function() {
    function clean(text) { return (text || '').replace(/\s+/g, ' ').trim(); }
    var table = document.querySelector('table');
    var headings = Array.from(document.querySelectorAll('th, h1, h2, h3, legend, caption')).map(function(el) { return clean(el.innerText); }).filter(Boolean);
    return JSON.stringify({
        success: true,
        text: clean(document.body ? document.body.innerText : ''),
        headings: headings.slice(0, 30),
        table_found: Boolean(table),
        table_text: table ? clean(table.innerText).slice(0, 2000) : '',
        url: window.location.href
    });
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


def read_resource_settings_rates(planet_id: int, *, execute_fn: Optional[Callable] = None) -> Optional[Dict[str, int]]:
    _execute = execute_fn or execute_checked_component
    result = _execute("resourcesettings", planet_id, RESOURCE_SETTINGS_PROBE_JS)
    return parse_resource_settings_rates(str(result.get("text") or ""))


def command_rates_probe(
    args: argparse.Namespace,
    *,
    execute_checked_component_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    exec_fn = execute_checked_component_fn or execute_checked_component
    result = exec_fn("resourcesettings", int(args.planet_id), RESOURCE_SETTINGS_PROBE_JS)
    output = {
        "planet_id": str(args.planet_id),
        "parsed_rates": parse_resource_settings_rates(str(result.get("text") or "")),
        "headings": result.get("headings", []),
        "text": result.get("text", ""),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return output


def technology_detail_interaction_js(tech_id: int) -> str:
    return f"""
    (function() {{
        var el = document.querySelector("li.technology[data-technology='{tech_id}'], [data-technology='{tech_id}']");
        if (!el) return JSON.stringify({{success:false, reason:"找不到科技 {tech_id}"}});
        ['mouseenter', 'mouseover', 'mousemove'].forEach(function(type) {{ el.dispatchEvent(new MouseEvent(type, {{bubbles:true, view:window}})); }});
        el.click();
        return JSON.stringify({{success:true}});
    }})()
    """


def technology_detail_extract_js(tech_id: int) -> str:
    return f"""
    (function() {{
        var el = document.querySelector("li.technology[data-technology='{tech_id}'], [data-technology='{tech_id}']");
        if (!el) return JSON.stringify({{success:false, reason:"詳情等待後找不到科技 {tech_id}"}});
        var selectors = ['#technologydetails', '#technologyDetail', '.technologydetails', '.technology_detail', '.detail', '.tooltip'];
        var details = selectors.map(function(selector) {{
            return Array.from(document.querySelectorAll(selector)).map(function(node) {{ return {{selector:selector, text:(node.innerText || '').trim()}}; }});
        }}).flat().filter(function(entry) {{ return entry.text; }});
        var globals = Object.keys(window).filter(function(key) {{ return /(technology|resource|cost|detail)/i.test(key); }}).slice(0, 100).map(function(key) {{
            var value = window[key];
            return {{key:key, type:typeof value, keys:value && typeof value === 'object' ? Object.keys(value).slice(0, 30) : []}};
        }});
        var screenDetailsSource = typeof window.getScreenDetails === 'function' ? String(window.getScreenDetails).slice(0, 6000) : '';
        return JSON.stringify({{success:true, tech_id:'{tech_id}', row_text:(el.innerText || '').trim(), details:details, globals:globals, screen_details_source:screenDetailsSource, network_entries:performance.getEntriesByType('resource').slice(-40).map(function(entry) {{ return entry.name; }}), body_tail:((document.body && document.body.innerText) || '').slice(-5000)}});
    }})()
    """


def command_detail_probe(
    args: argparse.Namespace,
    *,
    execute_checked_component_followup_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    component = args.component
    if component not in {"supplies", "research"}:
        raise RuntimeError("detail-probe 只允許 supplies 或 research。")
    exec_fn = execute_checked_component_followup_fn or execute_checked_component_followup
    result = exec_fn(
        component,
        int(args.planet_id),
        technology_detail_interaction_js(int(args.tech_id)),
        technology_detail_extract_js(int(args.tech_id)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


EXTERNAL_DATA_EXPORT_ACTIONS = (
    "speciesBonuses",
    "accountInfo",
    "technologyQuantities",
    "importExportInfo",
)


def external_data_export_path(action: str) -> str:
    """Build one fixed, same-origin, read-only official export path."""
    if action not in EXTERNAL_DATA_EXPORT_ACTIONS:
        raise ValueError(f"不允許的 externaldataexport action：{action}")
    return "/game/index.php?" + urlencode({
        "page": "componentOnly",
        "component": "externaldataexport",
        "action": action,
        "asJson": 1,
    })


def external_data_export_fetch_js(action: str) -> str:
    """Start one allowlisted authenticated export read on the current game page."""
    path = json.dumps(external_data_export_path(action))
    action_json = json.dumps(action)
    return f"""
    (function() {{
        var requestUrl = new URL({path}, window.location.origin);
        window.__ogameExternalExportRead = {{done:false, action:{action_json}, started_at:Date.now()}};
        fetch(requestUrl.href, {{
            method:'GET',
            credentials:'same-origin',
            headers:{{'X-Requested-With':'XMLHttpRequest', 'Accept':'application/json'}}
        }}).then(function(response) {{
            return response.text().then(function(body) {{
                window.__ogameExternalExportRead = {{
                    done:true,
                    action:{action_json},
                    response:{{
                        status:response.status,
                        response_url:response.url,
                        content_type:response.headers.get('content-type') || '',
                        body:body.slice(0, 1000000)
                    }}
                }};
            }});
        }}).catch(function(error) {{
            window.__ogameExternalExportRead = {{done:true, action:{action_json}, error:String(error)}};
        }});
        return JSON.stringify({{success:true, started:true, action:{action_json}}});
    }})()
    """


def classify_external_data_export_response(status: int, content_type: str, body: str) -> Dict[str, Any]:
    """Classify one export response; HTTP 200 alone is not proof of endpoint support."""
    text = str(body or "")
    schema = response_schema(text, content_type)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        lowered = text.lower()
        reason = "non_json_response"
        if "an error has occured" in lowered or "an error has occurred" in lowered:
            reason = "endpoint_unavailable_or_missing_required_header"
        return {
            "available": False,
            "reason": reason,
            "schema": schema,
            "body_preview": redact_sensitive_text(text[:1000]),
        }

    failure = isinstance(parsed, dict) and (
        parsed.get("success") is False
        or str(parsed.get("status") or "").lower() in {"failure", "error"}
        or bool(parsed.get("errors"))
    )
    http_ok = 200 <= int(status or 0) < 400
    return {
        "available": bool(http_ok and not failure),
        "reason": None if http_ok and not failure else ("api_failure" if failure else "http_error"),
        "schema": schema,
        "data": sanitize_query_trace(parsed),
    }


def external_data_export_probe_js() -> str:
    """Start four sequential authenticated GET exports without adding a cp parameter."""
    specs = [
        {"action": action, "path": external_data_export_path(action)}
        for action in EXTERNAL_DATA_EXPORT_ACTIONS
    ]
    specs_json = json.dumps(specs, ensure_ascii=False)
    return f"""
    (function() {{
        var specs = {specs_json};
        window.__ogameExternalExportProbe = {{done:false, started_at:Date.now(), results:[]}};
        (async function() {{
            for (var i = 0; i < specs.length; i++) {{
                var spec = specs[i];
                var requestUrl = new URL(spec.path, window.location.origin);
                var startedAt = Date.now();
                try {{
                    var response = await fetch(requestUrl.href, {{
                        method: 'GET',
                        credentials: 'same-origin',
                        headers: {{'X-Requested-With':'XMLHttpRequest', 'Accept':'application/json'}}
                    }});
                    var body = await response.text();
                    var headers = {{}};
                    response.headers.forEach(function(value, key) {{ headers[key] = value; }});
                    window.__ogameExternalExportProbe.results.push({{
                        action: spec.action,
                        request: {{
                            method: 'GET',
                            url: requestUrl.href,
                            headers: {{'X-Requested-With':'XMLHttpRequest', 'Accept':'application/json'}},
                            has_cp_parameter: requestUrl.searchParams.has('cp')
                        }},
                        response: {{
                            status: response.status,
                            response_url: response.url,
                            headers: headers,
                            content_type: response.headers.get('content-type') || '',
                            body: body.slice(0, 500000)
                        }},
                        duration_ms: Date.now() - startedAt
                    }});
                }} catch (error) {{
                    window.__ogameExternalExportProbe.results.push({{
                        action: spec.action,
                        request: {{
                            method: 'GET',
                            url: requestUrl.href,
                            headers: {{'X-Requested-With':'XMLHttpRequest', 'Accept':'application/json'}},
                            has_cp_parameter: requestUrl.searchParams.has('cp')
                        }},
                        response: {{error: String(error)}},
                        duration_ms: Date.now() - startedAt
                    }});
                }}
            }}
            window.__ogameExternalExportProbe.done = true;
            window.__ogameExternalExportProbe.finished_at = Date.now();
        }})();
        return JSON.stringify({{success:true, started:true, count:specs.length}});
    }})()
    """


EXTERNAL_DATA_EXPORT_EXTRACT_JS = """
(function() {
    var probe = window.__ogameExternalExportProbe;
    if (!probe || !probe.done) {
        return JSON.stringify({
            success: false,
            reason: probe ? "official export probe 尚未完成" : "official export probe 尚未啟動",
            probe: probe || null
        });
    }
    return JSON.stringify({
        success: true,
        probe: probe,
        active_planet: (function() {
            var selected = Array.from(document.querySelectorAll('a.planetlink[href*="cp="]')).find(function(el) {
                return el.classList.contains('active') || el.classList.contains('selected') || !!el.closest('.active, .selected, .current');
            });
            try { return selected ? new URL(selected.href).searchParams.get('cp') : new URL(window.location.href).searchParams.get('cp'); }
            catch (_) { return null; }
        })()
    });
})()
"""


def command_export_probe(
    args: argparse.Namespace,
    *,
    require_run_lease_fn: Optional[Callable] = None,
    read_active_planet_context_fn: Optional[Callable] = None,
    execute_followup_fn: Optional[Callable] = None,
    execute_component_fn: Optional[Callable] = None,
    atomic_write_json_fn: Optional[Callable] = None,
    export_probe_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Probe four official authenticated JSON exports without mutating game resources."""
    lease_check = require_run_lease_fn or get_dep("require_run_lease", require_run_lease)
    lease_check(str(args.run_id))
    planet_id = int(args.planet_id)
    active_ctx_fn = read_active_planet_context_fn or get_dep("read_active_planet_context", read_active_planet_context)
    before = active_ctx_fn()
    before_id = int(before["planet_id"])
    owned_ids = {int(value) for value in before.get("owned_planet_ids", []) if str(value).isdigit()}
    if planet_id not in owned_ids:
        raise RuntimeError(f"cp={planet_id} 不在目前頁面列出的自有星球中，已停止。")

    followup_fn = execute_followup_fn or get_dep("execute_checked_component_followup", execute_checked_component_followup)
    comp_fn = execute_component_fn or get_dep("execute_checked_component", execute_checked_component)
    write_json_fn = atomic_write_json_fn or get_dep("atomic_write_json", atomic_write_json)
    target_probe_file = export_probe_file or get_dep("EXPORT_PROBE_FILE", EXPORT_PROBE_FILE)

    probe_result: Optional[Dict[str, Any]] = None
    restored = before_id == planet_id
    try:
        probe_result = followup_fn(
            "overview",
            planet_id,
            external_data_export_probe_js(),
            EXTERNAL_DATA_EXPORT_EXTRACT_JS,
            wait_after_js=6.0,
        )
    finally:
        if probe_result is not None and before_id != planet_id:
            restore_result = comp_fn(
                "overview",
                before_id,
                "JSON.stringify({success:true, planet_id:(document.querySelector('meta[name=\"ogame-planet-id\"]') ? document.querySelector('meta[name=\"ogame-planet-id\"]').getAttribute('content') : new URL(window.location.href).searchParams.get('cp'))})",
            )
            restored = str(restore_result.get("planet_id") or "") == str(before_id)

    raw_probe = probe_result.get("probe") if isinstance(probe_result, dict) else None
    raw_results = raw_probe.get("results") if isinstance(raw_probe, dict) else None
    if not isinstance(raw_results, list):
        raise RuntimeError(f"official export probe 沒有回傳結果陣列：{probe_result}")

    endpoints: List[Dict[str, Any]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        request = sanitize_query_trace(item.get("request", {}))
        response = item.get("response") if isinstance(item.get("response"), dict) else {}
        classification = classify_external_data_export_response(
            int(response.get("status") or 0),
            str(response.get("content_type") or ""),
            str(response.get("body") or ""),
        ) if not response.get("error") else {
            "available": False,
            "reason": "fetch_error",
            "schema": {"kind": "error"},
            "body_preview": redact_sensitive_text(str(response.get("error") or "")),
        }
        endpoints.append({
            "action": item.get("action"),
            "request": request,
            "response": {
                "status": response.get("status"),
                "response_url": sanitize_trace_url(str(response.get("response_url") or "")),
                "content_type": response.get("content_type"),
                "headers": sanitize_query_trace(response.get("headers", {})),
                **classification,
            },
            "duration_ms": item.get("duration_ms"),
        })

    available_count = sum(1 for item in endpoints if (item.get("response") or {}).get("available"))
    output = {
        "version": 1,
        "captured_at": int(time.time()),
        "scope": "official authenticated externaldataexport GET endpoints",
        "planet_id": str(planet_id),
        "active_planet_before": str(before_id),
        "active_planet_during": str(probe_result.get("active_planet") or planet_id),
        "restored": restored,
        "requested_count": len(EXTERNAL_DATA_EXPORT_ACTIONS),
        "available_count": available_count,
        "supported": available_count > 0,
        "endpoints": endpoints,
    }
    write_json_fn(target_probe_file, output)
    summary = {
        "success": True,
        "supported": output["supported"],
        "available_count": available_count,
        "requested_count": len(EXTERNAL_DATA_EXPORT_ACTIONS),
        "restored": restored,
        "probe_file": target_probe_file,
        "endpoints": [
            {
                "action": item.get("action"),
                "status": (item.get("response") or {}).get("status"),
                "available": (item.get("response") or {}).get("available"),
                "reason": (item.get("response") or {}).get("reason"),
                "schema": (item.get("response") or {}).get("schema"),
            }
            for item in endpoints
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return output


def query_probe_interaction_js(tech_id: int) -> str:
    """Install page-local fetch/XHR recorders, then perform one natural detail click."""
    return f"""
    (function() {{
        window.__ogameQueryProbe = [];
        window.__ogameQueryProbeSeq = 0;
        function bodyText(value) {{
            if (value === undefined || value === null) return "";
            if (typeof value === "string") return value.slice(0, 500000);
            if (value instanceof URLSearchParams) return value.toString().slice(0, 500000);
            if (typeof FormData !== "undefined" && value instanceof FormData) {{
                return JSON.stringify(Array.from(value.entries())).slice(0, 500000);
            }}
            try {{ return JSON.stringify(value).slice(0, 500000); }} catch (_) {{ return String(value).slice(0, 500000); }}
        }}
        function record(entry) {{
            entry.sequence = ++window.__ogameQueryProbeSeq;
            entry.recorded_at = Date.now();
            window.__ogameQueryProbe.push(entry);
        }}

        var originalFetch = window.fetch;
        if (typeof originalFetch === "function") {{
            window.fetch = function(input, init) {{
                var options = init || {{}};
                var requestUrl = typeof input === "string" ? input : (input && input.url) || "";
                var method = String(options.method || (input && input.method) || "GET").toUpperCase();
                var requestHeaders = {{}};
                try {{ new Headers(options.headers || (input && input.headers) || {{}}).forEach(function(v, k) {{ requestHeaders[k] = v; }}); }} catch (_) {{}}
                var startedAt = Date.now();
                return originalFetch.apply(this, arguments).then(function(response) {{
                    var responseHeaders = {{}};
                    try {{ response.headers.forEach(function(v, k) {{ responseHeaders[k] = v; }}); }} catch (_) {{}}
                    response.clone().text().then(function(text) {{
                        record({{
                            transport: "fetch",
                            request: {{method:method, url:new URL(requestUrl, window.location.href).href, headers:requestHeaders, body:bodyText(options.body)}},
                            response: {{status:response.status, response_url:response.url, headers:responseHeaders, content_type:response.headers.get("content-type") || "", body:text.slice(0, 500000)}},
                            duration_ms: Date.now() - startedAt
                        }});
                    }}).catch(function(error) {{
                        record({{transport:"fetch", request:{{method:method, url:new URL(requestUrl, window.location.href).href, headers:requestHeaders, body:bodyText(options.body)}}, response:{{error:String(error)}}, duration_ms:Date.now()-startedAt}});
                    }});
                    return response;
                }});
            }};
        }}

        var xhrOpen = XMLHttpRequest.prototype.open;
        var xhrSend = XMLHttpRequest.prototype.send;
        var xhrSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader;
        XMLHttpRequest.prototype.open = function(method, url) {{
            this.__ogameProbeMeta = {{method:String(method || "GET").toUpperCase(), url:new URL(url, window.location.href).href, headers:{{}}, started_at:0}};
            return xhrOpen.apply(this, arguments);
        }};
        XMLHttpRequest.prototype.setRequestHeader = function(name, value) {{
            if (this.__ogameProbeMeta) this.__ogameProbeMeta.headers[String(name)] = String(value);
            return xhrSetRequestHeader.apply(this, arguments);
        }};
        XMLHttpRequest.prototype.send = function(body) {{
            var xhr = this;
            var meta = xhr.__ogameProbeMeta || {{method:"GET", url:"", headers:{{}}}};
            meta.started_at = Date.now();
            meta.body = bodyText(body);
            xhr.addEventListener("loadend", function() {{
                var responseBody = "";
                try {{
                    if (!xhr.responseType || xhr.responseType === "text") responseBody = xhr.responseText || "";
                    else if (xhr.responseType === "json") responseBody = JSON.stringify(xhr.response);
                }} catch (_) {{}}
                record({{
                    transport: "xhr",
                    request: {{method:meta.method, url:meta.url, headers:meta.headers, body:meta.body}},
                    response: {{status:xhr.status, response_url:xhr.responseURL || meta.url, headers_raw:(function() {{ try {{ return xhr.getAllResponseHeaders(); }} catch (_) {{ return ""; }} }})(), content_type:xhr.getResponseHeader("content-type") || "", body:String(responseBody).slice(0, 500000)}},
                    duration_ms: Date.now() - meta.started_at
                }});
            }}, {{once:true}});
            return xhrSend.apply(this, arguments);
        }};

        var el = document.querySelector("li.technology[data-technology='{tech_id}'], [data-technology='{tech_id}']");
        if (!el) return JSON.stringify({{success:false, reason:"找不到科技 {tech_id}"}});
        ['mouseenter', 'mouseover', 'mousemove'].forEach(function(type) {{ el.dispatchEvent(new MouseEvent(type, {{bubbles:true, view:window}})); }});
        el.click();
        return JSON.stringify({{success:true, tech_id:"{tech_id}"}});
    }})()
    """


QUERY_PROBE_EXTRACT_JS = """
(function() {
    return JSON.stringify({
        success:true,
        page_url:window.location.href,
        page_title:document.title,
        records:Array.isArray(window.__ogameQueryProbe) ? window.__ogameQueryProbe : [],
        resource_entries:performance.getEntriesByType('resource').map(function(entry) {
            return {url:entry.name, initiator_type:entry.initiatorType || '', duration_ms:Math.round(entry.duration || 0), transfer_size:entry.transferSize || 0};
        }).filter(function(entry) {
            try { return new URL(entry.url).hostname.endsWith('ogame.gameforge.com'); } catch (_) { return false; }
        })
    });
})()
"""


def is_safe_query_replay(record: Dict[str, Any]) -> bool:
    """Allow replay only for observed same-origin GET read pages/detail queries."""
    request = record.get("request") if isinstance(record, dict) else None
    if not isinstance(request, dict) or str(request.get("method") or "").upper() != "GET":
        return False
    try:
        parsed = urlsplit(str(request.get("url") or ""))
    except ValueError:
        return False
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    page = str(params.get("page") or "").lower()
    component = str(params.get("component") or "").lower()
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.hostname.endswith("ogame.gameforge.com")
        and (
            (page == "ajax" and component in {"technologydetails", "technologydetail"})
            or (
                page == "ingame"
                and component in {"supplies", "facilities", "research"}
                and str(params.get("cp") or "").isdigit()
            )
        )
    )


def query_replay_interaction_js(url: str) -> str:
    encoded_url = json.dumps(str(url))
    return f"""
    (function() {{
        var replayUrl = {encoded_url};
        var parsed = new URL(replayUrl, window.location.href);
        if (parsed.origin !== window.location.origin) return JSON.stringify({{success:false, reason:"拒絕跨來源重播"}});
        window.__ogameQueryReplay = null;
        fetch(parsed.href, {{method:"GET", credentials:"same-origin"}}).then(function(response) {{
            return response.text().then(function(body) {{
                var headers = {{}};
                response.headers.forEach(function(value, key) {{ headers[key] = value; }});
                window.__ogameQueryReplay = {{success:true, status:response.status, response_url:response.url, headers:headers, content_type:response.headers.get("content-type") || "", body:body.slice(0, 500000)}};
            }});
        }}).catch(function(error) {{ window.__ogameQueryReplay = {{success:false, error:String(error)}}; }});
        return JSON.stringify({{success:true, started:true}});
    }})()
    """


QUERY_REPLAY_EXTRACT_JS = """
(function() {
    if (!window.__ogameQueryReplay) return JSON.stringify({success:false, reason:"重播尚未完成"});
    return JSON.stringify({success:true, replay:window.__ogameQueryReplay});
})()
"""


def command_query_probe(
    args: argparse.Namespace,
    *,
    require_run_lease_fn: Optional[Callable] = None,
    execute_followup_fn: Optional[Callable] = None,
    atomic_write_json_fn: Optional[Callable] = None,
    query_trace_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Capture and sanitize three natural economy/technology detail queries."""
    lease_check = require_run_lease_fn or get_dep("require_run_lease", require_run_lease)
    lease_check(str(args.run_id))
    planet_id = int(args.planet_id)
    specs = [
        {"component": "supplies", "tech_id": 1, "label": "metal_mine_detail"},
        {"component": "facilities", "tech_id": 14, "label": "robotics_factory_detail"},
        {"component": "research", "tech_id": 124, "label": "astrophysics_detail"},
    ]
    followup_fn = execute_followup_fn or get_dep("execute_checked_component_followup", execute_checked_component_followup)
    write_json_fn = atomic_write_json_fn or get_dep("atomic_write_json", atomic_write_json)
    target_trace_file = query_trace_file or get_dep("QUERY_TRACE_FILE", QUERY_TRACE_FILE)

    samples: List[Dict[str, Any]] = []
    for index, spec in enumerate(specs):
        result = followup_fn(
            spec["component"],
            planet_id,
            query_probe_interaction_js(int(spec["tech_id"])),
            QUERY_PROBE_EXTRACT_JS,
            wait_after_js=3.0,
        )
        records = result.get("records") if isinstance(result, dict) else None
        if not isinstance(records, list):
            records = []
        same_origin_records = []
        for record in records:
            if not isinstance(record, dict):
                continue
            request = record.get("request")
            if not isinstance(request, dict):
                continue
            try:
                host = urlsplit(str(request.get("url") or "")).hostname or ""
            except ValueError:
                host = ""
            if host.endswith("ogame.gameforge.com"):
                same_origin_records.append(record)
        if same_origin_records:
            record = same_origin_records[0]
            observed_via = "page-local fetch/xhr recorder"
        else:
            page_url = str(result.get("page_url") or game_url(spec["component"], planet_id))
            record = {
                "transport": "navigation",
                "request": {"method": "GET", "url": page_url, "headers": {"cookie": "implicit browser session"}, "body": ""},
                "response": {},
            }
            observed_via = "natural browser navigation; detail data was server-rendered without fetch/xhr"

        sanitized = sanitize_query_trace(record)
        sample = {
            "label": spec["label"],
            "component": spec["component"],
            "tech_id": spec["tech_id"],
            "captured": bool((record.get("response") or {}).get("status")),
            "observed_via": observed_via,
            "trace": sanitized,
            "resource_entries": sanitize_query_trace(result.get("resource_entries", [])),
            "replay": {"attempted": False},
        }

        if getattr(args, "replay", False):
            if is_safe_query_replay(record):
                url = str(record["request"]["url"])
                try:
                    replay_result = followup_fn(
                        spec["component"],
                        planet_id,
                        query_replay_interaction_js(url),
                        QUERY_REPLAY_EXTRACT_JS,
                        wait_after_js=3.0,
                    )
                    replay_record = replay_result.get("replay") if isinstance(replay_result, dict) else {}
                    sample["replay"] = {
                        "attempted": True,
                        "url": sanitize_trace_url(url),
                        "success": bool(replay_record.get("success")),
                        "status": replay_record.get("status"),
                        "trace": sanitize_query_trace(replay_record),
                    }
                except Exception as exc:
                    sample["replay"] = {"attempted": True, "url": sanitize_trace_url(url), "success": False, "error": redact_sensitive_text(str(exc))}
            else:
                sample["replay"] = {"attempted": False, "skipped": True, "reason": "unsafe_replay_target"}
        samples.append(sample)

    output = {
        "version": 1,
        "captured_at": int(time.time()),
        "scope": "natural economy/technology detail click trace",
        "planet_id": str(planet_id),
        "samples": samples,
    }
    write_json_fn(target_trace_file, output)
    summary = {
        "success": True,
        "planet_id": str(planet_id),
        "samples_count": len(samples),
        "captured_count": sum(1 for s in samples if s["captured"]),
        "replay_attempted": any(s["replay"].get("attempted") for s in samples),
        "trace_file": target_trace_file,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return output


def cmd_probe(args: argparse.Namespace) -> Dict[str, Any]:
    """Unified dispatcher for `probe <type>` command."""
    probe_type = getattr(args, "probe_type", None)
    if probe_type == "rates":
        return command_rates_probe(args)
    elif probe_type == "detail":
        return command_detail_probe(args)
    elif probe_type == "export":
        return command_export_probe(args)
    elif probe_type == "query":
        return command_query_probe(args)
    else:
        raise ValueError(f"Unknown probe type: {probe_type}")
