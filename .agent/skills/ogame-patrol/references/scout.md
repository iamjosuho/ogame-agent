# 舊 Scout 參照（已停用）

排程巡邏不再啟動 Scout sub-agent。喚醒後只執行 `python3 scripts/ogame_ctl.py patrol-start --output json`；該入口負責 lease、固定資料來源、官方 movement 與 Empire matrix 的唯讀採集、coverage 驗證及精簡交接。詳見 `../SKILL.md`、`../CRONJOB_PROMPT.md`。

movement DOM 的待完成契約寫在 `scripts/ogame/browser.py` 的 `read_global_movement_evidence` 與 `scripts/ogame/patrol_start.py` 的 `_validate_movement` 註解中。未驗證頁面結構前，入口會 fail-closed，不把空事件列當成零敵襲。
