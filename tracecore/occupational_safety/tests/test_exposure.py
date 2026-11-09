"""Hồ sơ phơi nhiễm: báo ban đầu, thời gian → cờ, sơ cứu/dự phòng → lịch theo dõi (FEAT-071; FR-M16-01, FR-M16-03,
FR-M16-04, FR-M16-06; BRU-OCC-001; UC-55 bước 1-5, E3, E4; A-137 a, b, d)."""

import json
import os
import re

import frappe
from frappe.utils import add_days, add_to_date, getdate, now_datetime, today

from tracecore.core.errors import BlockedError
from tracecore.occupational_safety import exposure
from tracecore.occupational_safety.tests import os_fixtures as fx
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

DOCTYPE = "Occupational Exposure"
M16_DOCTYPE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "doctype")
# Trường có thể chứa kết quả xét nghiệm hay chẩn đoán của nhân viên (FR-M16-06.1)
FORBIDDEN = re.compile(r"result|diagnos|lab|serolog|hiv|hbsag|hcv|antibod|titer|\btest", re.IGNORECASE)


def _report(test, **values):
	data = {"employee": test.employee, "exposure_type": fx.SHARPS, "occurred_at": fx.hours_ago(1)}
	data.update(values)
	return exposure.create_report(data, channel="PDA")


