"""Lifecycle, Lease, Patrol Checkpoints, Git Commit, and Token Recording.

Manages the persistent patrol lease across separate CLI processes,
records phase checkpoints, and performs final audit/commit.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import fcntl
import json
import os
import secrets
import subprocess
import sys
import time
from typing import Any, Callable, Dict, Optional

from scripts.ogame.patrol_contract import (
    PATROL_PHASES,
    ROUTINE_CATEGORIES,
    ROUTINE_STATUSES,
    PatrolContractError,
    advance_patrol_contract,
    audit_patrol_contract,
    finalize_patrol_contract,
    new_patrol_contract,
)
from scripts.ogame.resolver import get_dep

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MEMORY_DIR = os.path.join(PROJECT_ROOT, "runtime", "memory")
PLAN_FILE = os.path.join(MEMORY_DIR, "patrol-plan.json")
NEXT_WAKE_FILE = os.path.join(MEMORY_DIR, "next_wake.txt")
RUN_LEASE_FILE = os.path.join(MEMORY_DIR, "patrol-run.json")
RUN_LEASE_GUARD_FILE = os.path.join(MEMORY_DIR, ".patrol-run.lock")
RUN_LEASE_TTL_SECONDS = 30 * 60


def _memory_dir(override: Optional[str] = None) -> str:
    return override or get_dep("MEMORY_DIR", MEMORY_DIR)


def _lease_file(override: Optional[str] = None) -> str:
    return override or get_dep("RUN_LEASE_FILE", RUN_LEASE_FILE)


def _guard_file(override: Optional[str] = None) -> str:
    return override or get_dep("RUN_LEASE_GUARD_FILE", RUN_LEASE_GUARD_FILE)


def _wake_file(override: Optional[str] = None) -> str:
    return override or get_dep("NEXT_WAKE_FILE", NEXT_WAKE_FILE)


def patrol_contract_file(lease_file: Optional[str] = None) -> str:
    target_lease = _lease_file(lease_file)
    return os.path.join(os.path.dirname(target_lease), "patrol-contract.json")


def patrol_last_run_file(lease_file: Optional[str] = None) -> str:
    target_lease = _lease_file(lease_file)
    return os.path.join(os.path.dirname(target_lease), "patrol-last-run.json")


def atomic_write_json(path: str, value: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f"{path}.tmp.{secrets.token_hex(4)}"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def load_json_file(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write_next_wake(epoch: int, next_wake_file: Optional[str] = None, memory_dir: Optional[str] = None) -> None:
    target_file = _wake_file(next_wake_file)
    target_dir = _memory_dir(memory_dir) or os.path.dirname(target_file)
    os.makedirs(target_dir, exist_ok=True)
    temp_path = f"{target_file}.tmp.{secrets.token_hex(4)}"
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(str(int(epoch)))
    os.replace(temp_path, target_file)


def load_next_wake(next_wake_file: Optional[str] = None) -> Optional[int]:
    target_file = _wake_file(next_wake_file)
    if not os.path.exists(target_file):
        return None
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return int(content) if content else None
    except Exception:
        return None


def acquire_run_lease(
    ttl_seconds: int = RUN_LEASE_TTL_SECONDS,
    *,
    memory_dir: Optional[str] = None,
    lease_file: Optional[str] = None,
    guard_file: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Acquire one persistent patrol lease across the Agent's separate CLI processes."""
    target_dir = _memory_dir(memory_dir)
    target_lease = _lease_file(lease_file)
    target_guard = _guard_file(guard_file)
    os.makedirs(target_dir, exist_ok=True)
    now = int(time.time())
    with open(target_guard, "a+", encoding="utf-8") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
        current = load_json_file(target_lease)
        if current and int(current.get("expires_at", 0)) > now:
            return None
        run_token = secrets.token_urlsafe(16)
        while run_token.startswith("-"):
            run_token = secrets.token_urlsafe(16)
        lease = {
            "run_id": run_token,
            "started_at": now,
            "updated_at": now,
            "expires_at": now + ttl_seconds,
            "pid": os.getpid(),
        }
        atomic_write_json(target_lease, lease)
        try:
            atomic_write_json(patrol_contract_file(target_lease), new_patrol_contract(run_token, now))
        except Exception:
            # The gate must not leave an owned lease when contract creation
            # fails before check-wake can return its run_id to the caller.
            stored = load_json_file(target_lease)
            if stored and stored.get("run_id") == run_token:
                os.unlink(target_lease)
            raise
        return lease


