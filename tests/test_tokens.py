import json
import os
import sqlite3
import tempfile
import unittest

from scripts.ogame.tokens import (
    DEFAULT_MEMORY_DIR,
    HEALTH_STEP_THRESHOLD,
    HEALTH_TOKEN_THRESHOLD,
    extract_token_stats,
    find_conversation_db,
    is_test_run,
    record_tokens,
)


def _make_meta_blob(prompt=100, candidates=10, cached=1000):
    def enc_varint(fn, val):
        b = bytearray()
        hdr = (fn << 3) | 0
        b.append(hdr)
        while val >= 0x80:
            b.append((val & 0x7F) | 0x80)
            val >>= 7
        b.append(val & 0x7F)
        return b

    nested = enc_varint(2, prompt) + enc_varint(3, candidates) + enc_varint(5, cached)
    subf = bytearray([(4 << 3) | 2, len(nested)]) + nested
    f = bytearray([(1 << 3) | 2, len(subf)]) + subf
    return bytes(f)


class TokenTelemetryTests(unittest.TestCase):
    def test_find_conversation_db_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertIsNone(find_conversation_db("non-existent-uuid", conv_dir=tmpdir))

    def test_is_test_run_detection(self):
        # Default memory dir with test prefixes -> True
        self.assertTrue(is_test_run("run-abc", DEFAULT_MEMORY_DIR))
        self.assertTrue(is_test_run("run-crash", DEFAULT_MEMORY_DIR))
        self.assertTrue(is_test_run("run-test-123", DEFAULT_MEMORY_DIR))
        # Custom temp memory dir -> False (allowed to test)
        self.assertFalse(is_test_run("run-abc", "/tmp/custom_memory"))
        # Non-test run_id in default dir without test env -> False
        self.assertFalse(is_test_run("real_patrol_token", DEFAULT_MEMORY_DIR))

    def test_record_tokens_blocked_for_test_in_production(self):
        # Calling with test run_id and default memory dir should be blocked
        res = record_tokens(run_id="run-abc")
        self.assertFalse(res["recorded"])
        self.assertEqual(res["reason"], "test_environment_detected_skipped")

    def test_record_tokens_creates_md_and_baseline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conv_dir = os.path.join(tmpdir, "conversations")
            mem_dir = os.path.join(tmpdir, "memory")
            os.makedirs(conv_dir)
            os.makedirs(mem_dir)

            conv_id = "11111111-2222-3333-4444-555555555555"
            db_path = os.path.join(conv_dir, f"{conv_id}.db")

            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE gen_metadata (idx integer, data blob, size integer NOT NULL DEFAULT 0, PRIMARY KEY (idx))")
            conn.commit()
            conn.close()

            res = record_tokens(conv_id=conv_id, run_id="run-test", memory_dir=mem_dir, conv_dir=conv_dir)
            self.assertTrue(res["recorded"])
            self.assertEqual(res["run_id"], "run-test")
            self.assertEqual(res["delta"]["total"], 0)
            self.assertTrue(res["is_new_conv"])

            md_path = os.path.join(mem_dir, "token-usage.md")
            baseline_path = os.path.join(mem_dir, ".token_baseline.json")
            self.assertTrue(os.path.exists(md_path))
            self.assertTrue(os.path.exists(baseline_path))

            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("# Token Usage Log", content)
            self.assertIn("`run-test`", content)
            self.assertIn("[新對話首輪]", content)

    def test_multi_conversation_isolation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conv_dir = os.path.join(tmpdir, "conversations")
            mem_dir = os.path.join(tmpdir, "memory")
            os.makedirs(conv_dir)
            os.makedirs(mem_dir)

            conv1 = "11111111-1111-1111-1111-111111111111"
            conv2 = "22222222-2222-2222-2222-222222222222"
            db1 = os.path.join(conv_dir, f"{conv1}.db")
            db2 = os.path.join(conv_dir, f"{conv2}.db")

            # Setup DB 1: 1 step (prompt 100, out 10, cached 1000 = total 1110)
            conn1 = sqlite3.connect(db1)
            conn1.execute("CREATE TABLE gen_metadata (idx integer, data blob, size integer NOT NULL DEFAULT 0, PRIMARY KEY (idx))")
            conn1.execute("INSERT INTO gen_metadata VALUES (?, ?, ?)", (0, _make_meta_blob(100, 10, 1000), 0))
            conn1.commit()
            conn1.close()

            # Setup DB 2: 1 step (prompt 500, out 50, cached 5000 = total 5550)
            conn2 = sqlite3.connect(db2)
            conn2.execute("CREATE TABLE gen_metadata (idx integer, data blob, size integer NOT NULL DEFAULT 0, PRIMARY KEY (idx))")
            conn2.execute("INSERT INTO gen_metadata VALUES (?, ?, ?)", (0, _make_meta_blob(500, 50, 5000), 0))
            conn2.commit()
            conn2.close()

            # 1. First record for conv1 (new conversation policy: full count as delta)
            res1 = record_tokens(conv_id=conv1, run_id="run-1", memory_dir=mem_dir, conv_dir=conv_dir)
            self.assertTrue(res1["is_new_conv"])
            self.assertEqual(res1["delta"]["total"], 1110)
            self.assertEqual(res1["cumulative"]["total"], 1110)

            # 2. First record for conv2 (should not subtract conv1's baseline!)
            res2 = record_tokens(conv_id=conv2, run_id="run-2", memory_dir=mem_dir, conv_dir=conv_dir)
            self.assertTrue(res2["is_new_conv"])
            self.assertEqual(res2["delta"]["total"], 5550)
            self.assertEqual(res2["cumulative"]["total"], 5550)

            # 3. Add second step to conv1 (prompt 200, out 20, cached 2000 = +2220)
            conn1 = sqlite3.connect(db1)
            conn1.execute("INSERT INTO gen_metadata VALUES (?, ?, ?)", (1, _make_meta_blob(200, 20, 2000), 0))
            conn1.commit()
            conn1.close()

            # 4. Second record for conv1 (should subtract conv1's prev, completely ignoring conv2's 5550!)
            res3 = record_tokens(conv_id=conv1, run_id="run-3", memory_dir=mem_dir, conv_dir=conv_dir)
            self.assertFalse(res3["is_new_conv"])
            # conv1 total is now 1110 + 2220 = 3330. Delta must be exactly 2220!
            self.assertEqual(res3["cumulative"]["total"], 3330)
            self.assertEqual(res3["delta"]["total"], 2220)
            self.assertEqual(res3["delta"]["prompt"], 200)
            self.assertEqual(res3["delta"]["cached"], 2000)

            # Verify baseline json structure
            baseline_path = os.path.join(mem_dir, ".token_baseline.json")
            with open(baseline_path, "r", encoding="utf-8") as f:
                baseline_data = json.load(f)
            self.assertIn("conversations", baseline_data)
            self.assertIn(conv1, baseline_data["conversations"])
            self.assertIn(conv2, baseline_data["conversations"])
            self.assertEqual(baseline_data["conversations"][conv1]["total_tokens"], 3330)
            self.assertEqual(baseline_data["conversations"][conv2]["total_tokens"], 5550)

    def test_legacy_baseline_backward_compatibility(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conv_dir = os.path.join(tmpdir, "conversations")
            mem_dir = os.path.join(tmpdir, "memory")
            os.makedirs(conv_dir)
            os.makedirs(mem_dir)

            conv_id = "33333333-3333-3333-3333-333333333333"
            db_path = os.path.join(conv_dir, f"{conv_id}.db")

            # Write legacy flat baseline file
            legacy_baseline = {
                "conv_id": conv_id,
                "last_updated": "2026-09-14 12:00",
                "total_prompt": 100,
                "total_cached": 1000,
                "total_candidates": 10,
                "total_tokens": 1110,
                "step_count": 1,
            }
            baseline_path = os.path.join(mem_dir, ".token_baseline.json")
            with open(baseline_path, "w", encoding="utf-8") as f:
                json.dump(legacy_baseline, f)

            # Create DB with 2 steps (1110 + 2220 = 3330)
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE gen_metadata (idx integer, data blob, size integer NOT NULL DEFAULT 0, PRIMARY KEY (idx))")
            conn.execute("INSERT INTO gen_metadata VALUES (?, ?, ?)", (0, _make_meta_blob(100, 10, 1000), 0))
            conn.execute("INSERT INTO gen_metadata VALUES (?, ?, ?)", (1, _make_meta_blob(200, 20, 2000), 0))
            conn.commit()
            conn.close()

            # Record tokens - should migrate smoothly
            res = record_tokens(conv_id=conv_id, run_id="run-migrated", memory_dir=mem_dir, conv_dir=conv_dir)
            self.assertTrue(res["recorded"])
            self.assertFalse(res["is_new_conv"])
            self.assertEqual(res["delta"]["total"], 2220)

            # Check migrated baseline structure
            with open(baseline_path, "r", encoding="utf-8") as f:
                new_baseline = json.load(f)
            self.assertIn("conversations", new_baseline)
            self.assertIn(conv_id, new_baseline["conversations"])

    def test_session_health_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conv_dir = os.path.join(tmpdir, "conversations")
            mem_dir = os.path.join(tmpdir, "memory")
            os.makedirs(conv_dir)
            os.makedirs(mem_dir)

            conv_id = "44444444-4444-4444-4444-444444444444"
            db_path = os.path.join(conv_dir, f"{conv_id}.db")

            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE gen_metadata (idx integer, data blob, size integer NOT NULL DEFAULT 0, PRIMARY KEY (idx))")
            # Insert 500 rows to trigger step threshold
            blob = _make_meta_blob(10, 1, 10)
            for i in range(501):
                conn.execute("INSERT INTO gen_metadata VALUES (?, ?, ?)", (i, blob, 0))
            conn.commit()
            conn.close()

            res = record_tokens(conv_id=conv_id, run_id="run-heavy", memory_dir=mem_dir, conv_dir=conv_dir)
            self.assertTrue(res["recorded"])
            self.assertIn("health_warning", res)
            self.assertIn("Session 上下文膨脹警告", res["health_warning"])


if __name__ == "__main__":
    unittest.main()
