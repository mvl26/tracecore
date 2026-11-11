"""Khai báo bệnh truyền nhiễm (FEAT-069; FR-M14-10, .1; BRU-MDR-005, BRU-HAI-005; UC-53 bước 5-6, E2, E3; A-150 Q1,
Q5, Q6)."""

import json
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, get_datetime, getdate, now_datetime

from tracecore.core.errors import BlockedError
from tracecore.microbiology import notifiable
from tracecore.microbiology.tests import outbreak_fixtures as of
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, bru


class NotifiableCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.ward = of.make_clinical("KB Khoa Nhiễm")
		self.other = of.make_clinical("KB Khoa Nhi")
		frappe.db.delete(notifiable.DOCTYPE, {"department": ["in", [self.ward, self.other]]})
		self.dengue = of.make_disease("T-DENGUE", "Sốt xuất huyết Dengue", "B")
		self.cholera = of.make_disease("T-TA", "Tả", "A")
		of.set_hours(a=12, b=24, c=None)

	def values(self, **extra):
		return {
			"department": self.ward,
			"patient_code": "BN0004821",
			"disease": self.dengue,
			"diagnosed_on": add_to_date(now_datetime(), hours=-2),
			**extra,
		}


class TestDeadline(NotifiableCase):
	def test_hours_come_from_group_settings(self):
		self.assertEqual(notifiable.deadline_hours("A"), 12)
		self.assertEqual(notifiable.deadline_hours("B"), 24)
		self.assertIsNone(notifiable.deadline_hours("C"))

	def test_report_due_by_is_diagnosis_plus_group_hours(self):
		diagnosed = get_datetime("2026-11-02 15:40:00")
		doc = notifiable.create_report(self.values(diagnosed_on=diagnosed))
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.status, notifiable.PENDING)
		self.assertEqual(doc.deadline_hours, 24)
		self.assertEqual(get_datetime(doc.due_by), get_datetime("2026-11-03 15:40:00"))
		self.assertEqual(doc.patient_code_masked, "***4821")

	def test_group_without_deadline_warns_and_notifies_config(self):
		measles = of.make_disease("T-SOI", "Sởi", "C")
		with patch("tracecore.core.notification.emit") as emit:
			doc = notifiable.create_report(self.values(disease=measles))
		self.assertFalse(doc.due_by)
		self.assertTrue(doc.flags.tc_warnings)
		self.assertIn(notifiable.CONFIG_EVENT, [call.args[0] for call in emit.call_args_list])


class TestCreate(NotifiableCase):
	def test_required_fields_block(self):
		for missing, code in (
			("patient_code", "NOTIFIABLE_PATIENT_REQUIRED"),
			("disease", "NOTIFIABLE_DISEASE_REQUIRED"),
			("diagnosed_on", "NOTIFIABLE_DATE_INVALID"),
		):
			with self.subTest(missing=missing), self.assertRaises(BlockedError) as caught:
				notifiable.create_report(self.values(**{missing: None}))
			self.assertEqual(caught.exception.block.code, code)

	def test_future_diagnosis_and_disabled_disease_block(self):
		with self.assertRaises(BlockedError):
			notifiable.create_report(self.values(diagnosed_on=add_to_date(now_datetime(), days=1)))
		off = of.make_disease("T-OFF", "Bệnh tắt", "B", disabled=1)
		with self.assertRaises(BlockedError) as caught:
			notifiable.create_report(self.values(disease=off))
		self.assertEqual(caught.exception.block.code, "NOTIFIABLE_DISEASE_REQUIRED")

	def test_department_user_only_own_department(self):
		user = of.make_dept_user("kb-r12@example.com", "TC R12", self.ward)
		frappe.set_user(user)
		doc = notifiable.create_report(self.values())
		self.assertEqual(doc.department, self.ward)
		with self.assertRaises(BlockedError) as caught:
			notifiable.create_report(self.values(department=self.other))
		self.assertEqual(caught.exception.block.code, "NOTIFIABLE_NOT_ALLOWED")

	def test_direct_insert_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": notifiable.DOCTYPE, **self.values()}).insert(ignore_permissions=True)

	@bru("BRU-HAI-005")
	def test_no_patient_name_field_and_code_is_password(self):
		path = Path(frappe.get_app_path("tracecore")) / (
			"microbiology/doctype/notifiable_disease_report/notifiable_disease_report.json"
		)
		fields = {row["fieldname"]: row["fieldtype"] for row in json.loads(path.read_text())["fields"]}
		self.assertEqual(fields["patient_code"], "Password")
		self.assertFalse(
			[name for name in fields if "name" in name and name not in ("disease_name", "department_name")]
		)


