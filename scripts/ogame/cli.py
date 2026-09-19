"""CLI argument parser and command dispatcher for OGame Controller.

Builds the top-level CLI argument parser and routes subcommands to
their respective domain module handlers.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, Dict, Optional

from scripts.ogame.patrol_contract import (
    PATROL_PHASES,
    ROUTINE_CATEGORIES,
    ROUTINE_STATUSES,
)
from scripts.ogame.policy import DEFAULT_CONSTANTS_PATH, DEFAULT_STRATEGY_PATH
from scripts.ogame import lifecycle as _lifecycle
from scripts.ogame import legacy_commands as _legacy
from scripts.ogame import execution as _execution
from scripts.ogame import probes as _probes
from scripts.ogame import colony_bootstrap as _bootstrap
from scripts.ogame import patrol_start as _patrol_start
from scripts.ogame import expedition_agent as _expedition_agent


def build_parser() -> argparse.ArgumentParser:
    """Build and return the comprehensive CLI argument parser."""
    parser = argparse.ArgumentParser(description="OGame Controller CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # check-wake
    p_init = subparsers.add_parser("init", aliases=["initialize"], help="Initialize configuration files and runtime memory templates")
    p_init.add_argument("--url", "--base-url", dest="url", help="OGame universe base URL (e.g. https://s1-en.ogame.gameforge.com/game/index.php)")
    p_init.add_argument("--universe", "--universe-name", dest="universe", help="Optional universe name for multi-universe lobby accounts")
    p_init.add_argument("--non-interactive", action="store_true", help="Do not prompt interactively for missing server info")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing configuration and memory files")
    p_init.add_argument("--output", choices=["human", "json"], default="human")

    p_check_wake = subparsers.add_parser("check-wake", help="Check next_wake gate without touching Chrome")
    p_check_wake.add_argument("--force", action="store_true", help="Ignore next_wake and allow connection")
    p_check_wake.add_argument("--acquire", action="store_true", help="Atomically acquire the single-run patrol lease")
    p_check_wake.add_argument("--output", choices=["human", "json"], default="human")

    p_patrol_start = subparsers.add_parser("patrol-start", help="Acquire the wake lease and hand off verified patrol sources in one command")
    p_patrol_start.add_argument("--output", choices=["json"], default="json")

    # finish-run
    p_finish_run = subparsers.add_parser("finish-run", help="Release the single-run patrol lease")
    p_finish_run.add_argument("--run-id", required=True, help="Patrol run token returned by check-wake --acquire")
    p_finish_run.add_argument("--commit", action="store_true", help="Also commit changes with standard Cronjob YY-MM-DD HH:mm format")
    p_finish_run.add_argument("--record-tokens", action="store_true", help="Record token consumption to runtime/memory/token-usage.md")
    p_finish_run.add_argument("--abort-reason", help="Release an intentionally aborted run with an exact reason code")
    p_finish_run.add_argument("--message", help="Optional commit message suffix")
    p_finish_run.add_argument("--all", action="store_true", help="Stage all changes (git add -A) instead of only memory state files")
    p_finish_run.add_argument("--output", choices=["human", "json"], default="human")

    # commit-patrol
    p_commit_patrol = subparsers.add_parser("commit-patrol", help="Commit patrol memory and code changes with format Cronjob YY-MM-DD HH:mm")
    p_commit_patrol.add_argument("--run-id", help="Patrol run token to associate with commit")
    p_commit_patrol.add_argument("--all", action="store_true", help="Stage all changes (git add -A) instead of only memory state files")
    p_commit_patrol.add_argument("--message", help="Optional commit message suffix")
    p_commit_patrol.add_argument("--abort-reason", help="Allow committing an explicitly aborted run")
    p_commit_patrol.add_argument("--output", choices=["human", "json"], default="human")

    # patrol-step
    p_patrol_step = subparsers.add_parser("patrol-step", help="Record one ordered patrol completion checkpoint")
    p_patrol_step.add_argument("--run-id", required=True, help="Active patrol run token")
    p_patrol_step.add_argument("--phase", required=True, choices=list(PATROL_PHASES[1:]))
    p_patrol_step.add_argument("--evidence-ref", required=True, help="Compact file/path/result reference proving this checkpoint")
    for category in ROUTINE_CATEGORIES:
        p_patrol_step.add_argument(f"--{category}", choices=list(ROUTINE_STATUSES))
    p_patrol_step.add_argument("--output", choices=["human", "json"], default="human")

    # patrol-audit
    p_patrol_audit = subparsers.add_parser("patrol-audit", help="Validate that every required patrol step is complete")
    p_patrol_audit.add_argument("--run-id", required=True, help="Active patrol run token")
    p_patrol_audit.add_argument("--output", choices=["human", "json"], default="human")

    # record-tokens
    p_rec_tokens = subparsers.add_parser("record-tokens", help="Record token telemetry from conversation SQLite")
    p_rec_tokens.add_argument("--run-id", help="Associate with patrol run ID")
    p_rec_tokens.add_argument("--conv-id", help="Conversation ID (auto-detected if omitted)")
    p_rec_tokens.add_argument("--note", default="", help="Optional note for the log entry")
    p_rec_tokens.add_argument("--output", choices=["human", "json"], default="human")

    # sync & empire
    p_sync = subparsers.add_parser("sync", help="Sync one planet (or the currently active planet)")
    p_sync.add_argument("--planet-id", type=int, help="OGame cp ID; pins all reads to this planet")

    subparsers.add_parser("list-planets", help="List owned planets and their cp IDs")

    p_sync_all = subparsers.add_parser("sync-all", help="Sync every planet from one Empire page; enrich rates via accountInfo (read-only)")
    p_sync_all.add_argument("--source", choices=["auto", "empire", "official", "html"], default="auto", help="Prefer Empire standalone, require Empire, require official JSON, or force historical page reads")

    p_matrix = subparsers.add_parser("matrix", help="View global resources/levels/queues from one Empire page")
    p_matrix.add_argument("--source", choices=["auto", "empire", "official", "html"], default="auto", help="Prefer Empire standalone, require Empire, require official JSON, or force historical page reads")
    p_matrix.add_argument("--output", choices=["human", "json"], default="human")
    p_matrix.add_argument("--run-id", help="Patrol run token to associate with scout report")

    subparsers.add_parser("list-tabs", help="List all open Chrome windows and tabs (read-only diagnostic)")

    p_lobby = subparsers.add_parser("lobby", help="Inspect or enter from Lobby")
    p_lobby.add_argument("--enter", action="store_true", help="Click play button to enter game")

    # inspect
    p_inspect = subparsers.add_parser("inspect", help="Read detailed readiness and displayed costs for technology IDs")
    p_inspect.add_argument("tech_ids", type=int, nargs="+", help="Technology IDs to inspect")
    p_inspect.add_argument("--planet-id", type=int, required=True, help="OGame cp ID")

    # compact patrol pipeline
    p_plan = subparsers.add_parser("plan", help="Read a compact snapshot and issue a short-lived action plan")
    p_plan.add_argument("--planet-id", type=int, required=True, help="Pinned OGame cp ID")
    p_plan.add_argument("--run-id", required=True, help="Patrol run token returned by check-wake --acquire")
    p_plan.add_argument("--diagnose", action="store_true", help="Include selector diagnostics for unparsed technologies (read-only)")
    p_plan.add_argument("--include-lifeforms", action="store_true", help="Also read Lifeform buildings/research and emit safe candidates")
    p_plan.add_argument("--include-cancel", action="store_true", help="Emit one opaque active-building cancellation candidate when exactly identified")
    p_plan.add_argument("--include-production", action="store_true", help="Also read shipyard/defense and emit one-unit safe production candidates")
    p_plan.add_argument("--include-fleet", action="store_true", help="Read bounded live fleet/target evidence and emit typed fleet candidates")
    p_plan.add_argument("--strategy", default=DEFAULT_STRATEGY_PATH, help="Versioned strategy.toml path")
    p_plan.add_argument("--constants", default=DEFAULT_CONSTANTS_PATH, help="Account constants.toml path")
    p_plan.add_argument("--output", choices=["human", "json"], default="human")

    p_bootstrap = subparsers.add_parser("colony-bootstrap", help="Timer-driven build and transport loop for one accepted colony")
    p_bootstrap.add_argument("--planet-id", type=int, required=True, help="Accepted colony cp ID")
    p_bootstrap.add_argument("--run-id", required=True, help="Active patrol run token")
    p_bootstrap.add_argument("--mode", choices=["plan", "run"], default="plan")
    p_bootstrap.add_argument("--source-id", type=int, action="append", default=[], help="Approved source cp ID; repeat in preferred order")
    p_bootstrap.add_argument("--target-metal", type=int, default=20)
    p_bootstrap.add_argument("--target-crystal", type=int, default=20)
    p_bootstrap.add_argument("--target-deuterium", type=int, default=17)
    p_bootstrap.add_argument("--max-robotics", type=int, default=10)
    p_bootstrap.add_argument("--max-nanite", type=int, default=1)
    p_bootstrap.add_argument("--lookahead-steps", type=int, default=6)
    p_bootstrap.add_argument("--max-wait-seconds", type=int, default=900)
    p_bootstrap.add_argument("--max-steps", type=int, default=64)
    p_bootstrap.add_argument("--min-fields", type=int, default=225, help="Fresh field acceptance threshold")
    p_bootstrap.add_argument("--source-reserve-metal", type=int, default=0)
    p_bootstrap.add_argument("--source-reserve-crystal", type=int, default=0)
    p_bootstrap.add_argument("--source-reserve-deuterium", type=int, default=0)
    p_bootstrap.add_argument("--strategy", default=DEFAULT_STRATEGY_PATH)
    p_bootstrap.add_argument("--constants", default=DEFAULT_CONSTANTS_PATH)
    p_bootstrap.add_argument("--confirm", action="store_true", help="Required for --mode run")
    p_bootstrap.add_argument("--output", choices=["human", "json"], default="human")

    p_expedition_agent = subparsers.add_parser(
        "expedition-agent",
        help="Fill live expedition vacancies from a named preset and schedule the next return",
    )
    p_expedition_agent.add_argument("--planet-id", type=int, required=True, help="Pinned origin planet cp ID")
    p_expedition_agent.add_argument("--run-id", required=True, help="Active patrol run token")
    p_expedition_agent.add_argument("--preset", default="agent", help="Case-insensitive exact expedition preset name")
    p_expedition_agent.add_argument("--max-wait-seconds", type=int, default=900, help="Maximum same-session timer window (0-900)")
    p_expedition_agent.add_argument("--max-cycles", type=int, default=8, help="Maximum same-session return cycles (1-8)")
    p_expedition_agent.add_argument("--state-file", default=_expedition_agent.STATE_FILE, help=argparse.SUPPRESS)
    p_expedition_agent.add_argument("--constants", default=DEFAULT_CONSTANTS_PATH, help="Account constants.toml path")
    p_expedition_agent.add_argument("--confirm", action="store_true", help="Confirm live expedition dispatches")
    p_expedition_agent.add_argument("--output", choices=["human", "json"], default="human")

    p_watch = subparsers.add_parser("watch", help="Reserve one planned action and schedule its next affordability check")
    p_watch.add_argument("--plan-id", required=True, help="Current plan token")
    p_watch.add_argument("--action-id", required=True, help="Candidate action ID returned by plan")
    p_watch.add_argument("--run-id", required=True, help="Patrol run token bound to the plan")
    p_watch.add_argument("--output", choices=["human", "json"], default="human")

    p_apply = subparsers.add_parser("apply", help="Re-validate and execute one action from the active plan")
    p_apply.add_argument("--plan-id", required=True, help="Current plan token")
    p_apply.add_argument("--action-id", required=True, help="Candidate action ID returned by plan")
    p_apply.add_argument("--planet-id", type=int, required=True, help="Target planet cp ID (pins execution)")
    p_apply.add_argument("--run-id", required=True, help="Patrol run token bound to the plan")
    p_apply.add_argument("--constants", default=DEFAULT_CONSTANTS_PATH, help="Account constants.toml path")
    p_apply.add_argument("--confirm", action="store_true", help="Required confirmation flag to execute mutation")
    p_apply.add_argument("--output", choices=["human", "json"], default="human")

    p_exec = subparsers.add_parser("execute-decision", help="Resolve an exact semantic target inside Python and emit only a compact result")
    p_exec.add_argument("--run-id", required=True, help="Patrol run token returned by check-wake --acquire")
    p_exec.add_argument("--target", required=True, help="Target decision label (e.g. crystal_mine, computer_tech, large_cargo)")
    p_exec.add_argument("--planet-id", type=int, help="Optional cp ID override; defaults to strategy target planet")
    p_exec.add_argument("--strategy", default=DEFAULT_STRATEGY_PATH, help="Versioned strategy.toml path")
    p_exec.add_argument("--constants", default=DEFAULT_CONSTANTS_PATH, help="Account constants.toml path")
    p_exec.add_argument("--confirm", action="store_true", help="Required confirmation flag to execute mutation")
    p_exec.add_argument("--output", choices=["human", "json"], default="human")

    # typed immutable workflow runner
    p_wf = subparsers.add_parser("workflow", help="Plan, run, or inspect an immutable typed workflow")
    wf_subs = p_wf.add_subparsers(dest="workflow_command", required=True)

    p_wf_plan = wf_subs.add_parser("plan", help="Compile a pinned snapshot and strategy into an immutable workflow plan")
    p_wf_plan.add_argument("--run-id", required=True, help="Patrol run token returned by check-wake --acquire")
    p_wf_plan.add_argument("--planet-id", type=int, help="Optional target planet cp ID; defaults to strategy target planet")
    p_wf_plan.add_argument("--strategy", default=DEFAULT_STRATEGY_PATH, help="Versioned strategy.toml path")
    p_wf_plan.add_argument("--constants", default=DEFAULT_CONSTANTS_PATH, help="Account constants.toml path")
    p_wf_plan.add_argument("--scope", choices=["primary", "all"], default="primary", help="Scope of workflow generation")
    p_wf_plan.add_argument("--include-lifeforms", action="store_true", help="Include lifeform buildings and research")
    p_wf_plan.add_argument("--include-production", action="store_true", help="Include shipyard and defense production")
    p_wf_plan.add_argument("--include-fleet", action="store_true", help="Include routine fleet candidates")
    p_wf_plan.add_argument("--dry-run", action="store_true", help="Print plan preview without writing journal")
    p_wf_plan.add_argument("--output", choices=["human", "json"], default="human")

    p_wf_run = wf_subs.add_parser("run", help="Execute an immutable workflow plan with fail-closed journal checkpoints")
    p_wf_run.add_argument("--workflow-id", required=True, help="Workflow ID returned by workflow plan")
    p_wf_run.add_argument("--run-id", required=True, help="Patrol run token matching the workflow lease")
    p_wf_run.add_argument("--confirm", action="store_true", help="Required acknowledgement to execute state changes")
    p_wf_run.add_argument("--max-steps", type=int, default=1, help="Maximum number of unblocked steps to execute")
    p_wf_run.add_argument("--step-id", help="Optional explicit step ID to execute; must match next pending unblocked step")
    p_wf_run.add_argument("--action-id", help="Optional explicit action ID to execute; must match next pending unblocked action")
    p_wf_run.add_argument("--output", choices=["human", "json"], default="human")

    p_wf_status = wf_subs.add_parser("status", help="Inspect an immutable workflow plan and journal history")
    p_wf_status.add_argument("--workflow-id", required=True, help="Workflow ID to inspect")
    p_wf_status.add_argument("--output", choices=["human", "json"], default="human")

    # diagnostic probes
    p_rates_probe = subparsers.add_parser("rates-probe", help="Read Resource settings once to validate rate selectors")
    p_rates_probe.add_argument("--planet-id", type=int, required=True, help="OGame cp ID")
    p_rates_probe.add_argument("--output", choices=["human", "json"], default="human")

    p_detail_probe = subparsers.add_parser("detail-probe", help="Open one technology detail panel and read it without mutation")
    p_detail_probe.add_argument("component", choices=["supplies", "facilities", "research", "shipyard", "defenses"], help="Technology component")
    p_detail_probe.add_argument("tech_id", type=int, help="Technology ID to open")
    p_detail_probe.add_argument("--planet-id", type=int, required=True, help="OGame cp ID")
    p_detail_probe.add_argument("--output", choices=["human", "json"], default="human")

    p_query_probe = subparsers.add_parser("query-probe", help="Capture sanitized fetch/XHR I/O from three natural detail queries")
    p_query_probe.add_argument("--planet-id", type=int, required=True, help="OGame cp ID")
    p_query_probe.add_argument("--run-id", required=True, help="Active patrol run token")
    p_query_probe.add_argument("--output", choices=["human", "json"], default="human")

    p_export_probe = subparsers.add_parser("export-probe", help="Probe four official authenticated externaldataexport GET endpoints")
    p_export_probe.add_argument("--planet-id", type=int, required=True, help="OGame cp ID")
    p_export_probe.add_argument("--run-id", required=True, help="Active patrol run token")
    p_export_probe.add_argument("--output", choices=["human", "json"], default="human")

    # traditional actions
    p_stor = subparsers.add_parser("storage", help="Check one planet's storage capacity and usage")
    p_stor.add_argument("--planet-id", type=int, help="OGame cp ID")

    p_bld = subparsers.add_parser("build", help="Upgrade building or mine")
    p_bld.add_argument("tech_id", type=int, help="Tech ID of building/mine")
    p_bld.add_argument("--planet-id", type=int, required=True, help="OGame cp ID")
    p_bld.add_argument("--run-id", required=True, help="Active patrol run token")
    p_bld.add_argument("--confirm", action="store_true", help="Required acknowledgement for a state-changing action")
    p_bld.add_argument("--output", choices=["human", "json"], default="human")

    p_res = subparsers.add_parser("research", help="Upgrade research technology")
    p_res.add_argument("tech_id", type=int, help="Tech ID of research")
    p_res.add_argument("--planet-id", type=int, required=True, help="OGame cp ID")
    p_res.add_argument("--run-id", required=True, help="Active patrol run token")
    p_res.add_argument("--confirm", action="store_true", help="Required acknowledgement for a state-changing action")
    p_res.add_argument("--output", choices=["human", "json"], default="human")

    p_lf = subparsers.add_parser("lifeform", help="Read Lifeform buildings/research on one pinned planet")
    p_lf.add_argument("--planet-id", type=int, required=True, help="OGame cp ID")
    p_lf.add_argument("--output", choices=["human", "json"], default="human")

    p_lfb = subparsers.add_parser("lifeform-build", help="Apply one fresh confirmed Lifeform candidate")
    p_lfb.add_argument("component", choices=["lfbuildings", "lfresearch"], help="Lifeform component domain")
    p_lfb.add_argument("tech_id", type=int, help="Lifeform technology ID to upgrade")
    p_lfb.add_argument("--planet-id", type=int, required=True, help="Pinned OGame cp ID")
    p_lfb.add_argument("--run-id", required=True, help="Active patrol run token")
    p_lfb.add_argument("--confirm", action="store_true", help="Required acknowledgement for a state-changing action")
    p_lfb.add_argument("--output", choices=["human", "json"], default="human")

    p_cb = subparsers.add_parser("cancel-building", help="Cancel only the exact active building queue from a fresh confirmed plan")
    p_cb.add_argument("--planet-id", type=int, required=True, help="Pinned OGame cp ID")
    p_cb.add_argument("--run-id", required=True, help="Active patrol run token")
    p_cb.add_argument("--confirm", action="store_true", help="Required acknowledgement for a state-changing action")
    p_cb.add_argument("--output", choices=["human", "json"], default="human")

    p_prod = subparsers.add_parser("produce", help="Produce ships or defense")
    p_prod.add_argument("tech_id", type=int, help="Tech ID of ship/defense")
    p_prod.add_argument("amount", type=int, help="Amount to produce")
    p_prod.add_argument("--planet-id", type=int, required=True, help="OGame cp ID")
    p_prod.add_argument("--run-id", required=True, help="Active patrol run token")
    p_prod.add_argument("--confirm", action="store_true", help="Required acknowledgement for a state-changing action")
    p_prod.add_argument("--output", choices=["human", "json"], default="human")

    p_col = subparsers.add_parser("colonize", help="Send Colony Ship to establish a new colony")
    p_col.add_argument("galaxy", type=int, help="Target galaxy (e.g. 1)")
    p_col.add_argument("system", type=int, help="Target system (e.g. 40)")
    p_col.add_argument("position", type=int, help="Target position (e.g. 7)")
    p_col.add_argument("--planet-id", type=int, required=True, help="Origin planet cp ID")
    p_col.add_argument("--run-id", required=True, help="Active patrol run token")
    p_col.add_argument("--confirm", action="store_true", help="Required acknowledgement for fleet dispatch")
    p_col.add_argument("--output", choices=["human", "json"], default="human")

    p_trans = subparsers.add_parser("transport", help="Transport resources to target coordinates/colony")
    p_trans.add_argument("galaxy", type=int, help="Target galaxy (e.g. 1)")
    p_trans.add_argument("system", type=int, help="Target system (e.g. 40)")
    p_trans.add_argument("position", type=int, help="Target position (e.g. 7)")
    p_trans.add_argument("--planet-id", type=int, required=True, help="Origin planet cp ID")
    p_trans.add_argument("--run-id", required=True, help="Active patrol run token")
    p_trans.add_argument("--metal", type=int, default=0, help="Metal amount to transport")
    p_trans.add_argument("--crystal", type=int, default=0, help="Crystal amount to transport")
    p_trans.add_argument("--deuterium", type=int, default=0, help="Deuterium amount to transport")
    p_trans.add_argument("--ship-tech", default="202", help="Cargo ship tech ID (202 for Small Cargo, 203 for Large Cargo)")
    p_trans.add_argument("--ship-amount", type=int, default=1, help="Cargo ship count to send")
    p_trans.add_argument("--mission", type=int, default=3, choices=[3, 4], help="Mission type (3 for Transport, 4 for Deployment)")
    p_trans.add_argument("--confirm", action="store_true", help="Required acknowledgement for fleet dispatch")
    p_trans.add_argument("--output", choices=["human", "json"], default="human")

    p_autotrans = subparsers.add_parser("auto-transport", help="Automatically calculate and dispatch transport to colony")
    p_autotrans.add_argument("--origin-id", type=int, required=True, help="Origin planet cp ID")
    p_autotrans.add_argument("--target-id", type=int, required=True, help="Target colony cp ID")
    p_autotrans.add_argument("--galaxy", type=int, required=True, help="Target galaxy")
    p_autotrans.add_argument("--system", type=int, required=True, help="Target system")
    p_autotrans.add_argument("--position", type=int, required=True, help="Target position")
    p_autotrans.add_argument("--run-id", required=True, help="Active patrol run token")
    p_autotrans.add_argument("--strategy", default=DEFAULT_STRATEGY_PATH, help="Versioned strategy.toml path")
    p_autotrans.add_argument("--constants", default=DEFAULT_CONSTANTS_PATH, help="Account constants.toml path")
    p_autotrans.add_argument("--dry-run", action="store_true", help="Calculate payload only without dispatching")
    p_autotrans.add_argument("--confirm", action="store_true", help="Required acknowledgement for fleet dispatch")
    p_autotrans.add_argument("--output", choices=["human", "json"], default="human")

    p_scan = subparsers.add_parser("scan", help="Scan galaxy system")
    p_scan.add_argument("galaxy", type=int, default=1, help="Galaxy number")
    p_scan.add_argument("system", type=int, default=1, help="System number")
    p_scan.add_argument("--system-end", type=int, help="End system number for multi-system range scan")
    p_scan.add_argument("--planet-id", type=int, help="OGame cp ID used to view the galaxy page")

    p_spy = subparsers.add_parser("spy", help="Dispatch espionage probe to target coordinates")
    p_spy.add_argument("galaxy", type=int, help="Target galaxy (e.g. 1)")
    p_spy.add_argument("system", type=int, help="Target system (e.g. 2)")
    p_spy.add_argument("position", type=int, help="Target position (e.g. 4)")
    p_spy.add_argument("--probes", type=int, default=1, help="Number of espionage probes to send (default: 1)")
    p_spy.add_argument("--planet-id", type=int, required=True, help="Origin planet cp ID")
    p_spy.add_argument("--run-id", required=True, help="Active patrol run token")
    p_spy.add_argument("--confirm", action="store_true", help="Required acknowledgement for fleet dispatch")
    p_spy.add_argument("--output", choices=["human", "json"], default="human")

    p_raid = subparsers.add_parser("raid", help="Dispatch cargo fleet to attack/harvest inactive target")
    p_raid.add_argument("galaxy", type=int, help="Target galaxy (e.g. 1)")
    p_raid.add_argument("system", type=int, help="Target system (e.g. 2)")
    p_raid.add_argument("position", type=int, help="Target position (e.g. 4)")
    p_raid.add_argument("--ship-tech", type=str, default="202", help="Ship technology ID (202: Small Cargo, 203: Large Cargo)")
    p_raid.add_argument("--ship-amount", type=int, default=1, help="Number of cargo ships to send (default: 1)")
    p_raid.add_argument("--planet-id", type=int, required=True, help="Origin planet cp ID")
    p_raid.add_argument("--run-id", required=True, help="Active patrol run token")
    p_raid.add_argument("--confirm", action="store_true", help="Required acknowledgement for fleet dispatch")
    p_raid.add_argument("--output", choices=["human", "json"], default="human")

    p_exp = subparsers.add_parser("expedition", help="Dispatch expedition fleet to position 16")
    p_exp.add_argument("galaxy", type=int, help="Target galaxy (e.g. 1)")
    p_exp.add_argument("system", type=int, help="Target system (e.g. 2)")
    p_exp.add_argument("--planet-id", type=int, required=True, help="Origin planet cp ID")
    p_exp.add_argument("--cargo-amount", type=int, default=5, help="Number of cargo ships (default: 5)")
    p_exp.add_argument("--combat-amount", type=int, default=1, help="Number of escort combat ships (default: 1)")
    p_exp.add_argument("--ship-tech", type=str, default="203", help="Cargo ship tech ID (default 203 Large Cargo)")
    p_exp.add_argument("--combat-tech", type=str, default="204", help="Combat escort tech ID (default 204 Light Fighter)")
    p_exp.add_argument("--run-id", required=True, help="Active patrol run token")
    p_exp.add_argument("--confirm", action="store_true", help="Required acknowledgement for fleet dispatch")
    p_exp.add_argument("--output", choices=["human", "json"], default="human")

    p_lf_exp = subparsers.add_parser("lifeform-explore", help="Dispatch lifeform discovery mission to target coordinates")
    p_lf_exp.add_argument("galaxy", type=int, help="Target galaxy (e.g. 1)")
    p_lf_exp.add_argument("system", type=int, help="Target system (e.g. 2)")
    p_lf_exp.add_argument("position", type=int, help="Target position (e.g. 4)")
    p_lf_exp.add_argument("--planet-id", type=int, required=True, help="Origin planet cp ID")
    p_lf_exp.add_argument("--run-id", required=True, help="Active patrol run token")
    p_lf_exp.add_argument("--confirm", action="store_true", help="Required acknowledgement for fleet dispatch")
    p_lf_exp.add_argument("--output", choices=["human", "json"], default="human")

    p_af = subparsers.add_parser("auto-fill-slots", help="Auto-fill remaining fleet slots using Lifeform Discoveries")
    p_af.add_argument("--planet-id", type=int, required=True, help="Origin planet cp ID")
    p_af.add_argument("--run-id", required=True, help="Active patrol run token")
    p_af.add_argument("--confirm", action="store_true", help="Required acknowledgement for fleet dispatch")
    p_af.add_argument("--output", choices=["human", "json"], default="human")

    p_findcol = subparsers.add_parser("find-colonies", help="Scan and list available 8th position (or specified position) colony slots in given range")
    p_findcol.add_argument("system", type=int, default=1, help="Start system number")
    p_findcol.add_argument("--system-end", type=int, help="End system number")
    p_findcol.add_argument("--galaxy", type=int, default=1, help="Galaxy number")
    p_findcol.add_argument("--position", type=int, default=8, help="Target position in solar system (default: 8)")
    p_findcol.add_argument("--planet-id", type=int, required=True, help="Pinned OGame cp ID")

    p_srep = subparsers.add_parser("spy-reports", help="Read and parse latest espionage reports")
    p_srep.add_argument("--planet-id", type=int, required=True, help="Pinned OGame cp ID")
    p_srep.add_argument("--msg-id", type=int, help="Specific message ID to fetch and parse")

    p_roi = subparsers.add_parser("roi", help="Calculate ROI & dynamic resource balancing")
    p_roi.add_argument("--planet-id", type=int, help="OGame cp ID")
    p_roi.add_argument("--run-id", required=True, help="Active patrol run token")
    p_roi.add_argument("--output", choices=["human", "json"], default="human")

    p_events = subparsers.add_parser("events", help="Read active fleet movements")
    p_events.add_argument("--planet-id", type=int, help="OGame cp ID")

    p_msgs = subparsers.add_parser("messages", help="Read recent messages/reports")
    p_msgs.add_argument("--planet-id", type=int, help="OGame cp ID")

    p_ships = subparsers.add_parser("ships", help="Read currently stationed ships")
    p_ships.add_argument("--planet-id", type=int, help="OGame cp ID")

    p_dbg = subparsers.add_parser("debug-page", help="Inspect current browser page URL, title, and key elements")
    p_dbg.add_argument("--component", default="shipyard", help="Component to inspect (default: shipyard)")
    p_dbg.add_argument("--planet-id", type=int, default=None, help="OGame cp ID")

    p_pi = subparsers.add_parser("planet-info", help="Read planet overview details (diameter, fields, temp, coords)")
    p_pi.add_argument("--planet-id", type=int, help="OGame cp ID")

    p_abandon = subparsers.add_parser("abandon-dialog", help="Open Abandon Colony dialog in Chrome for manual confirmation")
    p_abandon.add_argument("--planet-id", type=int, required=True, help="OGame cp ID to abandon")

    p_patrol = subparsers.add_parser("patrol", help="Execute complete automated patrol pipeline")
    p_patrol.add_argument("--planet-id", type=int, help="OGame cp ID for a single-planet patrol")
    p_patrol.add_argument("--all-planets", action="store_true", help="Sequentially read every planet before planning actions")
    p_patrol.add_argument("--force", action="store_true", help="Force patrol ignoring next_wake")

    return parser


def dispatch_command(args: argparse.Namespace, controller_globals: Optional[Dict[str, Any]] = None) -> Any:
    """Dispatch parsed arguments to the corresponding command handler."""
    lookup = controller_globals or {}

    def call(name: str, fallback: Callable) -> Any:
        fn = lookup.get(name, fallback)
        return fn(args)

    if args.command in {
        "build", "research", "lifeform-build", "cancel-building", "produce",
        "colonize", "transport", "auto-transport", "spy", "raid",
        "expedition", "lifeform-explore", "auto-fill-slots", "apply",
        "execute-decision", "colony-bootstrap", "expedition-agent",
    } or (args.command == "workflow" and args.workflow_command == "run"):
        req_safety = lookup.get("require_patrol_safety_reviewed", _lifecycle.require_patrol_safety_reviewed)
        req_safety(args.run_id)
    elif args.command in {"query-probe", "export-probe"}:
        req_lease = lookup.get("require_run_lease", _lifecycle.require_run_lease)
        req_lease(args.run_id)

    dispatch_map = {
        "init": ("command_init", _lifecycle.command_init),
        "initialize": ("command_init", _lifecycle.command_init),
        "patrol-start": ("command_patrol_start", _patrol_start.command_patrol_start),
        "check-wake": ("command_check_wake", _lifecycle.command_check_wake),
        "patrol-step": ("command_patrol_step", _lifecycle.command_patrol_step),
        "patrol-audit": ("command_patrol_audit", _lifecycle.command_patrol_audit),
        "finish-run": ("command_finish_run", _lifecycle.command_finish_run),
        "commit-patrol": ("command_commit_patrol", _lifecycle.command_commit_patrol),
        "record-tokens": ("command_record_tokens", _lifecycle.command_record_tokens),
        "sync": ("cmd_sync", _legacy.cmd_sync),
        "list-planets": ("cmd_list_planets", _legacy.cmd_list_planets),
        "sync-all": ("cmd_sync_all", _legacy.cmd_sync_all),
        "matrix": ("cmd_matrix", _legacy.cmd_matrix),
        "list-tabs": ("cmd_list_tabs", _legacy.cmd_list_tabs),
        "lobby": ("cmd_lobby", _legacy.cmd_lobby),
        "inspect": ("cmd_inspect", _legacy.cmd_inspect),
        "plan": ("command_plan", _execution.command_plan),
        "watch": ("command_watch", _execution.command_watch),
        "apply": ("command_apply", _execution.command_apply),
        "execute-decision": ("command_execute_decision", _execution.command_execute_decision),
        "colony-bootstrap": ("command_colony_bootstrap", _bootstrap.command_colony_bootstrap),
        "expedition-agent": ("command_expedition_agent", _expedition_agent.command_expedition_agent),
        "rates-probe": ("command_rates_probe", _probes.command_rates_probe),
        "detail-probe": ("command_detail_probe", _probes.command_detail_probe),
        "query-probe": ("command_query_probe", _probes.command_query_probe),
        "export-probe": ("command_export_probe", _probes.command_export_probe),
        "storage": ("cmd_storage", _legacy.cmd_storage),
        "build": ("cmd_build", _legacy.cmd_build),
        "research": ("cmd_research", _legacy.cmd_research),
        "lifeform": ("cmd_lifeform", _legacy.cmd_lifeform),
        "lifeform-build": ("cmd_lifeform_build", _legacy.cmd_lifeform_build),
        "cancel-building": ("cmd_cancel_building", _legacy.cmd_cancel_building),
        "produce": ("cmd_produce", _legacy.cmd_produce),
        "colonize": ("cmd_colonize", _legacy.cmd_colonize),
        "transport": ("cmd_transport", _legacy.cmd_transport),
        "auto-transport": ("cmd_auto_transport", _legacy.cmd_auto_transport),
        "scan": ("cmd_scan", _legacy.cmd_scan),
        "find-colonies": ("cmd_find_colonies", _legacy.cmd_find_colonies),
        "spy": ("cmd_spy", _legacy.cmd_spy),
        "raid": ("cmd_raid", _legacy.cmd_raid),
        "expedition": ("cmd_expedition", _legacy.cmd_expedition),
        "lifeform-explore": ("cmd_lifeform_explore", _legacy.cmd_lifeform_explore),
        "auto-fill-slots": ("cmd_auto_fill_slots", _legacy.cmd_auto_fill_slots),
        "spy-reports": ("cmd_spy_reports", _legacy.cmd_spy_reports),
        "events": ("cmd_events", _legacy.cmd_events),
        "messages": ("cmd_messages", _legacy.cmd_messages),
        "ships": ("cmd_ships", _legacy.cmd_ships),
        "debug-page": ("cmd_debug_page", _legacy.cmd_debug_page),
        "planet-info": ("cmd_planet_info", _legacy.cmd_planet_info),
        "abandon-dialog": ("cmd_open_abandon_dialog", _legacy.cmd_open_abandon_dialog),
        "roi": ("cmd_roi", _legacy.cmd_roi),
        "patrol": ("cmd_patrol", _legacy.cmd_patrol),
    }

    if args.command == "workflow":
        print_fn = lookup.get("print_workflow_output", _execution.print_workflow_output)
        if args.workflow_command == "plan":
            wf_plan_fn = lookup.get("command_workflow_plan", _execution.command_workflow_plan)
            result = wf_plan_fn(args)
        elif args.workflow_command == "run":
            wf_run_fn = lookup.get("command_workflow_run", _execution.command_workflow_run)
            result = wf_run_fn(args)
        else:
            wf_status_fn = lookup.get("command_workflow_status", _execution.command_workflow_status)
            result = wf_status_fn(args)
        print_fn(result, args.output)
        return result

    if args.command in dispatch_map:
        name, fallback = dispatch_map[args.command]
        result = call(name, fallback)
        if args.command == "colony-bootstrap":
            if args.output == "json":
                print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            else:
                print(f"colony-bootstrap: {result.get('status')} ({result.get('reason') or (result.get('decision') or {}).get('reason', '')})")
        return result

    raise RuntimeError(f"未知的命令：{args.command}")
