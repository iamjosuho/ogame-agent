---
name: script-evolution
description: "OGame 腳本自主維護與進化 SOP：維護 scripts/ogame 分層與 ogame_ctl.py 相容入口、封裝 DOM 查詢與遊戲操作、避免觸發權限彈窗的完整指引. Activate whenever adding new game actions, modifying CLI commands, or refactoring automation logic."
---

# OGame 腳本自主進化規範

## 1. 核心鐵律（🚨 零彈窗）

| 禁止 | 原因 | 替代 |
| :--- | :--- | :--- |
| `python3 -c "..."` 或行內動態代碼 | 觸發 IDE 安全沙盒強制人工審批彈窗 | 磁碟上的 `.py` 腳本：`python3 scripts/ogame_ctl.py <cmd>` |
| Skill 傳遞 DOM selector / URL / tech ID / 成本 | 耦合實作細節，破壞分層 | 只傳 `Intent`；Python 建立 immutable `WorkflowPlan` |

`scripts/ogame_ctl.py` 是唯一 CLI 入口（薄 adapter）；新實作集中於 `scripts/ogame/`。  
browser / Apple Events 細節僅限 private primitive；mutation atom 必須完成 planet pin → 前置驗證 → 執行 → postcondition，回傳 typed `ActionResult`（`applied/blocked/skipped/uncertain`）。

---

## 2. 四步進化流程

### 步驟 1：定義 typed contract 與安全 atom
- 先定義 atom 四狀態條件，再實作 private JS 提取 / 操作器。
- DOM 查詢必須防空指針（`?.` / `querySelector` 判空），回傳結構化 JSON：
  ```javascript
  (function() {
      var el = document.querySelector(".target");
      if (!el) return JSON.stringify({ success: false, reason: "Element not found" });
      return JSON.stringify({ success: true, data: ... });
  })()
  ```

### 步驟 2：擴充 `scripts/ogame/` 並接上 wrapper
```python
# ogame_ctl.py 薄 wrapper
def cmd_<feature>(args):
    adapters = build_private_adapters(args)
    return public_<feature>_atom(args.intent, adapters)

# subparser 註冊
p = subparsers.add_parser("<cmd>", help="說明")
p.add_argument("--option", type=int, default=1)
# dispatch
elif args.command == "<cmd>": cmd_<feature>(args)
```
更新 `ogame_ctl.py` 開頭 docstring 支援清單。純 policy/models/planning 不得 import browser；domain atom 透過注入 callback 使用 private primitive。

### 步驟 3：即時回歸驗證
- `python3 -B -m unittest discover -s tests -p 'test_*.py'`（注入 browser fake，禁止連線）。
- live 驗證需明確授權 + 有效 lease；mutation 還需 planet pin + confirmed plan + `--confirm`。

### 步驟 4：更新記憶與規則索引
若新指令涉及巡邏或戰略，同步更新：`AGENTS.md`、`.agent/skills/ogame-patrol/SKILL.md`、`runtime/memory/GameState.md`

---

## 3. 常用頁面 URL / Component 參考

| 功能區塊 | Component | Tech ID 範圍 |
| :--- | :--- | :--- |
| 帝國總覽 | `page=standalone&component=empire` | 全星資源、建築/科技/艦船/防禦等級；用 `empire_url()` 入口 |
| 概況 | `page=ingame&component=overview` | 基礎資源、座標 |
| 資源礦山 | `page=ingame&component=supplies` | 1金屬, 2水晶, 3重氫, 4太陽能, 22-24儲存槽 |
| 設施 | `page=ingame&component=facilities` | 14機器人, 15奈米, 21造船廠, 31實驗室 |
| 科技研究 | `page=ingame&component=research` | 113能源, 108電腦, 106間諜, 117脈衝, 124天體物理 |
| 造船廠 | `page=ingame&component=shipyard` | 202小運, 203大運, 210間諜機, 212太陽衛星 |
| 防禦 | `page=ingame&component=defenses` | 401導彈, 402輕雷射, 404重高斯, 407小護盾 |
| 艦隊派遣 | `page=ingame&component=fleetdispatch` | 派遣與任務設定 |
| 銀河系 | `page=ingame&component=galaxy&galaxy=X&system=Y` | 死羊掃描 |
| 動態事件 | `#eventboxContent` / `#eventHeader` | 飛行艦隊倒數與來襲預警 |

---

## 4. 錯誤處理要點

- **防空指針**：JS 內加 `|| 0` / `|| ""` 默認值。
- **Base64 傳遞**：AppleScript 執行 JS 前用 `base64.b64encode` 編碼，防跳脫。
- **大廳自動過渡**：`execute_in_game_tab` 已內建「馬上暢玩！」，直接給 `target_url` 即可。
