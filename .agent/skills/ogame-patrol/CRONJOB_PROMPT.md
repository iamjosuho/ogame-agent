# OGame 巡邏 Cronjob Prompt

排程 agent 醒來後，在讀取任何記憶、Skill 或啟動子代理之前，**第一步只執行**：

```bash
python3 scripts/ogame_ctl.py patrol-start --output json
```

入口內先執行 `check-wake --acquire`。`too_early`／`overlap` 靜默結束，不連線 OGame、不讀 memory、不啟動子代理。所有非 `ready` 狀態都停止；`aborted` 表示入口已標記 exact abort reason 並釋放 lease，`release_failed` 表示 lease 釋放未確認，須立即回報主人處理。只有 `status=ready` 時才保存 `run_id`，按精簡 JSON 的 evidence 路徑讀所需資料。入口已依序提交 `memory_loaded`、`scout_complete`；不得重做初始採集，也不得啟動 Scout sub-agent。

先審查 `movement-events.json`。`threat_status=hostile` 時啟動戒嚴並處理 Fleetsave；`unknown` 時禁止常規 mutation，直到事件方向安全審查釐清。`scout-report.json` 的 `alarms: []` 不代表零敵襲。主協調官親自提交 `safety_reviewed`，再依 `CHECKLIST.md`、`AGENTS.md` 和 `ogame-patrol/SKILL.md` 做策略與安全執行。`GameState.md` 由主協調官在後段按真實結果更新。

每輪逐項盤點 transport、expedition、farming、lifeform，依序提交 `strategy_complete`、`execution_complete`、`persistence_complete`；execution 不得留 `planned`。最後執行 `patrol-audit`，只有 `complete:true` 才以 `finish-run --run-id <run_id> --commit --output json` 正常收尾。已知 fail-closed 錯誤用 `finish-run --run-id <run_id> --abort-reason <exact_reason_code> --output json` 釋放 lease。

此檔是 repo 內的排程提示詞範本；更新它不會啟用或修改目前暫停的 Codex automation。
