"""Pure resource and 0/1 feasibility planning."""

from __future__ import annotations

import hashlib
import itertools
import secrets
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .models import Intent, IntentKind, WorkflowPlan, WorkflowStep
from .operations import assess_workflow_candidate
from .policy import AccountConstants, SAFETY_POLICY, SafetyPolicy, StrategyPolicy


RESOURCE_KEYS = ("metal", "crystal", "deuterium")
POLICY_PRECEDENCE = ("safety", "live_state", "confirmed_plan", "strategy", "skill_intent")


def resource_vector(value: Mapping[str, Any]) -> Dict[str, int]:
    return {key: int(value.get(key, 0) or 0) for key in RESOURCE_KEYS}


def can_afford(resources: Mapping[str, int], costs: Mapping[str, int]) -> bool:
    return all(int(resources.get(key, 0)) >= int(costs.get(key, 0)) for key in RESOURCE_KEYS)


def sum_costs(actions: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    return {
        key: sum(_candidate_commitment(action)[key] for action in actions)
        for key in RESOURCE_KEYS
    }


def _candidate_commitment(candidate: Mapping[str, Any]) -> Dict[str, int]:
    costs = resource_vector(candidate.get("costs") or {})
    if candidate.get("operation") == "fleet_dispatch" and candidate.get("mission") in {"transport", "deploy"}:
        payload = resource_vector(candidate.get("payload") or {})
        return {key: costs[key] + payload[key] for key in RESOURCE_KEYS}
    return costs


def feasible_packages(
    candidates: Sequence[Mapping[str, Any]],
    spendable: Mapping[str, int],
    storage_capacities: Optional[Mapping[str, int]] = None,
    initial_energy: Optional[int] = None,
    queue_busy: Optional[Mapping[str, bool]] = None,
    safety: SafetyPolicy = SAFETY_POLICY,
) -> List[Dict[str, Any]]:
    """Compute bounded 0/1 bundles without assigning any ROI score."""
    queue_busy = queue_busy or {}
    storage_capacities = storage_capacities or {}
    actionable: List[Mapping[str, Any]] = []
    for candidate in candidates:
        eligible = candidate.get("can_upgrade") is True or candidate.get("can_apply") is True
        if not eligible or queue_busy.get(str(candidate.get("queue")), False):
            continue
        if not candidate.get("energy_safe", True):
            continue
        if candidate.get("section") != "research" and not safety.storage_cost_is_safe(candidate.get("costs", {}), storage_capacities):
            continue
        if can_afford(spendable, _candidate_commitment(candidate)):
            actionable.append(candidate)

    packages: List[Dict[str, Any]] = []
    for size in range(1, len(actionable) + 1):
        for bundle in itertools.combinations(actionable, size):
            queues = [str(action["queue"]) for action in bundle]
            if len(queues) != len(set(queues)):
                continue
            costs = sum_costs(bundle)
            if not can_afford(spendable, costs):
                continue
            non_research_costs = sum_costs([a for a in bundle if a.get("section") != "research"])
            if any(non_research_costs.values()) and not safety.storage_cost_is_safe(non_research_costs, storage_capacities):
                continue
            energy_delta = sum(int(action.get("energy_delta") or 0) for action in bundle)
            if initial_energy is not None and initial_energy + energy_delta < safety.min_safe_energy:
                continue
            action_ids = [str(action["action_id"]) for action in bundle]
            package_id = hashlib.sha256("|".join(sorted(action_ids)).encode("utf-8")).hexdigest()[:12]
            packages.append(
                {
                    "package_id": package_id,
                    "action_ids": action_ids,
                    "costs": costs,
                    "queues": queues,
                    "total_energy_delta": energy_delta,
                }
            )
            if len(packages) >= 50:
                return packages
    return packages


def _candidate_map(confirmed_plan: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    candidates = confirmed_plan.get("candidates")
    if not isinstance(candidates, list):
        raise RuntimeError("confirmed plan 缺少 typed candidates。")
    result: Dict[str, Mapping[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict) or not candidate.get("action_id"):
            raise RuntimeError("confirmed plan candidate schema 無效。")
        result[str(candidate["action_id"])] = candidate
    return result


def build_workflow_plan(
    intent: Intent,
    confirmed_plan: Mapping[str, Any],
    run_id: str,
    strategy: StrategyPolicy,
    constants: AccountConstants,
    *,
    now: Optional[int] = None,
    safety: SafetyPolicy = SAFETY_POLICY,
) -> WorkflowPlan:
    """Resolve policy layers into an immutable plan without browser access."""
    now = int(time.time() if now is None else now)
    if not run_id:
        raise RuntimeError("WorkflowPlan 必須綁定有效 run_id。")
    if str(confirmed_plan.get("plan_id")) != intent.confirmed_plan_id:
        raise RuntimeError("Intent confirmed_plan_id 與目前 plan 不符。")
    if str(confirmed_plan.get("planet_id")) != intent.planet_id:
        raise RuntimeError("Intent planet_id 與 confirmed plan 不符。")
    if confirmed_plan.get("run_id") and str(confirmed_plan.get("run_id")) != run_id:
        raise RuntimeError("Workflow run_id 與 confirmed plan lease 不符。")
    if str(confirmed_plan.get("status", "active")) != "active":
        raise RuntimeError("confirmed plan 非 active；已 fail closed。")
    expires_at = int(confirmed_plan.get("expires_at", 0) or 0)
    if expires_at <= now:
        raise RuntimeError("confirmed plan 已逾時。")
    snapshot_hash = str(confirmed_plan.get("snapshot_hash", ""))
    if not snapshot_hash:
        raise RuntimeError("confirmed plan 缺少 snapshot_hash。")

    candidates = _candidate_map(confirmed_plan)
    try:
        selected = [candidates[action_id] for action_id in intent.action_ids]
    except KeyError as exc:
        raise RuntimeError(f"Intent action_id 不在 confirmed plan：{exc.args[0]}") from exc

    steps: List[WorkflowStep] = []
    if intent.kind == IntentKind.APPLY:
        assessments = [
            assess_workflow_candidate(candidate, confirmed_plan, constants=constants, safety=safety, now=now)
            for candidate in selected
        ]
        queues = [assessment.queue_key for assessment in assessments]
        if len(queues) != len(set(queues)):
            raise RuntimeError("Workflow mutation 佇列衝突。")
        watch_action_id = str(confirmed_plan.get("watch_action_id") or "")
        resource_source = "resources" if watch_action_id in intent.action_ids else "spendable_resources"
        resources = resource_vector(confirmed_plan.get(resource_source) or confirmed_plan.get("resources") or {})
        committed_resources = {
            key: sum(int(assessment.committed_resources[key]) for assessment in assessments)
            for key in RESOURCE_KEYS
        }
        if not can_afford(resources, committed_resources):
            raise RuntimeError("Workflow 依 confirmed live state 資源不足。")
        storage_limited = {
            key: sum(int(assessment.storage_limited_resources[key]) for assessment in assessments)
            for key in RESOURCE_KEYS
        }
        if any(storage_limited.values()):
            capacities_raw = confirmed_plan.get("storage_capacities")
            if not isinstance(capacities_raw, dict) or any(
                int(capacities_raw.get(key, 0) or 0) <= 0 for key in RESOURCE_KEYS
            ):
                raise RuntimeError("Workflow 缺少可信倉庫容量。")
            capacities = resource_vector(capacities_raw)
            if not safety.storage_cost_is_safe(storage_limited, capacities):
                raise RuntimeError("Workflow 違反 90% 倉庫花費限制。")
        energy_deltas = [
            assessment.energy_delta
            for assessment in assessments
            if assessment.energy_delta is not None
        ]
        if energy_deltas:
            current_energy = confirmed_plan.get("energy")
            energy_delta = sum(int(delta) for delta in energy_deltas)
            if not safety.energy_is_safe(
                int(current_energy) if current_energy is not None else None,
                energy_delta,
            ):
                raise RuntimeError("Workflow 能源將低於 MIN_SAFE_ENERGY 或即時能源未知。")
        busy = confirmed_plan.get("queue_busy") or {}
        for index, (candidate, assessment) in enumerate(zip(selected, assessments), start=1):
            if busy.get(assessment.queue_key, False):
                raise RuntimeError(f"{candidate['action_id']} 的即時佇列忙碌。")
            steps.append(
                WorkflowStep(
                    step_id=f"apply-{index:02d}",
                    kind=IntentKind.APPLY,
                    action_id=str(candidate["action_id"]),
                    planet_id=intent.planet_id,
                    mutation=True,
                    payload={"candidate": candidate},
                )
            )
    elif intent.kind == IntentKind.WATCH:
        candidate = selected[0]
        steps.append(
            WorkflowStep(
                step_id="watch-01",
                kind=IntentKind.WATCH,
                action_id=str(candidate["action_id"]),
                planet_id=intent.planet_id,
                mutation=False,
                payload={"candidate": candidate},
            )
        )
    else:
        for index, action_id in enumerate(intent.action_ids, start=1):
            steps.append(
                WorkflowStep(
                    step_id=f"read-{index:02d}",
                    kind=IntentKind.READ,
                    action_id=action_id,
                    planet_id=intent.planet_id,
                    mutation=False,
                    payload={"candidate": candidates[action_id]},
                )
            )

    return WorkflowPlan(
        schema_version=1,
        workflow_id=secrets.token_hex(8),
        run_id=run_id,
        created_at=now,
        expires_at=expires_at,
        confirmed_plan_id=intent.confirmed_plan_id,
        confirmed_plan_hash=snapshot_hash,
        safety_policy_version=safety.version,
        strategy_policy_version=strategy.policy_version,
        policy_precedence=POLICY_PRECEDENCE,
        steps=tuple(steps),
        metadata={"intent": intent.to_dict(), "strategy_profile": strategy.profile},
    )
