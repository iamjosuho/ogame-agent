---
name: ogame-expedition-agent
description: 使用主人維護的 agent fleet preset，安全補滿 OGame 遠征空槽、分散相鄰太陽系，並依最早返航時間續跑。適用於實際派遣或規劃遠征接力；不適用於 Lifeform discovery。
---

# OGame Expedition Agent

只透過 `scripts/ogame_ctl.py expedition-agent` 執行；不得重播錄影座標、直接點 Galaxy preset，或在 Skill 內組 DOM selector。

## 契約

- 第一步執行 `python3 scripts/ogame_ctl.py patrol-start --output json`。`skipped`／`aborted` 立即停止。
- `ready` 後親自審查 movement；完成 `safety_reviewed` checkpoint 前不得派艦。
- preset 名稱為 `agent`，使用去除前後空白後的 case-insensitive exact match。不存在、正規化後重名或內容無法解析時 fail-closed。
- preset 內容由主人維護並視為該編成的明確授權，不固定 50 大運＋探路者；每次 plan 與 apply 都重新驗證完整編成。
- 所有手動與 Agent 的 mission 15 都計入 live Expedition Slot。movement 必須以穩定 `fleet_id` 去重 outbound／return，並與 live slot 使用量相符。
- 只補空缺；永遠保留至少 1 個普通 Fleet Slot及至少 2 艘 preset 主運輸艦。非運輸艦數量以主人維護的 preset 為授權；路線計算後 send control 未確認可用（含燃料不足）時禁止提交。
- 目標只在來源 system `S`、`S-1`、`S+1` 間選擇；依現有負載選最少者，平手時用持久化 cursor 跨輪 round-robin。三系統外的手動遠征只占 slot，不影響配比。
- 每次派遣序列化，間隔 5–10 秒，且必須通過完整 fleet composition deduction 與 mission-15 event postcondition。不確定結果不得重試。

## 執行

安全審查完成後執行：

```bash
python3 scripts/ogame_ctl.py expedition-agent \
  --planet-id <來源星 cp> \
  --run-id <patrol run_id> \
  --preset agent \
  --max-wait-seconds 900 \
  --confirm \
  --output json
```

- `deferred`：已把最早確認的返航時間加 5–10 秒寫入 `runtime/memory/next_wake.txt`。本 Skill 不建立、更新或啟用 automation；外部 heartbeat 未啟用時，只回報下一次應喚醒時間。
- 最早返航在 15 分鐘內：同一 session 以不超過 30 秒的分段 Timer 續租，返航後 fresh-read movement 再補位。
- `blocked`／`uncertain` 或任何 anomaly：停止，不沿用舊計畫、不猜返航時間。

## 收尾

- Patrol 的 transport、expedition、farming、lifeform 四類仍須逐一評估並寫入 strategy／execution checkpoint；其他類別沒有動作時使用真實的 `not_due`、`no_surplus` 或 `blocked`，不得略過。
- 更新精簡 handoff 與 next wake，完成 `persistence_complete`、`patrol-audit`，最後以同一 `run_id` 執行 `finish-run` 釋放 lease。
