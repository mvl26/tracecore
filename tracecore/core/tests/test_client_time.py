"""A-160: thời điểm nghiệp vụ theo giờ máy khách — lệch giờ server chỉ ghi Audit Log, không từ chối (ADR-003)."""

import json
from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import client_time


def _skew_rows():
	return frappe.get_all(
		"Audit Log",
		filters={"action": "Override", "reason": client_time.SKEW_REASON},
		fields=["name", "new_value", "client_ts"],
		order_by="creation desc",
	)


class TestClientClockSkew(FrappeTestCase):
	def setUp(self):
		# Audit Log append-only: không xóa, chỉ đếm dòng mới của test này
		self.before = {row.name for row in _skew_rows()}

	def skew_logs(self):
		return [row for row in _skew_rows() if row.name not in self.before]

	def test_skewed_client_ts_is_accepted_and_logged(self):
		skewed = client_time.utc_now() - timedelta(hours=3)
		client_time.check_skew(skewed)  # không raise
		logs = self.skew_logs()
		self.assertEqual(len(logs), 1)
		payload = json.loads(logs[0].new_value)
		self.assertGreaterEqual(payload["skew_seconds"], 3 * 3600 - 5)
		self.assertEqual(payload["client_ts"], str(skewed))
		self.assertEqual(logs[0].client_ts, skewed)

	def test_future_client_ts_is_accepted_and_logged(self):
		future = client_time.utc_now() + timedelta(days=1)
		client_time.check_not_future(future)  # không raise
		self.assertEqual(len(self.skew_logs()), 1)

	def test_old_client_ts_on_replay_is_not_logged(self):
		client_time.check_not_future(client_time.utc_now() - timedelta(days=2))
		self.assertEqual(self.skew_logs(), [])

	def test_within_threshold_is_not_logged(self):
		client_time.check_skew(client_time.utc_now() - timedelta(seconds=30))
		client_time.check_not_future(client_time.utc_now() + timedelta(seconds=30))
		self.assertEqual(self.skew_logs(), [])

	def test_threshold_from_site_config(self):
		with patch.dict(frappe.conf, {"tc_client_ts_max_skew_seconds": 10}):
			client_time.check_skew(client_time.utc_now() - timedelta(seconds=60))
		self.assertEqual(len(self.skew_logs()), 1)

	def test_format_still_required(self):
		with self.assertRaises(client_time.ClientTimestampError):
			client_time.parse_client_ts("2026-11-13T09:00:00")
