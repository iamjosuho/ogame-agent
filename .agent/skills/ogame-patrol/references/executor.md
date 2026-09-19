# Python Executor 極簡執行契約

本文件由 Coordinator 參考；**不得注入 Executor sub-agent，亦不得啟動 Executor LLM**。
完整 confirmed plan 僅供 Python 使用，禁止讀入模型 context 或另存為
`plan-<planet>-<tech>.json`。

## 固定安全規則

- 所有 mutation 都要有本輪 `run_id` 與明示 `--confirm`。
- Python 必須以 fresh plan 唯一比對語意目標；0 筆或多筆皆 `blocked`。
- planet pin → prevalidation → execution → postcondition 不得省略。
- 任一 `uncertain` 立即停止整輪；不得重試、改星球或改走另一條 mutation 路徑。
- 不把 selector、URL、成本、完整 candidates、packages 或 workflow evidence 傳給 LLM。

## 建築／研究／生命形式／監視

Coordinator 只提供精確名稱、目標等級與 component：

```bash
python3 scripts/ogame_ctl.py execute-decision \
  --planet-id <cp> --run-id <run_id> \
  --target-name '<exact name>' --target-level <level> \
  --component <supplies|facilities|research|lfbuildings|lfresearch> \
  [--include-lifeforms] [--kind watch] [--confirm]
```

`apply` 必須帶 `--confirm`；`watch` 不帶。完整 plan 與 workflow JSON 由 wrapper
內部 capture，stdout 只允許 compact result。

## 生產

```bash
python3 scripts/ogame_ctl.py execute-decision \
  --planet-id <cp> --run-id <run_id> \
  --target-name '<exact name>' --component <shipyard|defenses> \
  --include-production --amount <N> --confirm
```

## 艦隊類操作

遠征、運輸、偵察、收割與生命探索使用既有 `ogame_ctl.py` 封裝子指令，維持
預設 human/compact 輸出。禁止加 `--output json` 後把完整輸出交給模型。攻擊仍僅
允許 fresh report 證實 `(i)/(I)`、Defense=0、Fleet=0 的目標。

遠征接力使用 `expedition-agent`：它以 case-insensitive exact match 解析唯一
`agent` preset，先核對 account-wide movement 與 live Expedition Slot，只補空缺，
並在來源 system 與正負一 system 間平衡。回傳 `deferred` 時沿用其精確 next wake；
不得另猜時間或重播 preset 點擊。

主線動作完成後，繼續處理 `strategic-decision.json` 中 `routine` 判定為 `planned` 的搬運、遠征、死羊與生命探索；不得把「主線已做」當成本輪結束條件。所有動作結束後核對必要搬運/避難的運力、燃料與空槽。取消強制補滿空槽：不得例行呼叫 auto-fill-slots。只有已確認具備餘裕且既有typed操作能遵守本輪資源/運力保留時，才按個別意圖執行副收入任務；至少保留1個Fleet Slot，必要時更多。

## 回傳

Coordinator 只保留 `status`、`plan_id`、`workflow_id`、`action_id`、`reason`、
`global_stop`、`evidence_ref`，且 stdout 硬上限為 2 KiB。完整執行證據留在 workflow journal；只有異常調查才依 path 定向讀取。
