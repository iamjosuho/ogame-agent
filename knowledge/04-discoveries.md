# 04｜Lifeform Discoveries（生命形態探索）

> 研究日期：2026-08-25（CST）  
> 研究基準版本：**OGame 13.0.0 / 13.0.0-r14**。
> 解鎖規則複核：2026-09-02（Lifeforms FAQ 於 2026-08-29 同步）。

## 1. 不是取代普通 Expedition

OGame 有兩個容易混淆的探索系統：

| 系統 | 艦隊 | 主要產出 | 位置/入口 |
|---|---|---|---|
| Regular Expedition | 需要送 ships | 資源、ships、DM、事件/戰鬥 | Galaxy slot 16 |
| Lifeform Discovery/Exploration | 不需要送 ships，但占用 fleet slot；需有可用 slot | 新 species、Lifeform XP、Artefacts | Galaxy view 的紫色 DNA 探索入口 |

因此 Discoveries 是 Lifeforms 的輔助/前置 progression，**不是取代 regular Expeditions**。兩者的統計與 report 類別也應分開記錄。

## 2. 解鎖與 mission 成本

- Human 起始；先在 Human tech tree 解鎖第一個 slot，把 `Intergalactic Envoys` 研究到 **level 1 即停**。更高等級不提高發現 species／Artefacts 的機率。
- 從 Galaxy view 選可探索座標；通常每次探索消耗 **5,000 Metal + 1,000 Crystal + 500 Deuterium**。
- 不需要派出任何 ship，但通常需要一個 free fleet slot；若帳號沒有可用 fleet slot，任務不能啟動。
- 若當前 planet 的 Lifeform residence 沒有可容納的 population，或已達人口上限，可能無法發起探索。
- 同一座標通常 **7 天內不可再次探索**；Galaxy view 的灰色 icon 代表冷卻。這是座標級 cooldown，不是帳號全域只能探索一次。

## 3. Daily credit 與產出

Artefacts update 引入每日 50 次的 discovery credit；未用額度會累積，不是 use-it-or-lose-it。這與「每天能否派 50 次」的 UI wording、舊 universe 的補發規則可能不同，代理應讀當前 counter。

探索可能得到：

1. 尚未發現的 Rock'tal、Mecha、Kaelesh；
2. 已知 species 的 Lifeform XP；
3. Artefacts；
4. 在部分版本/任務訊息中的探索結果變體。

探索一般不會讓 regular Expedition fleet 遭遇 Pirates/Aliens；它是另一種低船舶風險、固定資源費用的 progression mission，但大量派遣仍會消耗 fleet slots 與 Deut。

## 4. Artefacts 策略

Artefacts 可把原本隨機的 tech selection 變成指定購買：

- T1：200 Artefacts
- T2：400 Artefacts
- T3：600 Artefacts
- Storage cap：3,600；一次大掉落可短暫超過 cap，但達 cap 後後續不再獲得，直到花掉。

**給代理的 spend policy：**

- 前期不要把 Artefacts 花在無法改善當前 plan 的 tech；先保存到要跨 species 取關鍵 production/expedition/class tech 的 slot。
- 接近 3,600 時，先買既定 build plan 的 slot，避免繼續探索卻沒有 Artefact 收益。
- Reset tech tree 會重新產生選擇成本；只為大幅改變長期方向 reset，並在 v13 rollout/bugfix 期間避免 reset。

## 5. Lifeform XP 與物種解鎖優先級

探索新的或已知的 species 會給 XP；Artefacts update 把 XP curve 調整得較平滑，Lifeform level 上限通常為 **100**，上限 bonus 約 **+10%**。到 cap 後探索仍可為 Artefacts/highscore，但不再給 XP。**Sidian/官方舊公告的數值需以當前版本 UI 驗證。**

新帳號建議：

- 先完成第一個 Human T1 slot 與 `Intergalactic Envoys 1`。
- 有穩定 Deut（且不會拖延 Astro/colony）後，再固定派 discovery missions；每日 50 credit 不必一次耗完。
- 先找齊其他 species，再依 class/建築選擇 active species；不要因第一個隨機 tech 就鎖死整個 account。
- Explorer/Discoverer 型帳號可更早且每天派；純 miner 先在第一批 colony 與 food pipeline 穩定後派。

## 6. 自動化資料模型

每趟 Discovery 記錄：`source planet、target coordinate、sent/return time、cost、daily credit before/after、coordinate cooldown、species result、XP、Artefact delta、population/food 狀態`。

在派遣前檢查：

- 是否存在 free fleet slot；
- target coordinate 是否在 7-day cooldown；
- residence 是否有空間；
- Deut 是否會影響下一個 Astro/colonization；
- Artefact storage 是否接近 cap；
- 當前版本/Universe 是否已開 Lifeforms。

## 待確認

- Version 13.0.0-r14 的 exact daily-credit 累積上限、無 ship 但 fleet slot 的 UI 行為。
- 50/day 是否在所有新 universe 以相同速率恢復，以及舊帳號補發 missions 的 migration 規則。
- 不同 species、Lifeform level 對探索時間的精確公式；`Intergalactic Envoys > 1` 不提高發現結果機率。

## 來源

- [Official OGame US – Artefacts Update](https://board.us.ogame.gameforge.com/index.php?thread%2F104048-ogame-artefacts-update%2F)
- [Official OGame Forum – Lifeforms Information](https://board.en.ogame.gameforge.com/index.php?thread%2F834308-lifeforms-information%2F=)
- [Official OGame Origin – Lifeform guide](https://forum.origin.ogame.gameforge.com/forum/thread/64-lifeform)
- [Official OGame Origin – Lifeforms FAQ](https://forum.origin.ogame.gameforge.com/forum/thread/153-lifeforms-faq/)
- [Official OGame Forum – Lifeforms FAQs（2026-08-29 synced copy）](https://board.en.ogame.gameforge.com/index.php?thread/858187-lifeforms-faqs/)
- [Sidian OGame Wiki – Lifeforms overview](https://sidian.app/s/ogame-wiki/lifeforms/overview)
- [OGame Infinity community tool note（discoveries statistics separated from expeditions）](https://forum.origin.ogame.gameforge.com/forum/thread/104-ogame-infinity/)
- [Official OGame Forum – Version 13.0.0](https://board.en.ogame.gameforge.com/index.php?thread/857539-version-13-0-0/)
