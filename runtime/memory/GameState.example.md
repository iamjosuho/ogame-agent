# GameState — OGame Example Universe

> 用途：只保存下一輪需要承接的關鍵狀態。完整 live matrix 以 `scout-report.json` 為準；歷史結果見 `patrol-log.md`，此檔不重抄逐星數據或畫面報告。

## 最新交接

- 最後確認：2026-01-01 00:00 CST (run_id: `example-run-id`)。
- 安全：0 敵襲、0 驗證碼、0 封號警告；Session 正常；movement DOM 驗證通過 (`threat_status=none`, 0 events，艦隊全數在港)。
- 戰略狀態與隊列（2026-01-01 00:00 CST）：
  - 科研隊列：天體物理學 10（Astrophysics 10）全星系實驗室聯網研發中。
  - 星球狀態（Planet-A `[1:1:1]`）：重氫合成器 15 竣工落地，維持 M20/C18/D15 運轉，電力正常（+50 ⚡）。
  - 建築隊列：Planet-B 晶體礦 16 施工中；其餘星建築空閒。
  - 供電狀態：各星電力皆充沛達標（均在 -20⚡ 護欄內）。
  - 帝國總產能：金屬時產維持在 **+100.0k/h**，晶體 +50.0k/h，重氫時產維持在 **+20.0k/h**。
  - 物流與艦隊：在途艦隊全數在港，嚴格保留常規防守與 Fleet Slots。

## 耐久設定

- 玩家／宇宙：ExamplePlayer／Example Universe（s1-en）。
- 星球：Planet-A `[1:1:1]` cp `10000001`；Planet-B `[1:1:2]` cp `10000002`；Planet-C `[1:1:3]` cp `10000003`（共 3 星）。
- 策略唯一入口：`runtime/memory/TODO.md`。
- 船艦貨艙唯一來源：`scripts/ogame/config/constants.toml`；不得使用預設容量。
- Commander 已啟用；仍須由 live queue evidence 驗證可排程狀態。

## 資料分工

- `scout-report.json`：完整、最新、機器可讀的 resources／rates／storage／energy／levels／ships／defenses／queues／alarms。
- `strategic-decision.json`＋patrol contract：當輪決策、四項 routine 狀態與完成證據。
- workflow journal：mutation plan、postcondition 與完整執行證據。
- `patrol-log.md`：最近 20 輪的單行重點索引。

## 固定護欄

- 禁課金、禁代回訊息、禁攻擊活人或有 Defense／Fleet 的目標。
- mutation 序列化並逐項驗證；任一 `uncertain` 全局停止。
- 永遠保留至少 1 個 Fleet Slot；建築／研究花費不得超過對應倉容 90%。
- 電力容許下限 `-20`；所有即時數值與安全訊號都必須 fresh-read。
