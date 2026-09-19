"""Durable workflow journal and fail-closed execution runner."""

from __future__ import annotations

import json
import fcntl
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any, Callable, Dict, Mapping

from .models import ActionResult, ActionStatus, IntentKind, WorkflowPlan, WorkflowStep


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_MUTATION_THREAD_LOCKS: Dict[str, threading.Lock] = {}
_MUTATION_THREAD_LOCKS_GUARD = threading.Lock()


def _mutation_thread_lock(root: str) -> threading.Lock:
    with _MUTATION_THREAD_LOCKS_GUARD:
        return _MUTATION_THREAD_LOCKS.setdefault(root, threading.Lock())


class WorkflowJournal:
    """Keep active state hot and move only completed workflows to archive."""

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        self.active_dir = os.path.join(self.root, "active")
        self.archive_dir = os.path.join(self.root, "archive")

    def _path(self, directory: str, workflow_id: str) -> str:
        if not _SAFE_ID.fullmatch(workflow_id):
            raise RuntimeError("workflow_id 格式無效。")
        return os.path.join(directory, f"{workflow_id}.json")

    @staticmethod
    def _atomic_write(path: str, value: Mapping[str, Any]) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temporary = f"{path}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)

    def create(self, plan: WorkflowPlan) -> Dict[str, Any]:
        active_path = self._path(self.active_dir, plan.workflow_id)
        archive_path = self._path(self.archive_dir, plan.workflow_id)
        if os.path.exists(active_path) or os.path.exists(archive_path):
            raise RuntimeError("workflow_id 已存在。")
        state = {
            "schema_version": 1,
            "workflow_id": plan.workflow_id,
            "plan": plan.to_dict(),
            "plan_hash": plan.plan_hash,
            "status": "pending",
            "state_certainty": "certain",
            "in_flight_step_id": None,
            "active_run_id": plan.run_id,
            "lease_history": [plan.run_id],
            "results": [],
            "created_at": plan.created_at,
            "updated_at": plan.created_at,
        }
        self._atomic_write(active_path, state)
        return state

    def load(self, workflow_id: str) -> Dict[str, Any]:
        active_path = self._path(self.active_dir, workflow_id)
        archive_path = self._path(self.archive_dir, workflow_id)
        path = active_path if os.path.exists(active_path) else archive_path
        try:
            with open(path, encoding="utf-8") as handle:
                state = json.load(handle)
        except FileNotFoundError as exc:
            raise RuntimeError("找不到 workflow journal。") from exc
        if not isinstance(state, dict):
            raise RuntimeError("workflow journal schema 無效。")
        try:
            plan = WorkflowPlan.from_dict(state.get("plan", {}))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"WorkflowPlan schema 無效：{exc}") from exc
        if state.get("plan_hash") != plan.plan_hash:
            raise RuntimeError("WorkflowPlan immutable hash 不符；已 fail closed。")
        return state

    def _write_active(self, state: Dict[str, Any]) -> None:
        state["updated_at"] = int(time.time())
        self._atomic_write(self._path(self.active_dir, str(state["workflow_id"])), state)

    @contextmanager
    def mutation_lock(self):
        """Serialize stateful steps across threads and controller processes."""
        os.makedirs(self.root, exist_ok=True)
        with _mutation_thread_lock(self.root):
            with open(os.path.join(self.root, ".mutation.lock"), "a+", encoding="utf-8") as guard:
                fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(guard.fileno(), fcntl.LOCK_UN)

    def start(self, workflow_id: str, run_id: str) -> Dict[str, Any]:
        state = self.load(workflow_id)
        status = state.get("status")
        if status == "pending":
            if run_id != state.get("active_run_id"):
                raise RuntimeError("首次 workflow run 必須使用 WorkflowPlan 綁定的 lease。")
        elif status == "interrupted":
            if state.get("state_certainty") != "certain":
                raise RuntimeError("中斷狀態不確定；禁止換 lease 續跑。")
            if any(item.get("status") == ActionStatus.UNCERTAIN.value for item in state.get("results", [])):
                raise RuntimeError("已有 uncertain 結果；禁止續跑。")
            state["active_run_id"] = run_id
            history = state.setdefault("lease_history", [])
            if run_id not in history:
                history.append(run_id)
        elif status == "running":
            if run_id == state.get("active_run_id"):
                raise RuntimeError("journal 已由同一 lease 執行中。")
            if state.get("state_certainty") != "certain" or state.get("in_flight_step_id"):
                raise RuntimeError("journal 有 in-flight mutation；中斷狀態不確定，禁止續跑。")
            state["status"] = "interrupted"
            state["active_run_id"] = run_id
            history = state.setdefault("lease_history", [])
            if run_id not in history:
                history.append(run_id)
        else:
            raise RuntimeError(f"workflow 狀態 {status} 不可執行。")
        state["status"] = "running"
        state["state_certainty"] = "certain"
        self._write_active(state)
        return state

    def begin_stateful_step(self, workflow_id: str, step: WorkflowStep) -> Dict[str, Any]:
        state = self.load(workflow_id)
        if state.get("status") != "running":
            raise RuntimeError("只能對 running workflow 開始 stateful step。")
        completed = {item.get("step_id") for item in state.get("results", [])}
        if step.step_id in completed:
            raise RuntimeError("stateful step 已完成；拒絕重複執行 mutation。")
        if state.get("in_flight_step_id"):
            raise RuntimeError("已有 in-flight stateful step；已 fail closed。")
        state["in_flight_step_id"] = step.step_id
        state["state_certainty"] = "uncertain"
        self._write_active(state)
        return state

    def append_result(self, workflow_id: str, result: ActionResult) -> Dict[str, Any]:
        state = self.load(workflow_id)
        if state.get("status") != "running":
            raise RuntimeError("只能對 running workflow 寫入結果。")
        completed = {item.get("step_id") for item in state.get("results", [])}
        step_id = str(result.evidence.get("workflow_step_id", ""))
        if not step_id or step_id in completed:
            raise RuntimeError("workflow result step_id 缺失或重複。")
        in_flight = state.get("in_flight_step_id")
        if in_flight and in_flight != step_id:
            raise RuntimeError("workflow result 與 in-flight step 不符。")
        result_dict = result.to_dict()
        result_dict["step_id"] = step_id
        state.setdefault("results", []).append(result_dict)
        state["in_flight_step_id"] = None
        if result.status == ActionStatus.UNCERTAIN:
            state["status"] = "uncertain"
            state["state_certainty"] = "uncertain"
        elif result.status == ActionStatus.BLOCKED:
            state["status"] = "blocked"
            state["state_certainty"] = "certain"
        elif result.status == ActionStatus.SKIPPED:
            state["status"] = "skipped"
            state["state_certainty"] = "certain"
        else:
            state["state_certainty"] = "certain"
        self._write_active(state)
        return state

    def mark_interrupted(self, workflow_id: str, *, state_certain: bool) -> Dict[str, Any]:
        state = self.load(workflow_id)
        if state.get("status") != "running":
            raise RuntimeError("只有 running workflow 可標記 interrupted。")
        if state_certain and state.get("in_flight_step_id"):
            raise RuntimeError("仍有 in-flight step，不得標記為確定中斷。")
        state["status"] = "interrupted"
        state["state_certainty"] = "certain" if state_certain else "uncertain"
        self._write_active(state)
        return state

    def complete(self, workflow_id: str) -> Dict[str, Any]:
        state = self.load(workflow_id)
        if state.get("status") != "running":
            raise RuntimeError("只有 running workflow 可完成。")
        state["status"] = "completed"
        state["completed_at"] = int(time.time())
        self._write_active(state)
        source = self._path(self.active_dir, workflow_id)
        target = self._path(self.archive_dir, workflow_id)
        os.makedirs(self.archive_dir, exist_ok=True)
        os.replace(source, target)
        return state


