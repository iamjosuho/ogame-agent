# CHECKLIST.md — OGame 帝國巡邏標準作業核對清單

本核對清單為全帝國所有巡邏排程（Scheduled Patrol / Cronjob）常駐最高作業標準。  
每輪巡邏喚醒後，主協調官須依照本清單逐項核驗；初始資料由 Python 入口唯讀採集，策略與安全審查仍由主協調官負責。

---

## 📋 巡邏五大核心階段核對標準

### 🛡️ Phase 1：安全閘門與環境巡查（Safety & Integrity）
- [ ] **1.1 喚醒閘門與單實例租約**：喚醒後第一步只執行 `patrol-start --output json`；入口內先執行 `check-wake --acquire`。`too_early` 或 `overlap` 靜默退出；`aborted` 停止。`ready` 才保存 `run_id` 並讀取 evidence。
- [ ] **1.2 異常警報預檢**：確認無防刷驗證碼、無封號警告、無異常彈窗。若有立即全面中斷報警。
- [ ] **1.3 敵襲警報與動態戒嚴**：
  - 若偵測到來襲敵艦（Hostile Fleet）：**立即啟動動態戒嚴！** 凍結當輪所有遠征與探索，將所有可用槽位 100% 釋出供受威脅星球執行 Fleetsave。
- [ ] **1.4 大廳與 Session 檢核**：若停留在大廳（Lobby），自動點擊進入遊戲；若登入失效報警通知主人。
- [ ] **1.5 Empire 與 movement 快照契約**：入口驗證 `empire.standalone` 資源／倉容／等級／佇列及官方 movement 頁證據；缺 coverage 時不得以 0／空閒推論。`official.accountInfo` 產速缺失時使用 `null`。`scout-report.json` 的空 alarms 不代表零敵襲。
- [ ] **1.6 程式化流程狀態機**：入口依序提交 `memory_loaded → scout_complete`；主協調官讀 movement evidence 並完成安全審查後才提交 `safety_reviewed`。`hostile`／`unknown` 時，在安全狀態釐清前禁止常規 mutation。

---

### 🔬 Phase 2：戰略主線與經濟建設

- [ ] 讀 `runtime/memory/TODO.md` 最新戰略優先序；當前主線目標高於填滿佇列與副收入。
- [ ] fresh 確認核心科技等級、殖民星數、研究星倉容、殖民船與開荒條件，滿足完整條件前不提前視為已解鎖。
- [ ] 保留主線下一步成本、必要燃料及已排定工程承諾，未足額可 watch／等待，不升無關科技。
- [ ] **新星短工期不得等下一輪 Cron**：新殖民星驗收合格後，若 live queue 完工仍在本輪 lease／安全窗口內，以 `end_epoch` timer 等到完工並加 5～10 秒緩衝，fresh 重驗後立刻接續下一棟；超出安全窗口才記錄精確 `next_wake`。
- [ ] 新星一律使用 `colony-bootstrap` 公式 planner，動態追趕成熟星基準里程碑；不得由 Agent 自行拼 tech ID、成本、運輸 payload 或沿用舊候選。
- [ ] 餘裕才投入便宜礦與供電、增產生命科技或履帶車；既有資源偏好不壓過主線，未知成本不得假定為 0。
- [ ] 長期戰略目標未進入執行階段前，不提前大量生產前置單位或挪用核心擴張資金。

---

### 🚚 Phase 3：運輸艦與資源搬運

- [ ] **每輪都要評估搬運**：依各星資源、下次有效巡邏前產量、主線缺口、live 貨艙與在港／在途艦隊，判定本輪為 `planned`、`not_due`、`no_surplus` 或 `blocked`；不得只看主線建築後跳過物流。
- [ ] 依資源存量／預估產量、live 每艘貨艙、在港船與可及時返航船計算大運缺口，按需分批增造。
- [ ] 跨星物流優先支援研究星及殖民開荒；到港後才視為可花費資源，運載量以 live cargo SSOT 為準，嚴禁預設固定運力。
- [ ] **新星補給不得只靠每輪 Cron**：開工、完工、運輸到港時都重算下一批建設缺口與 ETA；來源星保留主線與 Fleetsave 餘裕後，按需分批續運，使資源儘量先於下一棟需求抵達。
- [ ] 防守以搬運與 Fleetsave 為主；不設定盲目消耗資源的固定防禦配額。
- [ ] 倉儲依主線研究門檻及預估滿倉時間規劃；運輸可填滿目標倉，不套用建築／研究 90% 支出護欄。
- [ ] 不把 Cron 當成即時保護；若暫停、登入／讀取失敗或時間不足，記錄限制並依風險回報。

