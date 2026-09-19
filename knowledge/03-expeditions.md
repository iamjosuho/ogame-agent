# 03｜Regular Expeditions（普通遠征）

> 研究日期：2026-08-25（CST）  
> 研究基準版本：**OGame 13.0.0 / 13.0.0-r14**；所有數字仍受 universe speed、Top-1 score、class、Lifeform tech、fleet slot 與版本修訂影響。
> 艦隊配置複核：2026-09-02（Gameforge 官方論壇 FAQ／攻略）。

## 1. 是什麼

Regular Expedition 是把 fleet 送到 Galaxy 的 **slot 16**，在未知空間停留後返航。需要 Astrophysics；同時可在外的 expedition 數量常見為 `floor(sqrt(Astrophysics level))`，Discoverer class 約多 2 slots，Admiral 再加 1。**精確 slots 需讀當前帳號 UI，因 item/officer/universe 設定可改。**

普通 Expedition 和 Lifeform Discovery 是不同任務：本檔只談需要艦船的普通 Expedition；後者見 [04-discoveries.md](04-discoveries.md)。

## 2. 可能結果

- 找到 Metal、Crystal 或 Deuterium
- 找到額外 ships（加入回程 fleet）
- 找到 Dark Matter
- Nothing/空手
- Pirate 或 Alien combat
- Black hole：fleet 全失的低頻高損結果
- 延遲或提前返航、Trader/其他訊息型結果（版本/設定可能不同）

資源/艦船/DM 讓 Expedition 有正期望值，但 combat、black hole 與 Deut fuel 是真實成本；不能把每次回收都當保證收入。

## 3. Reward cap 與 fleet composition

社群目前常用的 resource-find cap 由 universe 的 economy speed、當時全服 rank-1 points、Discoverer class、Pathfinder 及 Lifeform research 共同決定。常見基準表（非官方完整公式）是 Rank-1 general points 對 Metal cap 約：

| Rank-1 points | 單次基準 Metal cap |
|---:|---:|
| <10k | 40k |
| <100k | 500k |
| <1M | 1.2M |
| <5M | 1.8M |
| <25M | 2.4M |
| <50M | 3.0M |
| <75M | 3.6M |
| <100M | 4.2M |
| ≥100M | 5.0M |

社群計算器常見 multiplier：economy speed × Discoverer 約 1.5 ×（含 Pathfinder 約再乘 2）×相關 Lifeform research；**這不是官方承諾值，必須由當前 universe/實際報告校準。**

Fleet points 約按船的 Metal+Crystal value 計算；送太小的 fleet 可能壓低可得 reward cap，送太大的 fleet 則增加 fuel 與 combat exposure。

### 安全的資源型預設

- 以 **Large Cargos（LC）為主，搭 1 Espionage Probe**；按預期最大 find 調整 cargo capacity。若只是測試/低 cap，可用 Small Cargos。
- live class 為 **Discoverer** 且有備用艦時加入 **1 Pathfinder**，可提高 expedition loot；Pathfinder 本身有成本，低 cap/低活躍帳號不必盲目追求。
- 需要帶戰鬥艦時固定只帶 **1 艘可犧牲的最高適用艦**；多帶戰鬥艦不會線性提高收益，反而增加 fuel、fleet points 與 Pirates/Aliens 損失。早期小帳先以 1 Light Fighter 試跑，等有專用備用高階艦再換級。
- 不要為了「滿 cap」造超出能載回的艦隊；把 cargo hold 對準 `universe speed × class × Pathfinder × Lifeform` 的可能上限。

### 社群常見高回報預設（不是保證）

`1 Destroyer + 1 Espionage Probe + 足量 Large Cargos` 常被攻略用於提高可發現艦種並滿足 resource cap；它不是 encounter safety 保證。實際是否值得取決於 combat tech、fuel 價格與帳號承受能力，新手不應在沒有備用 Destroyer、simulation／戰報資料時直接照抄。

## 4. Combat risk

