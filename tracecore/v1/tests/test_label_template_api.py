"""RPC tracecore.v1.label_template.preview (FEAT-002 Task 4, E7): xem trước mẫu nhãn bằng dữ liệu mẫu trên Desk."""

import frappe

from tracecore.core import print as core_print
from tracecore.setup.label_templates import sample_pack_context
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import label_template as label_template_api

# Người dùng test có role TC; site CI mới chưa chạy Setup Wizard (xem factories.py).
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

SAMPLE = "Pack label - Steam"


class TestLabelTemplatePreview(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.local.response.pop("http_status_code", None)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		self.addCleanup(frappe.set_user, "Administrator")

	def test_preview_returns_zpl_for_sample(self):
		result = label_template_api.preview(SAMPLE)
		self.assertIs(result["ok"], True)
		row = frappe.db.get_value(
			"Label Template", SAMPLE, ["body", "width_mm", "height_mm", "dpi"], as_dict=True
		)
		expected = core_print.render(
			row.body,
			sample_pack_context(),
			False,
			dpi=row.dpi,
			width_mm=row.width_mm,
			height_mm=row.height_mm,
		)
		self.assertEqual(result["zpl"], expected)
		self.assertTrue(result["zpl"].startswith("^XA") and result["zpl"].endswith("^XZ"))
		self.assertIsNone(frappe.local.response.get("http_status_code"))

	def test_preview_unicode_flag_keeps_diacritics(self):
		folded = label_template_api.preview(SAMPLE, unicode=0)["zpl"]
		unicode_zpl = label_template_api.preview(SAMPLE, unicode="1")["zpl"]
		self.assertNotEqual(folded, unicode_zpl)

	def test_preview_broken_template_is_422(self):
		frappe.db.set_value("Label Template", SAMPLE, "body", "^XA{{ 1 / 0 }}^XZ")
		before = frappe.db.count("Audit Log")
		with request_headers({}):
			result = label_template_api.preview(SAMPLE)
		self.assertIs(result["ok"], False)
		self.assertEqual(result["error"]["code"], "LABEL_RENDER_FAILED")
		self.assertEqual(result["error"]["http_status"], 422)
		self.assertIn(SAMPLE, result["error"]["reason"])
		for key in ("title", "reason", "action"):
			self.assertTrue(result["error"][key], msg=key)
		self.assertEqual(frappe.local.response.http_status_code, 422)
		self.assertEqual(frappe.db.count("Audit Log"), before)

	def test_preview_unknown_template_is_not_found(self):
		with self.assertRaises(frappe.DoesNotExistError):
			label_template_api.preview("no-such-template")

	def test_preview_requires_r10_or_system_manager(self):
		frappe.set_user(make_user("preview-r04@example.com", roles=["TC R04"]))
		with self.assertRaises(frappe.PermissionError):
			label_template_api.preview(SAMPLE)
		frappe.set_user(make_user("preview-r10@example.com", roles=["TC R10"]))
		self.assertIs(label_template_api.preview(SAMPLE)["ok"], True)
		frappe.set_user("Administrator")
		self.assertIs(label_template_api.preview(SAMPLE)["ok"], True)
