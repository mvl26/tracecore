"""Thu hồi (FEAT-029, UC-14, FR-M2-20, FR-M2-11.7, BRU-REP-007): Recall Order, khóa gói, xác nhận, đóng, hook, nhắc."""

import frappe
from frappe.utils import add_to_date, now_datetime

from tracecore.core.errors import BlockedError
from tracecore.reprocessing import issuing, recall, usage
from tracecore.reprocessing.tests.test_usage import issue
from tracecore.tests import factories
from tracecore.tests.factories import make_department, make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

T8 = "TR-008"


def blocked(case, code, fn, *args, **kwargs):
	with case.assertRaises(BlockedError) as caught:
		fn(*args, **kwargs)
	case.assertEqual(caught.exception.block.code, code)
	return caught.exception.block


class RecallCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r01 = make_user("th-r01@example.com", ["TC R01"])
		self.r02 = make_user("th-r02@example.com", ["TC R02"])
		self.r06 = make_user("th-r06@example.com", ["TC R06"])
		self.dept = make_department("Khoa thu hồi A")
		self.other_dept = make_department("Khoa thu hồi B")
		self.ward_user = make_user("th-r08@example.com", ["TC R08"])
		self.stranger = make_user("th-r08-b@example.com", ["TC R08"])
		make_employee(first_name="Điều dưỡng A", department=self.dept, user_id=self.ward_user)
		make_employee(first_name="Điều dưỡng B", department=self.other_dept, user_id=self.stranger)
		self.nurse = make_employee(first_name="Người dùng gói", department=self.dept).name
		self.equipment = factories.make_sterilizer(name="Máy hấp thu hồi").name
		program = factories.make_sterilize_program(self.equipment)
		self.load = factories.make_load(self.equipment, program, [factories.make_load_ready_pack()]).name
		self.addCleanup(frappe.set_user, "Administrator")

	def on_load(self, pack):
		frappe.db.set_value("Pack", pack.name, "load", self.load, update_modified=False)
		return frappe.get_doc("Pack", pack.name)

	def affected(self):
		"""Bốn gói của mẻ: vừa giải phóng, trong kho, đã cấp cho khoa A, đã dùng cho bệnh nhân ở khoa A."""
		released = self.on_load(factories.make_released_pack())
		stocked = self.on_load(factories.make_stocked_pack())
		issued = self.on_load(issue(factories.make_stocked_pack(), self.dept))
		used = self.on_load(issue(factories.make_stocked_pack(), self.dept))
		usage.confirm(used.name, T8, self.nurse, patient_code="BN12345678", surgery_code="CA-1")
		return released, stocked, issued, used

	def lines(self, order):
		return {row.pack: row for row in frappe.get_doc("Recall Order", order).packs}

	def notices(self, user):
		return frappe.get_all(
			"Notification Log",
			filters={"for_user": user, "document_type": "Recall Order"},
			pluck="document_name",
		)


