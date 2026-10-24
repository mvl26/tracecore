"""Mở phiếu tiếp nhận T1 (FEAT-019 Task 3; FR-M2-01, FR-M2-01.1, FR-M2-01.5, FR-M2-01.7; AC-01, AC-02, AC-05)."""

import frappe

from tracecore.core.errors import BlockedError
from tracecore.reprocessing import receiving
from tracecore.reprocessing.tests.receiving_case import STATION, ReceivingCase
from tracecore.tests.factories import make_department, make_employee
from tracecore.tests.utils import bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestReceivingOpen(ReceivingCase):
	@bru("BRU-REP-012")
	def test_card_scan_derives_department_and_records_receiver_station_time(self):
		view = self.open(self.card)
		self.assertTrue(view["receipt"].startswith("RC-"))
		self.assertEqual(view["department"], self.department)
		self.assertEqual(view["deliverer"], self.deliverer.name)
		self.assertEqual(view["deliverer_name"], self.deliverer.employee_name)
		self.assertFalse(view["needs_card"])
		self.assertEqual(view["items"], [])
		doc = frappe.get_doc("Dirty Receipt", view["receipt"])
		self.assertEqual((doc.receiver, doc.station, doc.docstatus), (self.receiver, STATION, 0))
		self.assertTrue(doc.opened_at)

	@bru("BRU-REP-012")
	def test_employee_card_in_hospital_format_is_recognised(self):
		frappe.db.set_value("Employee", self.deliverer.name, "tc_card_id", "NV-00731")
		self.assertEqual(self.open("NV-00731")["deliverer"], self.deliverer.name)

	@bru("BRU-ID-006")
	def test_unknown_code_is_invalid_code(self):
		self.assertEqual(self.code_of(self.open, "NOT-A-CARD"), "SCAN_INVALID")
		self.assertEqual(self.code_of(self.open, "NV-99999"), "DELIVERER_NOT_FOUND")  # đúng dạng thẻ, chưa cấp
		# mã loại khác (Set ID, máy…) không thay cho thẻ người giao
		self.assertEqual(self.code_of(self.open, "TB-0001"), "SCAN_INVALID")

	def test_disabled_card_or_inactive_employee_is_not_found(self):
		frappe.db.set_value("Employee", self.deliverer.name, "tc_card_enabled", 0)
		self.assertEqual(self.code_of(self.open, self.card), "DELIVERER_NOT_FOUND")
		frappe.db.set_value("Employee", self.deliverer.name, {"tc_card_enabled": 1, "status": "Left"})
		self.assertEqual(self.code_of(self.open, self.card), "DELIVERER_NOT_FOUND")

	def test_deliverer_without_department_is_refused(self):
		card = "DLV-NODEPT"
		make_employee(card=card, first_name="No department")
		self.assertEqual(self.code_of(self.open, card), "DELIVERER_NO_DEPARTMENT")

	@bru("BRU-REP-012")
	def test_deliverer_without_card_picks_department_and_types_name(self):
		view = self.open(department=self.department, deliverer_name="  Nguyen Van A ")
		self.assertEqual((view["deliverer"], view["deliverer_name"]), (None, "Nguyen Van A"))
		self.assertTrue(view["needs_card"])  # R02 cấp thẻ sau (FR-M2-01.7)

	def test_manual_deliverer_needs_name_and_a_real_department(self):
		self.assertEqual(
			self.code_of(self.open, department=self.department, deliverer_name="  "), "DELIVERER_NAME_REQUIRED"
		)
		self.assertEqual(self.code_of(self.open, department="No such department", deliverer_name="A"), "DEPARTMENT_INVALID")
		root = frappe.get_doc({"doctype": "Department", "department_name": "Group dept", "is_group": 1})
		root.flags.ignore_mandatory = True
		root.insert(ignore_permissions=True)
		self.assertEqual(self.code_of(self.open, department=root.name, deliverer_name="A"), "DEPARTMENT_INVALID")

	def test_open_without_arguments_resumes_the_latest_draft_of_this_receiver_and_station(self):
		self.assertIsNone(self.open())
		first = self.open(self.card)["receipt"]
		self.assertEqual(self.open()["receipt"], first)
		other = receiving.open_receipt(STATION, make_employee(first_name="Other").name, self.now(), raw=self.card)
		self.assertNotEqual(other["receipt"], first)
		self.assertEqual(self.open()["receipt"], first)  # phiếu của người khác không lẫn vào

	def test_scanning_a_new_card_abandons_the_previous_draft(self):
		first = self.open(self.card)["receipt"]
		second = self.open(self.card)["receipt"]
		self.assertNotEqual(first, second)
		self.assertEqual(frappe.db.get_value("Dirty Receipt", first, "abandoned"), 1)
		self.assertEqual(self.open()["receipt"], second)

	def test_discard_keeps_the_record_but_closes_the_draft(self):
		name = self.open(self.card)["receipt"]
		receiving.discard(name, STATION, self.receiver)
		self.assertEqual(frappe.db.get_value("Dirty Receipt", name, ["abandoned", "docstatus"]), (1, 0))
		self.assertIsNone(self.open())
		self.assertEqual(self.code_of(receiving.discard, name, STATION, self.receiver), "RECEIPT_CLOSED")

	def test_someone_elses_draft_is_not_found(self):
		name = self.open(self.card)["receipt"]
		stranger = make_employee(first_name="Stranger").name
		self.assertEqual(self.code_of(receiving.discard, name, STATION, stranger), "RECEIPT_NOT_FOUND")
		self.assertEqual(self.code_of(receiving.discard, "RC-0000-00000", STATION, self.receiver), "RECEIPT_NOT_FOUND")

	def test_open_lists_departments_when_no_draft_exists(self):
		names = {row["name"] for row in receiving.departments()}
		self.assertIn(self.department, names)
		self.assertNotIn(make_department("Test operating room") + "x", names)

	def test_blocked_error_carries_result_reason_action(self):
		with self.assertRaises(BlockedError) as caught:
			self.open("NOT-A-CARD")
		block = caught.exception.block
		self.assertTrue(block.title and block.reason and block.action)