官方/ Wiki 社群資料常見 encounter 機率約 Pirates 5.6%、Aliens 2.6%，且各 encounter 有 large/extra-large 變體；**這些是歷史公開值，不保證 13.0.0 所有 universe 不變。** Pirates tech 通常相對玩家低、Aliens 相對高；combat 會留下約 10% destroyed fleet debris，需 Pathfinder 回收。不要把上述百分比當作精準自動化機率。

代理遇到 encounter 時應：

1. 先用當前 Weapons/Shield/Armour 與送出 fleet 做 simulator；
2. 將 fleet 風險上限設定為「black hole 可承受、combat 不影響殖民計畫」；
3. 不把唯一的 colony ship、主戰 fleet、全部 LC 或不可替代的 Deut fleet 一起放進 Expedition；
4. 在戰報中記錄結果，按數百次任務估計自己的實際 EV，而非只信第三方表格。

## 5. Class 與 current meta

- **Discoverer**：若玩家能高頻操作/每天持續派出大量 Expedition，通常是最高 Expedition income 的 class；多 slots、find bonus、Phalanx/expedition synergy 使其適合「expo economy」。
- **Collector**：若主要收入是礦，Expedition 只作額外收入；配 Rock'tal 的 production/crawler/energy buildings 通常比硬轉純 expo 更穩。
- **General**：偏 fleet/raiding；Expedition 可做，但要把 fleet exposure 與燃料納入 ROI。
- Kaelesh 的 expedition research（如 `Enhanced Sensor Technology`、`Sixth Sense`、`Telekinetic Tractor Beam`、`Gravitation Sensors`）很強，但 Artefacts 讓其他 species 也能選到相關 tech；因此 current meta 常把「species building 選 Rock'tal/Human」與「tech slot 取 Kaelesh expo tech」混合，而非自動全選 Kaelesh。

## 6. 給自動代理的派遣演算法

1. 讀取 universe economy speed、rank-1 points、Astrophysics slots、class、Lifeform tech、fleet/Deut reserve。
2. 設定 reserve：至少留 colony ship/研究所需 Deut 與一個可安全 fleetsave 的退路。
3. 以 UI 顯示的 flight/fuel cost 計算單次成本；任何 `expected resource + ship value + DM value - fuel - expected loss` 為負的組合不派。
4. 在一個 cycle 內使用低風險 LC+Probe（必要時 Pathfinder），不要把 cargo load 到超過可運輸上限。
5. 將每次 report 寫入資料集，按 50/100 次窗口估計 reward distribution；遇到版本/宇宙設定變更重新校準。
6. 每趟完成後立即 fleet-save 資源與 ships，不因「普通遠征很賺」而省略回避攻擊。

## 待確認

- 13.0.0-r14 各 universe 的實際 encounter odds、resource/ship cap 與 slot formula。
- 「1 Pathfinder exactly doubles cap」在所有新 universe、所有 bonus 疊加順序是否仍成立。
- Pirates/Aliens 百分比與 combat debris 10% 是否有 server-specific override。

## 來源

- [Official Gameforge – OGame Expeditions](https://gameforge.com/en-GB/games/ogame-expeditions.html)
- [Sidian OGame Wiki – Expeditions guide](https://sidian.app/s/ogame-wiki/guides/expeditions)
- [OGame Wiki – Expedition](https://ogame.fandom.com/wiki/Expedition)
- [OGame Forum – Expeditions: best fleet to send?](https://board.en.ogame.gameforge.com/index.php?thread/821576-expeditions-best-fleet-to-send/)
- [OGame Forum – Guide 10: Expedition guide](https://board.en.ogame.gameforge.com/index.php?thread/810634-guide-10-expedition-guide/)
- [OGame Forum – Expedition study](https://board.en.ogame.gameforge.com/index.php?thread/815144-expeditions-a-study-from-the-french-community/)
- [Official OGame Forum – Lifeforms FAQ](https://forum.origin.ogame.gameforge.com/forum/thread/153-lifeforms-faq/)
- [Official OGame Forum – Version 13.0.0](https://board.en.ogame.gameforge.com/index.php?thread/857539-version-13-0-0/)
