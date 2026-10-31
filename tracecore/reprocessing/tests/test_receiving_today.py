"""Phiếu đã tiếp nhận hôm nay tại trạm T1 (A-67): danh sách chỉ đọc cho mọi người có quyền ở trạm, và chi tiết bộ của phiếu."""

from datetime import timedelta

import frappe
from frappe.utils import get_datetime, now_datetime, nowdate

from tracecore.reprocessing import receiving
from tracecore.reprocessing.tests.receiving_case import STATION, ReceivingCase
from tracecore.tests.factories import make_employee

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestReceivedToday(ReceivingCase):
	def submitted(self, statuses=("At Department",), flag_first=False, receiver=None):
		"""Phiếu đã ghi sổ của `receiver` (mặc định người nhận của test) gồm các bộ ở `statuses`; trả (phiếu, các bộ)."""
		receiver = receiver or self.receiver
		receipt = receiving.open_receipt(STATION, receiver, raw=self.card, client_ts=self.now())["receipt"]
		units = []
		for index, status in enumerate(statuses):
			unit = self.new_set(status)
			receiving.scan_set(receipt, unit, STATION, receiver, client_ts=self.now())
			note = "Thiếu nắp" if flag_first and index == 0 else None
			receiving.confirm_line(
				receipt, unit, STATION, receiver, confirm_all=True, note=note, finalize=True
			)
			units.append(unit)
		receiving.submit(receipt, STATION, receiver, client_ts=self.now())
		return receipt, units

	def today(self, station=STATION):
		return receiving.received_today(station)

	def rows(self, station=STATION):
		return {row["receipt"]: row for row in self.today(station)["receipts"]}

	def test_lists_submitted_receipt_with_people_department_and_counts(self):
		receipt, _units = self.submitted(("At Department", "New"), flag_first=True)
		row = self.rows()[receipt]
		self.assertEqual((row["set_count"], row["flagged_count"]), (2, 1))
		self.assertEqual(row["department"], self.department)
		self.assertEqual(row["deliverer"], self.deliverer.name)
		self.assertEqual(row["deliverer_name"], self.deliverer.employee_name)
		self.assertEqual(row["receiver"], self.receiver)
		self.assertEqual(
			row["receiver_name"], frappe.db.get_value("Employee", self.receiver, "employee_name")
		)
		self.assertTrue(row["department_name"])
		self.assertTrue(row["received_at"])

	def test_deliverer_without_card_shows_the_typed_name(self):
		receipt = receiving.open_receipt(
			STATION,
			self.receiver,
			department=self.department,
			deliverer_name="Điều dưỡng A",
			client_ts=self.now(),
		)["receipt"]
		unit = self.new_set()
		receiving.scan_set(receipt, unit, STATION, self.receiver, client_ts=self.now())
		receiving.confirm_line(receipt, unit, STATION, self.receiver, confirm_all=True, finalize=True)
		receiving.submit(receipt, STATION, self.receiver, client_ts=self.now())
		row = self.rows()[receipt]
		self.assertFalse(row["deliverer"])
		self.assertEqual(row["deliverer_name"], "Điều dưỡng A")

	def test_excludes_drafts_dropped_cancelled_other_station_and_other_days(self):
		draft = self.opened()
		dropped, _units = self.submitted()
		frappe.db.set_value("Dirty Receipt", dropped, "abandoned", 1, update_modified=False)
		cancelled, _units = self.submitted()
		frappe.db.set_value("Dirty Receipt", cancelled, "docstatus", 2, update_modified=False)
		elsewhere, _units = self.submitted()
		frappe.db.set_value("Dirty Receipt", elsewhere, "station", "TR-OTHER", update_modified=False)
		yesterday, _units = self.submitted()
		frappe.db.set_value(
			"Dirty Receipt",
			yesterday,
			"received_at",
			get_datetime(now_datetime()) - timedelta(days=1),
			update_modified=False,
		)
		kept, _units = self.submitted()
		rows = self.rows()
		self.assertIn(kept, rows)
		for name in (draft, dropped, cancelled, elsewhere, yesterday):
			self.assertNotIn(name, rows)

	def test_shows_receipts_of_every_receiver_newest_first(self):
		first, _units = self.submitted()
		other = make_employee(first_name="Other receiver").name
		second, _units = self.submitted(receiver=other)
		# đầu ngày thay vì lùi vài phút: chạy ngay sau nửa đêm thì lùi sẽ rơi sang hôm qua
		older = get_datetime(nowdate())
		frappe.db.set_value("Dirty Receipt", first, "received_at", older, update_modified=False)
		names = [row["receipt"] for row in self.today()["receipts"]]
		self.assertEqual({first, second} - set(names), set())
		self.assertLess(names.index(second), names.index(first))

	def test_totals_count_receipts_sets_and_flagged_sets(self):
		before = self.today()
		self.submitted(("At Department", "New", "Awaiting Receipt"), flag_first=True)
		self.submitted(("At Department",))
		after = self.today()
		self.assertEqual(after["total_receipts"] - before["total_receipts"], 2)
		self.assertEqual(after["total_sets"] - before["total_sets"], 4)
		self.assertEqual(after["total_flagged"] - before["total_flagged"], 1)

	def test_receipt_sets_returns_sets_with_name_and_current_status(self):
		receipt, units = self.submitted(("At Department", "New"))
		sets = {row["set_id"]: row for row in receiving.receipt_sets(receipt, STATION)}
		self.assertEqual(sorted(sets), sorted(units))
		set_name = frappe.db.get_value("Instrument Set Type", self.set_type, "set_type_name")
		for unit in units:
			self.assertEqual(sets[unit]["set_name"], set_name)
			self.assertEqual(sets[unit]["status"], "Processing")
		frappe.db.set_value("Set Unit", units[0], "status", "Sterile", update_modified=False)
		sets = {row["set_id"]: row for row in receiving.receipt_sets(receipt, STATION)}
		self.assertEqual(sets[units[0]]["status"], "Sterile")

	def test_receipt_sets_rejects_draft_and_other_station_receipts(self):
		draft = self.opened()
		self.assertEqual(self.code_of(receiving.receipt_sets, draft, STATION), "RECEIPT_NOT_FOUND")
		receipt, _units = self.submitted()
		self.assertEqual(self.code_of(receiving.receipt_sets, receipt, "TR-OTHER"), "RECEIPT_NOT_FOUND")
		self.assertEqual(self.code_of(receiving.receipt_sets, "NO-SUCH", STATION), "RECEIPT_NOT_FOUND")
