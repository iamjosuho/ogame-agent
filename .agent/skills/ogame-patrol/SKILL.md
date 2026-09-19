---
name: ogame-patrol
description: "OGame 帝國巡邏 SOP：Python 單指令初始資料交接、Coordinator 策略與安全審查、全域矩陣、跨星物流、死羊收割、提交與租約管理。"
---

# OGame Patrol SOP

本技能為 OGame 帝國專屬管家巡邏中樞。排程喚醒後由主協調官先呼叫唯一 Python 入口，依 compact handoff 推進五階段流程並遵守 `AGENTS.md` 紅線護欄。

```
每 15 分鐘定時排程喚醒
       │
       ▼
┌──────────────────────────────────────┐
│       主協調官 Coordinator (Pro)     │
│  Phase 0: 只呼叫 patrol-start         │
│  Phase 2: 全局策略決策（親自執行）   │
│  Phase 4: 記憶寫回與靜默回報        │
└────────┬─────────────────────────────┘
         │ Phase 1: Python 唯讀採集
         ▼
┌──────────────────────────────────────┐
│       Python data collector          │
│  movement + Empire + compact handoff │
└────────┬─────────────────────────────┘
         │ 回傳狀態與證據路徑
         ▼
  Coordinator 親自審查 movement、安全狀態
  按需讀 TODO.md 與 scout-report.json
  套用 TODO.md 與 strategist.md 當前目標
  產出 strategic-decision.json
         │ Phase 3: 若有 mutations
         ▼
┌──────────────────────────────────────┐
│       Python Executor（無 LLM）      │
│  完整 plan 僅留在程序內與安全狀態檔  │
│  Agent 只接收 compact result         │
└──────────────────────────────────────┘
```

---

## Phase 0：單指令喚醒與資料交接

1. **喚醒後第一步**：不先讀任何檔案或啟動子代理，只執行：
   ```bash
   python3 scripts/ogame_ctl.py patrol-start --output json
   ```
   - 入口內先執行 lease gate；`too_early` 或 `overlap` 時靜默退出，**嚴禁連線 OGame**。
   - 所有非 `ready` 狀態都停止。`aborted` 已用 exact reason 釋放 lease；`release_failed` 表示釋放未確認，立即回報主人處理，不連線遊戲。
   - 只有 `status=ready` 時保存 `run_id`，按 `evidence` 路徑讀取所需檔案。入口已提交 `memory_loaded`、`scout_complete`；不可重交或跳步。

2. **精簡交接**：先看回傳的 `threat_status`、source／coverage 與路徑，再讀 `movement-events.json` 做安全審查；策略階段按需讀 `TODO.md`、`scout-report.json`、`GameState.md`、`errors.md` 和 `CHECKLIST.md`。完整矩陣不貼入 prompt，不讀 `patrol-plan.json`。

`patrol-start` 的 `memory_loaded` 是 Python 已讀取並驗證固定檔案，證據在 `patrol-start-sources.json`；不是宣稱 Coordinator 已逐字閱讀。後續 checkpoint 仍按 contract 順序執行。

---

## Phase 1：安全審查（Coordinator）

**不得啟動 Scout sub-agent。** 入口先讀官方 no-cp movement 頁，再採集 Empire matrix；兩份證據驗證成功才提交 `scout_complete`。主協調官親自查看 movement evidence：

- `hostile`：立即啟動動態戒嚴，凍結常規遠征／探索並按 live 證據處理 Fleetsave。
- `unknown`：停止常規 mutation，複核事件方向；未釐清前不得以 `alarms: []` 宣稱安全。
- 驗證碼、封號、防刷或登入失效：立即終止並依 exact reason abort。
- 安全審查完成後才提交 `patrol-step --phase safety_reviewed --evidence-ref runtime/memory/movement-events.json`，不得把入口的 `scout_complete` 當成安全放行。

CLI 會拒絕 `safety_reviewed` 之前的遊戲 mutation；checkpoint 只記錄順序與證據路徑，敵我方向的實際複核仍由 Coordinator 負責。

---

## Phase 2：全局策略決策（主協調官親自執行）

