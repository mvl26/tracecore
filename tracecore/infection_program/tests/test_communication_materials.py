"""Tài liệu truyền thông cho người bệnh, người nhà có QR (FEAT-073; FR-M17-06, FR-M17-06.1; UC-56 bước 6, E4; A-151 Q3)."""

import frappe
from frappe.utils import today

from tracecore.core.errors import BlockedError
from tracecore.food_safety.tests import factories as ff
from tracecore.infection_program import procedure_documents as docs
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import food_safety as api
from tracecore.www import tai_lieu


class TestCommunicationMaterial(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.r01 = ff.make_user("attp-doc-r01@example.com", [ff.R01])

	def test_draft_stays_draft_and_does_not_supersede_until_published(self):
		v1 = ff.make_material("TL-T1", 1)
		v2 = ff.make_material("TL-T1", 2, status=docs.DRAFT, supersedes=v1.name)
		self.assertEqual(frappe.db.get_value(docs.DOCTYPE, v2.name, "status"), docs.DRAFT)
		self.assertEqual(frappe.db.get_value(docs.DOCTYPE, v1.name, "status"), "Effective")
		self.assertEqual(docs.current_material("TL-T1")["name"], v1.name)
		frappe.set_user(self.r01)
		docs.publish(v2.name)
		self.assertEqual(frappe.db.get_value(docs.DOCTYPE, v2.name, "status"), "Effective")
		self.assertEqual(frappe.db.get_value(docs.DOCTYPE, v1.name, "status"), "Superseded")
		current = docs.current_material("TL-T1")
		self.assertEqual((current["state"], current["name"], current["version_no"]), ("current", v2.name, 2))

	def test_qr_url_is_fixed_per_document_code(self):
		url = docs.material_url("TL-T1")
		self.assertTrue(url.endswith("/tai-lieu/TL-T1"))
		self.assertTrue(docs.material_qr_png("TL-T1").startswith(b"\x89PNG"))

	def test_withdraw_needs_reason_and_only_r01(self):
		v1 = ff.make_material("TL-T2", 1)
		r11 = ff.make_user("attp-doc-r11@example.com", [ff.R11])
		frappe.set_user(r11)
		with self.assertRaises(frappe.PermissionError):
			docs.withdraw(v1.name, "Nội dung cũ")
		frappe.set_user(self.r01)
		with self.assertRaises(BlockedError) as ctx:
			docs.withdraw(v1.name, "")
		self.assertEqual(ctx.exception.block.code, "REASON_REQUIRED")
		docs.withdraw(v1.name, "Thay đổi quy định thăm")
		self.assertEqual(frappe.db.get_value(docs.DOCTYPE, v1.name, "status"), docs.WITHDRAWN)
		self.assertEqual(docs.current_material("TL-T2")["state"], "withdrawn")
		with self.assertRaises(BlockedError):
			docs.publish(v1.name)

	def test_draft_only_code_is_not_active(self):
		ff.make_material("TL-T3", 1, status=docs.DRAFT)
		self.assertEqual(docs.current_material("TL-T3")["state"], "draft")
		self.assertEqual(docs.current_material("TL-KHONG-CO")["state"], "missing")
		ff.make_material("QD-T3", 1, doc_type="Regulation")
		self.assertEqual(docs.current_material("QD-T3")["state"], "missing")

	def test_indicator_ignores_draft_and_withdrawn(self):
		frappe.db.delete(docs.DOCTYPE)
		ff.make_material("TL-T4", 1, issued_on="2026-10-01")
		ff.make_material("TL-T5", 1, status=docs.DRAFT, issued_on="2026-10-01")
		withdrawn = ff.make_material("TL-T6", 1, issued_on="2026-10-01")
		frappe.db.set_value(docs.DOCTYPE, withdrawn.name, "status", docs.WITHDRAWN)
		self.assertEqual(docs.current_documents("2026-10")[1], 1)


class TestPublicPage(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.v1 = ff.make_material("TL-WEB", 1)
		self.file_url = ff.attach(self.v1, b"noi dung v1", "tl-web-v1.txt")

	def _context(self, code):
		frappe.form_dict.code = code
		self.addCleanup(frappe.form_dict.pop, "code", None)
		context = frappe._dict()
		tai_lieu.get_context(context)
		return context

	def test_guest_sees_current_version_and_downloads_its_file(self):
		frappe.set_user("Guest")
		context = self._context("TL-WEB")
		self.assertEqual((context.state, context.title, context.version_no), ("current", self.v1.title, 1))
		self.assertIn("tracecore.v1.food_safety.material_file", context.file_link)
		api.material_file("TL-WEB")
		self.assertEqual(frappe.safe_decode(frappe.local.response.filecontent), "noi dung v1")

	def test_new_version_keeps_same_link(self):
		v2 = ff.make_material("TL-WEB", 2, supersedes=self.v1.name, issued_on=today())
		ff.attach(v2, b"noi dung v2", "tl-web-v2.txt")
		frappe.set_user("Guest")
		self.assertEqual(self._context("TL-WEB").version_no, 2)
		api.material_file("TL-WEB")
		self.assertEqual(frappe.safe_decode(frappe.local.response.filecontent), "noi dung v2")

	def test_withdrawn_and_unknown_show_notice_without_file(self):
		frappe.db.set_value(docs.DOCTYPE, self.v1.name, "status", docs.WITHDRAWN)
		frappe.set_user("Guest")
		context = self._context("TL-WEB")
		self.assertEqual(context.state, "withdrawn")
		self.assertFalse(context.get("file_link"))
		with self.assertRaises(frappe.DoesNotExistError):
			api.material_file("TL-WEB")
		self.assertEqual(self._context("KHONG-CO").state, "missing")
