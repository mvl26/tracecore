"""Cost Entry từ Maintenance Record đã ghi sổ (FEAT-044; FR-M5-04.3 phía M7; UC-27 A1; architecture A-47 C9)."""

import frappe
from frappe.utils import add_days, today

from tracecore.costing import from_maintenance
from tracecore.tests.factories import make_equipment, make_maintenance_record
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

ENTRY = "Cost Entry"
SOURCE = "Maintenance Record"


def entries_of(record):
	return frappe.get_all(
		ENTRY,
		filters={"source_doctype": SOURCE, "source_name": record.name},
		fields=["name", "category", "amount", "period_from", "period_to", "docstatus", "source"],
	)


class TestEntryFromMaintenance(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.machine = make_equipment()

	def submitted(self, kind="Preventive", **kwargs):
		values = {"cost": 2000000, "performed_on": today()}
		if kind == "Incident":
			values["post_repair_check"] = "Máy chạy tốt sau sửa"
		values.update(kwargs)
		doc = make_maintenance_record(self.machine.name, kind, **values)
		doc.submit()
		return doc

	def test_incident_with_cost_creates_a_draft_repair_entry(self):  # FR-M5-04.3
		record = self.submitted("Incident")
		(row,) = entries_of(record)
		self.assertEqual(
			(row.category, row.amount, row.docstatus, row.source), ("Repair Expense", 2000000, 0, "Invoice")
		)
		self.assertEqual((str(row.period_from), str(row.period_to)), (today(), today()))
		entry = frappe.get_doc(ENTRY, row.name)
		self.assertEqual(
			[(r.target_type, r.target, r.percent) for r in entry.allocations],
			[("Equipment", self.machine.name, 100)],
		)

	def test_other_record_types_create_a_maintenance_entry(self):
		for kind in ("Preventive", "Inspection", "Calibration"):
			extra = (
				{"certificate": "/files/cn.pdf", "valid_until": add_days(today(), 365)}
				if kind != "Preventive"
				else {}
			)
			with self.subTest(kind=kind):
				record = self.submitted(kind, **extra)
				(row,) = entries_of(record)
				self.assertEqual(row.category, "Maintenance Cost")

	def test_entry_uses_the_day_the_work_was_done(self):
		record = self.submitted("Preventive", performed_on=add_days(today(), -3))
		(row,) = entries_of(record)
		self.assertEqual((str(row.period_from), str(row.period_to)), (add_days(today(), -3),) * 2)

	def test_zero_cost_creates_nothing(self):
		self.assertEqual(entries_of(self.submitted("Preventive", cost=0)), [])

	def test_handler_is_idempotent(self):
		record = self.submitted("Incident")
		from_maintenance.on_maintenance_submit(record)
		from_maintenance.on_maintenance_submit(record)
		self.assertEqual(len(entries_of(record)), 1)

	def test_parts_are_listed_in_the_description(self):
		record = self.submitted(
			"Incident",
			parts=[
				{"part_name": "Gioăng cửa", "qty": 2, "rate": 150000},
				{"part_name": "Van", "qty": 1, "rate": 500000},
			],
		)
		(row,) = entries_of(record)
		description = frappe.db.get_value(ENTRY, row.name, "description")
		self.assertIn("Gioăng cửa", description)
		self.assertIn("Van", description)
		self.assertIn(record.name, description)

	def test_accountant_confirms_and_submits_the_draft(self):
		record = self.submitted("Incident")
		(row,) = entries_of(record)
		entry = frappe.get_doc(ENTRY, row.name)
		entry.submit()
		self.assertEqual(frappe.db.get_value(ENTRY, row.name, "docstatus"), 1)

	def test_draft_cannot_be_submitted_after_its_source_is_cancelled(self):
		record = self.submitted("Incident")
		(row,) = entries_of(record)
		record.reload()
		record.cancel()
		entry = frappe.get_doc(ENTRY, row.name)
		with self.assertRaises(frappe.ValidationError):
			entry.submit()
		self.assertEqual(frappe.db.get_value(ENTRY, row.name, "docstatus"), 0)

	def test_closed_period_does_not_block_the_maintenance_record(self):
		frappe.db.set_single_value("Cost Settings", "locked_until", today())
		record = self.submitted("Incident")
		self.assertEqual(frappe.db.get_value(SOURCE, record.name, "docstatus"), 1)
		self.assertEqual(entries_of(record), [])
		comments = frappe.get_all(
			"Comment", filters={"reference_doctype": SOURCE, "reference_name": record.name}, pluck="content"
		)
		self.assertTrue(any("Cost Settings" in c for c in comments), comments)

	def test_costing_does_not_import_equipment(self):
		import tracecore.costing.from_maintenance as module

		self.assertNotIn("tracecore.equipment", open(module.__file__, encoding="utf-8").read())