class TestReported(NotifiableCase):
	@bru("BRU-MDR-005")
	def test_only_tracks_reported_on_and_reference(self):
		doc = notifiable.create_report(self.values())
		done = notifiable.record_reported(doc.name, add_to_date(now_datetime(), hours=-1), "SGSDT-123")
		self.assertEqual(done.status, notifiable.REPORTED)
		self.assertEqual(done.report_ref, "SGSDT-123")
		self.assertEqual(done.reported_by, "Administrator")
		self.assertFalse(done.reported_late)
		self.assertEqual(notifiable.state_of(done.as_dict()), notifiable.STATE_REPORTED)

	@bru("BRU-MDR-005")
	def test_reported_without_reference_stays_pending(self):
		doc = notifiable.create_report(self.values())
		done = notifiable.record_reported(doc.name, add_to_date(now_datetime(), hours=-1), "")
		self.assertEqual(done.status, notifiable.PENDING)
		self.assertTrue(done.flags.tc_warnings)
		self.assertEqual(notifiable.state_of(done.as_dict()), notifiable.STATE_MISSING_REF)

	def test_late_report_flag_and_states(self):
		diagnosed = add_to_date(now_datetime(), hours=-30)
		doc = notifiable.create_report(self.values(diagnosed_on=diagnosed))
		self.assertEqual(notifiable.state_of(doc.as_dict()), notifiable.STATE_OVERDUE)
		done = notifiable.record_reported(doc.name, add_to_date(now_datetime(), hours=-1), "SGSDT-9")
		self.assertTrue(done.reported_late)
		self.assertEqual(notifiable.state_of(done.as_dict()), notifiable.STATE_LATE)

	def test_reported_before_diagnosis_blocked(self):
		doc = notifiable.create_report(self.values())
		with self.assertRaises(BlockedError) as caught:
			notifiable.record_reported(doc.name, add_to_date(now_datetime(), hours=-5), "X")
		self.assertEqual(caught.exception.block.code, "NOTIFIABLE_DATE_INVALID")

	def test_cancel_only_ic_staff_with_reason(self):
		doc = notifiable.create_report(self.values())
		user = of.make_dept_user("kb-r08@example.com", "TC R08", self.ward)
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			notifiable.cancel_report(doc.name, "nhập nhầm")
		frappe.set_user("Administrator")
		with self.assertRaises(BlockedError):
			notifiable.cancel_report(doc.name, "")
		cancelled = notifiable.cancel_report(doc.name, "nhập nhầm")
		self.assertEqual((cancelled.docstatus, cancelled.status), (2, notifiable.CANCELLED))

	def test_desk_edit_after_submit_blocked(self):
		doc = frappe.get_doc(notifiable.DOCTYPE, notifiable.create_report(self.values()).name)
		doc.report_ref = "SỬA TAY"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)


class TestRemind(NotifiableCase):
	def setUp(self):
		super().setUp()
		self.r11 = make_user("kb-r11@example.com", ["TC R11"])
		self.r08 = of.make_dept_user("kb-head@example.com", "TC R08", self.ward)

	def _remind(self, moment):
		with patch("tracecore.core.notification.emit") as emit:
			notifiable.remind(moment)
		return emit.call_args_list

	def test_half_then_overdue_then_daily(self):
		diagnosed = get_datetime("2026-11-02 08:00:00")
		doc = notifiable.create_report(self.values(diagnosed_on=diagnosed))
		self.assertEqual(self._remind(get_datetime("2026-11-02 12:00:00")), [])
		calls = self._remind(get_datetime("2026-11-02 21:00:00"))
		self.assertEqual(len(calls), 1)
		self.assertIn(self.r08, calls[0].kwargs["users"])
		self.assertIn(self.r11, calls[0].kwargs["users"])
		self.assertEqual(self._remind(get_datetime("2026-11-02 22:00:00")), [])
		self.assertEqual(len(self._remind(get_datetime("2026-11-03 09:00:00"))), 1)  # quá hạn
		self.assertEqual(self._remind(get_datetime("2026-11-03 18:00:00")), [])  # cùng ngày
		self.assertEqual(len(self._remind(get_datetime("2026-11-04 08:00:00"))), 1)  # mỗi ngày
		self.assertEqual(frappe.db.get_value(notifiable.DOCTYPE, doc.name, "remind_stage"), 2)

	def test_reported_stops_but_missing_reference_keeps_reminding(self):
		diagnosed = get_datetime("2026-11-02 08:00:00")
		done = notifiable.create_report(self.values(diagnosed_on=diagnosed))
		notifiable.record_reported(done.name, get_datetime("2026-11-02 09:00:00"), "SGSDT-1")
		partial = notifiable.create_report(self.values(diagnosed_on=diagnosed, patient_code="BN0009999"))
		notifiable.record_reported(partial.name, get_datetime("2026-11-02 09:00:00"), "")
		calls = self._remind(get_datetime("2026-11-03 09:00:00"))
		self.assertEqual([call.kwargs["doc"].name for call in calls], [partial.name])

	def test_no_deadline_no_reminder(self):
		measles = of.make_disease("T-SOI", "Sởi", "C")
		with patch("tracecore.core.notification.emit"):
			notifiable.create_report(
				self.values(disease=measles, diagnosed_on=get_datetime("2026-11-01 08:00:00"))
			)
		self.assertEqual(self._remind(get_datetime("2026-11-05 08:00:00")), [])
		self.assertTrue(getdate("2026-11-05"))