class TestExposureReport(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.department = factories.make_department("PN Ngoại TH")
		self.user = factories.make_user("os-staff@example.com", roles=["TC R08"])
		self.employee = fx.employee("PN Staff", self.department, user=self.user, designation="PN Nurse")
		fx.thresholds()
		fx.clear_templates()

	def test_report_records_reporter_time_channel_and_occupation(self):
		doc = _report(self, activity="Recapping", device="Needle 23G")
		self.assertEqual(doc.status, "New")
		self.assertEqual(doc.report_channel, "PDA")
		self.assertEqual(doc.occupation, "PN Nurse")
		self.assertEqual(doc.department, self.department)
		self.assertTrue(doc.name.startswith("PN-"))
		self.assertAlmostEqual(doc.minutes_to_report, 60, delta=1)
		self.assertEqual(doc.reported_by, "Administrator")

	def test_report_notifies_r01_and_r11_at_once(self):
		"""FR-M16-01.1: thông báo đến R11 ngay khi ghi (≤ 1 phút)."""
		from tracecore.core import notification

		notification.ensure_default_rules()
		r01 = factories.make_user("os-r01-notify@example.com", roles=["TC R01"])
		r11 = factories.make_user("os-r11-notify@example.com", roles=["TC R11"])
		doc = _report(self)
		for user in (r01, r11):
			self.assertTrue(
				frappe.db.exists(
					"Notification Delivery",
					{"event_code": "EXPOSURE_REPORTED", "recipient": user, "ref_name": doc.name},
				),
				user,
			)
		self.assertEqual(notification.EVENTS["EXPOSURE_REPORTED"][1], "Urgent")

	def test_future_time_is_blocked(self):
		with self.assertRaises(BlockedError) as raised:
			_report(self, occurred_at=add_to_date(now_datetime(), minutes=30))
		self.assertEqual(raised.exception.block.code, "EXPOSURE_TIME_INVALID")

	def test_source_patient_code_is_stored_masked_and_hashed(self):
		doc = _report(self, source_known="Yes", source_patient_code="bn-2026-001234")
		self.assertEqual(doc.source_patient_code_masked, "***1234")
		self.assertEqual(len(doc.source_patient_code_hash), 64)
		raw = frappe.db.get_value(DOCTYPE, doc.name, "source_patient_code")
		self.assertNotIn("1234", raw or "")
		self.assertEqual(doc.get_password("source_patient_code"), "BN-2026-001234")

	def test_source_code_dropped_when_source_not_known(self):
		doc = _report(self, source_known="No", source_patient_code="BN999")
		self.assertFalse(doc.source_patient_code_masked)
		self.assertFalse(doc.source_patient_code_hash)

	def test_report_late_flag_uses_configured_threshold(self):
		"""FR-M16-03, 03.1: ngưỡng lấy từ cấu hình; trống thì không gắn cờ."""
		late = _report(self, occurred_at=fx.hours_ago(5))
		self.assertFalse(late.report_late)
		fx.thresholds(report_hours=2)
		late = _report(self, occurred_at=fx.hours_ago(5))
		on_time = _report(self, occurred_at=fx.hours_ago(1))
		self.assertTrue(late.report_late)
		self.assertFalse(on_time.report_late)

	def test_handling_creates_schedule_from_approved_template(self):
		"""FR-M16-04: hạn = ngày phơi nhiễm + days_after; chép phiên bản mẫu."""
		template = fx.template()
		fx.thresholds(prophylaxis_hours=2)
		doc = _report(self, occurred_at=fx.hours_ago(3))
		doc = exposure.record_handling(
			doc.name,
			first_aid_done=1,
			first_aid_at=fx.hours_ago(2.9),
			prophylaxis="Given",
			prophylaxis_started_at=fx.hours_ago(0.5),
		)
		self.assertEqual(doc.status, "Following Up")
		self.assertEqual(doc.followup_template, template.name)
		self.assertEqual(doc.template_version, 1)
		self.assertEqual([r.step for r in doc.followups], ["Step 1", "Step 2", "Step 3"])
		base = getdate(doc.occurred_at)
		self.assertEqual(
			[getdate(r.due_date) for r in doc.followups], [base, add_days(base, 42), add_days(base, 180)]
		)
		self.assertAlmostEqual(doc.minutes_to_prophylaxis, 150, delta=1)
		self.assertTrue(doc.prophylaxis_late)

	def test_handling_without_template_warns_r01(self):
		"""UC-55 E4: chưa có mẫu Approved → không sinh lịch, báo R01."""
		from tracecore.core import notification

		notification.ensure_default_rules()
		r01 = factories.make_user("os-r01-tpl@example.com", roles=["TC R01"])
		fx.template(approve=False)
		doc = exposure.record_handling(_report(self).name, first_aid_done=1, prophylaxis="Not Indicated")
		self.assertFalse(doc.followups)
		self.assertEqual(doc.status, "New")
		self.assertTrue(
			frappe.db.exists(
				"Notification Delivery", {"event_code": "EXPOSURE_TEMPLATE_MISSING", "recipient": r01}
			)
		)

	def test_handling_needs_prophylaxis_decision(self):
		fx.template()
		with self.assertRaises(BlockedError) as raised:
			exposure.record_handling(_report(self).name, first_aid_done=1, prophylaxis=None)
		self.assertEqual(raised.exception.block.code, "EXPOSURE_HANDLING_INCOMPLETE")

	def test_schedule_is_generated_once(self):
		fx.template()
		name = _report(self).name
		exposure.record_handling(name, first_aid_done=1, prophylaxis="Refused")
		doc = exposure.record_handling(name, first_aid_done=1, prophylaxis="Refused")
		self.assertEqual(len(doc.followups), 3)

	def test_all_steps_done_completes_follow_up(self):
		fx.template(steps=(("Step 1", 0), ("Step 2", 1)))
		doc = exposure.record_handling(
			_report(self).name, first_aid_done=1, prophylaxis="Given", prophylaxis_started_at=now_datetime()
		)
		first, second = doc.followups
		doc = exposure.mark_followup_done(doc.name, first.name, today())
		self.assertEqual(doc.status, "Following Up")
		with self.assertRaises(BlockedError):
			exposure.mark_followup_done(doc.name, second.name, add_days(today(), 2))
		doc = exposure.mark_followup_done(doc.name, second.name, today())
		self.assertEqual(doc.status, "Completed")

	def test_cancel_needs_reason(self):
		name = _report(self).name
		with self.assertRaises(BlockedError):
			exposure.cancel(name, " ")
		doc = exposure.cancel(name, "Reported by mistake")
		self.assertEqual(doc.status, "Cancelled")
		self.assertEqual(doc.cancel_reason, "Reported by mistake")

	@bru("BRU-OCC-001")
	def test_no_lab_result_or_diagnosis_field_in_m16(self):
		"""FR-M16-06.1: quét JSON mọi DocType M16, không có trường kết quả xét nghiệm hay chẩn đoán."""
		checked = 0
		for folder in sorted(os.listdir(M16_DOCTYPE_DIR)):
			path = os.path.join(M16_DOCTYPE_DIR, folder, f"{folder}.json")
			if not os.path.exists(path):
				continue
			with open(path, encoding="utf-8") as handle:
				meta = json.load(handle)
			checked += 1
			for field in meta["fields"]:
				for text in (field["fieldname"], field.get("label") or ""):
					self.assertIsNone(FORBIDDEN.search(text), f"{meta['name']}.{field['fieldname']}")
			self.assertNotIn("patient_name", [f["fieldname"] for f in meta["fields"]])
		self.assertEqual(checked, 8)
