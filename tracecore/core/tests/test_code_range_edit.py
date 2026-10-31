"""Sửa dải mã offline trên Desk, trùng dải thì báo (A-75; ADR-003, FR-M9-06.2)."""

from unittest.mock import patch

import frappe
from frappe.utils import getdate, today

from tracecore.core import code_range
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, bru

STATION = "TR-004"
test_ignore = ["User"]


def two_ranges():
	first = code_range.allocate(STATION, today())
	second = code_range.allocate(STATION, today())
	return first, frappe.get_doc("Code Range", second["name"])


@bru("BRU-FLOW-004")
class TestCodeRangeEdit(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")

	def as_role(self, email, role):
		frappe.set_user(make_user(email, [role]))

	def test_r10_can_change_the_numbers_of_a_range(self):
		first, second = two_ranges()
		self.as_role("cr-r10@example.com", "TC R10")
		doc = frappe.get_doc("Code Range", first["name"])
		doc.to_no = doc.from_no + 99
		doc.save()
		self.assertEqual(frappe.db.get_value("Code Range", first["name"], "to_no"), doc.from_no + 99)

	def test_r02_can_only_read(self):
		first, _second = two_ranges()
		self.as_role("cr-r02@example.com", "TC R02")
		doc = frappe.get_doc("Code Range", first["name"])
		doc.to_no = doc.from_no + 99
		with self.assertRaises(frappe.PermissionError):
			doc.save()

	def test_overlap_is_saved_but_reported(self):
		first, second = two_ranges()
		with patch("tracecore.core.code_range.notification.emit") as emit:
			second.from_no = first["to_no"] - 10
			frappe.local.message_log = []
			second.save()
		self.assertEqual(emit.call_args.args[0], "CODE_RANGE_OVERLAP")
		self.assertIn(first["name"], emit.call_args.kwargs["message"])
		self.assertTrue(any(first["name"] in str(message) for message in frappe.local.message_log))
		self.assertEqual(frappe.db.get_value("Code Range", second.name, "from_no"), first["to_no"] - 10)

	def test_no_report_when_ranges_stay_apart(self):
		first, second = two_ranges()
		with patch("tracecore.core.code_range.notification.emit") as emit:
			second.to_no = second.to_no - 5
			second.save()
		emit.assert_not_called()

	def test_numbers_must_make_a_range(self):
		first, second = two_ranges()
		for from_no, to_no in ((0, 10), (50, 49), (1, code_range.MAX_NO + 1)):
			second.from_no, second.to_no = from_no, to_no
			with self.assertRaises(frappe.ValidationError):
				second.save()

	def test_station_prefix_and_date_cannot_change(self):
		first, _second = two_ranges()
		doc = frappe.get_doc("Code Range", first["name"])
		doc.prefix = "CY-990101-T009-"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_claim_uses_the_edited_range(self):
		first, _second = two_ranges()
		doc = frappe.get_doc("Code Range", first["name"])
		doc.to_no = doc.to_no + 50  # 250 nằm trong dải thứ hai cũ, đã sửa dải này kéo dài ra
		doc.save()
		code_range.claim(f"{first['prefix']}{doc.to_no:04d}", STATION, getdate(today()))
		self.assertTrue(frappe.db.exists("Code Registry", {"code": f"{first['prefix']}{doc.to_no:04d}"}))
