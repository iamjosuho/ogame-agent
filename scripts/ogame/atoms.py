"""Public domain-safe atoms built on injected private browser adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping

from .models import ActionResult, ActionStatus


@dataclass(frozen=True)
class PlannedMutationCallbacks:
    pin_and_read: Callable[[Mapping[str, Any], int], Mapping[str, Any]]
    prevalidate: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]
    execute: Callable[[Mapping[str, Any], int], Mapping[str, Any]]
    read_postcondition: Callable[[Mapping[str, Any], int], Mapping[str, Any]]
    verify_postcondition: Callable[[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]


def read_lifeform_atom(
    planet_id: int,
    read_component: Callable[[str, int], Mapping[str, Any]],
) -> Dict[str, Any]:
    """Read both Lifeform domains through the same planet-pinned adapter."""
    result: Dict[str, Any] = {"success": True, "planet_id": str(planet_id)}
    for component in ("lfbuildings", "lfresearch"):
        try:
            observed = read_component(component, planet_id)
        except Exception as exc:
            return {
                "success": False,
                "planet_id": str(planet_id),
                "reason": f"{component}_read_failed: {exc}",
            }
        if not isinstance(observed, Mapping) or observed.get("success") is not True:
            return {
                "success": False,
                "planet_id": str(planet_id),
                "reason": f"{component}_read_unconfirmed",
                "observed": dict(observed) if isinstance(observed, Mapping) else observed,
            }
        if str(observed.get("planet_id", planet_id)) != str(planet_id):
            return {
                "success": False,
                "planet_id": str(planet_id),
                "reason": f"{component}_planet_pin_mismatch",
                "observed": dict(observed),
            }
        result[component] = dict(observed)
    return result


def apply_planned_action_atom(
    candidate: Mapping[str, Any],
    planet_id: int,
    callbacks: PlannedMutationCallbacks,
) -> ActionResult:
    """Pin, prevalidate, execute, and prove one confirmed mutation."""
    action_id = str(candidate.get("action_id", ""))
    try:
        pinned = callbacks.pin_and_read(candidate, planet_id)
    except Exception as exc:
        return ActionResult(ActionStatus.BLOCKED, action_id, str(planet_id), f"planet_pin_failed: {exc}")
    if str(pinned.get("planet_id", "")) != str(planet_id):
        return ActionResult(ActionStatus.BLOCKED, action_id, str(planet_id), "planet_pin_mismatch", {"pin": pinned})

    try:
        validation = callbacks.prevalidate(candidate, pinned)
    except Exception as exc:
        return ActionResult(ActionStatus.BLOCKED, action_id, str(planet_id), f"prevalidation_failed: {exc}")
    if validation.get("skip"):
        return ActionResult(
            ActionStatus.SKIPPED,
            action_id,
            str(planet_id),
            str(validation.get("reason") or "already_satisfied"),
            {"pin": pinned, "prevalidation": validation},
        )
    if not validation.get("ok"):
        return ActionResult(
            ActionStatus.BLOCKED,
            action_id,
            str(planet_id),
            str(validation.get("reason") or "prevalidation_blocked"),
            {"pin": pinned, "prevalidation": validation},
        )

    try:
        execution = callbacks.execute(candidate, planet_id)
    except Exception as exc:
        return ActionResult(
            ActionStatus.UNCERTAIN,
            action_id,
            str(planet_id),
            f"execution_boundary_error: {exc}",
            {"pin": pinned, "prevalidation": validation},
        )
    if not execution.get("success"):
        status = ActionStatus.BLOCKED if execution.get("mutation_submitted") is False else ActionStatus.UNCERTAIN
        return ActionResult(
            status,
            action_id,
            str(planet_id),
            str(execution.get("reason") or "execution_result_not_successful"),
            {"pin": pinned, "prevalidation": validation, "execution": execution},
        )

    try:
        after = callbacks.read_postcondition(candidate, planet_id)
        verification = callbacks.verify_postcondition(candidate, execution, after)
    except Exception as exc:
        return ActionResult(
            ActionStatus.UNCERTAIN,
            action_id,
            str(planet_id),
            f"postcondition_read_failed: {exc}",
            {"pin": pinned, "prevalidation": validation, "execution": execution},
        )
    evidence = {
        "pin": pinned,
        "prevalidation": validation,
        "execution": execution,
        "post_state": after,
        "postcondition": verification,
    }
    if not verification.get("success"):
        reasons = verification.get("reasons") or ["postcondition_failed"]
        return ActionResult(
            ActionStatus.UNCERTAIN,
            action_id,
            str(planet_id),
            ", ".join(str(reason) for reason in reasons),
            evidence,
        )
    return ActionResult(ActionStatus.APPLIED, action_id, str(planet_id), evidence=evidence)
