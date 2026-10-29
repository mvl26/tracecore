"""Nối sự kiện M2 vào Cost Sheet (FEAT-046 Task 3; UC-29 kích hoạt khi mẻ giải phóng; A-53 h)."""

from unittest.mock import patch

import frappe

from tracecore.core import notification
from tracecore.costing import sheet
from tracecore.tests.utils import IsolatedTestCase

JOB = "tracecore.costing.sheet.run_job"


class TestSheetHooks(IsolatedTestCase):
	def test_m2_events_are_wired_to_costing(self):
		hooks = frappe.get_hooks()
		self.assertIn("tracecore.costing.sheet.on_load_release", hooks["tracecore_after_load_release"])
		self.assertIn("tracecore.costing.sheet.on_load_failed", hooks["tracecore_after_load_failed"])
		self.assertIn("tracecore.costing.sheet.on_wash_complete", hooks["tracecore_after_wash_complete"])

	def test_release_hook_enqueues_after_commit(self):
		with patch.object(sheet.frappe, "enqueue") as enqueue:
			sheet.on_load_release({"load": "ME-1", "packs": []})
			sheet.on_load_failed({"load": "ME-2"})
			sheet.on_wash_complete({"batch": "LR-1"})
		calls = [
			(c.args[0], c.kwargs["source_doctype"], c.kwargs["source_name"]) for c in enqueue.call_args_list
		]
		self.assertEqual(
			calls,
			[
				(JOB, "Sterilization Load", "ME-1"),
				(JOB, "Sterilization Load", "ME-2"),
				(JOB, "Wash Batch", "LR-1"),
			],
		)
		self.assertTrue(all(c.kwargs["enqueue_after_commit"] for c in enqueue.call_args_list))
		# một job cho mỗi nguồn dù hook chạy lại (review #6)
		self.assertEqual(enqueue.call_args_list[0].kwargs["job_id"], "tc-cost-sheet-Sterilization Load-ME-1")
		self.assertTrue(all(c.kwargs["deduplicate"] for c in enqueue.call_args_list))

	def test_job_errors_are_logged_not_raised(self):
		with (
			patch.object(sheet, "build", side_effect=RuntimeError("boom")),
			patch.object(sheet.frappe, "log_error") as log,
		):
			sheet.run_job("Sterilization Load", "ME-X")
		log.assert_called_once()

	def test_unpriced_event_is_registered(self):
		self.assertIn(sheet.UNPRICED_EVENT, notification.EVENTS)
		self.assertIn("TC R09", notification.EVENTS[sheet.UNPRICED_EVENT][4])
