"""Ghi sổ hồ sơ bảo trì, kiểm định, hiệu chuẩn (FEAT-039; FR-M5-03 .1-.3; UC-22; BRU-EQP-002; A-42 M4-M7)."""

import frappe
from frappe.utils import add_days, add_months, today

from tracecore.equipment import daily_test
from tracecore.tests.factories import make_equipment, make_maintenance_record
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

DOCTYPE = "Maintenance Record"
CERTIFICATE = "/files/chung-nhan.pdf"


def machine_value(machine, field):
	return frappe.db.get_value("Equipment", machine, field)


class MaintenanceCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.machine = make_equipment()

	def record(self, kind, **kwargs):
		"""Hồ sơ Nháp đủ dữ liệu để ghi sổ; kiểm định/hiệu chuẩn có sẵn chứng nhận và hạn 1 năm."""
		values = {"performed_on": today(), **kwargs}
		if kind in ("Inspection", "Calibration"):
			values.setdefault("certificate", CERTIFICATE)
			values.setdefault("valid_until", add_days(today(), 365))
		return make_maintenance_record(self.machine.name, kind, **values)

	def lock(self, reason, **fields):
		daily_test._apply(self.machine.name, status="Locked", lock_reason=reason, **fields)


class TestClosingRules(MaintenanceCase):
	@bru("BRU-EQP-002")
	def test_inspection_or_calibration_without_certificate_cannot_be_closed(self):  # FR-M5-03.3, UC-22 E1
		for kind in ("Inspection", "Calibration"):
			with self.subTest(kind=kind):
				doc = self.record(kind, certificate=None)
				with self.assertRaises(frappe.ValidationError):
					doc.submit()
				self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "docstatus"), 0)

	@bru("BRU-EQP-002")
	def test_inspection_or_calibration_without_valid_until_cannot_be_closed(self):  # FR-M5-03.3
		for kind in ("Inspection", "Calibration"):
			with self.subTest(kind=kind):
				doc = self.record(kind, valid_until=None)
				with self.assertRaises(frappe.ValidationError):
					doc.submit()
				self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "docstatus"), 0)

	def test_valid_until_cannot_be_before_the_work_was_done(self):
		doc = self.record("Inspection", valid_until=add_days(today(), -1))
		with self.assertRaises(frappe.ValidationError):
			doc.submit()

	def test_preventive_maintenance_needs_no_certificate(self):
		doc = self.record("Preventive")
		doc.submit()
		self.assertEqual(doc.docstatus, 1)

	def test_performed_on_defaults_to_today_when_closing(self):
		doc = make_maintenance_record(self.machine.name, "Preventive")
		doc.submit()
		self.assertEqual(str(frappe.db.get_value(DOCTYPE, doc.name, "performed_on")), str(today()))


class TestValidityDates(MaintenanceCase):
	@bru("BRU-EQP-002")
	def test_closing_updates_the_matching_due_date_of_the_machine(self):  # FR-M5-03
		cases = (
			("Inspection", "inspection_due"),
			("Calibration", "calibration_due"),
			("Preventive", "maintenance_due"),
		)
		for kind, field in cases:
			with self.subTest(kind=kind):
				until = add_days(today(), 200)
				self.record(kind, valid_until=until).submit()
				self.assertEqual(str(machine_value(self.machine.name, field)), str(until))

	def test_preventive_without_valid_until_uses_the_next_planned_date(self):
		self.record("Preventive", cycle_months=3).submit()
		self.assertEqual(
			str(machine_value(self.machine.name, "maintenance_due")), str(add_months(today(), 3))
		)

	def test_preventive_without_valid_until_or_cycle_leaves_the_due_date_alone(self):
		self.record("Preventive").submit()
		self.assertIsNone(machine_value(self.machine.name, "maintenance_due"))

	def test_cancelling_does_not_revert_the_due_date(self):
		doc = self.record("Inspection", valid_until=add_days(today(), 100))
		doc.submit()
		doc.cancel()
		self.assertEqual(str(machine_value(self.machine.name, "inspection_due")), str(add_days(today(), 100)))
		self.assertTrue(frappe.db.exists("Audit Log", {"ref_name": doc.name, "action": "Cancel"}))


