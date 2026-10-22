import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import code_registry
from tracecore.setup.permissions import build_custom_docperms, load_permission_matrix
from tracecore.tests.factories import (
	make_wash_batch,
	make_wash_machine,
	make_wash_program,
	make_wash_ready_set,
)
from tracecore.tests.utils import bru

test_ignore = ["Employee", "Item", "Batch", "User"]


class TestWashBatch(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.machine = make_wash_machine()
		self.program = make_wash_program(self.machine.name)
		self.unit = make_wash_ready_set()

	@bru("BRU-REP-016")
	def test_code_is_series_lr_yymmdd_nn_and_registered(self):
		first = make_wash_batch(self.machine, self.program, [self.unit])
		second = make_wash_batch(self.machine, self.program, [make_wash_ready_set()])
		for batch in (first, second):
			self.assertRegex(batch.name, r"^LR-\d{6}-\d{2}$")
			self.assertEqual(
				frappe.db.get_value("Code Registry", batch.name, ["prefix", "ref_doctype", "ref_name", "status"]),
				("LR", "Wash Batch", batch.name, "Active"),
			)
			self.assertTrue(code_registry.is_issued(batch.name))
		self.assertNotEqual(first.name, second.name)
		self.assertEqual(first.name[:9], second.name[:9])  # cùng ngày thì cùng LR-YYMMDD-
		self.assertEqual(first.status, "Running")

	@bru("BRU-REP-016")
	def test_code_cannot_be_typed(self):
		doc = frappe.get_doc(
			{
				"doctype": "Wash Batch",
				"name": "LR-999999-99",
				"batch_type": "Machine",
				"equipment": self.machine.name,
				"program": self.program.name,
				"operator": "HR-EMP-TEST",
				"started_at": frappe.utils.now_datetime(),
				"set_units": [{"set_unit": self.unit.name}],
			}
		)
		doc.flags.tc_washing = True
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
		self.assertNotEqual(doc.name, "LR-999999-99")
		self.assertTrue(re.fullmatch(r"LR-\d{6}-\d{2}", doc.name))

	def test_batch_is_created_only_by_the_service(self):
		doc = frappe.get_doc(
			{
				"doctype": "Wash Batch",
				"batch_type": "Machine",
				"equipment": self.machine.name,
				"program": self.program.name,
				"operator": "HR-EMP-TEST",
				"started_at": frappe.utils.now_datetime(),
				"set_units": [{"set_unit": self.unit.name}],
			}
		)
		doc.flags.ignore_links = True
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_cannot_be_deleted_or_cancelled(self):
		batch = make_wash_batch(self.machine, self.program, [self.unit])
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Wash Batch", batch.name, ignore_permissions=True, force=True)
		self.assertTrue(frappe.db.exists("Wash Batch", batch.name))
		batch.flags.tc_washing = True
		batch.submit()
		self.assertEqual(batch.docstatus, 1)
		with self.assertRaises(frappe.ValidationError):
			batch.cancel()
		self.assertEqual(frappe.db.get_value("Wash Batch", batch.name, "docstatus"), 1)

	def test_service_fields_are_guarded_from_desk_edits(self):
		batch = make_wash_batch(self.machine, self.program, [self.unit])

		def load():
			doc = frappe.get_doc("Wash Batch", batch.name)
			doc.flags.ignore_links = True  # operator là mã giả, không phải Employee thật
			return doc

		doc = load()
		doc.status = "Passed"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
		doc = load()
		doc.append("set_units", {"set_unit": make_wash_ready_set().name})
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
		doc = load()
		doc.status = "Passed"
		doc.flags.tc_washing = True
		doc.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Wash Batch", batch.name, "status"), "Passed")

	def test_same_set_twice_in_one_batch_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_wash_batch(self.machine, self.program, [self.unit, self.unit])

	def test_batch_requires_at_least_one_set(self):
		with self.assertRaises(frappe.ValidationError):
			make_wash_batch(self.machine, self.program, [])

	def test_permissions_match_ba_matrix(self):
		row = {r.doctype: r for r in load_permission_matrix()}["Wash Batch"]
		self.assertEqual(
			row.permissions,
			{
				"R01": "RA",
				"R02": "RWSA",
				"R03": "RWS",
				"R04": "RWS",
				"R05": "RWS",
				"R06": "RWS",
				"R07": "",
				"R08": "RW",
				"R09": "R",
				"R10": "R",
			},
		)
		records = [r for r in build_custom_docperms({"Wash Batch"}) if r["parent"] == "Wash Batch"]
		roles = {r["role"]: r for r in records}
		self.assertEqual(set(roles), {f"TC R{i:02d}" for i in (1, 2, 3, 4, 5, 6, 8, 9, 10)})
		self.assertEqual((roles["TC R03"].get("submit"), roles["TC R03"].get("write")), (1, 1))
		self.assertEqual((roles["TC R09"].get("write"), roles["TC R09"].get("submit")), (None, None))
		self.assertEqual((roles["TC R08"].get("write"), roles["TC R08"].get("submit")), (1, None))
		self.assertTrue(all(not r.get("delete") for r in records))