**不啟動 Strategist sub-agent**。主協調官在安全審查後按需讀取 `scout-report.json` 與策略檔案進行宏觀裁奪。

1. **讀取偵察快照**：
   ```bash
   view_file runtime/memory/scout-report.json
   ```
   （精簡 JSON 只提供狀態與路徑；需要逐星數值時才讀此檔。）

2. **套用決策準則**：先讀 `runtime/memory/TODO.md` 的最新設定目標，再依 `references/strategist.md` 裁奪。
   - 主線任務：依 `TODO.md` 指定之當前戰略目標（例如科技研發、新星殖民或基礎建設），含相關倉容、資源保留與開荒配套。
   - 必要配套：大型運輸艦、跨星搬運與Fleetsave；即時敵襲依安全流程優先處理。
   - 其次：經濟與礦產持續增長、增產生命科技/履帶車完整ROI比較，之後再進行後續擴張。
   - **每輪固定逐項盤點**：搬運、遠征、死羊偵察／收割、生命形式探索。主軸策略決定資源順位，不能取代例行巡邏；「僅用餘裕」只限制是否派遣，不得成為略過評估的理由。
   - 每項都要在 `strategic-decision.json` 留下 `planned`、`not_due`、`no_surplus`、`blocked` 或 `complete` 之一；不得因本輪已有主線建築／研究，便直接跳過其餘四項。
   - 副任務不再強制滿槽：先扣除主線保留、必要搬運／Fleetsave 船艦、燃料與安全槽位，仍有餘裕且 typed 安全條件成立才派遣。
   - 長期戰略目標不排擠當前主線資金。

3. **產出決策意圖**：將裁奪結果寫入 `runtime/memory/strategic-decision.json`（schema 詳見 `strategist.md`）。

4. **強制 checkpoint**：用四項實際狀態執行 `patrol-step --phase
   strategy_complete --evidence-ref runtime/memory/strategic-decision.json
   --transport <status> --expedition <status> --farming <status> --lifeform
   <status>`。四項缺一或狀態無效時 Python 必須拒絕。

5. **推進判斷**：
   - 只有四項例行盤點皆已留下狀態，且 `has_mutations == false`、無 `watch`，才可跳往 Phase 4。
   - 若有待執行項目：推進至 Phase 3。

---

## Phase 3：按需計畫與安全執行（Python Executor，無子代理）

**不得啟動 Executor sub-agent。** Coordinator 依
`references/executor.md` 直接呼叫磁碟上的 Python wrapper。這可省去一整個
子代理的 system prompt、Skill 注入、完整 plan 閱讀與結果轉述。

