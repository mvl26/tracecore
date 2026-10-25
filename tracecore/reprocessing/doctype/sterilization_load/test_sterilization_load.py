import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import code_registry
from tracecore.setup.permissions import build_custom_docperms, load_permission_matrix
from tracecore.tests.factories import (
	make_load,
	make_load_ready_pack,
	make_sterilize_program,
	make_sterilizer,
)
from tracecore.tests.utils import bru

test_ignore = ["Employee", "Item", "Batch", "User"]


class TestSterilizationLoad(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.machine = make_sterilizer()
		self.program = make_sterilize_program(self.machine.name)
		self.pack = make_load_ready_pack()

	@bru("BRU-REP-016")
	def test_code_is_series_me_yymmdd_nn_and_registered(self):
		first = make_load(self.machine, self.program, [self.pack])
		second = make_load(self.machine, self.program, [make_load_ready_pack()])
		for load in (first, second):
			self.assertRegex(load.name, r"^ME-\d{6}-\d{2}$")
			self.assertEqual(
				frappe.db.get_value(
					"Code Registry", load.name, ["prefix", "ref_doctype", "ref_name", "status"]
				),
				("ME", "Sterilization Load", load.name, "Active"),
			)
			self.assertTrue(code_registry.is_issued(load.name))
		self.assertNotEqual(first.name, second.name)
		self.assertEqual(first.name[:10], second.name[:10])  # cùng ngày thì cùng ME-YYMMDD-
		self.assertEqual(first.status, "Running")

	@bru("BRU-REP-016")
	def test_code_cannot_be_typed(self):
		doc = frappe.get_doc(
			{
				"doctype": "Sterilization Load",
				"name": "ME-999999-99",
				"equipment": self.machine.name,
				"program": self.program.name,
				"operator": "HR-EMP-TEST",
				"started_at": frappe.utils.now_datetime(),
				"packs": [{"pack": self.pack.name}],
			}
		)
		doc.flags.tc_sterilizing = True
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
		self.assertNotEqual(doc.name, "ME-999999-99")
		self.assertTrue(re.fullmatch(r"ME-\d{6}-\d{2}", doc.name))

	def test_load_is_created_only_by_the_service(self):
		doc = frappe.get_doc(
			{
				"doctype": "Sterilization Load",
				"equipment": self.machine.name,
				"program": self.program.name,
				"operator": "HR-EMP-TEST",
				"started_at": frappe.utils.now_datetime(),
				"packs": [{"pack": self.pack.name}],
			}
		)
		doc.flags.ignore_links = True
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_cannot_be_deleted_or_cancelled(self):
		load = make_load(self.machine, self.program, [self.pack])
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Sterilization Load", load.name, ignore_permissions=True, force=True)
		self.assertTrue(frappe.db.exists("Sterilization Load", load.name))
		load.flags.tc_sterilizing = True
		load.submit()
		self.assertEqual(load.docstatus, 1)
		with self.assertRaises(frappe.ValidationError):
			load.cancel()
		self.assertEqual(frappe.db.get_value("Sterilization Load", load.name, "docstatus"), 1)

	def test_service_fields_are_guarded_from_desk_edits(self):
		load = make_load(self.machine, self.program, [self.pack])

		def reload():
			doc = frappe.get_doc("Sterilization Load", load.name)
			doc.flags.ignore_links = True  # operator là mã giả, không phải Employee thật
			return doc

		doc = reload()
		doc.status = "Released"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
		doc = reload()
		doc.append("packs", {"pack": make_load_ready_pack().name})
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
		doc = reload()
		doc.status = "Cycle Complete"
		doc.flags.tc_sterilizing = True
		doc.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Sterilization Load", load.name, "status"), "Cycle Complete")

	def test_same_pack_twice_in_one_load_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_load(self.machine, self.program, [self.pack, self.pack])

	def test_load_requires_at_least_one_pack(self):
		with self.assertRaises(frappe.ValidationError):
			make_load(self.machine, self.program, [])

	def test_pack_load_field_is_guarded_from_desk_edits(self):
		load = make_load(self.machine, self.program, [self.pack])
		pack = frappe.get_doc("Pack", self.pack.name)
		self.assertEqual(pack.load, load.name)
		pack.load = None
		with self.assertRaises(frappe.ValidationError):
			pack.save(ignore_permissions=True)
		pack = frappe.get_doc("Pack", self.pack.name)
		pack.load = None
		pack.flags.tc_packing = True
		pack.save(ignore_permissions=True)
		self.assertFalse(frappe.db.get_value("Pack", self.pack.name, "load"))

	def test_permissions_match_ba_matrix(self):
		row = {r.doctype: r for r in load_permission_matrix()}["Sterilization Load"]
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
		records = [
			r for r in build_custom_docperms({"Sterilization Load"}) if r["parent"] == "Sterilization Load"
		]
		roles = {r["role"]: r for r in records}
		self.assertEqual(set(roles), {f"TC R{i:02d}" for i in (1, 2, 3, 4, 5, 6, 8, 9, 10)})
		self.assertEqual((roles["TC R05"].get("submit"), roles["TC R05"].get("write")), (1, 1))
		self.assertEqual((roles["TC R09"].get("write"), roles["TC R09"].get("submit")), (None, None))
		self.assertTrue(all(not r.get("delete") for r in records))
