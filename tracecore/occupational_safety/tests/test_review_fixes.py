"""Hồi quy các lỗi phát hiện khi review FEAT-071: giờ xử trí, mã BN bị xóa, danh sách SCR-64, yêu cầu tiêm chủng đã
duyệt, vaccine mẫu, ngưỡng giờ trống, nhóm báo cáo cho R13, nút duyệt, Sync Conflict không lộ sức khỏe nhân viên
(FR-M16-03, 05, 07, 09; BRU-OCC-003, BRU-OCC-004; NFR-MAINT-04)."""

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, today

from tracecore.core import sync
from tracecore.core.errors import BlockedError
from tracecore.occupational_safety import config, dashboard, exposure, immunization, indicators
from tracecore.occupational_safety.report.occupational_exposure_by_period import (
	occupational_exposure_by_period as report,
)
from tracecore.occupational_safety.tests import os_fixtures as fx
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1 import exposure as api

DOCTYPE = "Occupational Exposure"


class ExposureCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		fx.clear_templates()
		fx.thresholds()
		self.department = factories.make_department("PN Review Khoa")
		self.employee = fx.employee("PN Review Staff", self.department)

	def report(self, **values):
		data = {"employee": self.employee, "exposure_type": fx.SHARPS, "occurred_at": fx.hours_ago(3)}
		data.update(values)
		return exposure.create_report(data)


class TestHandlingTimes(ExposureCase):
	def test_prophylaxis_before_exposure_or_in_future_is_blocked(self):
		"""Không để giờ dự phòng trước giờ phơi nhiễm làm số phút = 0 và mất cờ muộn (FR-M16-03)."""
		name = self.report().name
		for moment in (fx.hours_ago(5), add_to_date(now_datetime(), hours=2)):
			with self.assertRaises(BlockedError) as raised:
				exposure.record_handling(name, 1, None, "Given", moment)
			self.assertEqual(raised.exception.block.code, "EXPOSURE_TIME_INVALID")


class TestPatientCodeCleared(ExposureCase):
	def test_clearing_code_clears_mask_and_hash(self):
		doc = self.report(source_known="Yes", source_patient_code="BN-CLEAR-7788")
		self.assertTrue(doc.source_patient_code_masked)
		doc.source_patient_code = ""
		doc.save(ignore_permissions=True)
		self.assertFalse(doc.source_patient_code_masked or doc.source_patient_code_hash)


class TestDashboardList(ExposureCase):
	def test_open_records_are_never_cut_by_the_limit(self):
		old = self.report(occurred_at=add_to_date(now_datetime(), days=-200))
		for _ in range(2):
			exposure.cancel(self.report().name, "Mistake")
		rows = dashboard.records(limit=1)
		self.assertIn(old.name, [row.name for row in rows])
		self.assertEqual(sum(1 for row in rows if row.status not in exposure.OPEN), 1)


class TestRequirementApproval(IsolatedTestCase):
	@bru("BRU-OCC-004")
	def test_changing_an_approved_requirement_needs_reapproval_and_recomputes_due(self):
		department = factories.make_department("PN Review Imm")
		employee = fx.employee("PN Review Imm Staff", department)
		req = fx.requirement("PN Review Vaccine", doses=3, interval=30, departments=[department])
		dose = frappe.get_doc(
			{
				"doctype": "Staff Immunization",
				"employee": employee,
				"vaccine": req.name,
				"dose_no": 1,
				"given_on": today(),
			}
		).insert(ignore_permissions=True)
		req.dose_interval_days = 60
		req.save(ignore_permissions=True)
		self.assertEqual(req.status, "Draft")
		self.assertNotIn(req.name, [v["vaccine"] for v in immunization.coverage()["vaccines"]])
		config.approve_requirement(req.name)
		self.assertEqual(
			str(frappe.db.get_value("Staff Immunization", dose.name, "next_due")), str(add_days(today(), 60))
		)

	def test_vaccine_name_is_trimmed(self):
		doc = fx.requirement("  PN Trim Vaccine  ", approve=False)
		self.assertEqual(doc.name, "PN Trim Vaccine")

	def test_default_vaccines_not_reinserted_after_hospital_edits(self):
		fx.requirement("PN Only Vaccine", approve=False)
		for name in frappe.get_all("Immunization Requirement", filters={"name": ["!=", "PN Only Vaccine"]}, pluck="name"):
			frappe.delete_doc("Immunization Requirement", name, force=True, ignore_permissions=True)
		config.ensure_default_config()
		self.assertEqual(frappe.get_all("Immunization Requirement", pluck="name"), ["PN Only Vaccine"])

	def test_approve_rpc_returns_inline_error(self):
		fx.clear_templates()
		doc = fx.template(steps=(), approve=False)
		result = api.approve_template(doc.name)
		self.assertFalse(result["ok"])
		self.assertTrue(result["error"]["reason"])
		ok = api.approve_requirement(fx.requirement("PN RPC Vaccine", doses=1, approve=False).name)
		self.assertEqual((ok["ok"], ok["status"]), (True, "Approved"))


class TestNoLimitAndR13Report(ExposureCase):
	def test_no_report_limit_means_no_on_time_rate(self):
		frappe.db.sql("update `tabOccupational Exposure` set status = 'Cancelled'")
		self.report()
		self.assertEqual(indicators.report_on_time(today()[:7], None)[:2], (0, 0))
		_columns, rows = report.execute({"from_date": today(), "to_date": today()})
		self.assertIsNone(rows[-1]["on_time_rate"])

	@bru("BRU-OCC-003")
	def test_r13_cannot_group_by_free_text_columns(self):
		self.report(device="Needle of patient Tran Van B")
		frappe.set_user(factories.make_user("os-review-r13@example.com", roles=["TC R13"]))
		columns, rows = report.execute({"from_date": today(), "to_date": today(), "group_by": "Device"})
		self.assertNotIn("Tran Van B", frappe.as_json(rows))
		self.assertEqual(columns[0]["label"], frappe._("Exposure Type"))


class TestSyncConflictPrivacy(IsolatedTestCase):
	@bru("BRU-OCC-003")
	def test_exposure_conflict_keeps_no_health_data_or_employee(self):
		import json
		import uuid

		name = sync.record_conflict(
			endpoint="tracecore.v1.exposure.report",
			key=str(uuid.uuid4()),
			client_ts=None,
			args={
				"station": "TR-X",
				"exposure_type": fx.SHARPS,
				"activity": "Recapping",
				"source_patient_code": "BN-PLAIN",
				"source_patient_code_enc": "abc",
			},
			error={"code": "EXPOSURE_TIME_INVALID"},
			http_status=422,
			session={"station": "TR-X", "employee": "EMP-X", "user": "Administrator"},
		)
		row = frappe.db.get_value("Sync Conflict", name, ["employee", "client_state"], as_dict=True)
		self.assertFalse(row.employee)
		self.assertEqual(set(json.loads(row.client_state)), {"station"})
		self.assertNotIn("source_patient_code", sync._redacted({"source_patient_code": "x"}))
