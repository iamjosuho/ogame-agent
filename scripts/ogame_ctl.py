#!/usr/bin/env python3
"""Unified OGame Controller CLI (scripts/ogame_ctl.py).

Thin router and backward-compatible entry point for the OGame Agent toolkit.
All heavy logic is factored into domain submodules under ``scripts/ogame/``:
  - browser: low-level Chrome/AppleScript primitives, DOM scripts & safety gates
  - lifecycle: patrol lease gates, contracts, audit, token telemetry & git commit
  - probes: external data export, query trace, and diagnostic probes
  - matrix: Empire snapshot, official accountInfo projection & global matrix
  - execution: formulas, prevalidation, verification, plan/apply & workflow runner
  - colony_bootstrap: deterministic new-colony build order, timer loop & supply line
  - expedition_agent: preset-driven expedition fill, movement balance & return timer
  - patrol_start: single-command wake gate and verified data handoff
  - legacy_commands: compatibility handlers for classic CLI subcommands
  - cli: argument parser definition and dispatch router
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Mapping, Optional

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Submodules
from scripts.ogame import browser as _browser
from scripts.ogame import lifecycle as _lifecycle
from scripts.ogame import probes as _probes
from scripts.ogame import matrix as _matrix
from scripts.ogame import execution as _execution
from scripts.ogame import colony_bootstrap as _bootstrap
from scripts.ogame import patrol_start as _patrol_start
from scripts.ogame import expedition_agent as _expedition_agent
from scripts.ogame import legacy_commands as _legacy
from scripts.ogame import resolver as _resolver
from scripts.ogame import cli as _cli

# Register this top-level module globals for dynamic mock resolution in tests
_resolver.register_controller(globals())
_matrix.register_controller(globals())
_execution.register_controller(globals())
_legacy.register_controller(globals())

# =============================================================================
# Constants & Configuration
# =============================================================================

GAME_BASE_URL = _browser.GAME_BASE_URL
MEMORY_DIR = _lifecycle.MEMORY_DIR
PLAN_FILE = _lifecycle.PLAN_FILE
RATES_FILE = _execution.RATES_FILE
NEXT_WAKE_FILE = _lifecycle.NEXT_WAKE_FILE
RUN_LEASE_FILE = _lifecycle.RUN_LEASE_FILE
RUN_LEASE_GUARD_FILE = _lifecycle.RUN_LEASE_GUARD_FILE
QUERY_TRACE_FILE = _probes.QUERY_TRACE_FILE
EXPORT_PROBE_FILE = _probes.EXPORT_PROBE_FILE
WORKFLOW_DIR = _execution.WORKFLOW_DIR
PLAN_TTL_SECONDS = _execution.PLAN_TTL_SECONDS
RUN_LEASE_TTL_SECONDS = _lifecycle.RUN_LEASE_TTL_SECONDS

DEFAULT_STRATEGY_PATH = _execution.DEFAULT_STRATEGY_PATH
SAFETY_POLICY = _execution.SAFETY_POLICY
RESOURCE_KEYS = _matrix.RESOURCE_KEYS
OFFICIAL_SNAPSHOT_SCHEMA_VERSION = _matrix.OFFICIAL_SNAPSHOT_SCHEMA_VERSION
OFFICIAL_RESOURCE_BUILDING_IDS = _matrix.OFFICIAL_RESOURCE_BUILDING_IDS
EXTERNAL_DATA_EXPORT_ACTIONS = _probes.EXTERNAL_DATA_EXPORT_ACTIONS
TECH_FORMULAS = _execution.TECH_FORMULAS

# =============================================================================
# Types & Exceptions
# =============================================================================

SafetyStopError = _matrix.SafetyStopError
ActionResult = _execution.ActionResult
ActionStatus = _execution.ActionStatus
Intent = _execution.Intent
IntentKind = _execution.IntentKind
WorkflowPlan = _execution.WorkflowPlan
DecisionValidationError = _execution.DecisionValidationError
FleetMission = _execution.FleetMission
StrategyPolicy = _execution.StrategyPolicy

# =============================================================================
# Browser Automation & DOM Reader Functions
# =============================================================================

game_url = _browser.game_url
empire_url = _browser.empire_url
checked_js = _browser.checked_js
run_applescript = _browser.run_applescript
execute_in_game_tab = _browser.execute_in_game_tab
execute_checked_component = _browser.execute_checked_component
execute_checked_component_followup = _browser.execute_checked_component_followup
execute_checked_component_result = _browser.execute_checked_component_result
read_active_planet_context = _browser.read_active_planet_context
read_header_snapshot = _browser.read_header_snapshot
read_technology_list = _browser.read_technology_list
read_fleet_state = _browser.read_fleet_state
read_events_state = _browser.read_events_state
read_galaxy_target_evidence = _browser.read_galaxy_target_evidence
require_confirmed_mutation = _browser.require_confirmed_mutation

HEADER_SNAPSHOT_JS = _browser.HEADER_SNAPSHOT_JS
TECHNOLOGY_LIST_JS = _browser.TECHNOLOGY_LIST_JS
FLEET_STATE_JS = _browser.FLEET_STATE_JS
EVENTS_STATE_JS = _browser.EVENTS_STATE_JS

# =============================================================================
# Lifecycle, Lease & Patrol Functions
# =============================================================================

patrol_contract_file = _lifecycle.patrol_contract_file
patrol_last_run_file = _lifecycle.patrol_last_run_file
atomic_write_json = _lifecycle.atomic_write_json
load_json_file = _lifecycle.load_json_file
write_next_wake = _lifecycle.write_next_wake
load_next_wake = _lifecycle.load_next_wake
acquire_run_lease = _lifecycle.acquire_run_lease
require_run_lease = _lifecycle.require_run_lease
release_run_lease = _lifecycle.release_run_lease

command_check_wake = _lifecycle.command_check_wake
command_finish_run = _lifecycle.command_finish_run
command_commit_patrol = _lifecycle.command_commit_patrol
command_patrol_step = _lifecycle.command_patrol_step
command_patrol_audit = _lifecycle.command_patrol_audit
command_record_tokens = _lifecycle.command_record_tokens
command_init = _lifecycle.command_init

# =============================================================================
# Matrix & Empire Functions
# =============================================================================

calc_storage_capacity = _matrix.calc_storage_capacity
official_integer = _matrix.official_integer
normalize_official_account_info = _matrix.normalize_official_account_info
official_planet_to_sync_state = _matrix.official_planet_to_sync_state
empire_planet_to_sync_state = _matrix.empire_planet_to_sync_state
read_owned_planets = _matrix.read_owned_planets
enrich_official_snapshot_planet_metadata = _matrix.enrich_official_snapshot_planet_metadata
read_official_account_snapshot = _matrix.read_official_account_snapshot
read_empire_snapshot = _matrix.read_empire_snapshot
normalize_empire_snapshot = _matrix.normalize_empire_snapshot
enrich_empire_with_official = _matrix.enrich_empire_with_official

cmd_matrix_empire = _matrix.cmd_matrix_empire
cmd_matrix_official = _matrix.cmd_matrix_official
cmd_matrix = _legacy.cmd_matrix
cmd_sync_all = _legacy.cmd_sync_all

# =============================================================================
# Diagnostic Probes
# =============================================================================

classify_external_data_export_response = _probes.classify_external_data_export_response
external_data_export_fetch_js = _probes.external_data_export_fetch_js
external_data_export_path = _probes.external_data_export_path
external_data_export_probe_js = _probes.external_data_export_probe_js
is_safe_query_replay = _probes.is_safe_query_replay
parse_resource_settings_rates = _probes.parse_resource_settings_rates
response_schema = _probes.response_schema
sanitize_query_trace = _probes.sanitize_query_trace
sanitize_trace_url = _probes.sanitize_trace_url

command_rates_probe = _probes.command_rates_probe
command_detail_probe = _probes.command_detail_probe
command_query_probe = _probes.command_query_probe
command_export_probe = _probes.command_export_probe

# =============================================================================
# Execution, Planning & Workflow Functions
# =============================================================================

calculate_technology_cost = _execution.calculate_technology_cost
estimate_action_duration = _execution.estimate_action_duration
parse_signed_number = _execution.parse_signed_number
normalize_number = _execution.normalize_number
parse_costs = _execution.parse_costs
resource_vector = _execution.resource_vector
subtract_resources = _execution.subtract_resources
can_afford = _execution.can_afford
resource_shortfall = _execution.resource_shortfall
sum_costs = _execution.sum_costs

action_component = _execution.action_component
action_queue = _execution.action_queue
action_from_item = _execution.action_from_item
lifeform_action_from_item = _execution.lifeform_action_from_item
cancel_building_action_from_snapshot = _execution.cancel_building_action_from_snapshot
production_action_from_item = _execution.production_action_from_item
prevalidate_planned_action = _execution.prevalidate_planned_action
prevalidate_fleet_dispatch = _execution.prevalidate_fleet_dispatch
verify_applied_action = _execution.verify_applied_action
apply_action_js = _execution.apply_action_js
galaxy_spy_shortcut_js = _execution.galaxy_spy_shortcut_js
feasible_packages = _execution.feasible_packages

parse_header_rates = _execution.parse_header_rates
cache_rates = _execution.cache_rates
mark_rates_stale = _execution.mark_rates_stale
load_cached_rates = _execution.load_cached_rates
get_rates_for_plan = _execution.get_rates_for_plan
read_fleet_precondition = _execution.read_fleet_precondition
read_fleet_postcondition = _execution.read_fleet_postcondition
create_fleet_confirmed_plan = _execution.create_fleet_confirmed_plan
execute_galaxy_spy_shortcut = _execution.execute_galaxy_spy_shortcut

command_plan = _execution.command_plan
command_watch = _execution.command_watch
command_apply = _execution.command_apply
command_execute_decision = _execution.command_execute_decision
command_colony_bootstrap = _bootstrap.command_colony_bootstrap
command_expedition_agent = _expedition_agent.command_expedition_agent
command_patrol_start = _patrol_start.command_patrol_start
require_patrol_safety_reviewed = _lifecycle.require_patrol_safety_reviewed
command_workflow_plan = _execution.command_workflow_plan
command_workflow_status = _execution.command_workflow_status
command_workflow_run = _execution.command_workflow_run
collect_patrol_fleet_candidates = _execution.collect_patrol_fleet_candidates
require_active_plan = _execution.require_active_plan
apply_planned_action_atom = _execution.apply_planned_action_atom
assess_workflow_candidate = _execution.assess_workflow_candidate
print_workflow_output = _execution.print_workflow_output

# =============================================================================
# Legacy & Operations Command Handlers
# =============================================================================

cmd_sync = _legacy.cmd_sync
cmd_build = _legacy.cmd_build
cmd_research = _legacy.cmd_research
cmd_produce = _legacy.cmd_produce
cmd_colonize = _legacy.cmd_colonize
cmd_cancel_building = _legacy.cmd_cancel_building
cmd_lifeform_build = _legacy.cmd_lifeform_build
cmd_auto_transport = _legacy.cmd_auto_transport
cmd_transport = _legacy.cmd_transport
cmd_scan = _legacy.cmd_scan
cmd_spy_reports = _legacy.cmd_spy_reports
cmd_find_colonies = _legacy.cmd_find_colonies
cmd_storage = _legacy.cmd_storage
cmd_ships = _legacy.cmd_ships
cmd_events = _legacy.cmd_events
cmd_messages = _legacy.cmd_messages
cmd_spy = _legacy.cmd_spy
cmd_raid = _legacy.cmd_raid
cmd_expedition = _legacy.cmd_expedition
cmd_lifeform = _legacy.cmd_lifeform
cmd_lifeform_explore = _legacy.cmd_lifeform_explore
cmd_auto_fill_slots = _legacy.cmd_auto_fill_slots
cmd_planet_info = _legacy.cmd_planet_info
cmd_open_abandon_dialog = _legacy.cmd_open_abandon_dialog
cmd_list_planets = _legacy.cmd_list_planets
cmd_lobby = _legacy.cmd_lobby
cmd_list_tabs = _legacy.cmd_list_tabs
cmd_inspect = _legacy.cmd_inspect
cmd_roi = _legacy.cmd_roi
cmd_patrol = _legacy.cmd_patrol
cmd_sync_all_html = _legacy.cmd_sync_all_html
cmd_matrix_html = _legacy.cmd_matrix_html
cmd_debug_page = _legacy.cmd_debug_page

# CLI parser export
build_parser = _cli.build_parser


def write_next_wake(epoch: int) -> None:
    return _lifecycle.write_next_wake(epoch, next_wake_file=NEXT_WAKE_FILE, memory_dir=MEMORY_DIR)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        _cli.dispatch_command(args, globals())
    except RuntimeError as exc:
        print(f"⛔ 已停止：{exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