class WorkflowRunner:
    """Run all reads in parallel, then serialize every stateful step."""

    def __init__(
        self,
        journal: WorkflowJournal,
        executor: Callable[[WorkflowStep, str], ActionResult],
        *,
        max_read_workers: int = 4,
    ) -> None:
        self.journal = journal
        self.executor = executor
        self.max_read_workers = max(1, max_read_workers)

    @staticmethod
    def _with_step_evidence(result: ActionResult, step: WorkflowStep) -> ActionResult:
        evidence = dict(result.evidence)
        evidence["workflow_step_id"] = step.step_id
        return ActionResult(
            result.status,
            result.action_id,
            result.planet_id,
            result.reason,
            evidence,
            result.observed_at,
        )

    def _execute_safely(self, step: WorkflowStep, run_id: str) -> ActionResult:
        try:
            result = self.executor(step, run_id)
        except Exception as exc:
            status = ActionStatus.UNCERTAIN if step.mutation else ActionStatus.BLOCKED
            result = ActionResult(status, step.action_id, step.planet_id, f"executor_error: {exc}")
        if result.action_id != step.action_id or result.planet_id != step.planet_id:
            result = ActionResult(
                ActionStatus.UNCERTAIN if step.mutation else ActionStatus.BLOCKED,
                step.action_id,
                step.planet_id,
                "executor_result_identity_mismatch",
                {"returned": result.to_dict()},
            )
        return self._with_step_evidence(result, step)

    def run(self, workflow_id: str, run_id: str) -> Dict[str, Any]:
        state = self.journal.start(workflow_id, run_id)
        plan = WorkflowPlan.from_dict(state["plan"])
        if int(time.time()) > plan.expires_at:
            self.journal.mark_interrupted(workflow_id, state_certain=True)
            raise RuntimeError("WorkflowPlan 已逾時；請建立新 plan。")
        done = {item.get("step_id") for item in state.get("results", [])}
        pending = [step for step in plan.steps if step.step_id not in done]
        reads = [step for step in pending if step.kind == IntentKind.READ]
        stateful = [step for step in pending if step.kind != IntentKind.READ]

        if reads:
            workers = min(self.max_read_workers, len(reads))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(self._execute_safely, step, run_id) for step in reads]
                read_results = [future.result() for future in futures]
            for result in [item for item in read_results if item.status == ActionStatus.APPLIED]:
                state = self.journal.append_result(workflow_id, result)
            failures = [item for item in read_results if item.status != ActionStatus.APPLIED]
            if failures:
                return self.journal.append_result(workflow_id, failures[0])

        for step in stateful:
            with self.journal.mutation_lock():
                self.journal.begin_stateful_step(workflow_id, step)
                result = self._execute_safely(step, run_id)
                state = self.journal.append_result(workflow_id, result)
            if result.status != ActionStatus.APPLIED:
                return state

        return self.journal.complete(workflow_id)


