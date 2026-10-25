"""Issue Note (FEAT-026 C1, C2, C11): chỉ dịch vụ cấp phát tạo/sửa, tên IS-YYYY-#####, không hủy, không xóa, quyền DT-ISSUE."""

import re

import frappe
from frappe.utils import now_datetime

from tracecore.tests.factories import make_department, make_stocked_pack
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix
from tracecore.ui.issue_print import tc_issue_note_context

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

SIGNATURE = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def make_note(**fields):
	doc = frappe.get_doc(
		{
			"doctype": "Issue Note",
			"department": make_department(),
			"station": "TR-007",
			"issued_by_user": frappe.session.user,
			**fields,
		}
	)
	doc.flags.tc_issuing = True
	return doc.insert(ignore_permissions=True)


class TestIssueNote(IsolatedTestCase):
	def test_name_follows_issue_series(self):
		note = make_note()
		self.assertRegex(note.name, re.compile(rf"^IS-{now_datetime().year}-\d{{5}}$"))

	def test_only_issuing_service_creates(self):
		doc = frappe.get_doc(
			{
				"doctype": "Issue Note",
				"department": make_department(),
				"issued_by_user": frappe.session.user,
			}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_only_issuing_service_edits_draft(self):
		name = make_note().name
		note = frappe.get_doc("Issue Note", name)  # tài liệu mới, không mang cờ của dịch vụ
		note.recipient_name = "Ai đó"
		with self.assertRaises(frappe.ValidationError):
			note.save(ignore_permissions=True)

	def test_cannot_cancel(self):
		note = make_note()
		note.flags.tc_issuing = True
		note.submit()
		with self.assertRaises(frappe.ValidationError):
			note.cancel()

	def test_cannot_delete(self):
		note = make_note()
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Issue Note", note.name, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Issue Note", note.name))

	def test_pack_count_follows_rows(self):
		note = make_note()
		self.assertEqual(note.pack_count, 0)

	def test_permissions_follow_matrix(self):
		assert_permission_matrix(self, "Issue Note")

	def test_station_user_limited_to_own_employee_can_read_and_print(self):
		# HRMS tự tạo User Permission Employee cho user gắn nhân viên; phiếu có người cấp/người nhận là nhân viên khác
		# vẫn phải đọc và in được ở kiosk T7 (in phiếu sau khi xác nhận, FEAT-026 C10)
		from frappe.permissions import add_user_permission

		from tracecore.tests.factories import make_employee, make_user

		user = make_user("t7-print@test.local", roles=("TC R06",))
		own = make_employee(user_id=user)
		add_user_permission("Employee", own.name, user)
		other = make_employee(department=make_department())
		note = make_note(issued_by=own.name, recipient=other.name)
		for ptype in ("read", "print"):
			self.assertTrue(frappe.has_permission("Issue Note", ptype, note, user=user), ptype)


class TestIssueNotePrint(IsolatedTestCase):
	"""Print Format TC Issue Note (C10, FR-M2-15.1): số phiếu, khoa, người nhận, gói, chữ ký."""

	def build(self, **fields):
		pack = make_stocked_pack()
		note = make_note(
			**{
				"recipient_name": "Điều dưỡng <b>In</b>",
				"sign_method": "Touch",
				"signature": SIGNATURE,
				"signed_at": now_datetime(),
				**fields,
			}
		)
		note.append(
			"packs",
			{
				"pack": pack.name,
				"set_unit": pack.set_unit,
				"set_type": pack.set_type,
				"set_name": "Bộ in thử",
			},
		)
		note.save(ignore_permissions=True)
		return note, pack

	def test_format_is_installed(self):
		self.assertEqual(frappe.db.get_value("Print Format", "TC Issue Note", "doc_type"), "Issue Note")

	def test_renders_note_pack_and_signature(self):
		note, pack = self.build()
		html = frappe.get_print("Issue Note", note.name, "TC Issue Note")
		self.assertIn(note.name, html)
		self.assertIn(pack.name, html)
		self.assertIn(SIGNATURE, html)
		self.assertIn("Not confirmed yet", html)  # nháp chưa ghi sổ
		self.assertIn("Điều dưỡng &lt;b&gt;In&lt;/b&gt;", html)  # giá trị động luôn được escape

	def test_context_for_card_signature_has_no_image(self):
		note, _pack = self.build(sign_method="Card", signature=None)
		context = tc_issue_note_context(note.name)
		self.assertIsNone(context["signature"])
		self.assertEqual(context["pack_count"], 1)
		self.assertEqual(context["packs"][0]["index"], 1)