class TestCreate(RecallCase):
	@bru("BRU-REP-007")
	def test_order_lists_every_affected_pack_and_locks_it(self):
		# FR-M2-20, FR-M2-20.1: Trong kho (khóa) / Đã cấp (chờ thu) / Đã dùng (báo bác sĩ); không nhập tay
		released, stocked, issued, used = self.affected()
		frappe.set_user(self.r02)
		order = recall.create(load=self.load, reason="Phát hiện rò hơi sau giải phóng")
		self.assertTrue(order.name.startswith("TH-"))
		self.assertEqual((order.status, order.docstatus, order.trigger), ("Open", 0, "Opened Manually"))
		lines = self.lines(order.name)
		self.assertEqual(set(lines), {released.name, stocked.name, issued.name, used.name})
		self.assertEqual(lines[released.name].action, "Lock in Stock")
		self.assertEqual(lines[stocked.name].action, "Lock in Stock")
		self.assertEqual(
			(lines[issued.name].action, lines[issued.name].department), ("Return from Department", self.dept)
		)
		self.assertEqual(lines[used.name].action, "Notify Physician")
		self.assertEqual({row.line_status for row in lines.values()}, {"Pending"})
		# gói chưa dùng bị khóa: Pack Recalled; bộ đang ở kho về Chờ tiếp nhận
		for pack in (released, stocked, issued):
			self.assertEqual(frappe.db.get_value("Pack", pack.name, "status"), "Recalled")
		self.assertEqual(frappe.db.get_value("Pack", used.name, "status"), "Used")
		self.assertEqual(frappe.db.get_value("Set Unit", stocked.set_unit, "status"), "Awaiting Receipt")
		self.assertEqual(frappe.db.get_value("Set Unit", issued.set_unit, "status"), "At Department")

	def test_used_pack_shows_only_masked_patient_code(self):
		# FR-M2-20.3, UC-14 E2
		*_others, used = self.affected()
		frappe.set_user(self.r02)
		line = self.lines(recall.create(load=self.load, reason="BI").name)[used.name]
		self.assertTrue(line.patient_code_masked)
		self.assertNotIn("12345678", line.patient_code_masked)

	def test_order_links_an_incident_and_notifies_r01_r02_and_the_department(self):
		# FR-M2-20 (thông báo khoa liên quan và R01), UC-14 bước 6 (NC/CAPA liên kết)
		self.affected()
		frappe.set_user(self.r02)
		order = recall.create(load=self.load, reason="BI")
		incident = frappe.get_doc("Incident CAPA", order.incident)
		self.assertEqual((incident.incident_type, incident.sterilization_load), ("Load Failed", self.load))
		for user in (self.r01, self.r02, self.ward_user):
			self.assertIn(order.name, self.notices(user))
		self.assertNotIn(order.name, self.notices(self.stranger))

	def test_order_by_indicator_lot_covers_every_load_using_it(self):
		# UC-14 A1: thu hồi theo lô chỉ thị sinh học lỗi
		stocked = self.on_load(factories.make_stocked_pack())
		row = frappe.get_doc(
			{
				"doctype": "Load Indicator Result",
				"load": self.load,
				"indicator": "biological",
				"result": "Pass",
				"lot": "BI-LOT-LOI",
			}
		)
		row.flags.tc_releasing = True
		row.insert(ignore_permissions=True)
		frappe.set_user(self.r02)
		order = recall.create(lot="BI-LOT-LOI", reason="Nhà sản xuất báo lỗi lô BI")
		self.assertEqual(set(self.lines(order.name)), {stocked.name})
		self.assertEqual(order.indicator_lot, "BI-LOT-LOI")

	def test_empty_duplicate_and_role_rules(self):
		frappe.set_user(self.r02)
		blocked(self, "RECALL_EMPTY", recall.create, load=self.load, reason="Không có gói đã giải phóng")
		blocked(self, "REASON_REQUIRED", recall.create, load=self.load, reason=" ")
		frappe.set_user("Administrator")
		self.affected()
		frappe.set_user(self.r02)
		recall.create(load=self.load, reason="Lần 1")
		blocked(self, "RECALL_EXISTS", recall.create, load=self.load, reason="Lần 2")
		frappe.set_user(self.r06)
		blocked(self, "RECALL_NOT_ALLOWED", recall.create, load=self.load, reason="x")

	def test_recalled_pack_cannot_be_issued_or_used(self):
		# BRU-REP-007: gói trong lệnh thu hồi bị khóa cấp phát (T7) và chặn sử dụng (T8)
		_released, stocked, issued, _used = self.affected()
		frappe.set_user(self.r02)
		recall.create(load=self.load, reason="BI")
		frappe.set_user("Administrator")
		note = issuing.create(self.other_dept, "TR-007")["issue_note"]
		blocked(self, "PACK_NOT_IN_STOCK", issuing.add_pack, note, stocked.name, "TR-007")
		blocked(self, "PACK_RECALLED", usage.scan, issued.name, T8, self.nurse)


