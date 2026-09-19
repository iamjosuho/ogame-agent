# 06｜新殖民星公式化開荒

> 研究日期：2026-09-14（CST）  
> 目標：母星能持續輸血時，以最短安全時間把合格新星拉到成熟星最低經濟線，並讓建築 queue 與補給線儘量不空轉。

## 結論

不存在跨所有 universe 與帳號都成立的單一固定 build order。建築時間受 Robotics Factory、Nanite Factory 與 universe speed 影響；礦場能否立即開工又受 Energy、storage、星位／溫度、職業與 Lifeform bonus 影響。正確的「固定」內容應是可重算的演算法，而不是一張靜態順序表。

本專案採以下明確目標：

1. 預設追趕成熟星最低經濟線 `Metal 20 / Crystal 20 / Deuterium 17`；可由 CLI 參數調整。
2. 在外部資源可持續供應的前提下，枚舉 Robotics／Nanite 終點，最小化到達目標所需的剩餘建築工時；工時相同時選資源成本較低者。預設最多 Robotics 10／Nanite 1，可由 CLI 調整。
3. Robotics 投資完成後，三礦依邊際加權回本排序；任何 mine 會使 Energy 低於 `-20` 時先補 Solar Plant。
4. 單棟成本超過對應 storage 90% 前，先 Just-in-Time 升級 storage。
5. 每次只執行一個 fresh candidate；完工後依 live `end_epoch` 設 timer，加 5～10 秒緩衝再重讀，不沿用舊 plan。
6. transport 以未來 6 個動作的預算為 look-ahead，受新星 storage headroom、來源星保留、來源存量 50%、真實 cargo SSOT 與 Fleet Slot 護欄共同限制；ETA 不明即停止，pending 未解除前不重送。

## 為何不是照 Quick Start 表

Quick Start Guide 的順序包含「等待本星自行產資」這個瓶頸，適合新帳號從零開始。此處的前提是六顆成熟星持續輸血，所以資源等待被移除後，Robotics 的提前投資價值大幅上升；原表不再是同一個最佳化問題。

近期 colony 指南也把 Robotics 1→6 視為新星最先建立的加速鏈，但之後是繼續衝 Robotics／Nanite，還是先讓 mines 回本，仍取決於資源供應與目標礦等。本模組因此把「最短時間到 M20/C20/D17」明文化為預設目標；若主人要改成「最低額外資源」或更高成熟線，必須調整 policy，不把不同目標混稱為同一個最優解。

## 程式入口

只讀規劃：

```bash
python3 scripts/ogame_ctl.py colony-bootstrap \
  --planet-id <new_cp> --run-id <run_id> --mode plan --output json
```

同輪 timer＋補給＋建造：

```bash
python3 scripts/ogame_ctl.py colony-bootstrap \
  --planet-id <new_cp> --run-id <run_id> --mode run \
  --source-id <source_cp> --source-id <source_cp> \
  --source-reserve-metal <M> --source-reserve-crystal <C> \
  --source-reserve-deuterium <D> --confirm --output json
```

`run` 會再次確認 `fields.total >= 225`。它只透過既有 typed atom 進行 planet pin、prevalidation、mutation 與 postcondition；任何 `uncertain` 全局停止。

## 公式來源與校準

- OGame Forum 的建築總表記載核心 base cost、Solar／mine Energy 公式，以及 Robotics 建築時間公式：<https://board.en.ogame.gameforge.com/index.php?thread/78613-all-buildings-researches-fleets-and-defences/>
- 近期整理的 Robotics Factory 條目列出 2 倍成本曲線與 `1/(1+R)` 建築時間效果：<https://sidian.app/s/ogame-wiki/buildings/facilities/robotics-factory>
- 近期 colony 實務指南建議新星先串 Robotics 1→6，再依資源供應與星球定位決定後續加速設施：<https://ogames.net/blog/ogame-robotics-nanite-factory-guide>
- 舊 Quick Start Guide 提供「本星自行產資」條件下的最快起步表，只作對照，不直接套用到外部輸血情境：<https://ogame.fandom.com/wiki/Quick_Start_Guide>

執行時仍以 live UI 的成本、`energy_delta`、storage 與 `end_epoch` 為最終真值；公式只負責排序與 look-ahead。
