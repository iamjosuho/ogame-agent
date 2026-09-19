"""Immutable, JSON-safe contracts shared by planning and execution."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, Mapping, Sequence, Tuple


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_thaw(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ActionStatus(str, Enum):
    APPLIED = "applied"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    UNCERTAIN = "uncertain"


class IntentKind(str, Enum):
    APPLY = "apply"
    WATCH = "watch"
    READ = "read"


@dataclass(frozen=True)
class Intent:
    """Typed input accepted from the patrol skill.

    The skill may select verified action IDs, but it cannot provide selectors,
    technology IDs, URLs, costs, or mutation payloads.
    """

    schema_version: int
    kind: IntentKind
    planet_id: str
    confirmed_plan_id: str
    action_ids: Tuple[str, ...]
    source: str = "skill"

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or self.schema_version != 1:
            raise ValueError("Intent schema_version 必須為 1。")
        if not isinstance(self.planet_id, str) or not self.planet_id.isdigit():
            raise ValueError("Intent planet_id 必須是數字 cp。")
        if not isinstance(self.confirmed_plan_id, str) or not self.confirmed_plan_id:
            raise ValueError("Intent 必須綁定 confirmed_plan_id。")
        if not isinstance(self.action_ids, tuple) or not all(
            isinstance(item, str) and item for item in self.action_ids
        ):
            raise ValueError("Intent action_ids 必須是非空字串陣列。")
        if not isinstance(self.source, str) or not self.source or len(self.source) > 80:
            raise ValueError("Intent source 必須是 1-80 字元字串。")
        if self.kind in {IntentKind.APPLY, IntentKind.WATCH} and not self.action_ids:
            raise ValueError("Mutation/watch Intent 必須包含 action_ids。")
        if self.kind == IntentKind.WATCH and len(self.action_ids) != 1:
            raise ValueError("Watch Intent 只能指定一個 action_id。")
        if len(set(self.action_ids)) != len(self.action_ids):
            raise ValueError("Intent action_ids 不得重複。")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Intent":
        allowed = {"schema_version", "kind", "planet_id", "confirmed_plan_id", "action_ids", "source"}
        extras = set(value) - allowed
        if extras:
            raise ValueError(f"Intent 包含未知欄位：{', '.join(sorted(extras))}")
        raw_actions = value.get("action_ids")
        if not isinstance(raw_actions, Sequence) or isinstance(raw_actions, (str, bytes)) or not all(
            isinstance(item, str) and item for item in raw_actions
        ):
            raise ValueError("Intent action_ids 必須是陣列。")
        if not isinstance(value.get("kind"), str):
            raise ValueError("Intent kind 必須是 apply/watch/read。")
        if not isinstance(value.get("planet_id"), str):
            raise ValueError("Intent planet_id 必須是字串 cp。")
        if not isinstance(value.get("confirmed_plan_id"), str):
            raise ValueError("Intent confirmed_plan_id 必須是字串。")
        if "source" in value and not isinstance(value["source"], str):
            raise ValueError("Intent source 必須是字串。")
        try:
            kind = IntentKind(str(value.get("kind")))
        except ValueError as exc:
            raise ValueError("Intent kind 必須是 apply/watch/read。") from exc
        return cls(
            schema_version=value.get("schema_version"),
            kind=kind,
            planet_id=value.get("planet_id", ""),
            confirmed_plan_id=value.get("confirmed_plan_id", ""),
            action_ids=tuple(raw_actions),
            source=value.get("source", "skill"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "planet_id": self.planet_id,
            "confirmed_plan_id": self.confirmed_plan_id,
            "action_ids": list(self.action_ids),
            "source": self.source,
        }


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    kind: IntentKind
    action_id: str
    planet_id: str
    mutation: bool
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "planet_id", str(self.planet_id))
        object.__setattr__(self, "payload", _freeze(self.payload))
        if not self.step_id or not self.action_id:
            raise ValueError("WorkflowStep 必須包含 step_id 與 action_id。")
        if self.mutation != (self.kind == IntentKind.APPLY):
            raise ValueError("只有 apply step 可以標記為 mutation。")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowStep":
        return cls(
            step_id=str(value["step_id"]),
            kind=IntentKind(str(value["kind"])),
            action_id=str(value["action_id"]),
            planet_id=str(value["planet_id"]),
            mutation=bool(value["mutation"]),
            payload=value.get("payload", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "kind": self.kind.value,
            "action_id": self.action_id,
            "planet_id": self.planet_id,
            "mutation": self.mutation,
            "payload": _thaw(self.payload),
        }


@dataclass(frozen=True)
class WorkflowPlan:
    schema_version: int
    workflow_id: str
    run_id: str
    created_at: int
    expires_at: int
    confirmed_plan_id: str
    confirmed_plan_hash: str
    safety_policy_version: str
    strategy_policy_version: str
    policy_precedence: Tuple[str, ...]
    steps: Tuple[WorkflowStep, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "policy_precedence", tuple(self.policy_precedence))
        object.__setattr__(self, "metadata", _freeze(self.metadata))
        if self.schema_version != 1:
            raise ValueError("WorkflowPlan schema_version 必須為 1。")
        if not self.workflow_id or not self.run_id:
            raise ValueError("WorkflowPlan 必須綁定 workflow_id 與 run_id。")
        if self.expires_at <= self.created_at:
            raise ValueError("WorkflowPlan expires_at 必須晚於 created_at。")
        if not self.steps:
            raise ValueError("WorkflowPlan 至少需要一個 step。")
        if len({step.step_id for step in self.steps}) != len(self.steps):
            raise ValueError("WorkflowPlan step_id 不得重複。")

    @property
    def plan_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowPlan":
        return cls(
            schema_version=int(value["schema_version"]),
            workflow_id=str(value["workflow_id"]),
            run_id=str(value["run_id"]),
            created_at=int(value["created_at"]),
            expires_at=int(value["expires_at"]),
            confirmed_plan_id=str(value["confirmed_plan_id"]),
            confirmed_plan_hash=str(value["confirmed_plan_hash"]),
            safety_policy_version=str(value["safety_policy_version"]),
            strategy_policy_version=str(value["strategy_policy_version"]),
            policy_precedence=tuple(str(item) for item in value["policy_precedence"]),
            steps=tuple(WorkflowStep.from_dict(item) for item in value["steps"]),
            metadata=value.get("metadata", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "confirmed_plan_id": self.confirmed_plan_id,
            "confirmed_plan_hash": self.confirmed_plan_hash,
            "safety_policy_version": self.safety_policy_version,
            "strategy_policy_version": self.strategy_policy_version,
            "policy_precedence": list(self.policy_precedence),
            "steps": [step.to_dict() for step in self.steps],
            "metadata": _thaw(self.metadata),
        }


@dataclass(frozen=True)
class ActionResult:
    status: ActionStatus
    action_id: str
    planet_id: str
    reason: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)
    observed_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self) -> None:
        object.__setattr__(self, "planet_id", str(self.planet_id))
        object.__setattr__(self, "evidence", _freeze(self.evidence))
        if not self.action_id or not self.planet_id:
            raise ValueError("ActionResult 必須包含 action_id 與 planet_id。")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ActionResult":
        return cls(
            status=ActionStatus(str(value["status"])),
            action_id=str(value["action_id"]),
            planet_id=str(value["planet_id"]),
            reason=str(value.get("reason", "")),
            evidence=value.get("evidence", {}),
            observed_at=int(value.get("observed_at", time.time())),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "action_id": self.action_id,
            "planet_id": self.planet_id,
            "reason": self.reason,
            "evidence": _thaw(self.evidence),
            "observed_at": self.observed_at,
        }
