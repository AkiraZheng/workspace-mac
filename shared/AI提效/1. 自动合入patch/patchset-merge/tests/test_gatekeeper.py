"""Tests for gatekeeper.py — state machine gatekeeper (v2: +in_progress, +current_state, +restore)."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import gatekeeper as gk


class TestFindTask(unittest.TestCase):
    def test_found_in_merge_order(self):
        data = {"merge_order": [{"task_id": "0001", "status": "pending"}]}
        task = gk.find_task(data, "0001")
        self.assertIsNotNone(task)
        self.assertEqual(task["status"], "pending")

    def test_found_in_deps_order(self):
        data = {"deps_order": [{"task_id": "dep-001"}], "merge_order": []}
        task = gk.find_task(data, "dep-001")
        self.assertIsNotNone(task)

    def test_not_found(self):
        data = {"merge_order": []}
        task = gk.find_task(data, "9999")
        self.assertIsNone(task)


class TestStateLog(unittest.TestCase):
    def test_ensure_creates_state_log(self):
        task = {}
        state_log = gk.ensure_state_log(task)
        self.assertEqual(task["state_log"], [])
        self.assertIs(state_log, task["state_log"])

    def test_ensure_keeps_existing(self):
        task = {"state_log": [{"step": "BUILD"}]}
        state_log = gk.ensure_state_log(task)
        self.assertEqual(len(state_log), 1)

    def test_has_step_passed_true(self):
        log = [{"step": "BUILD", "result": "pass"}]
        self.assertTrue(gk.has_step_passed(log, "BUILD"))

    def test_has_step_passed_false(self):
        log = [{"step": "BUILD", "result": "fail"}]
        self.assertFalse(gk.has_step_passed(log, "BUILD"))

    def test_has_step_passed_missing(self):
        log = []
        self.assertFalse(gk.has_step_passed(log, "BUILD"))

    def test_has_step_passed_in_progress_not_pass(self):
        log = [{"step": "BUILD", "result": "in_progress"}]
        self.assertFalse(gk.has_step_passed(log, "BUILD"))


class TestCheckPrerequisites(unittest.TestCase):
    def test_build_has_no_prereq(self):
        task = {"build_checkpoint": True}
        self.assertTrue(gk.check_prerequisites(task, [], "BUILD"))

    def test_commit_needs_build_pass(self):
        task = {"build_checkpoint": True}
        log = [{"step": "BUILD", "result": "pass"}]
        self.assertTrue(gk.check_prerequisites(task, log, "COMMIT"))

    def test_commit_fails_without_build(self):
        task = {"build_checkpoint": True}
        self.assertFalse(gk.check_prerequisites(task, [], "COMMIT"))

    def test_commit_no_build_needed_when_checkpoint_false(self):
        """关键修复：build_checkpoint=false 不需要 BUILD 前置"""
        task = {"build_checkpoint": False}
        self.assertTrue(gk.check_prerequisites(task, [], "COMMIT"))

    def test_done_needs_both(self):
        task = {"build_checkpoint": True}
        log = [
            {"step": "BUILD", "result": "pass"},
            {"step": "COMMIT", "result": "pass"},
        ]
        self.assertTrue(gk.check_prerequisites(task, log, "DONE"))


class TestRecordStep(unittest.TestCase):
    def test_records_step(self):
        task = {"state_log": [], "execution_log": []}
        gk.record_step(task, "BUILD", "pass", {"error_count": 0})
        self.assertEqual(len(task["state_log"]), 1)
        self.assertEqual(task["state_log"][0]["step"], "BUILD")
        self.assertEqual(task["state_log"][0]["result"], "pass")
        self.assertEqual(task["state_log"][0]["error_count"], 0)
        self.assertIn("time", task["state_log"][0])
        self.assertEqual(len(task["execution_log"]), 1)

    def test_records_in_progress(self):
        task = {"state_log": [], "execution_log": []}
        gk.record_step(task, "BUILD", "in_progress", None)
        self.assertEqual(len(task["state_log"]), 1)
        self.assertEqual(task["state_log"][0]["step"], "BUILD")
        self.assertEqual(task["state_log"][0]["result"], "in_progress")
        self.assertEqual(len(task["execution_log"]), 1)


class TestCurrentState(unittest.TestCase):
    def test_update_creates_new(self):
        data = {}
        gk.update_current_state(data, "0003", "PHASE_2_MERGE", "BUILD", "in_progress")
        self.assertEqual(data["current_state"]["phase"], "PHASE_2_MERGE")
        self.assertEqual(data["current_state"]["task_id"], "0003")
        self.assertEqual(data["current_state"]["step"], "BUILD")
        self.assertEqual(data["current_state"]["status"], "in_progress")
        self.assertIn("last_update", data["current_state"])

    def test_update_overwrites(self):
        data = {"current_state": {"phase": "OLD", "task_id": "0001",
                                   "step": "BUILD", "status": "pass"}}
        gk.update_current_state(data, "0005", "PHASE_2_MERGE", "COMMIT", "in_progress")
        self.assertEqual(data["current_state"]["task_id"], "0005")
        self.assertEqual(data["current_state"]["step"], "COMMIT")


class TestWorkflowHints(unittest.TestCase):
    def test_ensure_injects_missing(self):
        data = {}
        gk.ensure_workflow_hints(data)
        self.assertIn("workflow_hints", data)
        self.assertIn("BUILD_FIX", data["workflow_hints"])
        self.assertIn("COMMIT_ORDER", data["workflow_hints"])
        self.assertIn("REVERT_POLICY", data["workflow_hints"])
        self.assertIn("BUILD_REQUIREMENT", data["workflow_hints"])

    def test_ensure_preserves_existing(self):
        data = {"workflow_hints": {"custom": "override"}}
        gk.ensure_workflow_hints(data)
        self.assertEqual(data["workflow_hints"]["custom"], "override")


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        self.tmp_path = self.tmp.name
        data = {
            "merge_order": [
                {"task_id": "0001", "status": "pending", "execution_log": []},
            ]
        }
        json.dump(data, self.tmp)
        self.tmp.close()

    def tearDown(self):
        if os.path.exists(self.tmp_path):
            os.unlink(self.tmp_path)

    def _run_check(self, task_id, step):
        data = gk.load_merges_file(self.tmp_path)
        task = gk.find_task(data, task_id)
        if task is None:
            return False
        state_log = gk.ensure_state_log(task)
        return gk.check_prerequisites(task, state_log, step)

    def _run_full_record(self, task_id, step, result, **extra):
        """Full record including current_state + workflow_hints (like main())"""
        data = gk.load_merges_file(self.tmp_path)
        gk.ensure_workflow_hints(data)
        task = gk.find_task(data, task_id)
        gk.record_step(task, step, result, extra or None)

        if result == "pass":
            status_map = {"BUILD": "built", "COMMIT": "committed",
                          "REVIEW": "reviewed", "DONE": "done"}
            task["status"] = status_map.get(step, result)
        elif result == "in_progress":
            task["status"] = "in_progress"

        gk.update_current_state(data, task_id, "PHASE_2_MERGE", step, result)
        gk.save_merges_file(self.tmp_path, data)

    def _assert_restore(self, expected_exit, expected_task_id=None):
        """Simulate --restore call. Returns current_state or None."""
        data = gk.load_merges_file(self.tmp_path)
        gk.ensure_workflow_hints(data)
        current = data.get("current_state")
        if expected_exit == 0:
            self.assertIsNone(current)
        elif expected_exit == 10:
            self.assertIsNotNone(current)
            if expected_task_id:
                self.assertEqual(current["task_id"], expected_task_id)

    def test_build_then_commit_flow(self):
        self.assertFalse(self._run_check("0001", "COMMIT"))
        self._run_full_record("0001", "BUILD", "pass", error_count=0,
                              product="arch/arm64/boot/Image")
        self.assertTrue(self._run_check("0001", "COMMIT"))
        self._run_full_record("0001", "COMMIT", "pass", commit="abc123")
        self.assertTrue(self._run_check("0001", "DONE"))

        data2 = gk.load_merges_file(self.tmp_path)
        task2 = gk.find_task(data2, "0001")
        self.assertEqual(task2["status"], "committed")
        self.assertEqual(len(task2["state_log"]), 2)

    def test_build_fail_blocks_commit(self):
        self._run_full_record("0001", "BUILD", "fail", error_count=5)
        self.assertFalse(self._run_check("0001", "COMMIT"))

    def test_recommit_without_build_blocks(self):
        self.assertFalse(self._run_check("0001", "COMMIT"))

    def test_in_progress_state_persisted(self):
        self._run_full_record("0001", "BUILD", "in_progress")
        data = gk.load_merges_file(self.tmp_path)
        self.assertEqual(data["current_state"]["task_id"], "0001")
        self.assertEqual(data["current_state"]["step"], "BUILD")
        self.assertEqual(data["current_state"]["status"], "in_progress")

    def test_context_compression_recovery(self):
        """模拟上下文压缩后恢复：通过 current_state 知道上次在哪"""
        # BUILD in_progress
        self._run_full_record("0001", "BUILD", "in_progress")

        # 继续 BUILD → pass
        self._run_full_record("0001", "BUILD", "pass", error_count=0,
                              product="arch/arm64/boot/Image")

        # COMMIT in_progress → 到这里上下文压缩
        self._run_full_record("0001", "COMMIT", "in_progress")

        # 恢复：读 current_state
        data = gk.load_merges_file(self.tmp_path)
        current = data["current_state"]
        self.assertEqual(current["task_id"], "0001")
        self.assertEqual(current["step"], "COMMIT")
        self.assertEqual(current["status"], "in_progress")

        # 读取 workflow_hints
        hints = data.get("workflow_hints", {})
        self.assertIn("COMMIT_ORDER", hints)
        self.assertIn("REVERT_POLICY", hints)

        # COMMIT 应该可以继续（BUILD 已 pass）
        self.assertTrue(self._run_check("0001", "COMMIT"))

        # 完成 COMMIT
        self._run_full_record("0001", "COMMIT", "pass", commit="abc123")

        # 最终 current_state = pass
        data = gk.load_merges_file(self.tmp_path)
        self.assertEqual(data["current_state"]["status"], "pass")

    def test_workflow_hints_auto_injected(self):
        """即使初始 JSON 没有 workflow_hints，do_record 也能注入"""
        # 直接用空 merge_tasks.json
        data = {
            "merge_order": [
                {"task_id": "0001", "status": "pending", "execution_log": []},
            ]
        }
        gk.ensure_workflow_hints(data)
        self.assertIn("workflow_hints", data)
        self.assertIn("BUILD_FIX", data["workflow_hints"])

    def test_clear_current_state(self):
        self._run_full_record("0001", "BUILD", "in_progress")
        data = gk.load_merges_file(self.tmp_path)
        self.assertIsNotNone(data["current_state"])

        # 清除
        data["current_state"] = None
        gk.save_merges_file(self.tmp_path, data)

        data2 = gk.load_merges_file(self.tmp_path)
        self.assertIsNone(data2["current_state"])