- **高階意圖輸入**：只傳 `run_id`、`planet_id`、精確目標名稱／等級與動作種類；不得傳 DOM selector、URL、成本或自行拼裝 tech ID。
- **完整 plan 邊界**：`scripts/ogame_ctl.py execute-decision` 在 subprocess 內取得 fresh plan、唯一比對 candidate、建立 typed workflow 並立即執行。完整 plan 只存在 Python 記憶體與 `runtime/memory/patrol-plan.json`，**禁止 `view_file`、禁止貼入 prompt、禁止另存 `plan-<planet>-<tech>.json`**。`patrol-plan.json` 是單一短效槽位，因此每個操作都必須完整完成「fresh plan → resolve → journal → run」後才可處理下一顆星；禁止跨星預建 plan。
- **輸出邊界**：只接收單行 compact JSON：`status`、`plan_id`、`workflow_id`、`action_id`、`reason`、`global_stop`、`evidence_ref`。完整證據留在 workflow journal；除錯時只傳 evidence path。
- **安全流程不變**：所有 mutation 序列化，仍須 planet pin → prevalidation → execution → postcondition；`blocked` 停止該項，任一 `uncertain` 立即 `global_stop`。
- 遠征、運輸、偵察、收割與生命探索等已封裝操作，直接呼叫相應 `ogame_ctl.py` 子指令並使用預設精簡輸出；不得要求 `--output json` 後再全文閱讀。
- 若設定遠征接力且已建立唯一 `agent` preset 時，讀 `.agent/skills/ogame-expedition-agent/SKILL.md`，使用 `expedition-agent` 依 live movement／Expedition Slot 補位；不得改用 Galaxy 點擊重播或固定舊艦隊數。
- **新殖民星 timer 鏈**：新星通過 TODO 的方格／保留標準後，若 live queue `end_epoch` 落在本輪 lease 與安全執行窗口內，不得收尾等待下一個 Cron。以該 `end_epoch` 設同輪 timer，完工後加 5～10 秒隨機緩衝，重新取得 fresh plan 與 planet pin，再逐筆執行下一棟；不得沿用 timer 前的 candidate、資源或 queue 快照。若等待可能超出 lease／安全窗口，才保存精確 `next_wake` 後交回排程。
- **新星物流流水線**：新星每次開工、完工或運輸到港後，立刻重算下一批已驗證建設成本、現有資源、confirmed 在途 ETA 與貨艙缺口。來源星扣除主線承諾、必要 Fleetsave 運力／燃料後仍有餘裕時，主動使用既有 transport 封裝分批續運，使到貨早於下一次開工需求；cargo 只能取自 `scripts/ogame/config/constants.toml` 的 `[cargo_capacities]`，且每次派遣皆 fresh 驗證自有目標、倉容、可用船與至少 1 個保留 Fleet Slot。運輸與建築仍逐筆序列化，不得把在途資源當作已到貨。
- 新星驗收後上述兩項由 `python3 scripts/ogame_ctl.py colony-bootstrap --planet-id <new_cp> --run-id <run_id> --mode run --source-id <source_cp> ... --confirm` 統一執行。只可傳 Empire fresh 確認的 target/source cp；先把各來源星必留的主線資源用 `--source-reserve-*` 表達。命令回傳 `uncertain` 時立即全局停止，`blocked` 時記錄 exact reason，禁止改用手動拼裝 payload 繞過。
- 主線操作完成不代表本輪結束；依 `strategic-decision.json` 繼續處理已判定 `planned` 的例行項目，直到完成、blocked 或 uncertain 全局停止。
- 所有排定動作完成後，依 `references/executor.md` 核對保留運力與槽位；不因有空槽而自動補滿。
- **強制 checkpoint**：所有 planned 項目都實際解析為結果後，執行
  `patrol-step --phase execution_complete`，再次提交四項最終狀態。
  此時任何項目仍為 `planned` 都會被 Python 拒絕，不能進入記憶寫回。

---

## Phase 4：記憶寫回與靜默回報（主協調官親自執行）

收到 Executor 執行結果後，主協調官完成本輪收尾：

1. **更新記憶檔案**：
   - `runtime/memory/GameState.md`：只保留目前仍影響下一輪的關鍵狀態（進行中建築／研究、在途艦隊、主線瓶頸、異常與 next wake）。完整 live matrix 留在 `scout-report.json`，不得逐星重抄。
   - `runtime/memory/TODO.md`：若里程碑達成，標記完成並更新下一目標。
   - `runtime/memory/farm_targets.md`：更新出擊次數與戰報。
   - `runtime/memory/token-usage.md`：記錄本輪 Token 消耗（`finish-run --commit` 已自動內建，亦可透過 `python3 scripts/ogame_ctl.py record-tokens --run-id <run_id>` 補登）。
   - `runtime/memory/patrol-log.md`：只保留本輪最重要的 mutation／里程碑／異常與下一次喚醒；四項 routine 的完整狀態已由 `strategic-decision.json` 與 patrol contract 保存，不得在日誌重抄。

2. **插入極簡巡邏日誌**：
   在 `runtime/memory/patrol-log.md` **頂部插入**本輪極簡單行紀錄（**時間倒序，最新在最上方**，保留最近 20 筆）：
   ```markdown
   - YYYY-MM-DD HH:MM CST | #N | 重點（無則 no-op） | 結果 | next HH:MM
   ```
   - 「重點」只寫實際 mutation、已達成里程碑、`blocked`／`uncertain` 或需主人介入的異常；每輪最多一個短句。
   - 正常安全檢查只寫 `safe`；不得重抄全帝國資源、時產、各星 build status、完整中文摘要、詳細 reasoning 或四項 routine 明細。
   - 完整即時狀態與證據留在 `scout-report.json`、workflow journal、`strategic-decision.json` 與 patrol contract；終端／畫面回報不再複製進兩個 Markdown 檔。

