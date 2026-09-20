# ogame-agent

[English](README.md) | [繁體中文](README.zh-TW.md)

[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](https://github.com/iamjosuho/ogame-agent/actions)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python: >=3.11](https://img.shields.io/badge/python-%3E%3D3.11-brightgreen.svg)](pyproject.toml)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-black.svg?logo=apple&logoColor=white)](#platform-limitations--faq)

An experimental AI agent project that autonomously and safely manages an [OGame](https://gameforge.com/en-US/play/ogame) account within an active session using LLM reasoning and structured guardrails.

The agent's "code" comprises curated domain knowledge files, operational Standard Operating Procedures (SOPs), memory state files, and strict non-negotiable safety guardrails. Rather than acting as a headless, brittle bot, it operates like a dedicated personal steward—defensive, measured, and pacing actions at human cadences.

---

## Prerequisites

Before getting started, make sure you have the following 4 prerequisites ready:

1. **System & Runtime**: **macOS** with **Python `>= 3.11`** installed (uses built-in standard library, **zero external package dependencies**).
2. **Clone the Repository**:
   ```bash
   git clone https://github.com/iamjosuho/ogame-agent.git
   cd ogame-agent
   ```
3. **Browser Login & Obtain Universe URL**:
   - Log into your OGame universe account in **Google Chrome** and keep the game tab open.
   - Copy your universe URL from the address bar (e.g., `https://s1-en.ogame.gameforge.com/game/index.php`).
4. **🚨 Essential Chrome Setting (Required ⚠️)**:
   - In Google Chrome's top menu bar, open: **"View"** → **"Developer"** → check **"Allow JavaScript from Apple Events"**.  
   - *(This is macOS Chrome's native security control allowing local AppleScript communication; omitting this triggers an authorization error.)*

---

## ⚡ Quick Start

Choose your preferred way to get started:

### 🤖 Option A (Recommended): Let your AI Agent handle everything!

If you are using an AI Coding Agent such as [Google Antigravity](https://github.com/google-deepmind), **Claude Code**, **Cursor**, or **Windsurf**, you **don't need to type terminal commands manually**:

1. Open this repository folder in your AI Agent workspace.
2. Grab your logged-in OGame universe URL.
3. Prompt your Agent:
   > 💬 *"I am logged into OGame in Chrome. My universe URL is `<YOUR_UNIVERSE_URL>`. Please read `README.md`, initialize this project, and verify connection by running `matrix`!"*

The Agent will inspect the README, run initialization with your URL, and report your empire snapshot immediately!

---

### 💻 Option B: Manual Terminal 3-Step Setup

If you prefer running commands yourself in the terminal:

#### Step 1: Initialize Environment & Server URL
Run the built-in `init` command to set up memory stores and configure your server URL:
```bash
python3 scripts/ogame_ctl.py init
```
An interactive prompt will guide you through entering your universe URL:
```text
[INIT] Setting OGame server connection info:
  Enter your OGame universe URL [default: https://s1-en.ogame.gameforge.com/game/index.php]: 
  Enter universe name (optional for multi-universe accounts) [None]: 
```
> [!TIP]
> **One-liner CLI flag**: You can also supply the URL directly via CLI flags to skip prompting:  
> `python3 scripts/ogame_ctl.py init --url "https://s1-en.ogame.gameforge.com/game/index.php"`  
> To switch universes later, simply re-run `init --url <NEW_URL>` anytime!

#### Step 2: Verify Connection (Hello World Test)
Ensure Google Chrome is open on your logged-in OGame page, then run:
```bash
python3 scripts/ogame_ctl.py matrix
```
> 🎉 **Success!** If your terminal renders a clean dashboard showing your planets' resources, construction queues, and power levels, your environment and browser bridge are fully ready!

#### Step 3: Configure Ship Cargo Capacities (SSOT)
In OGame, real ship cargo capacities are dynamically modified by Hyperspace Technology, Collector class bonuses (+25%), and Lifeform research. Open `scripts/ogame/config/constants.toml` and enter your account's exact, live in-game capacities:

```toml
schema_version = 1

[cargo_capacities]
"202" = 5000   # Small Cargo capacity
"203" = 25000  # Large Cargo capacity
```

> [!IMPORTANT]
> **Single Source of Truth (SSOT)**: The agent never guesses cargo capacities or falls back to arbitrary defaults. Accurate values ensure reliable logistics and raid planning.

*(Optional)* You can also customize `scripts/ogame/config/strategy.toml` to tweak energy squeeze margins, transport thresholds, and inactive raid loot limits.

#### Step 4: Set Up Your AI Agent's Recurring Patrol (Required for Automation)
`init` and `matrix` prepare and verify the project; they do **not** create or enable a recurring task. To run autonomous patrols, create a recurring task, scheduled prompt, or Cron-based agent wakeup in the AI Agent you use.

1. Use your AI Agent's own scheduler (for example, its Scheduled Tasks, recurring prompt, or Cron integration) and keep the task scoped to this repository.
2. Set the frequency to suit your play style (hourly is a reasonable starting point); do not create overlapping schedules for the same account.
3. Paste or adapt the repository template: [`.agent/skills/ogame-patrol/CRONJOB_PROMPT.md`](.agent/skills/ogame-patrol/CRONJOB_PROMPT.md). It is deliberately versioned in the repository so you can review and tailor the prompt for the capabilities and scheduling syntax of your chosen AI Agent.

> [!IMPORTANT]
> The scheduler should wake an AI Agent that can follow the prompt and continue in this project. A bare OS Cron command running only `patrol-start` performs the safety-gated evidence handoff, but does not replace the Agent's strategy review or execution loop.

> [!NOTE]
> Updating `CRONJOB_PROMPT.md` changes only the template in this repository. It does not change, enable, pause, or delete a task already configured in your AI Agent; update that scheduler separately.

---

## Core Philosophy & Guardrails

1. **Safety over Efficiency**: Better to miss an upgrade cycle than perform an action that exposes automation patterns or risks fleet loss.
2. **Fail-Closed**: If unexpected page structures, modal dialogs, or anti-bot checks appear, immediately halt and alert the user.
3. **⚡ Energy Squeeze**: Power plants operate in tight coordination with mine upgrades, allowing energy deficits down to $\ge -20\text{ ⚡}$ to maximize economic throughput.
4. **Hard Red-Line Guardrails (🚨 Strictly Enforced)**:
   - Zero real-money or Dark Matter purchases.
   - Zero stored credentials; never enter passwords.
   - Never initiate diplomatic messaging or reply to in-game player PMs.
   - Never attack active players or defended planets (only `(i)`/`(I)` inactive farms with 0 defense and 0 fleet).
   - Always preserve at least **1 available Fleet Slot** for emergency fleetsave.

---

## Architecture

The system operates on an automated patrol cycle, driven by an external scheduler (e.g., Antigravity Scheduled Tasks or Cron), coordinating through typed Python execution primitives and strict safety guardrails:

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

## Testing

The test suite validates CLI argument dispatching, planning algorithms, policy guardrails, and data parsers using offline fixtures:

```bash
python3 -m unittest discover -s tests -v
```

All tests execute entirely offline without requiring a live Chrome session or external network requests.

---

## Platform Limitations & FAQ

- **macOS Exclusively**: This project currently supports **macOS only** due to its deep integration with macOS Apple Events.
- **Why AppleScript instead of Selenium / Playwright?**
  - Headless CDP browsers often trigger bot-detection fingerprinting and Cloudflare/Gameforge challenges.
  - Interacting with an active, existing **Google Chrome** tab via **AppleScript (`osascript`)** executes within your genuine player session with native human-like timing.
- **Security & Privacy**:
  - No account credentials or passwords are ever stored, typed, or transmitted by the scripts.
  - The human player logs in naturally through Chrome. The scripts simply operate within that authenticated session.
- **Common Troubleshooting**:
  - *AppleScript Error: Executing JavaScript through AppleScript is turned off*:
    Check that Chrome has enabled **View** → **Developer** → **Allow JavaScript from Apple Events**.

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