class TestConfirmAndClose(RecallCase):
	def open_order(self):
		packs = self.affected()
		frappe.set_user(self.r02)
		return recall.create(load=self.load, reason="BI"), packs

	@bru("BRU-REP-007")
	def test_close_only_when_every_line_is_confirmed(self):
		# FR-M2-20.2
		order, (released, stocked, issued, used) = self.open_order()
		blocked(self, "RECALL_INCOMPLETE", recall.close, order.name)
		frappe.set_user(self.r06)
		recall.confirm_pack(order.name, released.name, "Đã gỡ khỏi kho")
		recall.confirm_pack(order.name, stocked.name, "Đã gỡ khỏi kệ")
		frappe.set_user(self.ward_user)
		recall.confirm_pack(order.name, issued.name, "Khoa đã trả về CSSD")
		frappe.set_user(self.r01)
		recall.confirm_pack(order.name, used.name, "Đã báo bác sĩ điều trị")
		frappe.set_user(self.r02)
		closed = recall.close(order.name)
		self.assertEqual((closed.status, closed.docstatus, closed.closed_by), ("Closed", 1, self.r02))
		self.assertEqual({row.line_status for row in closed.packs}, {"Confirmed"})

	def test_who_may_confirm_each_line(self):
		order, (released, _stocked, issued, used) = self.open_order()
		frappe.set_user(self.stranger)  # R08 của khoa khác
		blocked(self, "RECALL_NOT_ALLOWED", recall.confirm_pack, order.name, issued.name)
		blocked(self, "RECALL_NOT_ALLOWED", recall.confirm_pack, order.name, released.name)
		frappe.set_user(self.r02)
		blocked(self, "RECALL_NOT_ALLOWED", recall.confirm_pack, order.name, used.name)  # chỉ R01 báo bác sĩ
		recall.confirm_pack(order.name, issued.name)
		blocked(self, "RECALL_LINE_DONE", recall.confirm_pack, order.name, issued.name)
		blocked(self, "RECALL_PACK_NOT_FOUND", recall.confirm_pack, order.name, "CY-KHONG-CO")


class TestHooksAndReminders(RecallCase):
	def test_bi_positive_after_release_opens_one_order(self):
		# FR-M2-11.7: BI dương tính sau giải phóng → tự lập lệnh, không trùng
		stocked = self.on_load(factories.make_stocked_pack())
		ctx = {"load": self.load, "equipment": self.equipment, "packs": []}
		first = recall.on_bi_positive(ctx)
		self.assertEqual(recall.on_bi_positive(ctx), first)
		order = frappe.get_doc("Recall Order", first)
		self.assertEqual((order.trigger, order.sterilization_load), ("BI Positive", self.load))
		self.assertIn(stocked.name, self.lines(first))

	def test_load_failed_without_released_packs_opens_nothing(self):
		ctx = {"load": self.load, "equipment": self.equipment, "program": None, "sets": [], "redo_from": "T4"}
		self.assertIsNone(recall.on_load_failed(ctx))

	def test_hooks_are_registered(self):
		self.assertIn(
			"tracecore.reprocessing.recall.on_bi_positive", frappe.get_hooks("tracecore_bi_positive")
		)
		self.assertIn(
			"tracecore.reprocessing.recall.on_load_failed", frappe.get_hooks("tracecore_after_load_failed")
		)

	def test_department_is_reminded_after_two_hours_at_most_every_two_hours(self):
		# UC-14 E3
		_released, _stocked, issued, _used = self.affected()
		frappe.set_user(self.r02)
		order = recall.create(load=self.load, reason="BI")
		frappe.set_user("Administrator")
		self.assertEqual(recall.remind_pending(), 0)  # chưa đủ 2 giờ
		frappe.db.set_value("Recall Order", order.name, "opened_at", add_to_date(now_datetime(), hours=-3))
		self.assertGreaterEqual(recall.remind_pending(), 1)
		self.assertEqual(recall.remind_pending(), 0)  # vừa nhắc xong
		self.assertGreaterEqual(self.notices(self.ward_user).count(order.name), 2)
