# ogame-agent

[English](README.md) | [繁體中文](README.zh-TW.md)

[![Tests](https://github.com/iamjosuho/ogame-agent/actions/workflows/test.yml/badge.svg)](https://github.com/iamjosuho/ogame-agent/actions/workflows/test.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python: >=3.11](https://img.shields.io/badge/python->=3.11-brightgreen.svg)](pyproject.toml)
[![Platform: macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](#平台限制)

這是一個實驗性專案，旨在透過大型語言模型（LLM）Agent 在維持登入的瀏覽器 Session 中，結合結構化安全護欄，自主、安全且符合人類節奏地經營一個 [OGame](https://gameforge.com/zh-TW/play/ogame) 帳號。

本專案的核心哲學是將知識庫、作業規範（SOP）、記憶狀態與全局護欄直接作爲 Agent 的「大腦與行為準則」。Agent 並非暴力無腦的無頭爬蟲或自動化 Bot，而是擔任專屬的「帝國防守經營管家」——以防禦與經營為本、注重安全、嚴格遵守人類節奏。

---

## 系統架構

整個系統依託外部排程驅動（例如 Antigravity Scheduled Tasks 或 Cron），透過 Python 類型化執行基語與嚴格的安全護欄進行巡邏循環：

```
+--------------------------------------------------------------------------+
|                       Antigravity Scheduled Task                         |
|             （每小時常駐排程 Cron / 事件觸發之 Session 內喚醒）           |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                  Phase 0：生命週期與單實例租約閘門                       |
|  - check-wake --acquire（原子取得單實例巡邏租約與喚醒冷卻檢查）         |
|  - 載入長效記憶狀態（GameState.md、TODO.md、farm_targets.md）            |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                      Phase 1：唯讀狀態偵察（Scout）                      |
|  - matrix / sync-all（帝國全貌單頁：各星資源、建築佇列、生產率）         |
|  - movements 與銀河系掃描（敵襲威脅偵測、艦隊動態、收割目標）            |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|             Phase 2：協調官戰略審查與威脅評估（Review）                  |
|  - 安全審查（Hostile 敵襲確認 -> 偵測威脅時立即 Fail-Closed 停止）       |
|  - 帝國 ROI 與跨星物流平衡（⚡ 極限壓電 >= -20、解除資源瓶頸）           |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                Phase 3：類型化純規劃與操作執行（Execution）              |
|  - 純規劃生成候選動作（礦產、科技、造船、物流運輸、死羊收割）           |
|  - 護欄前置驗證：永遠保留 >= 1 Fleet Slot、單次花費 <= 90% 倉庫容量      |
|  - 嚴格序列化提交：星球綁定 -> 前置驗證 -> 動作派遣 -> 後置驗證（Post）  |
|  - 任何狀態不確定（Uncertainty）立即終止並回滾                           |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                  Phase 4：記憶持久化與釋放租約（Persistence）            |
|  - 回寫最新狀態至記憶庫並追加巡邏日誌                                    |
|  - 記錄對話 Token 消耗遙測數據                                           |
|  - 釋放巡邏租約（finish-run）並計算寫入下次喚醒時間 next_wake            |
+--------------------------------------------------------------------------+
                                     |
                 +-------------------+-------------------+
                 |                                       |
                 v                                       v
+---------------------------------+     +----------------------------------+
|        本機瀏覽器互動橋樑       |     |           全局紅線護欄           |
|  - AppleScript / Apple Events   |     |  - 嚴禁任何付費或暗物質交易      |
|  - 直接控制當前活躍 Chrome 標籤 |     |  - 嚴禁攻擊活躍玩家與防禦星球    |
|  - 零帳號密碼儲存，安全無虞     |     |  - 僅限 0防 0艦 閒置死羊收割     |
|  - 動作間保持 5-10 秒隨機延遲   |     |  - 遇驗證碼或異常彈窗立即停機    |
+---------------------------------+     +----------------------------------+
```

### 核心哲學

1. **安全 > 效率**：寧可少升一級礦，也絕不做任何可能暴露自動化特徵或導致艦隊損失的動作。
2. **不確定就不動作（Fail-Closed）**：遇到非預期的頁面結構、異常彈窗或疑似偵測警示，立即終止一切操作並回報。
3. **⚡ 極限壓電哲學**：發電廠產能由三礦即時吞噬，容許能量下探至 $\ge -20\text{ ⚡}$ 極限運轉，產能轉化率維持巔峰。
4. **單一真理來源（SSOT）**：船艦真實裝載容量與科技加成以 `scripts/ogame/config/constants.toml` 的 `[cargo_capacities]` 為唯一標準，嚴禁使用過時預設值或公式腦補。

---

## 目錄結構

```
.
├── AGENTS.md                  # Agent 常駐全局規範、核心心法與紅線護欄
├── CHECKLIST.md               # 快速檢查表與巡邏驗證手冊
├── LICENSE                    # GNU General Public License v3 (GPL-3.0)
├── pyproject.toml             # Python 專案打包配置與元數據
├── README.md                  # 英文專案說明文件
├── README.zh-TW.md            # 繁體中文專案說明文件
│
├── .agent/skills/             # Agent 執行作業手冊與技能定義
│   ├── ogame-patrol/          # 巡邏循環與協調官審查 SOP
│   ├── ogame-expedition-agent/# 遠征補槽與接力排程手冊
│   ├── ogame-agent-dev/       # 代碼開發與 Token 密度優化指引
│   └── script-evolution/      # CLI 與自動化腳本進化規範
│
├── knowledge/                 # OGame 當代遊戲 Meta 知識庫
│   ├── 01-economy.md          # 礦產升級配比、能源規劃與 ROI 試算
│   ├── 02-lifeforms.md        # 生命體建築、科技加成與流派配置
│   ├── 03-expeditions.md      # 遠征機制、艦隊配置與收益模型
│   ├── 04-discoveries.md      # 生命體探索任務與神器機制
│   ├── 05-new-player-path.md  # 開荒新手 14 天里程碑指南
│   ├── 06-colony-bootstrap.md # 新殖民星快速開荒建造序列
│   └── 06-inactive-farming.md # 安全閒置死羊收割策略
│
├── runtime/
│   ├── memory/                # 執行期長效記憶狀態（提供 *.example.md 範本）
│   │   ├── GameState.example.md   # 帝國資產、礦產等級與艦隊快照
│   │   ├── TODO.example.md        # 戰略目標與待辦事項清單
│   │   ├── farm_targets.example.md# (i)/(I) 閒置死羊收割清單
│   │   ├── patrol-log.example.md  # 歷史巡邏執行記錄
│   │   └── errors.example.md      # 執行錯誤與異常處理歷史
│   └── screenshots/           # 巡邏過程之診斷截圖
│
├── scripts/
│   ├── ogame_ctl.py           # 統一相容 CLI 入口腳本
│   └── ogame/                 # 模組化 Python 控制器引擎
│       ├── atoms.py           # 原子操作（鎖定星球、前置驗證、派遣、後置檢查）
│       ├── browser.py         # AppleScript / Chrome 原生通訊驅動
│       ├── cli.py             # 命令列參數解析與子命令分派
│       ├── colony_bootstrap.py# 新殖民星開荒規劃器
│       ├── empire.py          # 帝國單頁資料讀取與解析
│       ├── execution.py       # 動作分發與底層執行
│       ├── expedition_agent.py# 遠征空槽自動補滿與定時器調度
│       ├── farming.py         # 間諜報告解析與死羊收割規劃
│       ├── lifecycle.py       # 巡邏租約、喚醒閘門與 Git 提交封裝
│       ├── matrix.py          # 帝國全景矩陣渲染
│       ├── models.py          # 不可變領域模型與類型合約
│       ├── operations.py      # 動作候選建立與政策驗證
│       ├── patrol_contract.py # 循序巡邏生命週期檢查點契約
│       ├── patrol_start.py    # 單指令巡邏初始資料交接
│       ├── planning.py        # 純規劃引擎（政策約束與可行性計算）
│       ├── policy.py          # 凍結之安全策略常數與門檻
│       ├── probes.py          # 頁面診斷探針
│       ├── resolver.py        # 科技名稱與 ID 雙向查找
│       ├── tokens.py          # 對話 Token 消耗遙測追蹤
│       ├── workflow.py        # 類型化不可變工作流執行器與日誌
│       └── config/
│           ├── constants.toml     # 帳號專屬貨艙容量與實體常數
│           ├── server.example.toml# 伺服器連線配置範本
│           └── strategy.toml      # 可自訂策略檔案與行為門檻
│
├── tests/                     # 單元測試套件
│   └── fixtures/              # 離線測試用之 Mock 資料與 HTML 探針
└── docs/                      # 系統架構設計規範與 API 映射表
```

---

## 運行環境要求

- **作業系統**：macOS（底層透過 AppleScript / Apple Events 控制瀏覽器）。
- **Python 版本**：Python `>= 3.11`（使用標準庫內建的 `tomllib`）。完全無需安裝第三方依賴套件。
- **網頁瀏覽器**：Google Chrome。請在瀏覽器中登入您的 OGame 宇宙並保持開啟。
- **Agent 運行環境**：[Google Antigravity](https://github.com/google-deepmind) 或支援 Shell 腳本執行與定時任務排程的 LLM Agent 環境。

---

## 安裝與設定流程

### 1. 複製專案庫

```bash
git clone https://github.com/iamjosuho/ogame-agent.git
cd ogame-agent
```

### 2. 設定伺服器連線 URL

將範本配置檔複製為 `server.toml`：

```bash
cp scripts/ogame/config/server.example.toml scripts/ogame/config/server.toml
```

編輯 `scripts/ogame/config/server.toml`，填入您的 OGame 伺服器網址：

```toml
base_url = "https://s1-en.ogame.gameforge.com/game/index.php"
# 選填：若大廳帳號關聯多個宇宙，可指定宇宙名稱
# universe_name = "Earth"
```

> [!NOTE]
> `server.toml` 已被 `.gitignore` 排除，絕不會被推送到版本控制庫，確保個人伺服器資訊不外洩。

### 3. 設定船隻貨艙容量（單一真理來源 SSOT）

OGame 內的真實貨艙運力受超空間科技、收藏家職業加成（+25%）及生命體科技多重動態影響。請打開 `scripts/ogame/config/constants.toml`，填入您帳號在遊戲內計算後的精確運力：

```toml
schema_version = 1

[cargo_capacities]
"202" = 5000   # 小型運輸艦（Small Cargo）真實運力
"203" = 25000  # 大型運輸艦（Large Cargo）真實運力
```

> [!IMPORTANT]
> Agent 嚴禁使用預設值或自行腦補推算運力；準確填寫此設定檔可確保跨星物流搬運與死羊收割零失誤。

### 4. 調整營運策略檔案

依據發展需求自訂 `scripts/ogame/config/strategy.toml` 中的壓電門檻、運輸門檻與收割參數：

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

### 5. 初始化記憶庫檔案

從範本檔案建立本機執行期所需的長效記憶狀態：

```bash
cp runtime/memory/GameState.example.md runtime/memory/GameState.md
cp runtime/memory/TODO.example.md runtime/memory/TODO.md
cp runtime/memory/farm_targets.example.md runtime/memory/farm_targets.md
cp runtime/memory/patrol-log.example.md runtime/memory/patrol-log.md
cp runtime/memory/errors.example.md runtime/memory/errors.md
```

---

## 常用指令與 CLI 操作說明

所有遊戲互動統一經由 `scripts/ogame_ctl.py` 執行。

### 唯讀檢查與狀態檢視

```bash
# 檢視全帝國資源、建築佇列與能源概況（Matrix 矩陣）
python3 scripts/ogame_ctl.py matrix

# 透過帝國單頁同步所有星球狀態
python3 scripts/ogame_ctl.py sync-all

# 列出所有擁有的星球與內部 cp ID
python3 scripts/ogame_ctl.py list-planets

# 讀取當前進行中的艦隊動態與活動事件
python3 scripts/ogame_ctl.py events --planet-id <PLANET_ID>

# 試算礦產升級投資報酬率（ROI）
python3 scripts/ogame_ctl.py roi --planet-id <PLANET_ID> --run-id <RUN_ID>
```

### 自動化巡邏流程

Agent 典型的自動化巡邏循環：

```bash
# 1. 取得單實例執行租約並交接最新資料來源
python3 scripts/ogame_ctl.py patrol-start --output json

# 2. 生成不可變工作流計畫
python3 scripts/ogame_ctl.py workflow plan --run-id <RUN_ID> --planet-id <PLANET_ID> --output json

# 3. 執行計畫步驟並通過後置安全驗證
python3 scripts/ogame_ctl.py workflow run --workflow-id <WORKFLOW_ID> --run-id <RUN_ID> --confirm --output json

# 4. 釋放執行租約並記錄記憶日誌
python3 scripts/ogame_ctl.py finish-run --run-id <RUN_ID> --record-tokens
```

### 單項操作指令

```bash
# 升級建築或礦場（科技代碼 1 為金屬礦）
python3 scripts/ogame_ctl.py build 1 --planet-id <PLANET_ID> --run-id <RUN_ID> --confirm

# 研發科技（科技代碼 113 為能源科技）
python3 scripts/ogame_ctl.py research 113 --planet-id <PLANET_ID> --run-id <RUN_ID> --confirm

# 派遣運輸艦隊至目標座標 [銀河:太陽系:位置]
python3 scripts/ogame_ctl.py transport 1 2 3 --planet-id <PLANET_ID> --run-id <RUN_ID> \
  --metal 10000 --crystal 5000 --ship-tech 203 --ship-amount 1 --confirm

# 快捷派遣單架間諜探測器
python3 scripts/ogame_ctl.py spy 1 2 4 --planet-id <PLANET_ID> --run-id <RUN_ID> --confirm

# 新殖民星自動化開荒（自動排定機器人工廠/三礦/太陽能發電廠）
python3 scripts/ogame_ctl.py colony-bootstrap --planet-id <COLONY_ID> --run-id <RUN_ID> --mode plan
```

---

## 測試驗證

本專案具備完整的單元測試套件，使用離線 Mock 與 HTML 探針資料驗證 CLI 命令、規劃演算、政策護欄與數據解析器：

```bash
python3 -m unittest discover -s tests -v
```

測試全程離線執行，不需要連線 OGame 伺服器，亦無需開啟 Chrome。

---

## 平台限制

- **僅支援 macOS**：目前專案僅支援 **macOS** 平台。
- **瀏覽器自動化機制設計考量**：
  - 本專案不使用 Selenium、Playwright 或無頭 CDP 驅動（此類工具極易被伺服器之指紋追蹤與防刷檢測識別）。
  - 取而代之，專案透過 **AppleScript（`osascript`）** 與本機已開啟的 **Google Chrome** 標籤通訊。
- **資訊安全與隱私**：
  - 程式碼內部**絕不儲存、輸入或傳輸任何遊戲帳號與密碼**。
  - 玩家以正常方式在 Chrome 瀏覽器登入遊戲，腳本僅在您已授權的 Session 內運作。

---

## ⚠️ 免責聲明

> [!WARNING]
> **請在充分理解風險後自行承擔使用責任。**
>
> 1. **服務條款限制**：使用任何腳本、輔助程式或自動化工具可能違反 **OGame 服務條款（Terms of Service, ToS）** 與 Gameforge 營運規則，並可能導致遊戲帳號遭受暫時或永久封鎖。
> 2. **學術與實驗用途**：本專案僅供學術研究、AI Agent 架構探討、長效記憶管理與人機協作控制系統之教育實驗使用。
> 3. **無擔保聲明**：本軟體依據 GNU GPL-3.0 協議以「現狀（AS IS）」提供，不提供任何明示或默示之保證。作者與貢獻者不對使用本軟體所產生的任何直接或間接後果承擔任何法律與經濟責任。

---

## 致謝與參考先例

- [danlig/travian-agent](https://github.com/danlig/travian-agent) — 本專案 Markdown 長效記憶體系與自主管家哲學的重要啟發來源。
- [TheOnlyBeardedBeast/ogame-agent](https://github.com/TheOnlyBeardedBeast/ogame-agent) — OGame 自動化架構的早期探索與參考。
