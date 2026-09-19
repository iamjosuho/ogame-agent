"""One-command, fail-closed data handoff for a scheduled patrol.

The command owns only the wake gate and initial read-only sources. Strategy,
safety_reviewed, mutations, persistence, audit, and normal finish-run remain
with the coordinator. The movement DOM adapter is deliberately provisional;
see browser.read_global_movement_evidence for the next agent's handoff.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from scripts.ogame import browser, lifecycle, matrix
from scripts.ogame.policy import DEFAULT_CONSTANTS_PATH, load_account_constants


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_FILES = {
    "checklist": Path("CHECKLIST.md"),
    "game_state": Path("runtime/memory/GameState.md"),
    "todo": Path("runtime/memory/TODO.md"),
    "errors": Path("runtime/memory/errors.md"),
}
RESOURCE_KEYS = ("metal", "crystal", "deuterium")


class PatrolStartError(RuntimeError):
    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


def _source_manifest(project_root: Path, constants_path: Path, constants_loader: Callable) -> Dict[str, Any]:
    files = {**SOURCE_FILES, "constants": constants_path}
    manifest: Dict[str, Any] = {}
    for name, relative_path in files.items():
        path = relative_path if relative_path.is_absolute() else project_root / relative_path
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise PatrolStartError("memory_source_missing", f"{name} 無法讀取：{exc}") from exc
        if name != "errors" and not raw.strip():
            raise PatrolStartError("memory_source_invalid", f"{name} 為空。")
        if name != "constants":
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PatrolStartError("memory_source_invalid", f"{name} 不是 UTF-8。") from exc
        manifest[name] = {
            "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
    try:
        constants = constants_loader(str(manifest["constants"]["path"]))
        if not constants.cargo_capacities:
            raise RuntimeError("cargo_capacities 為空。")
    except Exception as exc:
        raise PatrolStartError("account_constants_invalid", str(exc)) from exc
    return manifest


def _validate_movement(value: Mapping[str, Any]) -> str:
    """Require a proved account-wide page before scout_complete.

    HANDOFF FOR THE MOVEMENT DOM AGENT: Return success=True, scope='account',
    coverage='verified', threat_status='none'|'hostile'|'unknown', and events[]
    only after validating the real movement root/empty state and event direction
    evidence. 'unknown' is allowed for ambiguous rows and blocks routine work
    until coordinator safety review. Unverified page/selector coverage aborts.
    Add fixture-based tests for both a real empty page and mixed own/incoming
    rows; the current browser adapter intentionally returns unverified.
    """
    if not isinstance(value, Mapping) or value.get("success") is not True:
        raise PatrolStartError("movement_read_failed", "movement 沒有結構化成功證據。")
    if value.get("scope") != "account" or value.get("coverage") != "verified":
        raise PatrolStartError("movement_dom_unverified", "movement 帳號範圍或 DOM coverage 未驗證。")
    page_evidence = value.get("page_evidence")
    if not isinstance(page_evidence, Mapping) or page_evidence.get("root_verified") is not True:
        raise PatrolStartError("movement_dom_unverified", "movement root 未驗證。")
    events = value.get("events")
    status = value.get("threat_status")
    if not isinstance(events, list) or status not in {"none", "hostile", "unknown"}:
        raise PatrolStartError("movement_evidence_invalid", "movement 事件或敵襲狀態無效。")
    if not events and page_evidence.get("empty_state_verified") is not True:
        raise PatrolStartError("movement_dom_unverified", "空事件頁缺少 empty-state 證據。")
    if status == "none" and events:
        if any(
            not isinstance(event, Mapping)
            or event.get("direction") not in {"own", "neutral"}
            or not str(event.get("direction_evidence") or "").strip()
            for event in events
        ):
            raise PatrolStartError("movement_direction_unverified", "無敵襲結論缺少逐列方向證據。")
    if status == "hostile":
        hostile_ids = value.get("hostile_event_ids")
        if not isinstance(hostile_ids, list) or not hostile_ids:
            raise PatrolStartError("movement_evidence_invalid", "敵襲缺少可追溯 event ID。")
        identified = {
            event.get("id") for event in events
            if isinstance(event, Mapping)
            and event.get("direction") == "incoming_hostile"
            and str(event.get("direction_evidence") or "").strip()
        }
        if not set(hostile_ids).issubset(identified):
            raise PatrolStartError("movement_direction_unverified", "敵襲 ID 缺少敵方來向證據。")
    return str(status)


def _validate_matrix(value: Mapping[str, Any], run_id: str) -> str:
    if not isinstance(value, Mapping) or value.get("success") is not True:
        raise PatrolStartError("matrix_invalid", "matrix 沒有成功證據。")
    if not str(value.get("source") or "").startswith("empire.standalone"):
        raise PatrolStartError("matrix_source_invalid", "matrix 未來自 Empire standalone。")
    if value.get("queue_coverage") != "empire.standalone":
        raise PatrolStartError("matrix_queue_unverified", "Empire queue coverage 未驗證。")
    if value.get("active_planet_restored") is not True or value.get("run_id") != run_id:
        raise PatrolStartError("matrix_context_invalid", "matrix planet restore 或 run_id 不符。")
    planets = value.get("planets")
    if not isinstance(planets, list) or not planets:
        raise PatrolStartError("matrix_planets_invalid", "matrix 星球清單為空。")
    planet_ids = set()
    for planet in planets:
        if not isinstance(planet, Mapping):
            raise PatrolStartError("matrix_planets_invalid", "matrix 星球列格式無效。")
        cp = planet.get("planet_id")
        if isinstance(cp, bool) or not isinstance(cp, int) or cp <= 0 or cp in planet_ids:
            raise PatrolStartError("matrix_planets_invalid", "matrix 星球 ID 缺失或重複。")
        planet_ids.add(cp)
        for key in ("resources", "storage"):
            vector = planet.get(key)
            if not isinstance(vector, Mapping) or any(
                isinstance(vector.get(resource), bool)
                or not isinstance(vector.get(resource), int)
                or vector.get(resource) < 0
                for resource in RESOURCE_KEYS
            ):
                raise PatrolStartError("matrix_planets_invalid", f"matrix {key} 不完整。")
        if not isinstance(planet.get("queues"), list) or any(
            not isinstance(planet.get(key), bool)
            for key in ("building_busy", "research_busy", "shipyard_busy", "lifeform_building_busy", "lifeform_research_busy")
        ):
            raise PatrolStartError("matrix_planets_invalid", "matrix queue 欄位不完整。")
        if any(not isinstance(planet.get(key), Mapping) for key in ("buildings", "researches", "ships", "defenses")):
            raise PatrolStartError("matrix_planets_invalid", "matrix 等級或艦船欄位不完整。")
    rates_coverage = str(value.get("rates_coverage") or "not_provided")
    if rates_coverage != "official.accountInfo":
        for planet in planets:
            rates = planet.get("rates") if isinstance(planet, Mapping) else None
            if not isinstance(rates, Mapping) or any(rates.get(key) is not None for key in RESOURCE_KEYS):
                raise PatrolStartError("matrix_rates_invalid", "未知產速必須為 null。")
        totals = value.get("totals")
        total_rates = totals.get("rates") if isinstance(totals, Mapping) else None
        if not isinstance(total_rates, Mapping) or any(total_rates.get(key) is not None for key in RESOURCE_KEYS):
            raise PatrolStartError("matrix_rates_invalid", "未知總產速必須為 null。")
    return rates_coverage


def command_patrol_start(
    args: argparse.Namespace,
    *,
    project_root: Path = PROJECT_ROOT,
    memory_dir: Optional[Path] = None,
    gate_fn: Callable = lifecycle.command_check_wake,
    movement_fn: Callable = browser.read_global_movement_evidence,
    matrix_fn: Callable = matrix.cmd_matrix,
    step_fn: Callable = lifecycle.command_patrol_step,
    finish_fn: Callable = lifecycle.command_finish_run,
    release_fn: Callable = lifecycle.release_run_lease,
    constants_loader: Callable = load_account_constants,
    write_fn: Callable = lifecycle.atomic_write_json,
) -> Dict[str, Any]:
    """Acquire once, prepare verified sources, and print only compact JSON."""
    target_dir = Path(memory_dir or project_root / "runtime" / "memory")
    gate_args = argparse.Namespace(acquire=True, force=False, output="json", silent=True)
    gate = gate_fn(gate_args)
    if not isinstance(gate, Mapping) or gate.get("acquired") is not True or not gate.get("run_id"):
        # Real check-wake exits 0 on too_early/overlap, before game I/O.
        return {"status": "skipped", "reason": str(gate.get("reason", "not_due")) if isinstance(gate, Mapping) else "not_due"}
    run_id = str(gate["run_id"])
    stage = "sources"
    result_path = target_dir / "patrol-start-result.json"
    try:
        sources = _source_manifest(project_root, Path(DEFAULT_CONSTANTS_PATH), constants_loader)
        sources_path = target_dir / "patrol-start-sources.json"
        write_fn(str(sources_path), {"run_id": run_id, "sources": sources})
        memory_step = step_fn(argparse.Namespace(run_id=run_id, phase="memory_loaded", evidence_ref=str(sources_path), output="json", silent=True))
        if not isinstance(memory_step, Mapping) or memory_step.get("success") is not True:
            raise PatrolStartError("memory_checkpoint_failed", "memory_loaded checkpoint 未確認成功。")

        stage = "movement"
        movement = movement_fn()
        movement_path = target_dir / "movement-events.json"
        threat_status = None
        try:
            threat_status = _validate_movement(movement)
        finally:
            # Preserve raw evidence for the DOM agent, but never publish it as
            # verified when validation fails.
            movement_record = {
                **movement,
                "run_id": run_id,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "validation_status": "verified" if threat_status else "unverified",
            }
            write_fn(str(movement_path), movement_record)

        stage = "matrix"
        with redirect_stdout(io.StringIO()):
            # Internal patrol mode keeps accountInfo rate enrichment, but does
            # not downgrade to official/HTML if the Empire safety source fails.
            snapshot = matrix_fn(argparse.Namespace(source="patrol", output="json", run_id=run_id))
        rates_coverage = _validate_matrix(snapshot, run_id)
        scout_path = target_dir / "scout-report.json"
        try:
            written_snapshot = json.loads(scout_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PatrolStartError("matrix_report_missing", "matrix 未寫入有效 scout-report.json。") from exc
        if written_snapshot != snapshot:
            raise PatrolStartError("matrix_report_mismatch", "scout-report.json 與本輪 matrix 回傳不符。")
        # Keep the old matrix alarms field out of the threat decision: it is
        # currently synthesized as [] even when movement was never read.
        scout_step = step_fn(argparse.Namespace(run_id=run_id, phase="scout_complete", evidence_ref=f"{scout_path}+{movement_path}", output="json", silent=True))
        if not isinstance(scout_step, Mapping) or scout_step.get("success") is not True:
            raise PatrolStartError("scout_checkpoint_failed", "scout_complete checkpoint 未確認成功。")

        result = {
            "status": "ready",
            "run_id": run_id,
            "next_phase": "safety_reviewed",
            "threat_status": threat_status,
            "routine_blocked_until_safety_review": threat_status != "none",
            "source": snapshot["source"],
            "queue_coverage": snapshot["queue_coverage"],
            "rates_coverage": rates_coverage,
            "evidence": {
                "sources": str(sources_path),
                "movement": str(movement_path),
                "scout": str(scout_path),
                "handoff": str(result_path),
            },
        }
        write_fn(str(result_path), result)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return result
    except Exception as exc:
        reason = exc.reason_code if isinstance(exc, PatrolStartError) else f"patrol_start_{stage}_failed"
        result = {"status": "aborted", "run_id": run_id, "abort_reason": reason, "handoff": str(result_path)}
        try:
            write_fn(str(result_path), result)
        except Exception:
            result["handoff"] = None
        finally:
            # No commit: this is an initial-source abort, not a completed run.
            try:
                finished = finish_fn(argparse.Namespace(run_id=run_id, abort_reason=reason, commit=False, record_tokens=False, output="json", silent=True))
                if not isinstance(finished, Mapping) or finished.get("released") is not True:
                    raise RuntimeError("finish-run 未確認釋放 lease。")
            except Exception:
                # lifecycle.finish-run can fail before its own release finally
                # if contract finalization cannot be written. Release only this
                # run's lease as a last resort and disclose lost finalization.
                try:
                    result["lease_released_by_fallback"] = release_fn(run_id)
                except Exception:
                    result["lease_released_by_fallback"] = False
                result["contract_finalization_failed"] = True
                if not result["lease_released_by_fallback"]:
                    result["status"] = "release_failed"
                try:
                    write_fn(str(result_path), result)
                except Exception:
                    result["handoff"] = None
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return result
