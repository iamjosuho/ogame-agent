# errors.md — 已知陷阱

## 瀏覽器/自動化層

1. **OGame 大廳 Play 用 window.open 彈窗**——合成 DOM click 可觸發，但需 profile 已允許 popup（已修：`lobby.ogame.gameforge.com` 允許彈窗）
2. **Chrome 未正常關閉會丟 session cookie**——巡邏結束務必讓瀏覽器正常退出；profile 已設 `restore_on_startup=1`、`exit_type=Normal`
3. **driver 綁定流程**：`cua_browser_state(pid, window_id)` 綁定 → 不帶 pid 再呼叫取 snapshot → mutation 後要重新 snapshot；每次重啟瀏覽器 pid/window_id 都會變
4. **遊戲是繁中介面**：按鈕名稱用中文（資源/設施/科技/造船廠），座標顯示如「母星 [1:1:1]」

## 遊戲層

（待巡邏中發現後補充）

## 環境層

5. **螢幕鎖定/顯示器不可用時整條瀏覽器路線失效**：Chrome 視窗擷取回 0x0、focus_app 回 `process_activated=false`、`cua_browser_prepare(existing_profile)` 因「consent sheet 無法出現」被拒（browser_wrong_target_refused）。重試多次無效。此時不要硬試——記異常、next_wake +60min，等解鎖螢幕後下一輪自然恢復。
6. **鎖屏時絕不能呼叫 cua_browser_prepare**：鎖屏下 prepare 會嘗試彈出 DevTools 授權對話框並堆積重複的「允許遠端偵測」彈窗。正確順序：先 capture 驗證畫面可用 → 若 0x0/空白＝鎖屏，**直接記錄異常並把 next_wake 推遲，完全跳過所有綁定與 prepare 呼叫**。只有 capture 正常才繼續綁定流程。
7. **watchdog idle 輸出必須是固定字串**：任何隨時間變動的內容（倒數分鐘等）都會讓 monitor 每分鐘判定「有變化」而誤喚醒 agent。idle 時輸出固定字串，只在 WAKE/idle 狀態切換時輸出變化。
8. **畫面已恢復可擷取但既有 profile 綁定仍不可用**：Chrome capture 正常、OGame 資源頁可見；`cua_browser_prepare(existing_profile)` 回 `browser_wrong_target_refused`，之後原生互動核准提示逾時。依 SOP 不重試、不進行遊戲操作；下輪再先做 capture，若仍需綁定且再次被拒，檢查 Cua/Chrome 控制核准狀態。
9. **`ogame_ctl.py sync` 的 AppleScript 系統服務連線失效**：在取得 OGame Overview 前，`osascript` 回報 `Connection invalid` 並以語法錯誤 `-2741` 終止。此輪沒有讀到即時頁面、也沒有遊戲動作。下輪僅先做一次 `sync`；若重現，停止後檢查 macOS Apple Events／Chrome 自動化服務狀態，勿反覆重試。
10. **heartbeat 首輪驗證的 `list-planets` 失敗**：Apple Events `Connection invalid`、`com.apple.hiservices-xpcservice`、AppleScript `-2741`。依 fail-closed 停止，未執行 `sync-all`、plan 或 mutation；修復 macOS Apple Events／Chrome 自動化服務。
11. **heartbeat 逐星 plan pin 驗證失敗**：本輪 `list-planets` 與 `sync-all` 成功，但部分星球 plan 回報「星球 pin 驗證失敗」。候選與佇列證據不完整，禁止決策與 mutation；不得重試同輪。
12. **heartbeat 前置記憶缺檔**：唯讀 sub-agent 讀到 `GameState.md`，但 `TODO.md` 不存在，依 fail-closed 未執行任何 OGame command；需補回策略檔後再驗證。
13. **heartbeat 絕對路徑前置讀取仍回報缺檔**：回報 `TODO.md`、`errors.md` 缺失，故未執行 list-planets／sync-all／plan；主工作區稍後檢查兩檔仍存在，疑似 sub-agent worktree 狀態不一致，需先釐清。
14. **重試已確認同一服務故障持續**：依更新後多星球 SOP 先執行 `list-planets`，仍在取得官方頁面前以相同 `Connection invalid`／`-2741` 中止。已達同一輪可安全重試上限；後續等待修復 macOS Apple Events／Chrome 自動化服務後再巡邏，勿在本次 session 再嘗試。
15. **新排程輪次仍持續同一服務故障**：唯讀 `list-planets` 在取得官方頁面前再現 `Connection Invalid error for service com.apple.hiservices-xpcservice`、`Connection invalid` 與 `-2741`。未取得登入或遊戲狀態，故不重試、不執行 ROI 或遊戲動作。
16. **已定位並驗證修復途徑**：故障源為受限 sandbox 無法連上 macOS GUI/Apple Events，非 Chrome Session、OGame 登入或控制腳本語法。以 macOS GUI 權限執行相同 `list-planets` 和 `sync --planet-id 10000001` 均成功；後續巡邏的所有 `ogame_ctl.py` 查詢與變更都必須在 GUI 權限下執行。
17. **經濟／科技頁的 detail 資料為 server-rendered，點科技列不會自然產生 fetch/XHR**：`supplies`、`facilities`、`research` 的 `#technologydetails_content` 初始為空，科技列本身只帶 `data-technology`、`data-status`、等級與按鈕狀態；合成點擊未觀察到 detail Query。若要逆向唯讀資料，先以 planet-pinned GET 取得完整 HTML；頁面正常另載入 chat/eventlist/ipimenu Query，但它們不是成本來源。不得因看不到 detail endpoint 而猜測 mutation URL。
18. **OGame 已支援四個官方 `externaldataexport` JSON endpoints，但不能只看 HTTP 200**：請求必須帶 `X-Requested-With: XMLHttpRequest`，否則可能以 HTTP 200 回傳純文字錯誤。固定使用 `export-probe`，只允許四個 GET action、不得自行拼 URL；`technologyQuantities` 不帶 `cp`，避免已知的作用中星球 Session side effect。`newAjaxToken` 必須在落盤前去敏。
19. **`accountInfo.allianceClassId` 可為 `null`，且 `sid$` 去敏規則會誤傷 `characterClassId` / `allianceClassId`**：class ID 在 stable schema 中必須是 nullable integer；session ID 去敏只匹配獨立 `sid` 或 `-sid` / `_sid`，不得以任意 `sid` 字尾判斷。官方快照仍須排除 `playerName` 與 `newAjaxToken`。
20. **新輪次 `list-planets` 再現 AppleScript `Connection Invalid`／`com.apple.hiservices-xpcservice`／`-2741`**：未取得即時星球清單，依規則停止並釋放本輪租約；不可重試或執行遊戲變更，待修復 macOS Apple Events／Chrome 自動化服務後再做一次唯讀檢查。
21. **本輪 `list-planets` 再現 Apple Events `Connection invalid`／`com.apple.hiservices-xpcservice`／`-2741`**：唯讀偵察 fail closed，未執行 `sync-all`、逐星 `plan` 或任何 mutation；待修復 macOS Apple Events／Chrome 自動化服務。
22. **本輪 `list-planets` 再現 Apple Events `Connection Invalid`／`com.apple.hiservices-xpcservice`／`-2741`**：唯讀偵察子任務 fail closed，未執行 `sync-all`、逐星 `plan` 或任何 mutation；待修復 macOS Apple Events／Chrome 自動化服務。
23. **Luna child 的 `list-planets` 參數契約不相容**：依 child 回報，該命令拒絕 `--run-id`／`--output json`，本輪只試一次即停止；未執行 `sync-all`、逐星 `plan` 或 mutation。
24. **plan --include-fleet 正常會先 yield session_id 且約 50–60 秒才完成**：必須持續對同一 session 使用 write_stdin；第一次 30 秒無輸出不是逾時，也不得重開或平行跑。已用多星嚴格序列實證成功。
25. **系統自動續跑喚醒後，Luna 的 `sync-all --source auto` 完成但無輸出**：多星 `list-planets` 成功；依 fail-closed 未執行逐星 plan、決策或 mutation，也未重試。下輪重新從 `check-wake` 與 Luna 唯讀開始。
26. **新版全局 `matrix --source auto --output json` 首次偵察失敗**：AppleScript／Google Chrome 回報索引錯誤 `-1719`，本輪未取得 fresh 全局矩陣；`scout-report.json` 為舊資料，不得用於決策。依 fail-closed 凍結決策、執行與所有 mutation。
27. **Planet-D 排產 25 座飛彈發射器回報 uncertain**：`action produce:be21da73b589dfb7: uncertain (production_target_not_queued_or_completed, resource_deduction_mismatch)`。依 fail-closed 全局停止當輪後續 mutation，未進行盲目重試，保存狀態並安全收尾。
28. **Planet-C 跨星輸血 fleet_send 按鈕停用 (off)**：`action fleet:794b24e3361bb6f2: uncertain (fleet_send_missing_or_disabled)`。根因：單大運裝載 25,000 滿額時加算飛行油料超載。解法：預留燃料空間或加派 1 艘大運（本輪 2 大運裝載 45k 資源已完美驗證通過！）。
29. **Planet-B 防禦盾 6→7 workflow 回報 uncertain**：`research:110 uncertain (no_target_level_or_queue_evidence, resource_deduction_mismatch)`——execution 顯示 success/mutation_submitted=true，但 pin 護盾仍 Lv6、資源分文未扣、research queue 閒置，屬「點擊未生效」乾淨狀態（⚠️事後證偽：次輪 live pin 顯示護盾已 Lv7，該輪實為證據延遲、最終落地！此「乾淨」判斷錯誤）。依 fail-closed 全局停止本輪後續 mutation，下輪以 fresh plan 重試即可。注意：plan 有效期僅 120 秒，intent 組裝與 workflow plan 必須緊接 fresh plan。
30. **`ogame_ctl.py` 以系統預設 python3 (3.9.6) 啟動即 `ModuleNotFoundError: tomllib`**：本輪 shell 的 `python3` 為 macOS 系統 3.9，不支援 tomllib；改用 `/opt/homebrew/bin/python3` (3.14) 後全指令正常。下輪若 `check-wake` 出現同樣 traceback，直接換 homebrew python 重試。
31. **科研 uncertain 伴隨「已扣資＋佇列證據延遲」新模式**：Planet-B 護盾 7→8 workflow 回報 `uncertain (no_target_level_or_queue_evidence, resource_deduction_mismatch)`，但 45 秒後 verify plan 顯示 M/C 已扣約成本，佇列仍閒、等級仍 7。研判為「提交成功＋證據延遲」而非乾淨未生效。下輪禁盲目重試：先以 fresh plan 查科研佇列是否 running／等級是否推進；若仍閒置＋等級不變才可重試，防 double-spend。
32. **active tab 漂移至 Lobby＋uncertain 證據延遲再現**：mutation 約 1 分鐘後的 plan 被守衛拒絕（`expected=None, observed=None, url=lobby...`），但遊戲分頁仍在；以 `lobby --enter` 點擊暢玩重返。另：workflow uncertain 配 immediate post-state「零扣資＋佇列閒」仍可能是證據延遲——教訓：uncertain 後禁當輪重試，一律 sleep≥60s 後 verify；verify 前若遇 lobby 守衛，先 lobby --enter 再 verify。
33. **workflow plan 被「即時佇列忙碌」乾淨拒絕**：Planet-F 建築佇列 busy 時 `workflow plan` 直接拒絕建單（`⛔ 即時佇列忙碌`），Commander 多槽位預約排程不經此路徑。教訓：佇列忙＝乾淨停止信號，不重試、不改走相容 CLI；滿倉星等下輪佇列空出再追加。
34. **plan 候選成本解析可信度需人工把關**：Planet-E plan 中金屬儲存器 3→4 顯示成本僅 M4、重氫儲存槽 1→2 僅 D2（costs_raw 無資源數字、estimated_duration 僅 10s），明顯為解析 artifact，真實成本應為數千。教訓：成本異常低廉（與同級儲存器 M8000/C4000 量級不符）時一律視為不可信，禁執行；以 costs_raw 有明確數字＋estimated_duration 合理者為準。
35. **uncertain→verify→落地案例＋verify-plan 成本為準**：Planet-E 晶體 15→16 workflow 回報 uncertain，90 秒後 verify plan 顯示精準扣資＋建築佇列 busy，證實落地。成本存疑時以 OGame 公式（晶體礦 48×1.6^n、金屬礦 60×1.5^n、重氫 225×1.5^n／75×1.5^n）交叉驗證，通過者可執行。
36. **Planet-C 跨星運輸至 Planet-G 回報 uncertain (target_mission_event_not_found)**：派艦成功後立即讀取 movement events，因 OGame 事件清單生成存在短暫延遲，即時核驗回報 uncertain。30 秒後以 `events` 重新查詢證實 8 大運已成功升空在途（Planet-C `[1:1:3]` -> Planet-G `[1:1:7]`，ETA 04:20:17 CST）。依 fail-closed 規範全局停止當輪後續 mutation，未重試，安全收尾等待物資抵港。
37. **Planet-G 晶體儲存器 5→6 提交後短暫出現 uncertain (no_target_level_or_queue_evidence, resource_deduction_mismatch)**：點擊提交成功但即時快照未見扣款與佇列變化。60 秒後執行 verify-plan 證實精準扣款且 building_queue active，排程落地建造中，證實為證據延遲。
38. **Planet-G 金屬儲存器 7→8 提交後短暫出現 uncertain (no_target_level_or_queue_evidence, resource_deduction_mismatch)**：點擊提交成功但即時快照因無緩衝未見扣款與佇列變化。60 秒後執行 verify-plan 證實精準扣款且 building_queue active，排程落地建造中，再次證實為 post_state 即時讀取缺乏延遲緩衝之證據延遲。
