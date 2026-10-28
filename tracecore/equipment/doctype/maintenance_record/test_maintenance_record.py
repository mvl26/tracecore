"""Maintenance Record (FEAT-039; FR-M5-03, FR-M5-04; UC-22; BRU-EQP-002): dữ liệu, đặt tên, xóa, quyền (A-43 M3, M9, M10)."""

import frappe

from tracecore.tests.factories import make_equipment, make_maintenance_record, make_user
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

DOCTYPE = "Maintenance Record"


class TestMaintenanceRecord(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.machine = make_equipment()

	def test_equipment_is_required(self):
		with self.assertRaises(frappe.MandatoryError):
			make_maintenance_record(None)

	@bru("BRU-EQP-002")
	def test_four_record_types_are_named_bt(self):
		for kind in ("Preventive", "Inspection", "Calibration", "Incident"):
			doc = make_maintenance_record(self.machine.name, kind)
			self.assertRegex(doc.name, r"^BT-\d{4}-\d{5}$")
			self.assertEqual(doc.record_type, kind)

	def test_unknown_record_type_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_maintenance_record(self.machine.name, "Other")

	@bru("BRU-EQP-002")
	def test_negative_numbers_are_blocked(self):  # UC-22 E3
		for field in ("cost", "downtime_hours", "cycle_months", "sla_hours"):
			with self.assertRaises(frappe.ValidationError, msg=field):
				make_maintenance_record(self.machine.name, "Incident", **{field: -1})

	def test_negative_part_quantity_or_rate_is_blocked(self):
		for part in (
			{"part_name": "Gioăng", "qty": -1, "rate": 1000},
			{"part_name": "Gioăng", "qty": 1, "rate": -1},
		):
			with self.assertRaises(frappe.ValidationError):
				make_maintenance_record(self.machine.name, "Incident", parts=[part])

	def test_part_amount_is_quantity_times_rate(self):
		doc = make_maintenance_record(
			self.machine.name, "Incident", parts=[{"part_name": "Gioăng", "qty": 2, "rate": 150000}]
		)
		self.assertEqual(doc.parts[0].amount, 300000)

	def test_record_cannot_be_deleted(self):
		doc = make_maintenance_record(self.machine.name, "Preventive")
		with self.assertRaises(frappe.ValidationError):
			doc.delete()
		self.assertTrue(frappe.db.exists(DOCTYPE, doc.name))

	@bru("BRU-EQP-002")
	def test_permissions_follow_a42_m10(self):
		"""R02 làm hết; R10 tạo/sửa không ghi sổ; R01 và R09 chỉ đọc; KTV không thấy."""
		expected = {
			"TC R02": {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1},
			"TC R10": {"read": 1, "write": 1, "create": 1, "submit": 0, "cancel": 0},
			"TC R01": {"read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0},
			"TC R09": {"read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0},
			"TC R03": {"read": 0, "write": 0, "create": 0, "submit": 0, "cancel": 0},
			"TC R04": {"read": 0, "write": 0, "create": 0, "submit": 0, "cancel": 0},
			"TC R05": {"read": 0, "write": 0, "create": 0, "submit": 0, "cancel": 0},
			"TC R06": {"read": 0, "write": 0, "create": 0, "submit": 0, "cancel": 0},
			"TC R07": {"read": 0, "write": 0, "create": 0, "submit": 0, "cancel": 0},
			"TC R08": {"read": 0, "write": 0, "create": 0, "submit": 0, "cancel": 0},
		}
		for role, flags in expected.items():
			user = make_user(f"mr-{role.split()[-1].lower()}@example.com", [role])
			for ptype, allowed in flags.items():
				self.assertEqual(
					int(bool(frappe.has_permission(DOCTYPE, ptype, user=user))),
					allowed,
					msg=f"{role} {ptype}",
				)
