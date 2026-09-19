# ogame-agent

[English](README.md) | [繁體中文](README.zh-TW.md)

[![Tests](https://github.com/iamjosuho/ogame-agent/actions/workflows/test.yml/badge.svg)](https://github.com/iamjosuho/ogame-agent/actions/workflows/test.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python: >=3.11](https://img.shields.io/badge/python->=3.11-brightgreen.svg)](pyproject.toml)
[![Platform: macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](#platform-limitations)

An experimental AI agent project that autonomously and safely manages an [OGame](https://gameforge.com/en-US/play/ogame) account within an active session using LLM reasoning and structured guardrails.

The agent's "code" comprises curated domain knowledge files, operational Standard Operating Procedures (SOPs), memory state files, and strict non-negotiable safety guardrails. Rather than acting as a headless, brittle bot, it operates like a dedicated personal steward—defensive, measured, and pacing actions at human cadences.

---

## Architecture

The system operates on an automated patrol cycle, driven by an external scheduler (e.g., Antigravity Scheduled Tasks or Cron), coordinating through typed Python execution primitives and strict safety guardrails.

```
+--------------------------------------------------------------------------+
|                       Antigravity Scheduled Task                         |
|             (Hourly Cron / Event-driven In-Session Agent Wakeup)         |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                  Phase 0: Lifecycle & Lease Gatekeeper                   |
|  - check-wake --acquire (Single-instance run lease & cooldown gate)      |
|  - Load persistent memory (GameState.md, TODO.md, farm_targets.md)       |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                      Phase 1: Read-Only Scout                            |
|  - matrix / sync-all (Empire overview: resources, queues, production)    |
|  - movements & galaxy scan (Inbound threats, fleet events, targets)      |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|             Phase 2: Strategy Review & Threat Assessment                 |
|  - Safety Review (Hostile movement check -> fail-closed if attacked)     |
|  - Empire ROI & Logistics balancing (Energy Squeeze >= -20, Bottlenecks) |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                Phase 3: Typed Planning & Mutation Execution              |
|  - Pure planning: candidate generation (mines, tech, ships, logistics)   |
|  - Safety guards: reserve >= 1 Fleet Slot, cost <= 90% storage capacity  |
|  - Serial execution: Planet Pin -> Prevalidation -> Dispatch -> Postcond |
|  - Fail-closed rollback on uncertainty or unexpected state changes       |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                  Phase 4: Persistence & Lease Release                    |
|  - Update state memory & append patrol log                               |
|  - Record token consumption telemetry                                    |
|  - Release run lease (finish-run) & schedule next_wake timer             |
+--------------------------------------------------------------------------+
                                     |
                 +-------------------+-------------------+
                 |                                       |
                 v                                       v
+---------------------------------+     +----------------------------------+
|      Local Browser Bridge       |     |        Safety Guardrails         |
|  - AppleScript / Apple Events   |     |  - Zero real-money purchases     |
|  - Controls active Chrome tab   |     |  - No attacks on active players  |
|  - Zero stored credentials      |     |  - Inactive (i)/(I) farming only |
|  - Human-paced delays (5-10s)   |     |  - Emergency halt on CAPTCHAs    |
+---------------------------------+     +----------------------------------+
```

### Core Philosophy

1. **Safety over Efficiency**: Better to miss an upgrade cycle than perform an action that exposes automation patterns or risks fleet loss.
2. **Fail-Closed**: If unexpected page structures, modal dialogs, or anti-bot checks appear, immediately halt and alert the user.
3. **⚡ Energy Squeeze**: Power plants operate in tight coordination with mine upgrades, allowing energy deficits down to $\ge -20\text{ ⚡}$ to maximize economic throughput.
4. **Single Source of Truth (SSOT)**: Ship cargo capacities and account-specific bonuses are explicitly declared in `scripts/ogame/config/constants.toml`. Capacities are never guessed or inferred with fallback defaults.

---

## Project Structure

```
.
├── AGENTS.md                  # Global agent rules, core philosophy, and hard guardrails
├── CHECKLIST.md               # Quick verification and patrol checklists
├── LICENSE                    # GNU General Public License v3 (GPL-3.0)
├── pyproject.toml             # Python packaging configuration and metadata
├── README.md                  # English project documentation
├── README.zh-TW.md            # Traditional Chinese project documentation
│
├── .agent/skills/             # Agent operational playbooks and skill definitions
│   ├── ogame-patrol/          # Automated patrol loop and coordinator guidelines
│   ├── ogame-expedition-agent/# Expedition scheduling and dispatch playbook
│   ├── ogame-agent-dev/       # Codebase enhancement and token optimization rules
│   └── script-evolution/      # CLI and automation script evolution guidelines
│
├── knowledge/                 # OGame meta knowledge and reference guides
│   ├── 01-economy.md          # Mine upgrade progression, energy, and ROI formulas
│   ├── 02-lifeforms.md        # Lifeform buildings, research, and selection
│   ├── 03-expeditions.md      # Expedition mechanics, fleet compositions, and yields
│   ├── 04-discoveries.md      # Lifeform discovery missions and artifact rules
│   ├── 05-new-player-path.md  # 14-day early-game milestone roadmap
│   ├── 06-colony-bootstrap.md # Rapid colony bootstrapping guidelines
│   └── 06-inactive-farming.md # Safe inactive farm harvesting strategies
│
├── runtime/
│   ├── memory/                # Long-term memory state files (*.example.md provided)
│   │   ├── GameState.example.md   # Snapshot of empire assets, mines, and fleets
│   │   ├── TODO.example.md        # Strategic objectives and action backlog
│   │   ├── farm_targets.example.md# Inactive (i)/(I) harvest target list
│   │   ├── patrol-log.example.md  # Historical patrol execution records
│   │   └── errors.example.md      # Execution error incident register
│   └── screenshots/           # Diagnostic screenshots captured during patrols
│
├── scripts/
│   ├── ogame_ctl.py           # Unified CLI compatibility entry point
│   └── ogame/                 # Modular Python controller engine
│       ├── atoms.py           # Atomic mutation primitives (pin, validate, mutate, verify)
│       ├── browser.py         # Private AppleScript / Chrome event bridge
│       ├── cli.py             # CLI parser and subcommand dispatcher
│       ├── colony_bootstrap.py# Autonomous colony bootstrap planner
│       ├── empire.py          # Standalone Empire page reader and parser
│       ├── execution.py       # Action dispatcher and execution handlers
│       ├── expedition_agent.py# Expedition slot dispatcher and timer scheduler
│       ├── farming.py         # Espionage report parser and raid planner
│       ├── lifecycle.py       # Patrol run lease, wake gate, and commit wrappers
│       ├── matrix.py          # Unified empire overview renderer
│       ├── models.py          # Immutable domain models and typed contracts
│       ├── operations.py      # Candidate builder and operation validators
│       ├── patrol_contract.py # Ordered patrol lifecycle checkpoint contract
│       ├── patrol_start.py    # Compact patrol handoff and source collector
│       ├── planning.py        # Pure planning engine (policy + constraints)
│       ├── policy.py          # Frozen safety policy constants and thresholds
│       ├── probes.py          # Diagnostic probe handlers
│       ├── resolver.py        # Technology and ship ID lookup tables
│       ├── tokens.py          # Token consumption telemetry tracker
│       ├── workflow.py        # Typed immutable workflow runner with journal
│       └── config/
│           ├── constants.toml     # Account-specific cargo capacities and constants
│           ├── server.example.toml# Server URL configuration template
│           └── strategy.toml      # Tunable strategy profiles and thresholds
│
├── tests/                     # Unit test suite
│   └── fixtures/              # Mock API and HTML probes for offline verification
└── docs/                      # Technical design specifications and API maps
```

---

## Prerequisites

- **Operating System**: macOS (Required for AppleScript / Apple Events browser interaction).
- **Python**: Python `>= 3.11` (Utilizes standard library `tomllib`). No external third-party dependencies required.
- **Web Browser**: Google Chrome. You must be logged into your OGame universe account in an active tab.
- **Agent Environment**: [Google Antigravity](https://github.com/google-deepmind) (or an equivalent LLM agent environment capable of running bash commands and scheduling tasks).

---

## Installation & Configuration

### 1. Clone the Repository

```bash
git clone https://github.com/iamjosuho/ogame-agent.git
cd ogame-agent
```

### 2. Configure Server URL

Copy the template configuration to `server.toml`:

```bash
cp scripts/ogame/config/server.example.toml scripts/ogame/config/server.toml
```

Edit `scripts/ogame/config/server.toml` to specify your universe URL:

```toml
base_url = "https://s1-en.ogame.gameforge.com/game/index.php"
# Optional: if your lobby account has multiple universes, specify the universe name
# universe_name = "Earth"
```

> [!NOTE]
> `server.toml` is excluded by `.gitignore` to prevent leaking server details or account URLs.

### 3. Configure Cargo Capacities (Single Source of Truth)

In OGame, ship cargo capacity is modified dynamically by Hyperspace Technology, Collector class (+25%), and Lifeform research. Open `scripts/ogame/config/constants.toml` and update the values with your account's exact, live capacities:

```toml
schema_version = 1

[cargo_capacities]
"202" = 5000   # Small Cargo capacity
"203" = 25000  # Large Cargo capacity
```

> [!IMPORTANT]
> The agent never guesses cargo capacities or falls back to arbitrary defaults. Accurate values ensure reliable logistics and raid planning.

### 4. Adjust Strategy Profiles

Customize `scripts/ogame/config/strategy.toml` to adjust energy squeeze margins, logistics boundaries, and farming target criteria:

```toml
[power_squeeze]
enabled = true
surplus_threshold = 30
target_energy = 0

[logistics]
minimum_transport_amount = 1000
maximum_transport_per_resource = 10000

[farming]
minimum_raid_loot = 5000
max_concurrent_raids = 2
```

### 5. Initialize Memory Files

Create your local runtime memory files from the provided templates:

```bash
cp runtime/memory/GameState.example.md runtime/memory/GameState.md
cp runtime/memory/TODO.example.md runtime/memory/TODO.md
cp runtime/memory/farm_targets.example.md runtime/memory/farm_targets.md
cp runtime/memory/patrol-log.example.md runtime/memory/patrol-log.md
cp runtime/memory/errors.example.md runtime/memory/errors.md
```

---

## Running & CLI Reference

All interactions are driven through `scripts/ogame_ctl.py`.

### Inspection & Telemetry (Read-Only)

```bash
# Display overall empire status (resources, mines, queues, energy)
python3 scripts/ogame_ctl.py matrix

# Synchronize all planets via the standalone Empire view
python3 scripts/ogame_ctl.py sync-all

# List owned planets and their internal cp IDs
python3 scripts/ogame_ctl.py list-planets

# Check active fleet movements
python3 scripts/ogame_ctl.py events --planet-id <PLANET_ID>

# Calculate mine upgrade Return on Investment (ROI)
python3 scripts/ogame_ctl.py roi --planet-id <PLANET_ID> --run-id <RUN_ID>
```

### Autonomous Patrol Workflow

A typical patrol cycle initiated by the agent:

```bash
# 1. Acquire single-instance lease and retrieve fresh sources
python3 scripts/ogame_ctl.py patrol-start --output json

# 2. Generate an immutable workflow plan
python3 scripts/ogame_ctl.py workflow plan --run-id <RUN_ID> --planet-id <PLANET_ID> --output json

# 3. Execute planned steps with fail-closed safety checks
python3 scripts/ogame_ctl.py workflow run --workflow-id <WORKFLOW_ID> --run-id <RUN_ID> --confirm --output json

# 4. Release run lease and commit memory state
python3 scripts/ogame_ctl.py finish-run --run-id <RUN_ID> --record-tokens
```

### Specific Operations

```bash
# Upgrade building or mine (Tech ID 1 = Metal Mine)
python3 scripts/ogame_ctl.py build 1 --planet-id <PLANET_ID> --run-id <RUN_ID> --confirm

# Upgrade research (Tech ID 113 = Energy Technology)
python3 scripts/ogame_ctl.py research 113 --planet-id <PLANET_ID> --run-id <RUN_ID> --confirm

# Dispatch transport to target coordinates [Galaxy:System:Position]
python3 scripts/ogame_ctl.py transport 1 2 3 --planet-id <PLANET_ID> --run-id <RUN_ID> \
  --metal 10000 --crystal 5000 --ship-tech 203 --ship-amount 1 --confirm

# Dispatch single-probe quick-spy to target coordinates
python3 scripts/ogame_ctl.py spy 1 2 4 --planet-id <PLANET_ID> --run-id <RUN_ID> --confirm

# Rapid colony bootstrapping (automatic robotics/mines/solar progression)
python3 scripts/ogame_ctl.py colony-bootstrap --planet-id <COLONY_ID> --run-id <RUN_ID> --mode plan
```

---

## Testing

The test suite validates CLI argument dispatching, planning algorithms, policy guardrails, and data parsers using offline fixtures:

```bash
python3 -m unittest discover -s tests -v
```

All tests execute entirely offline without requiring a live Chrome session or external network requests.

---

## Platform Limitations

- **macOS Only**: This project currently supports **macOS exclusively**.
- **Browser Automation Rationale**: Rather than relying on Selenium, Playwright, or headless CDP drivers—which frequently trigger automated anti-bot fingerprinting—this project interfaces directly with an active, existing **Google Chrome** tab via **AppleScript (`osascript`)**.
- **Security & Privacy**:
  - No account credentials or passwords are ever stored, typed, or transmitted by the scripts.
  - The human player logs in naturally through Chrome. The scripts simply operate within that authenticated session.

---

## ⚠️ Disclaimer

> [!WARNING]
> **Use at your own risk.**
>
> 1. **Terms of Service**: Automating gameplay, botting, or using scripted assistants may violate the **OGame Terms of Service (ToS)** and Gameforge rules. Use of this software could result in temporary suspension or permanent termination of your game account.
> 2. **Educational & Experimental Purpose**: This project is published strictly as an academic exploration of autonomous LLM agents, long-term memory architectures, fail-closed safety systems, and human-in-the-loop task orchestration.
> 3. **No Warranty**: This software is provided under the GNU General Public License v3 "AS IS", without warranty of any kind, express or implied. The author and contributors assume no liability for any direct or indirect consequences resulting from the use of this project.

---

## Acknowledgments

- [danlig/travian-agent](https://github.com/danlig/travian-agent) — The pioneering inspiration for Markdown-based persistent memory and agent self-governance.
- [TheOnlyBeardedBeast/ogame-agent](https://github.com/TheOnlyBeardedBeast/ogame-agent) — Reference and motivation for OGame automation architectures.