3. **完成 persistence checkpoint**：
   - 記憶與日誌全部寫回後執行 `patrol-step --phase persistence_complete
     --evidence-ref runtime/memory/patrol-log.md`。

4. **每輪強制稽核與 Git 提交 (Mandatory Patrol Commit)**：
   - 先執行 `patrol-audit --run-id <run_id> --output json`；只有
     `complete:true` 才是正常完成。
   - **正常收尾只使用下列一步到位指令**：
     ```bash
     python3 scripts/ogame_ctl.py finish-run --run-id <run_id> --commit --output json
     ```
   - 任一 checkpoint、routine 或 evidence 缺失時，Python 拒絕正常 commit、
     將該輪標為 `incomplete`，但仍安全釋放 lease。
   - 已知錯誤而提早 fail closed 時，使用 `--abort-reason <exact_reason_code>`；
     不得把 aborted 偽裝成 completed。
   - **Commit Message 規格**：`Cronjob YY-MM-DD HH:mm [run: <run_id>]`（強制 CST 時區，例如 `Cronjob 26-09-06 06:30`）。
   - **核心目的**：確保主人能隨時由版本控制 diff 精確追蹤每次改動細節，作為後續策略優化方向依據。

5. **靜默原則回報**：
   - ✅ **例行等待/監視**：僅在終端輸出極簡單行摘要。
   - 🔔 **升級開工/物流啟動/里程碑**：條理清晰回報動態。
   - 🚨 **任何異常/需授權決策**：立即報警通知主人。

---

## 附錄 A：首次偵察
此為人工初始化程序；若排程入口缺少必要記憶檔案，`patrol-start` 會 abort，不在該輪繞過 lease 與 checkpoint 建檔。人工初始化不執行遊戲 mutation，只做：
1. 記錄宇宙名稱、星球位置、初始資源與建築等級。
2. 建立 GameState.md、TODO.md、errors.md。
3. 完整截圖存檔至 `runtime/screenshots/`。
4. 向主人回報帳號現況。

## 附錄 B：防禦評估（被攻擊時）
1. 讀取來襲艦隊規模與抵達時間。
2. MVP 階段唯一標準動作：Fleetsave（艦隊+資源派往自家殖民地或月球，選擇抵達時間晚於攻擊抵達的任務）。
3. 若無法 fleetsave（資源太多運不完）→ 通知主人，不擅自判斷。
4. 事後記錄損失與事件全貌到 `runtime/memory/`。

## 附錄 C：閒置死羊收割作業細則（Inactive Farming）
1. 僅對銀河系標記為 `(i)` 或 `(I)` 的星球發送探測機。
2. 出征安全核對表：
   - [ ] 間諜報告防禦設施數 = 0
   - [ ] 間諜報告艦隊駐留數 = 0
   - [ ] 報告時間在 2 小時內
   - [ ] 出征次數依 `AGENTS.md` 最新死羊規則，不設舊的固定次數上限
   - [ ] 出征後仍保有至少 1 個可用 Fleet Slot
3. 戰報記錄：掠奪資源寫入 `patrol-log.md` 並更新 `farm_targets.md`。

## 異常處理表

| 狀況 | 動作 |
|---|---|
| 登入失效 | 通知主人重新登入（嚴禁自行嘗試輸入密碼） |
| 頁面改版/元素找不到 | 記錄 errors.md，跳過該動作 |
| 疑似偵測警告/驗證碼 | 全面停止，通知主人 |
| 間諜報告顯示有防禦/艦隊 | 放棄攻擊，將該星球自出征清單標記為跳過 |
| LLM 判斷兩難 | 選保守選項，並在回報中說明 |
| `reason: overlap` | 靜默結束，不連線、不接管、不清除另一輪租約 |
