"""Pure, ordered completion contract for one scheduled patrol run.

The contract makes omissions observable and machine-blocking.  It does not
perform browser I/O and it never owns or releases the patrol lease.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


PATROL_PHASES = (
    "wake_gate",
    "memory_loaded",
    "scout_complete",
    "safety_reviewed",
    "strategy_complete",
    "execution_complete",
    "persistence_complete",
)
ROUTINE_CATEGORIES = ("transport", "expedition", "farming", "lifeform")
ROUTINE_STATUSES = ("planned", "not_due", "no_surplus", "blocked", "complete")


class PatrolContractError(ValueError):
    """The caller attempted to skip or falsify a required patrol checkpoint."""


def new_patrol_contract(run_id: str, started_at: int) -> Dict[str, Any]:
    if not isinstance(run_id, str) or not run_id:
        raise PatrolContractError("patrol contract 必須綁定非空 run_id。")
    if isinstance(started_at, bool) or not isinstance(started_at, int) or started_at <= 0:
        raise PatrolContractError("patrol contract started_at 必須是正整數時間戳。")
    return {
        "schema_version": 1,
        "run_id": run_id,
        "started_at": started_at,
        "status": "active",
        "completed_phases": ["wake_gate"],
        "routine": {},
        "evidence": {"wake_gate": "check-wake --acquire"},
    }


def _normalize_routine(value: Optional[Mapping[str, Any]], *, final: bool) -> Dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(ROUTINE_CATEGORIES):
        raise PatrolContractError(
            "routine 必須完整包含 transport/expedition/farming/lifeform。"
        )
    routine: Dict[str, str] = {}
    for category in ROUTINE_CATEGORIES:
        status = value.get(category)
        if not isinstance(status, str) or status not in ROUTINE_STATUSES:
            raise PatrolContractError(f"routine.{category} 狀態無效：{status}")
        if final and status == "planned":
            raise PatrolContractError(
                f"routine.{category} 尚為 planned；execution 收尾前必須解析為最終狀態。"
            )
        routine[category] = status
    return routine


def advance_patrol_contract(
    state: Mapping[str, Any],
    phase: str,
    evidence_ref: str,
    *,
    routine: Optional[Mapping[str, Any]] = None,
    updated_at: int,
) -> Dict[str, Any]:
    if state.get("schema_version") != 1 or state.get("status") != "active":
        raise PatrolContractError("patrol contract 不在 active schema-v1 狀態。")
    if phase not in PATROL_PHASES[1:]:
        raise PatrolContractError(f"未知 patrol phase：{phase}")
    if not isinstance(evidence_ref, str) or not evidence_ref.strip():
        raise PatrolContractError("每個 patrol checkpoint 都必須提供 evidence_ref。")

    completed = state.get("completed_phases")
    if not isinstance(completed, list) or not all(item in PATROL_PHASES for item in completed):
        raise PatrolContractError("patrol completed_phases 格式無效。")
    expected_index = len(completed)
    if expected_index >= len(PATROL_PHASES):
        if phase == completed[-1]:
            return dict(state)
        raise PatrolContractError("patrol contract 已完成所有 phase。")
    expected = PATROL_PHASES[expected_index]
    if phase != expected:
        raise PatrolContractError(f"不得跳步：下一步必須是 {expected}，不是 {phase}。")

    normalized_routine: Optional[Dict[str, str]] = None
    if phase == "strategy_complete":
        normalized_routine = _normalize_routine(routine, final=False)
    elif phase == "execution_complete":
        normalized_routine = _normalize_routine(routine, final=True)
    elif routine is not None:
        raise PatrolContractError("只有 strategy/execution checkpoint 可以提交 routine 狀態。")

    result = dict(state)
    result["completed_phases"] = [*completed, phase]
    result["updated_at"] = int(updated_at)
    evidence = dict(state.get("evidence") or {})
    evidence[phase] = evidence_ref.strip()
    result["evidence"] = evidence
    if normalized_routine is not None:
        result["routine"] = normalized_routine
    return result


def audit_patrol_contract(state: Optional[Mapping[str, Any]], run_id: str) -> Dict[str, Any]:
    missing_phases = list(PATROL_PHASES)
    reasons = []
    if not isinstance(state, Mapping):
        return {
            "complete": False,
            "run_id": run_id,
            "missing_phases": missing_phases,
            "reasons": ["patrol_contract_missing"],
        }
    if state.get("schema_version") != 1:
        reasons.append("schema_version_invalid")
    if state.get("run_id") != run_id:
        reasons.append("run_id_mismatch")
    completed = state.get("completed_phases")
    if not isinstance(completed, list):
        completed = []
        reasons.append("completed_phases_invalid")
    missing_phases = [phase for phase in PATROL_PHASES if phase not in completed]
    if completed != list(PATROL_PHASES[: len(completed)]):
        reasons.append("phase_order_invalid")
    try:
        _normalize_routine(state.get("routine"), final=True)
    except PatrolContractError as exc:
        reasons.append(str(exc))
    evidence = state.get("evidence")
    if not isinstance(evidence, Mapping) or any(
        not isinstance(evidence.get(phase), str) or not evidence.get(phase, "").strip()
        for phase in completed
    ):
        reasons.append("checkpoint_evidence_incomplete")
    if missing_phases:
        reasons.append("required_phases_incomplete")
    return {
        "complete": not reasons,
        "run_id": run_id,
        "missing_phases": missing_phases,
        "reasons": reasons,
        "routine": dict(state.get("routine") or {}),
    }


def finalize_patrol_contract(
    state: Mapping[str, Any],
    status: str,
    ended_at: int,
    *,
    reason: str = "",
) -> Dict[str, Any]:
    if status not in {"completed", "aborted", "incomplete"}:
        raise PatrolContractError(f"patrol final status 無效：{status}")
    result = dict(state)
    result["status"] = status
    result["ended_at"] = int(ended_at)
    if reason:
        result["reason"] = reason
    return result
