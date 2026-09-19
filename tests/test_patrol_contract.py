from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PatrolContractTests(unittest.TestCase):
    def test_every_round_requires_all_routine_categories(self):
        skill = (ROOT / ".agent/skills/ogame-patrol/SKILL.md").read_text(encoding="utf-8")
        checklist = (ROOT / "CHECKLIST.md").read_text(encoding="utf-8")
        strategist = (
            ROOT / ".agent/skills/ogame-patrol/references/strategist.md"
        ).read_text(encoding="utf-8")
        cron_prompt = (
            ROOT / ".agent/skills/ogame-patrol/CRONJOB_PROMPT.md"
        ).read_text(encoding="utf-8")
        scout = (
            ROOT / ".agent/skills/ogame-patrol/references/scout.md"
        ).read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

        for category in ("transport", "expedition", "farming", "lifeform"):
            self.assertIn(category, strategist)
            self.assertIn(category, checklist)

        self.assertIn("每輪固定逐項盤點", skill)
        self.assertIn("只有四項例行盤點皆已留下狀態", skill)
        self.assertIn("主線動作不能取代這項檢查", checklist)
        self.assertIn("patrol-audit", skill)
        self.assertIn("execution_complete", cron_prompt)
        self.assertIn("不再啟動 Scout sub-agent", scout)
        self.assertIn("patrol-start --output json", cron_prompt)
        self.assertIn("patrol-audit", agents)
        self.assertIn("quick-spy", agents)

    def test_routine_audit_does_not_restore_forced_slot_filling(self):
        skill = (ROOT / ".agent/skills/ogame-patrol/SKILL.md").read_text(encoding="utf-8")
        checklist = (ROOT / "CHECKLIST.md").read_text(encoding="utf-8")
        executor = (
            ROOT / ".agent/skills/ogame-patrol/references/executor.md"
        ).read_text(encoding="utf-8")

        self.assertIn("副任務不再強制滿槽", skill)
        self.assertIn("不強制補滿所有可用遠征槽位", checklist)
        self.assertIn("不得例行呼叫 auto-fill-slots", executor)

    def test_markdown_memory_is_compact_and_nonduplicative(self):
        skill = (ROOT / ".agent/skills/ogame-patrol/SKILL.md").read_text(encoding="utf-8")
        checklist = (ROOT / "CHECKLIST.md").read_text(encoding="utf-8")
        scout = (
            ROOT / ".agent/skills/ogame-patrol/references/scout.md"
        ).read_text(encoding="utf-8")

        for text in (skill, checklist):
            self.assertIn("不得重抄", text)
        self.assertIn("完整 live matrix", checklist)
        self.assertIn("完整矩陣不貼入 prompt", skill)
        self.assertIn("fail-closed", scout)
        self.assertIn("四項 routine 的完整狀態已由", skill)


if __name__ == "__main__":
    unittest.main()
