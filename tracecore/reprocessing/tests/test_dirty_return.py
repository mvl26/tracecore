"""Khoa gửi yêu cầu lấy đồ bẩn (FEAT-100, A-160; FR-M2-26 .1-.3; BRU-FLOW-003)."""

import frappe
from frappe.utils import now_datetime, today

from tracecore.reprocessing import dirty_return, usage
from tracecore.reprocessing.tests.test_usage import STATION, issue
from tracecore.tests.factories import make_department, make_employee, make_stocked_pack
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def receive_at_t1(set_unit):
	"""Dòng tiếp nhận T1 của bộ (ghi thẳng, không chạy cả luồng tiếp nhận): đủ để yêu cầu thành Đã tiếp nhận."""
	receipt = frappe.new_doc("Dirty Receipt")
	receipt.update({"name": "RC-TEST-" + frappe.generate_hash(length=8), "abandoned": 0})
	receipt.db_insert()
	item = frappe.new_doc("Dirty Receipt Item")
	item.update(
		{
			"name": frappe.generate_hash(length=10),
			"parent": receipt.name,
			"parenttype": "Dirty Receipt",
			"parentfield": "items",
			"idx": 1,
			"set_unit": set_unit,
			"creation": now_datetime(),
		}
	)
	item.db_insert()


class DirtyReturnCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.dept = make_department("Khoa gửi trả đồ bẩn")
		self.nurse = make_employee(first_name="Điều dưỡng gửi trả", department=self.dept).name
		self.unused = issue(make_stocked_pack(), self.dept)
		self.used = issue(make_stocked_pack(), self.dept)
		usage.confirm(
			self.used.name,
			STATION,
			self.nurse,
			patient_code="BN12345678",
			surgery_code="CA-100",
			surgeon="BS",
			room="P1",
		)

	def line(self, pack, condition="Complete"):
		return {"set_id": pack.set_unit, "condition": condition}

	def rejected(self, *args, **kwargs):
		with self.assertRaises(dirty_return.ReturnRejected) as raised:
			dirty_return.create(*args, **kwargs)
		return raised.exception


class TestCandidates(DirtyReturnCase):
	def test_lists_unused_and_used_sets_of_the_department_only(self):
		other = issue(make_stocked_pack(), make_department("Khoa khác gửi trả"))
		rows = {row["set_id"]: row for row in dirty_return.candidates(self.dept)}
		self.assertFalse(rows[self.unused.set_unit]["used"])
		self.assertTrue(rows[self.used.set_unit]["used"])
		self.assertEqual(rows[self.unused.set_unit]["cycle_id"], self.unused.name)
		self.assertEqual(rows[self.unused.set_unit]["set_type"], self.unused.set_type)
		self.assertTrue(rows[self.unused.set_unit]["set_name"])
		self.assertNotIn(other.set_unit, rows)

	def test_sets_in_a_waiting_request_are_not_offered_again(self):
		dirty_return.create(self.dept, [self.line(self.used)])
		ids = [row["set_id"] for row in dirty_return.candidates(self.dept)]
		self.assertEqual(ids, [self.unused.set_unit])


