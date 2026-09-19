"""Layered OGame controller implementation.

``scripts/ogame_ctl.py`` remains the only supported CLI entrypoint.  Policy,
typed contracts, pure planning, private browser primitives, public atoms, and
workflow execution live behind that compatibility boundary.
"""

from .farming import evaluate_farming_targets, parse_farm_targets_md
from .models import ActionResult, ActionStatus, Intent, IntentKind, WorkflowPlan, WorkflowStep
from .operations import FleetMission, build_fleet_candidate, build_patrol_fleet_candidates, resolve_expedition_preset
from .patrol_contract import (
    PATROL_PHASES,
    ROUTINE_CATEGORIES,
    advance_patrol_contract,
    audit_patrol_contract,
    new_patrol_contract,
)
from .policy import SAFETY_POLICY, SafetyPolicy, StrategyPolicy, load_strategy_policy
from .tokens import extract_token_stats, find_conversation_db, record_tokens

__all__ = [
    "ActionResult",
    "ActionStatus",
    "Intent",
    "IntentKind",
    "FleetMission",
    "PATROL_PHASES",
    "ROUTINE_CATEGORIES",
    "SAFETY_POLICY",
    "SafetyPolicy",
    "StrategyPolicy",
    "WorkflowPlan",
    "WorkflowStep",
    "build_fleet_candidate",
    "build_patrol_fleet_candidates",
    "resolve_expedition_preset",
    "advance_patrol_contract",
    "audit_patrol_contract",
    "evaluate_farming_targets",
    "extract_token_stats",
    "find_conversation_db",
    "load_strategy_policy",
    "new_patrol_contract",
    "parse_farm_targets_md",
    "record_tokens",
]
