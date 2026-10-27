"""T1 tiếp nhận offline: cả phiếu thành một lệnh khi phát lại (FEAT-009 Task 5; UC-05 E3, FR-M9-06; A-40 D3)."""

from datetime import timedelta

import frappe

from tracecore.core.errors import BlockedError
from tracecore.reprocessing import receiving
from tracecore.reprocessing.tests.receiving_case import BOM, STATION, ReceivingCase


class TestSubmitOffline(ReceivingCase):
	def payload(self, *units, **overrides):
		return {
			"deliverer_raw": self.card,
			"items": [{"set_id": unit, "confirm_all": 1, "note": None} for unit in units],
			**overrides,
		}

	def test_submit_offline_receipt_all_sets(self):
		first, second = self.new_set(), self.new_set("Awaiting Receipt")
		moment = self.now() - timedelta(hours=3)
		result = receiving.submit_offline(STATION, self.receiver, moment, self.payload(first, second))
		self.assertEqual(sorted(result["sets"]), sorted([first, second]))
		doc = frappe.get_doc("Dirty Receipt", result["receipt"])
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.deliverer, self.deliverer.name)
		for unit in (first, second):
			self.assertEqual(frappe.db.get_value("Set Unit", unit, "status"), "Processing")

	def test_submit_offline_manual_deliverer_and_line_ticks(self):
		unit = self.new_set()
		payload = {
			"department": self.department,
			"deliverer_name": "Điều dưỡng A",
			"items": [
				{
					"set_id": unit,
					"lines": [{"instrument": code, "confirmed": 1} for code, _qty in BOM],
					"note": "Thiếu nắp hộp",
				}
			],
		}
		result = receiving.submit_offline(STATION, self.receiver, self.now(), payload)
		doc = frappe.get_doc("Dirty Receipt", result["receipt"])
		self.assertEqual((doc.needs_card, doc.deliverer_name), (1, "Điều dưỡng A"))
		self.assertEqual(doc.items[0].abnormal_note, "Thiếu nắp hộp")

	def test_submit_offline_rolls_back_on_one_bad_set(self):
		good, bad = self.new_set(), self.new_set("Sterile")
		receipts = frappe.db.count("Dirty Receipt")
		with self.assertRaises(BlockedError) as caught:
			receiving.submit_offline(STATION, self.receiver, self.now(), self.payload(good, bad))
		self.assertEqual(caught.exception.block.code, "STATUS_INVALID_FOR_STATION")
		self.assertEqual(frappe.db.count("Dirty Receipt"), receipts)
		self.assertEqual(frappe.db.get_value("Set Unit", good, "status"), "At Department")

	def test_submit_offline_keeps_live_draft(self):
		live = self.open(self.card)["receipt"]
		unit = self.new_set()
		receiving.submit_offline(STATION, self.receiver, self.now(), self.payload(unit))
		self.assertEqual(frappe.db.get_value("Dirty Receipt", live, ["docstatus", "abandoned"]), (0, 0))

	def test_submit_offline_empty_rejected(self):
		with self.assertRaises(BlockedError) as caught:
			receiving.submit_offline(STATION, self.receiver, self.now(), self.payload())
		self.assertEqual(caught.exception.block.code, "RECEIPT_EMPTY")
