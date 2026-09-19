# Phase 2 決策準則參考手冊（Coordinator 親自使用）

> **用途**：本文件供主協調官（Coordinator）在 Phase 2 直接套用，進行全帝國宏觀策略裁奪。  
> **職責邊界**：產出高階語意意圖 `strategic-decision.json`；**不拼裝 tech ID 或 DOM 選擇器**，意圖與底層執行解耦。

---

## 任務目標

統籌全帝國各星球（動態讀取 GameState.md 與 scout-report.json）的即時資源供需、跨星物流、科研衝刺與壓電礦建，產出合法、平衡且符合當前戰略方針的高階決策意圖 `runtime/memory/strategic-decision.json`。

---

## 輸入材料

- `runtime/memory/scout-report.json`（Empire standalone 最新全星資源、實際倉容、能量、等級與佇列矩陣，及 accountInfo 補充產速）
- `runtime/memory/TODO.md`（當前戰略方針與里程碑目標）
- `runtime/memory/GameState.md`（歷史世界狀態與艦隊駐留）
- `runtime/memory/farm_targets.md`（周邊死羊目標資料庫與出擊計數）
- `runtime/memory/errors.md`（已知陷阱與防坑指南）

---

## 策略裁奪準則

以 runtime/memory/TODO.md 為當前策略主要入口，不從舊日誌重建優先序。

1. **主線目標優先**：依 TODO.md 設定之主線目標（如關鍵科研、殖民、新星開荒等）。先保留下一步已驗證成本，無關研究可等待；研究佇列空閒不代表必須花錢。
2. **運力與避難配套**：大型運輸艦依實際資源、下次巡邏前產量、即時貨艙與可用船數補足。已確認敵襲先Fleetsave；平時搬運/殖民優先於副收入。保留至少1個Fleet Slot，必要時更多；不得假設Cron能即時保護。
3. **經濟與礦產**：扣除主線與運力資金後，比較便宜礦、必要供電、增產生命科技及履帶車的完整成本/增益；成本不明不排名為零成本。既有水晶高金屬1–2級偏好仍保留，但不得壓過當前主線。
4. **例行循環必評估、派遣才看餘裕**：每輪依序盤點搬運、遠征、死羊偵察／收割、生命探索；不得因已有主線動作而停止決策。遠征、死羊、生命探索不得佔用必要運力、燃料、資金及槽位。沒有強制3隊遠征或空槽全滿的目標；總槽位和貨艙從live讀取，不能固定12槽或大運35k。
5. **長期戰略目標**：重大戰略目標（如高階艦船、特殊研究、造月等高成本項目）須獨立評估；經濟穩定後重評完整前置與預算，不因長期目標排擠當前主線資金。未授權聯絡或安排其他玩家攻擊。

金屬過剩優先用於主線、礦產、運輸艦或搬運，不再使用固定飛彈發射器配額。其他科研、研究所、奈米與機器人需有當輪瓶頸證據，不為空檔自動升級。
所有動作仍受AGENTS.md安全護欄約束，缺乏確認候選則watch/等待。每輪簡短記錄主線瓶頸、保留資源、運力缺口、下一步，以及四項例行盤點狀態。

## 每輪例行盤點契約

fresh Scout 正常完成後，Coordinator 必須逐項產生結果；狀態限 `planned`、`not_due`、`no_surplus`、`blocked`、`complete`：

1. `transport`：跨星主線缺口、爆倉風險、下輪前產量、可用貨艙與必要大運缺口。
2. `expedition`：遠征上限／在途隊伍、可用安全槽位、船艦與燃料；不要求固定隊數。
3. `farming`：既有目標、報告是否在2小時內、是否需偵察，以及 `(i)/(I)`、0防0艦、24小時次數門檻。
4. `lifeform`：是否仍缺物種、每日上限、7日冷卻、重氫與槽位；物種目標完成後標記 `complete`。

`no_surplus` 必須是扣除主線保留、必要搬運／Fleetsave 運力與燃料後的結果，不能只因「目前有主線」就直接填入。`blocked` 必須附短 reason code；任一 `uncertain` 不屬於可繼續狀態，必須全局停止。

---

## 極簡輸出契約 (`runtime/memory/strategic-decision.json`)

此檔是耐久決策紀錄，不是 LLM 間的大型訊息。只保存 Python 執行所需欄位；
理由、資源快照、成本、前置條件與安全規則不得重複抄入，分別留在巡邏日誌、
`scout-report.json` 與 Python policy。

```json
{"v":1,"run_id":"<run_id>","ops":[
  {"kind":"upgrade","planet_id":"<cp>","target_name":"重氫合成器","target_level":12,"component":"supplies"},
  {"kind":"expedition","planet_id":"<cp>","target":"[X:Y:Z]","cargo":5,"combat":1}
],"watch":null,"routine":{
  "transport":{"status":"planned"},"expedition":{"status":"planned"},
  "farming":{"status":"blocked","reason":"no_fresh_report"},"lifeform":{"status":"complete"}
}}
```

- `routine` 四個 key 缺一不可，每項 `status` 限使用上述五值；`blocked` 另附短 `reason`。它是每輪是否確實盤點的 compact 證據，不是派滿槽位指令。
- 只有 `routine` 完整，且 `ops=[]`、`watch=null` 時才可直接收尾。
- 不得放入完整 candidates、packages、resources、DOM、URL、成本或長篇 reasoning。
- 不得由 Coordinator 猜 tech ID；名稱必須由 Python 在 fresh plan 中唯一解析。

---

## Phase 2 完成後的行動

完成 `strategic-decision.json` 寫入後：
1. 若四項 `routine` 狀態完整、`has_mutations == false` 且無 `watch`：**直接跳往 Phase 4**，無需啟動 Executor。
2. 若有待執行項目（遠征、輸血、升級、排產等）：Coordinator 直接推進至 **Python Executor** Phase 3；不得啟動 Executor sub-agent。
