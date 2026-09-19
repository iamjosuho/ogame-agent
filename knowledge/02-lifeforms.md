# 02｜Lifeforms（生命形態）

> 研究日期：2026-08-25（CST）  
> 研究基準版本：**OGame 13.0.0（近期 live 修訂版 13.0.0-r14；Lifeforms 原始內容屬 v9，不是 v8）**

## 1. 系統概念

Lifeforms 是 v9 加入的平行成長系統。四個 species：

- **Humans**：起始 species；均衡、研究/探索導向。帳號開局通常先由 Humans 解鎖 `Intergalactic Envoys`，但找到其他 species 後並非只有 Humans 能持有這項科技。
- **Rock'tal**：偏 Collector/miner；大量生產、Energy、Crawler/防禦相關 synergy。
- **Mechas**：偏 General/fleet；艦船、燃料、造船/戰鬥相關。
- **Kaelesh**：偏 Discoverer/探索；Expedition、DM、艦船發現、殖民地/衛星相關。

每顆 planet 一次選一個 active species；不同 planet 可以不同 species。species 名稱本身不是直接 bonus，真正效果來自 buildings、research 與 Lifeform level。

## 2. Population、Food、Buildings

- 每 species 有 population housing/production、food production/storage，以及升到 Tier 2/Tier 3 的建築。
- Population 用來解鎖 Lifeform buildings/research slot；Food 必須足以餵養 population。食物耗盡會造成 population 減少，進而讓門檻型科技失效。
- Lifeform buildings 一般使用 Metal/Crystal/Deuterium，位於獨立的 Lifeform building queue，不佔普通 planet fields；部分建築仍要 Energy。
- Lifeform buildings 的效果只作用於「建造它的 planet」。Lifeform research 的 bonus 雖然在各 planet 各自升級，效果會跨 empire 疊加（但只有該 species active/符合條件時生效）。
- 一顆 planet 有 18 個 Lifeform tech slots，分 Tier 1/2/3；需要先完成前一 Tier 的 slots 才能進下一 Tier。典型 population gate：T1 slots 約 200k、300k、400k、500k、750k、1M；T2 約 1.2M、3M、5M、7M、9M、11M；T3 約 13M、26M、56M、112M、224M、448M。**門檻受版本/特定 Psionic Modulator 等效果影響，UI 為準。**
- 解鎖 slot 不等於科技已升到 level 1；解鎖後仍要選擇並研究技術。原生 species tech 通常一定出現，其他已發現 species 的 tech 可能隨機出現。

## 3. 如何解鎖其他 species

1. 保持 Human（或已擁有可用科技的 species），累積足夠 population。
2. 在 Human tech tree 解鎖第一個 slot，把 `Intergalactic Envoys` 研究到 **level 1 即停**；更高等級不提高發現 species／Artefacts 的機率。
3. 從 Galaxy view 的紫色 DNA/探索入口發出 Lifeform Discovery missions；找到 Rock'tal、Mecha、Kaelesh 後，才可把它們的 buildings/species 放到 planet 或在 tech selection 中看到其科技。
4. 發現 species 不需要把該 species 永遠放在某顆 planet；但要留意切換會取消/中斷相關 queue/flight，並需重建 population。

## 4. Artefacts 與隨機 tech tree

Artefacts 由 Discovery missions 找到，可直接購買指定 species 的 tech slot，降低 RNG：

- Tier 1 slot：200 Artefacts
- Tier 2 slot：400 Artefacts
- Tier 3 slot：600 Artefacts
- 儲存上限通常是 3,600；若一次掉落超過剩餘容量，可短暫超過，但達上限後後續 mission 不再給 Artefacts，直到花掉。

Reset tech tree 後重新選指定組合仍要付 Artefacts；不要為了小幅理論改善頻繁 reset。

## 5. 切換與 v13 風險

- 同一 planet 切換 species 有約 **48 小時 cooldown**；切換時建造中的 Lifeform queue 可能取消並返還資源，人口/食物狀態會重置或需要重建；既有 building/research level 是否保留、哪些 flight 被中斷，應以當前 UI 警告為準。
- 官方 v13 rollout 曾特別警告：若帳號在更新時處於停用 Lifeforms 或 reset Technology Tree 的隱藏/儲存 configuration 狀態，該 stored configuration 可能被永久刪除。自動代理在 reset/switch 前後必須讀回 tech tree，且避免在版本更新窗口操作。

## 6. 新帳號何時投入？

**保守的通用答案：早開、慢投資。** Human 的最低人口/food/Research Centre 可在核心礦與第一殖民地穩定後建立；不要在 Day 0 把稀缺 Deut/Crystal 大量轉進高等 Lifeform buildings。

- **Collector/miner**：官方 FAQ 的社群建議是先把幾個 colonies 建起來，約在 Astro 9 左右才重投資 Lifeforms；實際門檻由 economy speed 決定。優先 Rock'tal，利用 planet-local production buildings，再以 Artefacts 選有用的跨 empire production tech。
- **高頻率 Discoverer（約 100+ regular Expeditions/day 的社群經驗值）**：可以更早投入，因為 Expedition 收入能支付 Lifeform costs；Human 早期解 `Intergalactic Envoys`，之後依 Artefacts/planet specialization 調整。
- **低頻率 Discoverer 或不確定玩法**：先 Human，逐步解鎖其他 species；不要僅因 Kaelesh 名義上是 explorer 就全盤切換，Artefacts 使跨 species tech 可被購買，而 buildings 才是難以替代的差異。
- **代理預設**：在第一 colony 前，Lifeforms 只做不會拖慢 Astro/colony 的最低建設；第一 colony 後，維持 food surplus，解 T1 slot，再依 class/expedition 活躍度決定 Rock'tal/Human/Mecha。

## 7. 給代理的安全檢查

- 每次升人口先確認 `food production > consumption` 且 storage 能覆蓋離線時間。
- 只在解鎖下一個有明確 ROI 的 slot 時升住宅；population 不是可運輸貨幣，也不是普通遊戲的必要資源。
- 切換 species 前記錄所有 planet 的 tech/building levels、active flight、food/population；切換後逐項驗證。
- Artefacts 接近 3,600 時優先花在明確 build plan，避免因 cap 停止累積。

## 待確認

- 13.0.0-r14 是否改動任何 Lifeform cost/queue/cooldown、Population gate 或 species bonus；官方 changelog 多為 backend/bugfix，執行時應重新讀 UI。
- 各 universe 的 Lifeforms 開關、exploration daily credit 是否一致。
- 社群「100+ expos/day」「Astro 9」是經驗法則，不是官方硬門檻。

## 來源

- [Official OGame Origin – Lifeforms FAQ](https://forum.origin.ogame.gameforge.com/forum/thread/153-lifeforms-faq/)
- [Official OGame Forum – Lifeforms Information](https://board.en.ogame.gameforge.com/index.php?thread%2F834308-lifeforms-information%2F=)
- [Official OGame Forum – Lifeforms expansion](https://board.en.ogame.gameforge.com/index.php?thread/831881-ogame-new-expansion-lifeforms/)
- [Official OGame US – Artefacts Update](https://board.us.ogame.gameforge.com/index.php?thread%2F104048-ogame-artefacts-update%2F)
- [OGame Wiki – Lifeform](https://ogame.fandom.com/wiki/Lifeform)
- [Sidian OGame Wiki – Lifeforms overview（2026-05-25 更新）](https://sidian.app/s/ogame-wiki/lifeforms/overview)
- [Official OGame Forum – Version 13.0.0](https://board.en.ogame.gameforge.com/index.php?thread/857539-version-13-0-0/)
