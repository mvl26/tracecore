import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.factories import (
	make_batch,
	make_instrument,
	make_item,
	make_maintenance,
	make_set_unit,
	make_user,
)

# Batch/User (ERPNext/Frappe) kéo theo test record Item, Email Account → Company… cần Setup Wizard;
# site CI mới chưa chạy wizard nên bỏ phụ thuộc này (dữ liệu tạo qua tracecore/tests/factories.py).
test_ignore = ["Batch", "User"]


class TestInstrumentMaintenance(FrappeTestCase):
	def test_one_maintenance_row_per_set_unit_instrument(self):
		su = make_set_unit()
		row = make_maintenance(su.name, "KC-M1")
		self.assertEqual(row.name, f"{su.name}-KC-M1")
		with self.assertRaises(frappe.DuplicateEntryError):
			make_maintenance(su.name, "KC-M1")
		# cặp khác vẫn tạo được: cùng bộ khác dụng cụ, cùng dụng cụ khác bộ
		self.assertTrue(make_maintenance(su.name, "KC-M2"))
		self.assertTrue(make_maintenance(make_set_unit().name, "KC-M1"))

	def test_counters_default_to_zero_and_can_be_seeded(self):
		su = make_set_unit()
		fresh = make_maintenance(su.name, "KC-M3")
		self.assertEqual((fresh.cycles_since_maint, fresh.deferred_count), (0, 0))
		seeded = make_maintenance(su.name, "KC-M4", cycles_since=55, deferred_count=2)
		self.assertEqual(
			frappe.db.get_value(
				"Instrument Maintenance", seeded.name, ["cycles_since_maint", "deferred_count"]
			),
			(55, 2),
		)

	def test_counters_not_negative(self):
		su = make_set_unit()
		make_instrument("KC-M5")
		for field in ("cycles_since_maint", "deferred_count"):
			with self.assertRaises(frappe.ValidationError, msg=field):
				frappe.get_doc(
					{
						"doctype": "Instrument Maintenance",
						"set_unit": su.name,
						"instrument": "KC-M5",
						field: -1,
					}
				).insert()

	def test_last_maintenance_and_deferral_fields(self):
		su = make_set_unit()
		user = make_user("maint.tester@example.com")
		make_item("VT-DAU-M", "Lubricant", has_batch_no=1)
		make_batch("VT-DAU-M", "DAU-M-001")
		row = make_maintenance(su.name, "KC-M6")
		row.update(
			{
				"last_maint_on": "2026-10-19 08:30:00",
				"last_maint_by": user,
				"last_oil_batch": "DAU-M-001",
				"last_defer_on": "2026-10-20 09:00:00",
				"last_defer_reason": "Urgent surgery",
			}
		)
		row.save()
		stored = frappe.db.get_value(
			"Instrument Maintenance",
			row.name,
			["last_maint_by", "last_oil_batch", "last_defer_reason"],
			as_dict=True,
		)
		self.assertEqual(
			(stored.last_maint_by, stored.last_oil_batch, stored.last_defer_reason),
			(user, "DAU-M-001", "Urgent surgery"),
		)

	def test_set_unit_and_instrument_cannot_change(self):
		su = make_set_unit()
		row = make_maintenance(su.name, "KC-M7")
		row.instrument = make_instrument("KC-M8").name
		with self.assertRaises(frappe.ValidationError):
			row.save()

	def test_audit_log_and_delete_blocked(self):
		row = make_maintenance(make_set_unit().name, "KC-M9", cycles_since=3)
		self.assertEqual(
			frappe.db.count(
				"Audit Log",
				{"ref_doctype": "Instrument Maintenance", "ref_name": row.name, "action": "Create"},
			),
			1,
		)
		row.cycles_since_maint = 4
		row.save()
		updated = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Instrument Maintenance", "ref_name": row.name, "action": "Update"},
			fields=["old_value", "new_value"],
		)
		self.assertEqual(len(updated), 1)
		self.assertEqual(frappe.parse_json(updated[0].old_value), {"cycles_since_maint": 3})
		self.assertEqual(frappe.parse_json(updated[0].new_value), {"cycles_since_maint": 4})
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Instrument Maintenance", row.name)
		self.assertTrue(frappe.db.exists("Instrument Maintenance", row.name))