MAX_ERROR_CHARS = 600
MAX_STDOUT_BYTES = 2048


class DecisionValidationError(RuntimeError):
    """The requested semantic intent is invalid before any mutation starts."""


class ControllerExecutionError(RuntimeError):
    """The controller failed and mutation state may require a global stop."""


def bounded_text(value: Any, limit: int = MAX_ERROR_CHARS) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def format_compact_json(value: Any, pretty: bool = False) -> str:
    kwargs = {"ensure_ascii": False}
    if pretty:
        kwargs["indent"] = 2
    else:
        kwargs["separators"] = (",", ":")
    encoded = json.dumps(value, **kwargs)
    if len(encoded.encode("utf-8")) > MAX_STDOUT_BYTES:
        fallback = {
            key: value.get(key)
            for key in (
                "planet_id", "status", "plan_id", "workflow_id", "action_id",
                "global_stop", "evidence_ref",
            )
            if isinstance(value, dict) and value.get(key) is not None
        }
        fallback["reason"] = "compact_output_budget_exceeded"
        encoded = json.dumps(fallback, ensure_ascii=False, separators=(",", ":"))
    return encoded


def select_candidates(
    plan: Mapping[str, Any],
    action_ids: Any = None,
    target_name: Any = None,
    component: Any = None,
    target_level: Any = None,
) -> List[Dict[str, Any]]:
    candidates = [item for item in plan.get("candidates", []) if isinstance(item, dict)]
    if action_ids:
        wanted = set(action_ids)
        return [item for item in candidates if item.get("action_id") in wanted]

    normalized_name = " ".join(str(target_name or "").split()).casefold()
    matches = []
    for candidate in candidates:
        candidate_name = " ".join(str(candidate.get("name") or "").split()).casefold()
        candidate_component = str(candidate.get("component") or candidate.get("section") or "")
        if candidate_name != normalized_name:
            continue
        if component and candidate_component != component:
            continue
        if target_level is not None and candidate.get("target_level") != target_level:
            continue
        matches.append(candidate)
    return matches


def candidate_block_reason(candidate: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    if (
        candidate.get("actionable_now") is False
        or candidate.get("can_apply") is False
        or candidate.get("can_upgrade") is False
    ):
        return {
            "code": "not_actionable",
            "queue": candidate.get("queue"),
            "shortfall": candidate.get("resource_shortfall") or {},
        }
    return None


def compact_results(results: Any) -> List[Dict[str, Any]]:
    compact = []
    for item in results or []:
        if not isinstance(item, dict):
            continue
        compact.append({
            key: item.get(key)
            for key in ("step_id", "action_id", "planet_id", "status", "reason")
            if item.get(key) is not None
        })
    return compact


def rotate_workflow_archives(journal_root: str, max_age_days: int = 7, keep_latest: int = 10) -> int:
    """Purge stale workflow archives beyond retention period and count limits."""
    archive_dir = os.path.join(journal_root, "archive")
    if not os.path.isdir(archive_dir):
        return 0
    now = time.time()
    cutoff = now - (max_age_days * 86400)
    entries = []
    for fname in os.listdir(archive_dir):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(archive_dir, fname)
        try:
            mtime = os.path.getmtime(path)
            entries.append((mtime, path))
        except OSError:
            pass
    entries.sort(key=lambda x: x[0], reverse=True)
    deleted = 0
    for idx, (_, path) in enumerate(entries):
        if idx >= keep_latest or mtime < cutoff:
            try:
                os.remove(path)
                deleted += 1
            except OSError:
                pass
    return deleted

