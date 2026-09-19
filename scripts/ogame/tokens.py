"""Token tracking and usage telemetry module for Antigravity sessions.

Parses conversation SQLite metadata to extract exact prompt, cache,
and output token counts for monitoring and optimization.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

CST = timezone(timedelta(hours=8))
DEFAULT_CONV_DIR = os.path.expanduser("~/.gemini/antigravity/conversations")
DEFAULT_MEMORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "runtime",
    "memory",
)


def _parse_protobuf(data: bytes) -> Dict[int, List[Tuple[str, Any]]]:
    """Lightweight pure-python protobuf field parser."""
    idx = 0
    fields: Dict[int, List[Tuple[str, Any]]] = {}
    while idx < len(data):
        try:
            byte = data[idx]
            idx += 1
            wire_type = byte & 7
            field_num = byte >> 3
            if wire_type == 0:  # varint
                val = 0
                shift = 0
                while True:
                    b = data[idx]
                    idx += 1
                    val |= (b & 0x7F) << shift
                    shift += 7
                    if not (b & 0x80):
                        break
                fields.setdefault(field_num, []).append(("varint", val))
            elif wire_type == 2:  # length delimited
                length = 0
                shift = 0
                while True:
                    b = data[idx]
                    idx += 1
                    length |= (b & 0x7F) << shift
                    shift += 7
                    if not (b & 0x80):
                        break
                val_bytes = data[idx : idx + length]
                idx += length
                fields.setdefault(field_num, []).append(("len", val_bytes))
            elif wire_type == 1:  # 64-bit
                idx += 8
            elif wire_type == 5:  # 32-bit
                idx += 4
            else:
                break
        except Exception:
            break
    return fields


def find_conversation_db(
    conv_id: Optional[str] = None, conv_dir: str = DEFAULT_CONV_DIR
) -> Optional[Tuple[str, str]]:
    """Locate active conversation DB path and ID."""
    if conv_id:
        db_path = os.path.join(conv_dir, f"{conv_id}.db")
        if os.path.exists(db_path):
            return conv_id, db_path

    env_id = os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or os.environ.get(
        "CONVERSATION_ID"
    )
    if env_id:
        db_path = os.path.join(conv_dir, f"{env_id}.db")
        if os.path.exists(db_path):
            return env_id, db_path

    if not os.path.exists(conv_dir):
        return None

    # Scan for most recently modified UUID.db
    pattern = os.path.join(conv_dir, "*.db")
    dbs = glob.glob(pattern)
    valid_dbs = []
    for p in dbs:
        fname = os.path.basename(p)
        base, _ = os.path.splitext(fname)
        if re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            base,
            re.IGNORECASE,
        ):
            valid_dbs.append((os.path.getmtime(p), base, p))

    if not valid_dbs:
        return None

    valid_dbs.sort(key=lambda x: x[0], reverse=True)
    return valid_dbs[0][1], valid_dbs[0][2]


def extract_token_stats(db_path: str) -> Dict[str, Any]:
    """Read gen_metadata from SQLite and aggregate token metrics."""
    if not os.path.exists(db_path):
        return {"error": f"Database not found: {db_path}"}

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        cur.execute("SELECT idx, data FROM gen_metadata ORDER BY idx ASC")
        rows = cur.fetchall()
    except Exception as exc:
        conn.close()
        return {"error": str(exc)}
    conn.close()

    total_prompt = 0
    total_cached = 0
    total_candidates = 0
    total_tokens = 0
    steps: List[Dict[str, int]] = []

    for idx, data in rows:
        try:
            f = _parse_protobuf(data)
            if 1 not in f or not f[1]:
                continue
            subdata = f[1][0][1]
            subf = _parse_protobuf(subdata)
            if 4 not in subf or not subf[4]:
                continue
            nested = _parse_protobuf(subf[4][0][1])

            # Field 2 = prompt_tokens, Field 3 = candidate_tokens, Field 5 = cached_tokens
            prompt_tokens = nested.get(2, [("?", 0)])[0][1]
            candidates_tokens = nested.get(3, [("?", 0)])[0][1]
            cached_tokens = nested.get(5, [("?", 0)])[0][1]
            tot = prompt_tokens + candidates_tokens + cached_tokens

            total_prompt += prompt_tokens
            total_candidates += candidates_tokens
            total_cached += cached_tokens
            total_tokens += tot

            steps.append(
                {
                    "step": idx,
                    "prompt": prompt_tokens,
                    "cached": cached_tokens,
                    "candidates": candidates_tokens,
                    "total": tot,
                }
            )
        except Exception:
            continue

    return {
        "step_count": len(steps),
        "total_prompt": total_prompt,
        "total_cached": total_cached,
        "total_candidates": total_candidates,
        "total_tokens": total_tokens,
        "latest_step": steps[-1] if steps else None,
    }


HEALTH_STEP_THRESHOLD = 500
HEALTH_TOKEN_THRESHOLD = 150_000_000


def is_test_run(run_id: Optional[str], memory_dir: str) -> bool:
    """Detect if execution is part of automated tests and prevent polluting production memory."""
    # If caller explicitly provided a non-default custom memory directory, allow test execution
    if os.path.abspath(memory_dir) != os.path.abspath(DEFAULT_MEMORY_DIR):
        return False
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("TEST_ENV"):
        return True
    if run_id and any(
        run_id.startswith(prefix)
        for prefix in ("run-test", "run-abc", "run-crash", "run-flag", "run-err")
    ):
        return True
    return False


def _load_baseline(baseline_file: str) -> Dict[str, Any]:
    """Load baseline dictionary supporting multi-conversation structure and legacy formats."""
    if not os.path.exists(baseline_file):
        return {"active_conv_id": "", "conversations": {}}
    try:
        with open(baseline_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "conversations" not in data:
            legacy_conv = data.get("conv_id", "")
            return {
                "active_conv_id": legacy_conv,
                "conversations": {
                    legacy_conv: {
                        "last_updated": data.get("last_updated", ""),
                        "total_prompt": data.get("total_prompt", 0),
                        "total_cached": data.get("total_cached", 0),
                        "total_candidates": data.get("total_candidates", 0),
                        "total_tokens": data.get("total_tokens", 0),
                        "step_count": data.get("step_count", 0),
                    }
                }
                if legacy_conv
                else {},
            }
        return data
    except Exception:
        return {"active_conv_id": "", "conversations": {}}


def record_tokens(
    conv_id: Optional[str] = None,
    run_id: Optional[str] = None,
    note: str = "",
    memory_dir: str = DEFAULT_MEMORY_DIR,
    conv_dir: str = DEFAULT_CONV_DIR,
) -> Dict[str, Any]:
    """Calculate token delta and record into runtime/memory/token-usage.md."""
    if is_test_run(run_id, memory_dir):
        return {
            "recorded": False,
            "reason": "test_environment_detected_skipped",
            "run_id": run_id,
        }

    found = find_conversation_db(conv_id, conv_dir=conv_dir)
    if not found:
        return {"recorded": False, "reason": "conversation_db_not_found"}

    active_conv_id, db_path = found
    stats = extract_token_stats(db_path)
    if "error" in stats:
        return {"recorded": False, "reason": stats["error"]}

    os.makedirs(memory_dir, exist_ok=True)
    baseline_file = os.path.join(memory_dir, ".token_baseline.json")
    md_file = os.path.join(memory_dir, "token-usage.md")

    baseline_data = _load_baseline(baseline_file)
    convs = baseline_data.setdefault("conversations", {})

    now_cst = datetime.now(CST).strftime("%Y-%m-%d %H:%M")
    run_marker = run_id or "session"

    is_new_conv = active_conv_id not in convs
    if is_new_conv:
        delta_prompt = stats["total_prompt"]
        delta_cached = stats["total_cached"]
        delta_candidates = stats["total_candidates"]
        delta_total = stats["total_tokens"]
        if note:
            note_text = f"{note} [新對話首輪]"
        else:
            note_text = "巡邏完成 [新對話首輪]" if run_id else "記錄 [新對話首輪]"
    else:
        prev = convs[active_conv_id]
        prev_prompt = prev.get("total_prompt", 0)
        prev_cached = prev.get("total_cached", 0)
        prev_candidates = prev.get("total_candidates", 0)
        prev_total = prev.get("total_tokens", 0)

        delta_prompt = max(0, stats["total_prompt"] - prev_prompt)
        delta_cached = max(0, stats["total_cached"] - prev_cached)
        delta_candidates = max(0, stats["total_candidates"] - prev_candidates)
        delta_total = max(0, stats["total_tokens"] - prev_total)
        note_text = note or ("巡邏完成" if run_id else "記錄")

    # Update conversation baseline
    convs[active_conv_id] = {
        "last_updated": now_cst,
        "total_prompt": stats["total_prompt"],
        "total_cached": stats["total_cached"],
        "total_candidates": stats["total_candidates"],
        "total_tokens": stats["total_tokens"],
        "step_count": stats["step_count"],
    }
    baseline_data["active_conv_id"] = active_conv_id

    with open(baseline_file, "w", encoding="utf-8") as f:
        json.dump(baseline_data, f, indent=2, ensure_ascii=False)

    # Prepare markdown line
    table_line = (
        f"| {now_cst} | `{run_marker}` | {delta_prompt:,} | "
        f"{delta_cached:,} | {delta_candidates:,} | **{delta_total:,}** | "
        f"{stats['total_tokens']:,} | {note_text} |\n"
    )

    if not os.path.exists(md_file):
        header = (
            "# Token Usage Log\n\n"
            "> 本文件記錄各輪巡邏與 Session 任務之 Token 實際消耗數據。\n"
            "> 數據來源自 Antigravity Conversation 核心遙測，供策略精簡與 Token 密度優化分析。\n\n"
            "| 時間 (CST) | Run ID | 本輪 Prompt | 本輪 Cache | 本輪 Output | 本輪 Total | 累計 Total | 備註 |\n"
            "|:---|:---|---:|---:|---:|---:|---:|:---|\n"
        )
        content = header + table_line
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        with open(md_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        insert_idx = len(lines)
        for i, l in enumerate(lines):
            if l.startswith("|:---|"):
                insert_idx = i + 1
                break
        lines.insert(insert_idx, table_line)
        with open(md_file, "w", encoding="utf-8") as f:
            f.writelines(lines)

    health_warning = None
    if (
        stats["step_count"] >= HEALTH_STEP_THRESHOLD
        or stats["total_tokens"] >= HEALTH_TOKEN_THRESHOLD
    ):
        health_warning = (
            f"⚠️ Session 上下文膨脹警告：當前對話已累積 {stats['step_count']} 步、"
            f"{stats['total_tokens']:,} tokens。建議在空檔重開新對話重設排程以釋放 Cache。"
        )

    res: Dict[str, Any] = {
        "recorded": True,
        "conv_id": active_conv_id,
        "run_id": run_marker,
        "is_new_conv": is_new_conv,
        "delta": {
            "prompt": delta_prompt,
            "cached": delta_cached,
            "candidates": delta_candidates,
            "total": delta_total,
        },
        "cumulative": {
            "prompt": stats["total_prompt"],
            "cached": stats["total_cached"],
            "candidates": stats["total_candidates"],
            "total": stats["total_tokens"],
        },
        "step_count": stats["step_count"],
    }
    if health_warning:
        res["health_warning"] = health_warning
    return res
