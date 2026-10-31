import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.setup.permissions import build_custom_docperms, load_permission_matrix
from tracecore.tests.factories import make_department, make_employee, make_set_unit
from tracecore.tests.utils import assert_permission_matrix, bru

test_ignore = ["Employee", "User", "Department"]


def make_receipt(flags=True, **fields):
	"""Dirty Receipt nháp dựng trực tiếp (không qua dịch vụ) để test ràng buộc của DocType."""
	doc = frappe.get_doc(
		{
			"doctype": "Dirty Receipt",
			"department": make_department(),
			"receiver": make_employee().name,
			"station": "TR-001",
			**fields,
		}
	)
	doc.flags.tc_receiving = flags
	doc.flags.ignore_links = True
	return doc.insert(ignore_permissions=True)


class TestDirtyReceipt(FrappeTestCase):
	def test_name_follows_series_rc_year(self):
		doc = make_receipt()
		self.assertRegex(doc.name, r"^RC-\d{4}-\d{5}$")
		self.assertEqual(doc.docstatus, 0)

	@bru("BRU-REP-012")
	def test_only_the_receiving_service_creates_and_changes_a_receipt(self):
		with self.assertRaises(frappe.ValidationError):
			make_receipt(flags=False)
		doc = make_receipt()
		doc.flags.tc_receiving = False
		doc.department = make_department("Another department")
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
		doc = frappe.get_doc("Dirty Receipt", doc.name)
		with self.assertRaises(frappe.ValidationError):
			doc.submit()

	def test_same_set_twice_is_rejected(self):
		unit = make_set_unit().name
		doc = make_receipt()
		doc.append("items", {"set_unit": unit})
		doc.append("items", {"set_unit": unit})
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_receipt_is_not_deleted_or_cancelled(self):
		doc = make_receipt()
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Dirty Receipt", doc.name, ignore_permissions=True, force=True)
		self.assertTrue(frappe.db.exists("Dirty Receipt", doc.name))
		doc.flags.tc_receiving = True
		doc.submit()
		with self.assertRaises(frappe.ValidationError):
			doc.cancel()

	def test_confirm_line_keeps_no_received_quantity(self):
		# FR-M2-23.2: ghi bất thường chỉ có văn bản, không lưu số lượng thực nhận
		fields = {f.fieldname for f in frappe.get_meta("Dirty Receipt Confirm Line").fields}
		self.assertEqual(
			fields, {"set_unit", "instrument", "instrument_name", "qty", "position", "confirmed"}
		)

	def test_permissions_match_ba_matrix(self):
		row = {r.doctype: r for r in load_permission_matrix()}["Dirty Receipt"]
		self.assertEqual(row.code, "DT-RECEIPT")
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
		records = [r for r in build_custom_docperms({"Dirty Receipt"}) if r["parent"] == "Dirty Receipt"]
		self.assertTrue(records)
		self.assertTrue(all(not r.get("delete") for r in records))
		self.assertFalse(re.search("R07", " ".join(r["role"] for r in records)))
		assert_permission_matrix(self, "Dirty Receipt")


class TestDirtyReceiptDeliverer(FrappeTestCase):
	@bru("BRU-REP-012")
	def test_deliverer_without_card_stays_empty(self):  # FR-M2-01.7, A-30
		doc = make_receipt(needs_card=1, deliverer=make_employee().name, deliverer_name="Người giao")
		self.assertIsNone(frappe.db.get_value("Dirty Receipt", doc.name, "deliverer"))
		self.assertEqual(frappe.db.get_value("Dirty Receipt", doc.name, "deliverer_name"), "Người giao")

	def test_deliverer_with_card_is_kept(self):
		deliverer = make_employee().name
		doc = make_receipt(needs_card=0, deliverer=deliverer)
		self.assertEqual(frappe.db.get_value("Dirty Receipt", doc.name, "deliverer"), deliverer)

	def test_desk_does_not_fill_deliverer_from_user_permission(self):
		field = frappe.get_meta("Dirty Receipt").get_field("deliverer")
		self.assertTrue(field.ignore_user_permissions)