def require_run_lease(
    run_id: str,
    ttl_seconds: int = RUN_LEASE_TTL_SECONDS,
    *,
    memory_dir: Optional[str] = None,
    lease_file: Optional[str] = None,
    guard_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate and renew the named lease; fail closed if another run owns it."""
    if not run_id:
        raise RuntimeError("缺少 --run-id；禁止執行未受單實例租約保護的巡邏。")
    target_dir = _memory_dir(memory_dir)
    target_lease = _lease_file(lease_file)
    target_guard = _guard_file(guard_file)
    os.makedirs(target_dir, exist_ok=True)
    now = int(time.time())
    with open(target_guard, "a+", encoding="utf-8") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
        lease = load_json_file(target_lease)
        if not lease or lease.get("run_id") != run_id:
            raise RuntimeError("run_id 不屬於目前巡邏租約；可能有另一輪排程正在執行。")
        if int(lease.get("expires_at", 0)) <= now:
            raise RuntimeError("run_id 租約已逾時；停止本輪並重新從 check-wake --acquire 開始。")
        lease["updated_at"] = now
        lease["expires_at"] = now + ttl_seconds
        lease["pid"] = os.getpid()
        atomic_write_json(target_lease, lease)
    return lease


def require_patrol_safety_reviewed(
    run_id: str,
    *,
    memory_dir: Optional[str] = None,
    lease_file: Optional[str] = None,
    guard_file: Optional[str] = None,
) -> None:
    """Block patrol game mutations until ordered safety_reviewed is recorded.

    HANDOFF FOR THE MOVEMENT DOM AGENT: This gates checkpoint order, not a
    machine-verified resolution of hostile/unknown events. If you add a typed
    safety verdict, persist it with safety_reviewed and check it here before
    routine mutations; keep a separate, tightly scoped Fleetsave path for a
    credible hostile event. Never treat a bare evidence_ref as zero threat.
    """
    require_run_lease(run_id, memory_dir=memory_dir, lease_file=lease_file, guard_file=guard_file)
    contract = load_json_file(patrol_contract_file(_lease_file(lease_file)))
    if not isinstance(contract, dict) or contract.get("run_id") != run_id or "safety_reviewed" not in (contract.get("completed_phases") or []):
        raise RuntimeError("safety_reviewed 尚未完成；禁止遊戲 mutation。")


def release_run_lease(
    run_id: str,
    *,
    memory_dir: Optional[str] = None,
    lease_file: Optional[str] = None,
    guard_file: Optional[str] = None,
) -> bool:
    """Release only the lease owned by run_id."""
    if not run_id:
        raise RuntimeError("finish-run 需要 --run-id。")
    target_dir = _memory_dir(memory_dir)
    target_lease = _lease_file(lease_file)
    target_guard = _guard_file(guard_file)
    os.makedirs(target_dir, exist_ok=True)
    with open(target_guard, "a+", encoding="utf-8") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
        lease = load_json_file(target_lease)
        if not lease:
            return False
        if lease.get("run_id") != run_id:
            raise RuntimeError("拒絕釋放其他巡邏所持有的租約。")
        if os.path.exists(target_lease):
            os.unlink(target_lease)
        return True


def print_command_output(args: argparse.Namespace, output: Dict[str, Any], human: str) -> None:
    if getattr(args, "silent", False):
        return
    if getattr(args, "output", "human") == "json":
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(human)


def command_check_wake(
    args: argparse.Namespace,
    *,
    next_wake_file: Optional[str] = None,
    memory_dir: Optional[str] = None,
    lease_file: Optional[str] = None,
    guard_file: Optional[str] = None,
) -> Dict[str, Any]:
    wake_time = load_next_wake(next_wake_file)
    now = int(time.time())
    if wake_time and now < wake_time and not getattr(args, "force", False):
        remaining = wake_time - now
        wake_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(wake_time))
        too_early = {
            "due": False,
            "reason": "too_early",
            "next_wake": wake_time,
            "remaining_seconds": remaining,
        }
        human_msg = f"⏳ 尚未到達下次喚醒時間 (尚餘 {remaining} 秒，排定喚醒: {wake_str})。靜默跳過，停止對 OGame 連線。若需手動覆寫請帶 --force。"
        print_command_output(args, too_early, human_msg)
        sys.exit(0)
    output: Dict[str, Any] = {"due": True}
    if getattr(args, "acquire", False):
        target_dir = _memory_dir(memory_dir)
        target_lease = _lease_file(lease_file)
        target_guard = _guard_file(guard_file)
        lease = acquire_run_lease(memory_dir=target_dir, lease_file=target_lease, guard_file=target_guard)
        if lease is None:
            current = load_json_file(target_lease) or {}
            overlap = {
                "due": True,
                "acquired": False,
                "reason": "overlap",
                "active_since": current.get("started_at"),
                "lease_expires_at": current.get("expires_at"),
            }
            print_command_output(args, overlap, "wake gate: overlap; skipped")
            sys.exit(0)
        output.update({"acquired": True, "run_id": lease["run_id"], "lease_expires_at": lease["expires_at"]})
    label = f"wake gate: acquired run {output['run_id']}" if output.get("acquired") else "wake gate: due"
    print_command_output(args, output, label)
    return output


def _routine_from_args(args: argparse.Namespace) -> Optional[Dict[str, str]]:
    values = {
        category: getattr(args, category, None)
        for category in ROUTINE_CATEGORIES
    }
    present = {key: value for key, value in values.items() if value is not None}
    if not present:
        return None
    if len(present) != len(ROUTINE_CATEGORIES):
        missing = ",".join(key for key, value in values.items() if value is None)
        raise RuntimeError(f"routine 狀態必須四項一起提交；缺少：{missing}")
    return {key: str(value) for key, value in values.items()}


def command_patrol_step(
    args: argparse.Namespace,
    *,
    memory_dir: Optional[str] = None,
    lease_file: Optional[str] = None,
    guard_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Advance exactly one ordered patrol checkpoint under the active lease."""
    require_run_lease(args.run_id, memory_dir=memory_dir, lease_file=lease_file, guard_file=guard_file)
    path = patrol_contract_file(lease_file)
    state = load_json_file(path)
    if not state:
        raise RuntimeError("本輪 patrol contract 不存在；必須重新從 check-wake --acquire 開始。")
    try:
        updated = advance_patrol_contract(
            state,
            args.phase,
            args.evidence_ref,
            routine=_routine_from_args(args),
            updated_at=int(time.time()),
        )
    except PatrolContractError as exc:
        raise RuntimeError(str(exc)) from exc
    atomic_write_json(path, updated)
    output = {
        "success": True,
        "run_id": args.run_id,
        "phase": args.phase,
        "next_phase": PATROL_PHASES[len(updated["completed_phases"])]
        if len(updated["completed_phases"]) < len(PATROL_PHASES)
        else None,
        "routine": updated.get("routine", {}),
    }
    print_command_output(args, output, f"patrol checkpoint: {args.phase}")
    return output


def command_patrol_audit(
    args: argparse.Namespace,
    *,
    memory_dir: Optional[str] = None,
    lease_file: Optional[str] = None,
    guard_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Report whether this run is allowed to claim normal completion."""
    require_run_lease(args.run_id, memory_dir=memory_dir, lease_file=lease_file, guard_file=guard_file)
    output = audit_patrol_contract(load_json_file(patrol_contract_file(lease_file)), args.run_id)
    print_command_output(
        args,
        output,
        "patrol audit: complete" if output["complete"] else
        f"patrol audit: incomplete ({','.join(output['missing_phases'])})",
    )
    return output


def command_finish_run(
    args: argparse.Namespace,
    *,
    memory_dir: Optional[str] = None,
    lease_file: Optional[str] = None,
    guard_file: Optional[str] = None,
    commit_fn: Optional[Callable[[argparse.Namespace], Dict[str, Any]]] = None,
    release_fn: Optional[Callable[[str], bool]] = None,
) -> Dict[str, Any]:
    target_dir = _memory_dir(memory_dir)
    target_lease = _lease_file(lease_file)
    target_guard = _guard_file(guard_file)
    contract_path = patrol_contract_file(target_lease)
    contract_raw = load_json_file(contract_path)
    contract = contract_raw if isinstance(contract_raw, dict) and contract_raw.get("run_id") == args.run_id else None
    audit = audit_patrol_contract(contract, args.run_id) if contract else None
    abort_reason = str(getattr(args, "abort_reason", "") or "").strip()
    contract_complete = bool(audit and audit.get("complete"))
    if contract:
        if abort_reason:
            final_status = "aborted"
            final_reason = abort_reason
        elif contract_complete:
            final_status = "completed"
            final_reason = ""
        else:
            final_status = "incomplete"
            final_reason = ",".join(audit.get("reasons") or ["patrol_contract_incomplete"])
        finalized_contract = finalize_patrol_contract(
            contract,
            final_status,
            int(time.time()),
            reason=final_reason,
        )
        atomic_write_json(contract_path, finalized_contract)
        atomic_write_json(patrol_last_run_file(target_lease), finalized_contract)
    commit_res = None
    token_res = None
    try:
        if getattr(args, "record_tokens", False) or getattr(args, "commit", False):
            try:
                try:
                    from scripts.ogame.tokens import record_tokens
                except ImportError:
                    from ogame.tokens import record_tokens
                token_kwargs: Dict[str, Any] = {
                    "conv_id": getattr(args, "conv_id", None),
                    "run_id": args.run_id,
                }
                if target_dir:
                    token_kwargs["memory_dir"] = target_dir
                token_res = record_tokens(**token_kwargs)
            except Exception as exc:
                token_res = {"recorded": False, "reason": "exception", "error": str(exc)}
        if getattr(args, "commit", False):
            if audit is not None and not contract_complete and not abort_reason:
                commit_res = {
                    "committed": False,
                    "reason": "patrol_contract_incomplete",
                    "audit": audit,
                }
            else:
                commit_args = args
                if audit is not None or abort_reason:
                    commit_args = argparse.Namespace(**vars(args))
                    commit_args.contract_verified = contract_complete
                    commit_args.allow_incomplete = bool(abort_reason)
                actual_commit = commit_fn or get_dep("command_commit_patrol", command_commit_patrol)
                commit_res = actual_commit(commit_args)
    except Exception as exc:
        commit_res = {"committed": False, "reason": "commit_exception", "error": str(exc)}
    finally:
        actual_release = release_fn or get_dep("release_run_lease", release_run_lease)
        if release_fn is not None:
            released = release_fn(args.run_id)
        elif memory_dir is not None or lease_file is not None or guard_file is not None:
            released = actual_release(args.run_id, memory_dir=target_dir, lease_file=target_lease, guard_file=target_guard)
        else:
            released = actual_release(args.run_id)

    output: Dict[str, Any] = {"released": released, "run_id": args.run_id}
    if audit is not None:
        output["patrol_complete"] = contract_complete
        output["patrol_audit"] = audit
    if abort_reason:
        output["aborted"] = True
        output["abort_reason"] = abort_reason
    if token_res is not None:
        output["tokens"] = token_res
        if token_res.get("health_warning") and getattr(args, "output", "human") != "json":
            print(token_res["health_warning"])
    if commit_res is not None:
        output["commit"] = commit_res
    print_command_output(args, output, f"run {args.run_id}: {'released' if released else 'already absent'}")
    return output


def command_record_tokens(args: argparse.Namespace) -> Dict[str, Any]:
    try:
        from scripts.ogame.tokens import record_tokens
    except ImportError:
        from ogame.tokens import record_tokens
    token_kwargs: Dict[str, Any] = {
        "conv_id": getattr(args, "conv_id", None),
        "run_id": getattr(args, "run_id", None),
        "note": getattr(args, "note", ""),
    }
    if getattr(args, "memory_dir", None):
        token_kwargs["memory_dir"] = args.memory_dir
    res = record_tokens(**token_kwargs)
    if getattr(args, "output", "human") == "json":
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        if res.get("recorded"):
            d = res["delta"]
            c = res["cumulative"]
            print(f"📊 Token 記錄成功 [{res['run_id']}]: 本輪 Prompt={d['prompt']:,} | Cache={d['cached']:,} | Output={d['candidates']:,} | 本輪 Total={d['total']:,} (累計={c['total']:,})")
            if res.get("health_warning"):
                print(res["health_warning"])
        else:
            print(f"⚠️ Token 記錄未執行: {res.get('reason')}")
    return res


def command_commit_patrol(args: argparse.Namespace, *, lease_file: Optional[str] = None) -> Dict[str, Any]:
    """Stage patrol memory state files and commit with standard format: Cronjob YY-MM-DD HH:mm."""
    run_id = getattr(args, "run_id", None)
    contract = load_json_file(patrol_contract_file(lease_file)) if run_id else None
    if contract and contract.get("run_id") == str(run_id) and not getattr(args, "allow_incomplete", False):
        require_run_lease(str(run_id), lease_file=lease_file)
        audit = audit_patrol_contract(contract, str(run_id))
        if not audit["complete"] and not getattr(args, "contract_verified", False):
            output = {
                "committed": False,
                "reason": "patrol_contract_incomplete",
                "audit": audit,
            }
            print_command_output(args, output, "git commit blocked: patrol contract incomplete")
            return output

    # 1. 強制 CST (UTC+8) 時區
    cst_tz = timezone(timedelta(hours=8))
    now_str = datetime.now(cst_tz).strftime("%y-%m-%d %H:%M")

    # 2. 組合 Commit Message
    run_marker = f" [{run_id}]" if run_id else ""
    msg_suffix = f" {args.message.strip()}" if getattr(args, "message", None) else ""
    commit_msg = f"Cronjob {now_str}{run_marker}{msg_suffix}"

    repo_root = PROJECT_ROOT

    try:
        # 3. 定向暫存：支援新建、修改與刪除 (利用 --ignore-missing 確保刪除也能被 stage)
        if getattr(args, "all", False):
            subprocess.run(["git", "add", "-A"], cwd=repo_root, check=False)
        else:
            target_files = [
                "runtime/memory/GameState.md",
                "runtime/memory/TODO.md",
                "runtime/memory/patrol-log.md",
                "runtime/memory/farm_targets.md",
                "runtime/memory/errors.md",
                "runtime/memory/token-usage.md",
            ]
            contract_target = "runtime/memory/patrol-contract.json"
            if os.path.exists(os.path.join(repo_root, contract_target)):
                target_files.append(contract_target)
            last_run_target = "runtime/memory/patrol-last-run.json"
            if os.path.exists(os.path.join(repo_root, last_run_target)):
                target_files.append(last_run_target)
            existing_targets = [f for f in target_files if os.path.exists(os.path.join(repo_root, f))]
            if existing_targets:
                subprocess.run(["git", "add", "--"] + existing_targets, cwd=repo_root, check=False)
            deleted_targets = [f for f in target_files if not os.path.exists(os.path.join(repo_root, f))]
            if deleted_targets:
                subprocess.run(["git", "add", "-u", "--"] + deleted_targets, cwd=repo_root, check=False)

        # 4. 檢查是否有 staged changes
        diff_check = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo_root)
        if diff_check.returncode == 0:
            output = {"committed": False, "reason": "nothing_to_commit", "commit_msg": commit_msg}
            print_command_output(args, output, "git commit: nothing to commit, working tree clean")
            return output

        # 5. 執行 commit
        res = subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_root, capture_output=True, text=True)
        success = (res.returncode == 0)

        # 6. 防污染：若 commit 失敗，自動 git reset 清空 staging 狀態
        if not success:
            subprocess.run(["git", "reset"], cwd=repo_root, capture_output=True)

        output = {
            "committed": success,
            "commit_msg": commit_msg,
            "stdout": res.stdout.strip(),
            "stderr": res.stderr.strip() if not success else ""
        }
        print_command_output(args, output, f"git committed: {commit_msg}" if success else f"git commit failed: {res.stderr.strip()}")
        return output
    except Exception as exc:
        err_output = {
            "committed": False,
            "reason": "git_exception",
            "commit_msg": commit_msg,
            "error": str(exc)
        }
        print_command_output(args, err_output, f"git commit exception: {exc}")
        return err_output
