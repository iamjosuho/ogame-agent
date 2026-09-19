# 01｜Economy：資源、礦、能源與 Crawlers

> 研究日期：2026-08-25（CST）  
> 研究基準版本：**OGame 13.0.0（近期 live 修訂版 13.0.0-r14；各 universe 參數可能不同）**

## 1. 資源與每小時產量

OGame 的基本資源是 **Metal、Crystal、Deuterium、Energy**；Energy 不是庫存貨幣，而是生產設備的供需平衡。以下是標準公式的基線寫法；最後還要乘上 universe 的 economy speed 與所有適用的 planet/account/class/Lifeform bonus：

- **Metal Mine L**：`30 × L × 1.1^L` Metal/小時
- **Crystal Mine L**：`20 × L × 1.1^L` Crystal/小時
- **Deuterium Synthesizer L**：`10 × L × 1.1^L × (-0.002 × T + 1.28)` Deuterium/小時；`T` 為星球平均溫度。
- Deuterium 公式在 redesigned/new universe 有另一個社群觀察版本 `10 × L × 1.1^L × (-0.004 × T + 1.36)`；**待確認**，代理應以遊戲 Resource settings 顯示的產量校準。
- 初始固定收入與生產倍率、Metal/Crystal/Deut 的 planet position bonus、Plasma Technology、Geologist/Collector 等會疊加在基線上，不能只用上式預測 UI 最終值。

**自動化規則**：每次升級後讀取實際「per hour」值，記錄增量與成本；不要假設所有新 universe 是 1x。

## 2. Mine 升級成本與經濟性

標準下一級成本（`L` 是要升到的等級）大致為：

- Metal Mine：`Metal = floor(60 × 1.5^(L-1))`；`Crystal = floor(15 × 1.5^(L-1))`
- Crystal Mine：`Metal = floor(48 × 1.6^(L-1))`；`Crystal = floor(24 × 1.6^(L-1))`
- Deuterium Synthesizer：常見基線 `Metal = 225 × 1.5^(L-1)`、`Crystal = 75 × 1.5^(L-1)`；不同版本/計算器顯示的四捨五入需以 UI 為準。

經濟決策用 **payback/ROI**：

`回本時間 = 升級總成本（先用當前交易比換算成同一資源單位） ÷ 每小時新增產量`

注意：

- Crystal 的成本倍率 1.6，高於 Metal/Deut 常見的 1.5，故在通用回本期模型中 Crystal 不宜無腦超前；早期常態採 `Metal > Crystal > Deut`。
- **【科技衝刺期戰略例外（Crystal Supremacy）】**：當帝國進入衝刺高階天體物理學（Astrophysics）、超空間技術或核心科研時，全帝國晶體消耗量常為金屬的 2 倍以上；此時各星戰略方針強制採取「水晶超前準則（$\text{Crystal} \ge \text{Metal} + 1 \sim 2$）」，優先拉高晶體時產以化解科技點火瓶頸，不受通用 ROI 滯後限制。
- 不能只看「最便宜」：若下一個里程碑缺 Crystal/Deut，應按瓶頸資源的影子價格排序。
- 早期可接受短暫負 Energy：若該 mine 的增產價值高於能源缺口造成的損失，就先升礦再補 Solar；但不可長時間讓整個星球低效率運轉。
- 送出或被掠走前，把資源投入建築/研究或 transport/fleetsave；倉庫中可被搶的閒置資源本身沒有 ROI。

## 3. Energy balance

主要來源：Solar Plant、Fusion Reactor、Solar Satellites；主要消耗：Metal/Crystal/Deut mines、Fusion Reactor 的 Deuterium、Crawlers 及部分 Lifeform buildings。