---

### 🚀 Phase 4：保留安全運力後再做副收入

- [ ] 從 live 讀總槽位及占用，至少保留 1 個 Fleet Slot；依多星搬運與避難需求保留更多。
- [ ] 先保留必要運輸艦／燃料及主線資源；遠征、收割、生命探索只用餘裕。
- [ ] **遠征每輪必評估**：核對遠征上限、在途／返航隊伍、可用槽位、船艦與燃料；有餘裕才派，否則留下 `not_due`、`no_surplus` 或 `blocked`。
- [ ] 啟用遠征接力時只用 `expedition-agent` 解析唯一 `agent` preset，先把手動 mission 15 去重計入，再動態補 live 空缺；不得固定舊艦隊數或重播 Galaxy 點擊。
- [ ] **死羊每輪必評估**：檢查 `farm_targets.md`、報告新鮮度與可用槽位；需要更新情報時先安全偵察，有合格 fresh report 才收割，否則留下未派原因。
- [ ] 單架死羊偵察優先使用目標銀河系列的原生 quick-spy；不得為此重走 Fleet dispatch 座標表單。快捷控制缺失或目標列狀態改變時 `blocked`，不可盲點或繞過。
- [ ] **生命探索每輪必評估**：確認尚未完成的物種目標、每日上限、7日座標冷卻、可用槽位與重氫；已找齊則記 `complete`，其餘依結果記錄或派遣。
- [ ] 不強制補滿所有可用遠征槽位，不要求離開時空槽剛好=1，不盲目呼叫 auto-fill-slots。
- [ ] 副任務仍須既有安全 typed 流程；死羊報告 2 小時內、(i)/(I)、Defense=0、Fleet=0；閒置死羊無固定出擊次數上限。
- [ ] 無法確認艦隊、成本或任務安全時停止該項；uncertain則全局停止。
- [ ] **本輪結束閘門**：搬運、遠征、死羊、生命探索四項 routine（`transport`、`expedition`、`farming`、`lifeform`）都已得到 `planned`、`not_due`、`no_surplus`、`blocked` 或 `complete` 狀態，才能進入 Phase 5；有主線動作不能取代這項檢查。
- [ ] 提交 `strategy_complete` 時四項 routine 缺一不可；提交 `execution_complete` 時四項都必須成為最終狀態，禁止仍留 `planned`。

---

### 💾 Phase 5：記憶寫回、固化與釋放（Persistence & Teardown）
- [ ] **5.1 記憶檔案刷新**：
  - 更新 `runtime/memory/GameState.md`（只留進行中 queue、在途艦隊、主線瓶頸、異常與 next wake；完整 live matrix 不重抄）。
  - 更新 `runtime/memory/TODO.md`（核心科技蓄水進度、里程碑）。
  - 更新 `runtime/memory/farm_targets.md`（出擊次數、戰報）。
- [ ] **5.2 巡邏極簡日誌插入**：
  - 在 `runtime/memory/patrol-log.md` 頂部插入最新單行紀錄（時間倒序，最新在最上方）。
  - 紀錄格式：`YYYY-MM-DD HH:MM CST | #N | 重點（無則 no-op） | 結果 | next HH:MM`。
  - 只寫 mutation、里程碑、異常或需主人介入事項；正常安全檢查縮成 `safe`。不得重抄資源／時產、各星 build status、完整中文摘要或 routine 明細。
- [ ] **5.3 persistence checkpoint 與稽核**：更新完成後提交 `persistence_complete`，再執行 `patrol-audit`；只有 `complete:true` 可正常提交。
- [ ] **5.4 🔒 強制 Git 提交與租約釋放（Mandatory Patrol Commit）**：
  - 在單實例租約保護下執行：
    ```bash
    python3 scripts/ogame_ctl.py finish-run --run-id <run_id> --commit --output json
    ```
  - Commit Message 規格：`Cronjob YY-MM-DD HH:mm [run: <run_id>]`。
  - 缺步時正常 commit 必須被拒絕、該輪標記 `incomplete`，但 lease 仍須釋放；已知 fail-closed 錯誤必須用 `--abort-reason <code>` 留下明確狀態。
