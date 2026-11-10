"""Xóa định danh khi hết thời hạn lưu (FEAT-063; NFR-PRIV-02; OQ-V12-07; A-144 Q3)."""

import frappe
from frappe.utils import add_months, getdate, today

from tracecore.hai_surveillance import cases, retention
from tracecore.hai_surveillance.tests import factories as f
from tracecore.hai_surveillance.tests import hai_fixtures as h
from tracecore.tests.utils import IsolatedTestCase

SETTINGS = "IC Program Settings"


class TestRetention(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		h.clear_definitions("TVAP")
		h.make_definition("TVAP", effective_from="2025-01-01", hours=0, days=0)
		self.ward = f.make_ward("KSNK Retention ICU")
		old = add_months(getdate(today()), -14)
		self.old_case = h.make_case(self.ward, onset=old, admitted=f"{old} 00:00:00", code="BN-RET-0001")
		cases.decide(self.old_case.name, cases.CONFIRMED)
		self.new_case = h.make_case(
			self.ward, onset=today(), admitted=f"{today()} 00:00:00", code="BN-RET-0002"
		)
		cases.decide(self.new_case.name, cases.CONFIRMED)
		self.episode = h.make_episode(
			self.ward, inserted_on=add_months(old, -1), removed_on=old, code="BN-RET-0003"
		)

	def _set_months(self, months):
		frappe.db.set_single_value(SETTINGS, "patient_data_retention_months", months)

	def test_empty_setting_keeps_everything(self):
		self._set_months(None)
		self.assertEqual(retention.run(), {"HAI Case": 0, "Device Episode": 0})

	def test_expired_records_are_deidentified_and_audited(self):
		self._set_months(12)
		result = retention.run()
		self.assertGreaterEqual(result["HAI Case"], 1)
		self.assertGreaterEqual(result["Device Episode"], 1)
		row = frappe.db.get_value(
			"HAI Case",
			self.old_case.name,
			["patient_code_masked", "patient_code_hash", "birth_year", "deidentified", "status"],
			as_dict=True,
		)
		self.assertEqual((row.patient_code_masked, row.patient_code_hash, row.birth_year), (None, None, 0))
		self.assertEqual((row.deidentified, row.status), (1, cases.CONFIRMED))  # số liệu giữ nguyên
		self.assertFalse(
			frappe.db.sql(
				"select count(*) from `__Auth` where doctype=%s and name=%s", ("HAI Case", self.old_case.name)
			)[0][0]
		)
		self.assertEqual(frappe.db.get_value("HAI Case", self.new_case.name, "deidentified"), 0)
		self.assertIsNone(frappe.db.get_value("Device Episode", self.episode.name, "patient_code_hash"))
		self.assertTrue(
			frappe.db.exists("Audit Log", {"ref_doctype": "HAI Case", "ref_name": self.old_case.name})
		)
		self.assertEqual(retention.run()["HAI Case"], 0)  # chạy lại không làm gì thêm

	def test_scheduled_daily(self):
		self.assertIn(
			"tracecore.hai_surveillance.retention.run", frappe.get_hooks("scheduler_events")["daily"]
		)
