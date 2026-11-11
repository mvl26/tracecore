"""Kỳ báo cáo tháng: khóa / mở khóa có lý do (FEAT-063; FR-M13-11, FR-M13-11.1; BRU-HAI-002, BRU-RPT-003; A-144 Q1)."""

import frappe

from tracecore.core.errors import BlockedError
from tracecore.hai_surveillance import cases, census, periods
from tracecore.hai_surveillance.tests import factories as f
from tracecore.hai_surveillance.tests import hai_fixtures as h
from tracecore.tests.utils import IsolatedTestCase, bru

MONTH = "2026-09"


class TestReportingPeriod(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		h.clear_definitions("TVAP")
		h.make_definition("TVAP", effective_from="2026-01-01")
		frappe.db.delete("IC Reporting Period", {"month": MONTH})
		self.ward = f.make_ward("KSNK Period ICU")
		frappe.db.delete("Ward Daily Census", {"department": self.ward})
		self.census = f.make_census(self.ward, census_date="2026-09-10")
		self.case = h.make_case(self.ward, onset="2026-09-12", admitted="2026-09-01 08:00:00")
		self.r01 = f.factories.make_user("period-r01@test.local", [h.R01])
		self.r11 = f.factories.make_user("period-r11@test.local", [h.R11])

	def block(self, fn, *args, **kwargs):
		with self.assertRaises(BlockedError) as caught:
			fn(*args, **kwargs)
		return caught.exception.block

	def test_name_follows_month(self):
		frappe.set_user(self.r01)
		doc = periods.lock(MONTH)
		self.assertEqual(doc.name, "KY-2026-09")
		self.assertEqual(doc.locked, 1)
		self.assertEqual(doc.locked_by, self.r01)

	def test_invalid_month(self):
		frappe.set_user(self.r01)
		self.assertEqual(self.block(periods.lock, "2026-13").code, "HAI_PERIOD_INVALID")

	def test_only_r01_locks(self):
		frappe.set_user(self.r11)
		with self.assertRaises(frappe.PermissionError):
			periods.lock(MONTH)

	@bru("BRU-HAI-002")
	def test_locked_census_cannot_be_edited_or_added(self):
		frappe.set_user(self.r01)
		periods.lock(MONTH)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Ward Daily Census", self.census.name, "locked"), 1)
		values = f.census_values(self.ward, census_date="2026-09-10", patients=30)
		block = self.block(census.save, values, name=self.census.name)
		self.assertEqual(block.code, "CENSUS_PERIOD_LOCKED")  # FR-M13-11.1
		block = self.block(census.save, f.census_values(self.ward, census_date="2026-09-11"))
		self.assertEqual(block.code, "CENSUS_PERIOD_LOCKED")

	def test_locked_case_cannot_be_edited_decided_or_created(self):
		frappe.set_user(self.r01)
		periods.lock(MONTH)
		doc = frappe.get_doc("HAI Case", self.case.name)
		doc.outcome = "Recovered"
		self.assertEqual(self.block(doc.save).code, "HAI_PERIOD_LOCKED")
		self.assertEqual(
			self.block(cases.decide, self.case.name, cases.EXCLUDED, reason="x").code, "HAI_PERIOD_LOCKED"
		)
		frappe.set_user("Administrator")
		block = self.block(h.make_case, self.ward, onset="2026-09-20", admitted="2026-09-01 08:00:00")
		self.assertEqual(block.code, "HAI_PERIOD_LOCKED")
		# kỳ khác vẫn mở
		self.assertTrue(h.make_case(self.ward, onset="2026-10-20", code="BN-0000002222").name)

	@bru("BRU-RPT-003")
	def test_unlock_needs_reason_and_audits(self):
		frappe.set_user(self.r01)
		periods.lock(MONTH)
		self.assertEqual(self.block(periods.unlock, MONTH, " ").code, "HAI_CASE_REASON_REQUIRED")
		doc = periods.unlock(MONTH, "Bổ sung ca NKVM sau ra viện")
		self.assertEqual(doc.locked, 0)
		self.assertEqual(doc.unlock_count, 1)
		self.assertEqual(frappe.db.get_value("Ward Daily Census", self.census.name, "locked"), 0)
		self.assertTrue(
			frappe.db.exists(
				"Audit Log",
				{
					"ref_doctype": "IC Reporting Period",
					"ref_name": doc.name,
					"reason": "Bổ sung ca NKVM sau ra viện",
				},
			)
		)
		census.save(f.census_values(self.ward, census_date="2026-09-10", patients=30), name=self.census.name)

	def test_unlock_only_r01(self):
		frappe.set_user(self.r01)
		periods.lock(MONTH)
		frappe.set_user(self.r11)
		with self.assertRaises(frappe.PermissionError):
			periods.unlock(MONTH, "x")

	def test_period_rows_show_missing_census_departments(self):
		frappe.set_user(self.r01)
		rows = {row["month"]: row for row in periods.rows(months=[MONTH])}
		self.assertGreaterEqual(rows[MONTH]["missing_wards"], 1)  # khoa chỉ có 1/30 ngày mẫu số
		self.assertEqual(rows[MONTH]["locked"], 0)

	def test_direct_edit_of_period_doc_blocked(self):
		frappe.set_user(self.r01)
		doc = periods.lock(MONTH)
		frappe.set_user("Administrator")
		doc = frappe.get_doc("IC Reporting Period", doc.name)  # bản mới, không mang cờ dịch vụ
		doc.locked = 0
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
