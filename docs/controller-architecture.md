# OGame Controller 分層架構

`scripts/ogame_ctl.py` 是唯一相容 CLI 入口；新實作集中在 `scripts/ogame/`。這個邊界保留既有 `plan`、`watch`、`apply`、`sync-all` 等呼叫方式，同時讓 Skill 不再產生 browser payload。

## 分層

| 層 | 模組 | 責任 |
|---|---|---|
| Safety policy | `policy.py` | frozen、不可由 TOML/CLI/Skill 覆寫的硬護欄；包含 `MIN_SAFE_ENERGY=-20`、90% 倉庫限制與至少保留 1 個 Fleet Slot |
| Strategy policy | `scripts/ogame/config/strategy.toml` | 版本化 schema；嚴格驗證，未知/缺漏/無效欄位一律 fail closed |
| Typed contracts | `models.py` | `Intent`、immutable `WorkflowPlan`、`WorkflowStep`、typed `ActionResult` |
| Pure planning | `planning.py` | 0/1 可行包與政策合併；不接觸瀏覽器、不評 ROI |
| Operation policy | `operations.py` | 建立並驗證 Python confirmed fleet candidates，以及驗證 upgrade／production／Lifeform／cancel；不接受 Skill payload |
| Private browser primitives | `browser.py` | 私有 AppleScript/Chrome 傳輸；可注入 runner 以做離線測試 |
| Public domain atoms | `atoms.py` | mutation 固定執行 planet pin → prevalidation → execute → postcondition |
| Workflow runtime | `workflow.py` | 唯讀平行、mutation 序列、journal、resume 與 uncertain 全局停止 |

政策優先序固定為：`SafetyPolicy > 即時狀態 > confirmed plan > StrategyPolicy > Skill Intent`。

## Typed Intent 與 CLI

Skill 只寫入 schema v1 JSON object，例如：

```json
{
  "schema_version": 1,
  "kind": "apply",
  "planet_id": "12345678",
  "confirmed_plan_id": "plan-token",
  "action_ids": ["supplies:1"],
  "source": "ogame-patrol"
}
```

允許欄位只有 `schema_version`、`kind`、`planet_id`、`confirmed_plan_id`、`action_ids`、`source`；selector、URL、tech ID、成本與程式碼都會被拒絕。

```sh
python3 scripts/ogame_ctl.py workflow plan \
  --intent-file runtime/memory/workflow-intent.json \
  --run-id RUN_ID --output json

python3 scripts/ogame_ctl.py workflow run \
  --workflow-id WORKFLOW_ID \
  --run-id RUN_ID --confirm --output json

python3 scripts/ogame_ctl.py workflow status \
  --workflow-id WORKFLOW_ID --output json
```

預設輸出是精簡 human-readable；Skill 一律指定 `--output json`。舊 `plan` / `watch` / `apply` 仍保留相容介面，但 patrol Skill 的變更路徑只走 typed workflow。

## Journal 與停止語意

- Active journal 位於 `runtime/memory/workflows/active/`；只有 `completed` 才移入 `archive/`。
- `ActionResult.status` 只有 `applied`、`blocked`、`skipped`、`uncertain`。
- browser mutation 邊界之後若無法建立可信 postcondition，回傳 `uncertain`，整個 workflow 立即 fail closed。
- 跨 process mutation lock 位於所有 `command_apply` 共用入口；workflow 已持鎖時只傳內部旗標避免巢狀鎖，相容 wrapper 不能繞過序列化。
- Stateful step 執行前會先 durable 記錄 `in_flight_step_id` 並把 certainty 設為 uncertain；因此 process 在 mutation 邊界死亡時不能盲目續跑。
- 中斷後只有 `state_certainty=certain`、沒有 `in_flight_step_id` 且沒有 uncertain 結果，才可換新 lease；confirmed plan ID、snapshot hash 與 planet binding 都必須仍相符。
- `WorkflowPlan` 序列化後以 deterministic hash 保護，不接受 journal 內 plan 被修改。

## 相容與演進邊界

- 沒有導入 `uv`；仍使用 Python 標準函式庫與 `unittest`。
- Typed Intent schema v1 仍只有 apply/watch/read 與 opaque `action_id`；Python confirmed candidate 可描述 upgrade、production、Lifeform、精確 queue cancellation，以及 transport/deploy/colonize/spy/raid。
- `plan --include-lifeforms`、`--include-production`、`--include-cancel`、`--include-fleet` 會產生對應候選。Fleet candidates 只接受 bounded live reads 與本機明確證據；Skill 不得自行補座標、船種或 payload，也不得直接呼叫相容 mutation CLI。
- 相容 `produce`、`lifeform-build`、`cancel-building` 與 fleet 命令會先建立 fresh confirmed plan，再走相同 public atom。planet pin、成本／容量／能量／Fleet Slot 重驗及 postcondition 任一不足，結果就是 `blocked` 或 `uncertain`。
- 歷史 compatibility mutation 函式內不可達的 direct-JS bodies 已移除；新 domain logic 優先落在 `scripts/ogame/`，`scripts/ogame_ctl.py` 只保留讀取 adapter、CLI parser 與薄 wrapper。
