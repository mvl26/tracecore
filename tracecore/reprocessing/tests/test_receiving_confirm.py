"""Xác nhận thành phần và ghi chú bất thường tại T1 (FEAT-019 Task 5; FR-M2-23.1 đến .7; AC-08..AC-10)."""

import base64
import io

import frappe
from PIL import Image

from tracecore.reprocessing import receiving
from tracecore.reprocessing.tests.receiving_case import BOM, STATION, ReceivingCase
from tracecore.tests.utils import bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def image_b64(fmt="PNG", size=(8, 8)):
	buffer = io.BytesIO()
	Image.new("RGB", size, (200, 30, 30)).save(buffer, format=fmt)
	return base64.b64encode(buffer.getvalue()).decode()


class TestReceivingConfirm(ReceivingCase):
	def setUp(self):
		super().setUp()
		self.receipt = self.opened()
		self.unit = self.new_set()
		self.scan(self.receipt, self.unit)

	def confirm(self, **kwargs):
		return receiving.confirm_line(self.receipt, self.unit, STATION, self.receiver, **kwargs)

	def lines(self):
		return {
			row.instrument: row.confirmed
			for row in frappe.get_doc("Dirty Receipt", self.receipt).confirm_lines
			if row.set_unit == self.unit
		}

	@bru("BRU-REP-012")
	def test_confirm_all_ticks_every_line_in_one_call(self):
		item = self.confirm(confirm_all=True)
		self.assertTrue(all(line["confirmed"] for line in item["lines"]))
		self.assertEqual(set(self.lines().values()), {1})
		self.assertEqual((item["lines_confirmed"], item["lines_total"]), (len(BOM), len(BOM)))

	def test_individual_lines_can_be_ticked_and_unticked(self):
		self.confirm(lines=[{"instrument": "RV-KC-01", "confirmed": 1}, {"instrument": "RV-KC-03", "confirmed": 1}])
		self.assertEqual(self.lines(), {"RV-KC-01": 1, "RV-KC-02": 0, "RV-KC-03": 1})
		self.confirm(lines=[{"instrument": "RV-KC-01", "confirmed": 0}])
		self.assertEqual(self.lines()["RV-KC-01"], 0)

	def test_line_that_is_not_in_the_bom_is_refused(self):
		self.assertEqual(
			self.code_of(self.confirm, lines=[{"instrument": "RV-KC-99", "confirmed": 1}]), "BOM_LINE_INVALID"
		)

	def test_set_that_is_not_on_the_receipt_is_refused(self):
		self.assertEqual(
			self.code_of(receiving.confirm_line, self.receipt, self.new_set(), STATION, self.receiver, confirm_all=True),
			"SET_NOT_FOUND",
		)

	@bru("BRU-REP-012")
	def test_abnormal_note_is_text_only_and_flags_the_set_for_review(self):
		item = self.confirm(note="  Thiếu 1 kẹp, có vật lạ  ")
		self.assertEqual((item["note"], item["needs_review"]), ("Thiếu 1 kẹp, có vật lạ", 1))
		doc = frappe.get_doc("Dirty Receipt", self.receipt)
		self.assertEqual((doc.items[0].needs_review, doc.flagged_count), (1, 1))
		item = self.confirm(note="")
		self.assertEqual((item["note"], item["needs_review"]), (None, 0))
		self.assertEqual(frappe.db.get_value("Dirty Receipt", self.receipt, "flagged_count"), 0)

	def test_note_left_alone_when_not_sent(self):
		self.confirm(note="Gỉ sét")
		item = self.confirm(confirm_all=True)
		self.assertEqual(item["note"], "Gỉ sét")

	@bru("BRU-REP-012")
	def test_finalize_with_every_line_ticked(self):
		item = self.confirm(confirm_all=True, finalize=True)
		self.assertEqual(item["confirmed"], 1)

	@bru("BRU-REP-012")
	def test_finalize_reminds_when_lines_are_unticked_and_there_is_no_note(self):
		self.confirm(lines=[{"instrument": "RV-KC-01", "confirmed": 1}])
		with self.assertRaises(receiving.BlockedError) as caught:
			self.confirm(finalize=True)
		block = caught.exception.block
		self.assertEqual(block.code, "CONFIRM_INCOMPLETE")
		self.assertEqual(len(block.items), 2)  # hai dòng chưa tick
		self.assertEqual(frappe.get_doc("Dirty Receipt", self.receipt).items[0].confirmed, 0)
		self.assertEqual(self.confirm(finalize=True, ack_incomplete=True)["confirmed"], 1)

	def test_finalize_without_reminder_when_a_note_explains_the_gap(self):
		self.assertEqual(self.confirm(note="Thiếu 2 dụng cụ", finalize=True)["confirmed"], 1)

	@bru("BRU-REP-012")
	def test_edits_stay_possible_until_the_receipt_is_submitted_and_reopen_the_set(self):
		self.confirm(confirm_all=True, finalize=True)
		item = self.confirm(lines=[{"instrument": "RV-KC-02", "confirmed": 0}])
		self.assertEqual(item["confirmed"], 0)  # sửa xong phải Xác nhận bộ lại
		self.confirm(note="Hỏng bản lề", finalize=True)
		receiving.discard(self.receipt, STATION, self.receiver)
		self.assertEqual(self.code_of(self.confirm, confirm_all=True), "RECEIPT_CLOSED")


class TestReceivingPhoto(ReceivingCase):
	def setUp(self):
		super().setUp()
		self.receipt = self.opened()
		self.unit = self.new_set()
		self.scan(self.receipt, self.unit)

	def attach(self, content, name="anh.png"):
		return receiving.attach_photo(self.receipt, self.unit, STATION, self.receiver, name, content)

	def test_valid_photo_is_stored_privately_and_flags_the_set(self):
		item = self.attach(image_b64("PNG"))
		self.assertTrue(item["photo"].startswith("/private/files/"))
		self.assertEqual(item["needs_review"], 1)
		file_doc = frappe.get_doc("File", {"file_url": item["photo"]})
		self.assertEqual(
			(file_doc.attached_to_doctype, file_doc.attached_to_name, file_doc.is_private),
			("Dirty Receipt", self.receipt, 1),
		)

	def test_jpeg_and_webp_are_accepted_and_a_new_photo_replaces_the_old_one(self):
		first = self.attach(image_b64("JPEG"))["photo"]
		second = self.attach(image_b64("WEBP"))["photo"]
		self.assertNotEqual(first, second)
		self.assertEqual(frappe.get_doc("Dirty Receipt", self.receipt).items[0].abnormal_photo, second)

	def test_photo_content_is_checked_not_the_file_name(self):
		for content in (
			base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'/>").decode(),
			base64.b64encode(b"plain text").decode(),
			"%%% not base64 %%%",
			image_b64("GIF"),
		):
			self.assertEqual(self.code_of(self.attach, content, "anh.jpg"), "PHOTO_INVALID", content[:20])

	def test_oversize_photo_is_refused(self):
		big = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * receiving.PHOTO_MAX_BYTES).decode()
		self.assertEqual(self.code_of(self.attach, big), "PHOTO_INVALID")

	def test_photo_alone_does_not_confirm_lines(self):
		self.attach(image_b64())
		self.assertEqual(frappe.get_doc("Dirty Receipt", self.receipt).items[0].confirmed, 0)