class TestCreate(DirtyReturnCase):
	@bru("BRU-FLOW-003")
	def test_request_is_recorded_without_changing_set_or_pack_status(self):
		before = {
			pack.name: (
				frappe.db.get_value("Pack", pack.name, "status"),
				frappe.db.get_value("Set Unit", pack.set_unit, "status"),
			)
			for pack in (self.unused, self.used)
		}
		out = dirty_return.create(
			self.dept, [self.line(self.unused, "Missing instruments"), self.line(self.used)]
		)
		doc = frappe.get_doc("Dirty Return Request", out["request"])
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual((doc.department, doc.set_count), (self.dept, 2))
		self.assertEqual(doc.requested_by, frappe.session.user)
		self.assertTrue(doc.requested_at)
		lines = {row.set_unit: row for row in doc.items}
		self.assertEqual(lines[self.unused.set_unit].return_condition, "Missing instruments")
		self.assertEqual(lines[self.unused.set_unit].used, 0)
		self.assertEqual(lines[self.used.set_unit].return_condition, "Complete")
		self.assertEqual(lines[self.used.set_unit].used, 1)
		self.assertEqual(lines[self.unused.set_unit].pack, self.unused.name)
		# yêu cầu chỉ là thông báo: bộ và gói giữ nguyên trạng thái tới khi T1 quét tiếp nhận
		for pack in (self.unused, self.used):
			self.assertEqual(
				before[pack.name],
				(
					frappe.db.get_value("Pack", pack.name, "status"),
					frappe.db.get_value("Set Unit", pack.set_unit, "status"),
				),
			)

	def test_items_may_arrive_as_json_text(self):
		out = dirty_return.create(self.dept, frappe.as_json([self.line(self.used)]))
		self.assertEqual(frappe.db.get_value("Dirty Return Request", out["request"], "set_count"), 1)

	def test_rejects_empty_foreign_duplicate_and_bad_condition(self):
		self.assertEqual(self.rejected(self.dept, []).code, "NO_SETS")
		self.assertEqual(self.rejected(self.dept, "not json").code, "NO_SETS")
		foreign = issue(make_stocked_pack(), make_department("Khoa khác gửi trả"))
		self.assertEqual(self.rejected(self.dept, [self.line(foreign)]).code, "SET_NOT_RETURNABLE")
		self.assertEqual(self.rejected(self.dept, [self.line(self.used, "Lost")]).code, "CONDITION_INVALID")
		self.assertEqual(
			self.rejected(self.dept, [self.line(self.used), self.line(self.used)]).code, "SET_REPEATED"
		)
		dirty_return.create(self.dept, [self.line(self.used)])
		error = self.rejected(self.dept, [self.line(self.used)])
		self.assertEqual(error.code, "SET_NOT_RETURNABLE")
		# kết quả → lý do → hành động
		self.assertTrue(error.title and error.reason and error.action)
		self.assertEqual(frappe.db.count("Dirty Return Request", {"department": self.dept}), 1)

	def test_request_cannot_be_changed_or_made_outside_the_service(self):
		doc = frappe.get_doc(
			{
				"doctype": "Dirty Return Request",
				"department": self.dept,
				"items": [{"set_unit": self.used.set_unit, "return_condition": "Complete"}],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)
		out = dirty_return.create(self.dept, [self.line(self.used)])
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Dirty Return Request", out["request"]).cancel()


class TestRequestsToday(DirtyReturnCase):
	def test_status_follows_t1_receipts_after_the_request(self):
		out = dirty_return.create(self.dept, [self.line(self.unused), self.line(self.used)])
		row = dirty_return.requests_on(self.dept, today())[0]
		self.assertEqual(row["request"], out["request"])
		self.assertEqual((row["set_count"], row["received_count"], row["status"]), (2, 0, "Waiting"))
		self.assertTrue(row["requested_at"])
		self.assertTrue(row["requested_by_name"])
		receive_at_t1(self.used.set_unit)
		row = dirty_return.requests_on(self.dept, today())[0]
		self.assertEqual((row["received_count"], row["status"]), (1, "Partly received"))
		# bộ đã về T1 không còn giữ chỗ trong yêu cầu đang chờ
		self.assertNotIn(self.used.set_unit, dirty_return.pending_sets(self.dept))
		self.assertIn(self.unused.set_unit, dirty_return.pending_sets(self.dept))
		receive_at_t1(self.unused.set_unit)
		row = dirty_return.requests_on(self.dept, today())[0]
		self.assertEqual((row["received_count"], row["status"]), (2, "Received"))

	def test_only_requests_of_the_department_and_day(self):
		dirty_return.create(self.dept, [self.line(self.used)])
		self.assertEqual(dirty_return.requests_on(make_department("Khoa khác gửi trả"), today()), [])
		self.assertEqual(dirty_return.requests_on(self.dept, "2020-01-01"), [])