class TestExpiryLock(MaintenanceCase):
	@bru("BRU-EQP-002")
	def test_valid_inspection_reopens_a_machine_locked_for_expiry(self):
		self.lock("Inspection Expired", inspection_due=add_days(today(), -2))
		self.record("Inspection").submit()
		state = frappe.db.get_value("Equipment", self.machine.name, ["status", "lock_reason"], as_dict=True)
		self.assertEqual((state.status, state.lock_reason), ("Ready", None))

	def test_inspection_that_is_still_expired_keeps_the_machine_locked(self):
		self.lock("Inspection Expired", inspection_due=add_days(today(), -5))
		self.record(
			"Inspection", performed_on=add_days(today(), -2), valid_until=add_days(today(), -1)
		).submit()
		state = frappe.db.get_value("Equipment", self.machine.name, ["status", "lock_reason"], as_dict=True)
		self.assertEqual((state.status, state.lock_reason), ("Locked", "Inspection Expired"))

	def test_lock_reason_follows_the_remaining_expired_date(self):
		self.lock(
			"Inspection Expired",
			inspection_due=add_days(today(), -2),
			calibration_due=add_days(today(), -3),
		)
		self.record("Inspection").submit()
		state = frappe.db.get_value("Equipment", self.machine.name, ["status", "lock_reason"], as_dict=True)
		self.assertEqual((state.status, state.lock_reason), ("Locked", "Calibration Expired"))
		self.record("Calibration").submit()
		state = frappe.db.get_value("Equipment", self.machine.name, ["status", "lock_reason"], as_dict=True)
		self.assertEqual((state.status, state.lock_reason), ("Ready", None))

	def test_a_machine_locked_for_a_failed_daily_test_is_not_reopened(self):
		self.lock(daily_test.LOCK_DAILY_TEST)
		self.record("Inspection").submit()
		state = frappe.db.get_value("Equipment", self.machine.name, ["status", "lock_reason"], as_dict=True)
		self.assertEqual((state.status, state.lock_reason), ("Locked", "Daily Test"))


class TestNextRecord(MaintenanceCase):
	@bru("BRU-EQP-002")
	def test_closing_a_cyclic_record_plans_the_next_one(self):  # FR-M5-03.2
		doc = self.record("Inspection", cycle_months=12, contract_no="HD-01", sla_hours=48)
		doc.submit()
		self.assertTrue(doc.next_record)
		self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "next_record"), doc.next_record)
		nxt = frappe.get_doc(DOCTYPE, doc.next_record)
		self.assertEqual(nxt.docstatus, 0)
		self.assertEqual(
			(nxt.equipment, nxt.record_type, nxt.cycle_months, nxt.contract_no, nxt.sla_hours),
			(self.machine.name, "Inspection", 12, "HD-01", 48),
		)
		self.assertEqual(str(nxt.planned_date), str(add_months(today(), 12)))
		self.assertFalse(nxt.certificate)

	def test_one_off_record_plans_nothing(self):
		doc = self.record("Preventive", cycle_months=0)
		doc.submit()
		self.assertFalse(doc.next_record)
		self.assertEqual(frappe.db.count(DOCTYPE, {"equipment": self.machine.name, "docstatus": 0}), 0)

	def test_amending_reuses_the_planned_record_instead_of_adding_another(self):
		doc = self.record("Calibration", cycle_months=6)
		doc.submit()
		planned = doc.next_record
		doc.cancel()
		amended = frappe.copy_doc(doc)
		amended.docstatus = 0  # Desk "Amend" đặt lại về Nháp; copy_doc giữ nguyên docstatus của bản đã hủy
		amended.amended_from = doc.name
		amended.performed_on = add_days(today(), 1)
		amended.insert()
		amended.submit()
		self.assertEqual(amended.next_record, planned)
		self.assertEqual(frappe.db.count(DOCTYPE, {"equipment": self.machine.name, "docstatus": 0}), 1)
		self.assertEqual(
			str(frappe.db.get_value(DOCTYPE, planned, "planned_date")),
			str(add_months(add_days(today(), 1), 6)),
		)