- 常見 Solar Plant energy 基線為 `20 × L × 1.1^L`；Fusion Reactor 基線為 `30 × L × (1.05 + 0.01 × Energy Technology)^L`，實際值請以當前版本 UI/計算器校驗。
- Solar Satellites 的輸出受 planet 平均溫度影響；溫暖星球衛星產能高，但 Deut bonus 較差，寒冷星球反之。不要用固定「每顆衛星」數字跨 universe 推算。
- 若總 Energy 不足，礦的 production efficiency 會按不足比例下降；先維持小幅正值，避免在代理忙碌/離線期間突然跌到低效率。
- Fusion 用 Deuterium 換 Energy，應在 Deut 供應穩定、需要節省 fields 或不想暴露大量 satellites 時使用；新手通常先 Solar Plant，避免把 Deut 同時耗在 fusion、research、fleet。
- Energy Technology 會改善 Fusion 輸出；是否值得升級要以實際新增 energy 與建設成本回本期決定。

## 4. Crawler 系統

Crawler 是 Shipyard 造出的採礦無人機，成本常見為 **2,000 Metal + 2,000 Crystal + 1,000 Deuterium**；每個 active Crawler 提高 Metal、Crystal、Deuterium 的產量，並消耗 Energy。

- 社群/ Wiki 的標準 bonus：每個 Crawler 對各礦約 **+0.02%**（`0.0002`）的 production；它不是固定每小時資源。
- 常見 active cap：`8 × (Metal Mine level + Crystal Mine level + Deut Synthesizer level)`。
- Collector class 常見為 cap ×1.5、並提高 Crawler 效果；**Crawler 的 Collector 能源消耗在不同資料源/版本說法不一致（50 或加倍），待確認**，應以當前 Resource settings 顯示的每顆 Energy 消耗為準。
- cap 以上的 Crawler 通常仍佔艦隊/資源，卻不增加生產；代理必須只建到 active cap，除非有明確版本例外。
- Crawlers、Solar Satellites 都提高被摧毀時的潛在損失；不要在低礦等級或沒有安全 fleetsave/防護時提早堆滿。

**ROI 判定**：

`Crawler 回本時間 ≈ (crawler 成本 + 為其補足 Energy 的成本) ÷ (總產量 × 每 crawler bonus)`

以當前交易率、Energy 來源、Collector multiplier、mine cap 與被摧毀風險計算。低等礦時先升礦通常比造 Crawlers 好；高等礦且 Energy/防護已解決時才逐步啟用。

## 5. 給遊戲代理的操作規則

1. 每次建造前記錄 `production/hour、energy surplus、storage fill time、upgrade cost、增產量`。
2. 若 Energy deficit，先判斷升礦是否仍帶來正淨產量；否則立即補 Solar/Fusion/Satellites。
3. 以 bottleneck resource 與回本期排序，不使用固定的永久礦比。
4. Crawler 永不超過當前 active cap；若類別/版本改變 cap 或 energy，重新讀 UI。
5. 保存至少一份當前 universe 設定快照，讓後續計算可追溯。

## 待確認

- 新/重製 universe 的 Deuterium 溫度公式與小數/四捨五入。
- Version 13.0.0-r14 在每個 universe 對 Crawler active cap、Collector energy multiplier 的實際顯示。
- Planet position、Plasma、Lifeform 等 bonus 的疊加順序；執行時以遊戲產量欄位作黑盒校準。

## 來源

- [OGame Wiki – Formulas](https://ogame.fandom.com/wiki/Formulas)
- [OGame Wiki – Crawler](https://ogame.fandom.com/wiki/Crawler)
- [Sidian OGame Wiki – Metal Mine](https://sidian.app/s/ogame-wiki/buildings/resources/metal-mine)
- [Sidian OGame Wiki – Crawler](https://sidian.app/s/ogame-wiki/ships/civil/crawler)
- [OGame Forum – The Ultimate Miner Guide](https://board.en.ogame.gameforge.com/index.php?thread%2F808518-the-ultimate-miner-guide%2F=)
- [Official OGame Forum – Version 13.0.0](https://board.en.ogame.gameforge.com/index.php?thread/857539-version-13-0-0/)
