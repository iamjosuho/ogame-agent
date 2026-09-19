# OGame controller / ogamed / MCP endpoint map

This document records the read-path comparison used to evolve `scripts/ogame_ctl.py` into a possible OGame MCP backend. It is an implementation map, not authorization to run a third-party bot.

## Reference snapshot

- Upstream: `https://github.com/alaingilbert/ogame`
- Inspected commit: `325667f573cc9fd257ecff10d7f2de77c9e212a5`
- Commit date: `2025-06-26T18:37:13-07:00`
- Important limitation: this snapshot predates the June 2026 PTS `externaldataexport` announcement and contains no implementation of those four actions.

## Read-path mapping

| Controller capability | Current `ogame_ctl.py` path | Closest `ogamed` service method | Underlying OGame request in inspected source | MCP-shaped tool candidate |
|---|---|---|---|---|
| Owned planets | `list-planets` | `GET /bot/planets` | `GET page=ingame&component=overview` and parse planet links | `ogame_list_planets` |
| Current resources | `sync-all`/`matrix`: Empire standalone first; `plan`: pinned header extraction | `GET /bot/planets/:id/resources` | `GET page=fetchResources&cp=<id>` | `ogame_get_resources` |
| Supplies/building levels | `read_technology_list("supplies")` | `GET /bot/planets/:id/resources-buildings` | `GET page=ingame&component=supplies&cp=<id>` | `ogame_get_supplies` |
| Facilities | `read_technology_list("facilities")` | `GET /bot/planets/:id/facilities` | `GET page=ingame&component=facilities&cp=<id>` | `ogame_get_facilities` |
| Research | `read_technology_list("research")` | `GET /bot/get-research` | `GET page=ingame&component=research` | `ogame_get_research` |
| Combined technology quantities | Per-section page reads | `GET /bot/celestials/:id/techs` | `GET page=fetchTechs&cp=<id>` | `ogame_get_technology_quantities` |
| Technology detail/cost | `detail-probe`, `query-probe` | library `TechnologyDetails` | `GET page=ingame&component=technologydetails&ajax=1&action=getDetails&technology=<id>&cp=<id>` | `ogame_get_action_details` |
| Construction queues | `sync-all`/`matrix`: Empire displayed markers; `plan`: pinned page extraction | `GET /bot/planets/:id/constructions` | `GET overview&cp=<id>` and parse construction queues | `ogame_get_queues` |
| Resource settings/rates | `rates-probe`, resource-settings fallback | `GET /bot/planets/:id/resource-settings` plus formula engine | `GET page=ingame&component=resourceSettings&cp=<id>` | `ogame_get_production` |
| Official authenticated export | `export-probe` | Not present in inspected `ogamed` snapshot | `GET page=componentOnly&component=externaldataexport&action=<fixed action>&asJson=1` | `ogame_get_account_export` |

## Official export probe contract

`export-probe` issues exactly four sequential same-origin GET requests from the existing authenticated Chrome game session:

1. `speciesBonuses`
2. `accountInfo`
3. `technologyQuantities`
4. `importExportInfo`

Every request includes `X-Requested-With: XMLHttpRequest`, omits `cp`, and is classified by parsed content rather than HTTP 200 alone. Raw cookies are never read or persisted. Token-like response fields are redacted before the structured result is written to `runtime/memory/api-export-probe.json`.

## Live validation example

Validated on `s1-en` using the existing authenticated Chrome session:

| Action | HTTP | Result | Useful coverage |
|---|---:|---|---|
| `speciesBonuses` | 200 | JSON available | Species levels/XP/bonuses plus static resource, ship, defense, and class data |
| `accountInfo` | 200 | JSON available | Owned planets, account research, resources, real production, buildings/facilities, ships, defenses, species, buffs, and officers |
| `technologyQuantities` | 200 | JSON available | Building, facility, research, ship, defense, and lifeform technology quantities keyed by technology ID |
| `importExportInfo` | 200 | JSON available | Current Import/Export item, price, rarity, and offer state |

All four requests omitted `cp`; the active planet remained `12345678`. Every `newAjaxToken` value was persisted as `[REDACTED]`.

The Empire standalone page is now the primary consolidated overview, with `accountInfo` retained as a production-rate supplement:

- `sync-all --source auto` navigates once to the fixed same-origin `page=standalone&component=empire` URL. It reads all planets' displayed resources, exact capacities, energy, fields, temperature, buildings/facilities, research, ships, defenses, Lifeform quantities, and displayed queue markers. One `accountInfo` GET then adds hourly/base production and account metadata.
- `matrix --source auto` uses that same combined snapshot and no longer opens one pinned `supplies` page per planet. It still restores the previously active planet in a `finally` path.
- `--source empire` and `--source official` are explicit fail-closed diagnostic modes; `--source html` is the historical page-by-page compatibility path. Empire-only reads expose `rates_coverage=not_provided` and use `null`, never zero, for missing rates.
- `plan` and `apply` remain on the existing pinned page flow because a consolidated overview is not sufficient evidence for next-level cost/availability or mutation postconditions.

Live validation on `s1-en` confirmed that the Empire page returned all planets and that both `sync-all --source empire` and `sync-all --source auto` restored the original active planet. Auto mode reported `queue_coverage=empire.standalone` and `rates_coverage=official.accountInfo`.

## Stable controller read contract

`normalize_empire_snapshot` and `normalize_official_account_info` isolate both external schemas behind controller schema version `1`. Their fixed top-level fields include:

- `schema_version`, `source`, `captured_at`, `queue_coverage`, and `rates_coverage`
- `account`: stable player ID, nullable class IDs, officer flags, and account research levels
- `planet_count` and `planets`: stable planet ID, UI label, coordinates, fields, temperature, equipment summary, resources, exact storage, energy, production coverage, buildings, ships, defenses, Lifeform quantities, and typed queue evidence

Player name and `newAjaxToken` are deliberately excluded. Production floats are truncated to conservative integer hourly rates. Malformed or duplicate planet IDs, missing required Empire groups, or mismatched Empire/API planet sets reject the relevant enrichment path; missing rates remain explicit instead of being fabricated.

## Recommended MCP boundary

Keep the controller as the safety and state authority. An MCP adapter should be thin and expose only versioned schemas around controller functions:

- Read tools may return empire snapshots and verified candidate actions.
- The model may rank candidates but may not invent URLs, technology IDs, selectors, or mutation payloads.
- Mutation tools must retain `run_id`, `plan_id`, `action_id`, explicit planet pinning, confirmation, and postcondition checks.
- High-risk upstream capabilities such as Dark Matter use, auction bidding, messaging, teardown, cancellation, or unrestricted fleet dispatch must not be registered as MCP tools.
