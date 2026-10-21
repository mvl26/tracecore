"""Mẫu nhãn QR đối tượng (FEAT-005 Task 2, A-05 R2): Equipment, Station, Roll, Employee Card, Location."""

from unittest.mock import patch

import frappe

from tracecore.core import gs1
from tracecore.core import print as core_print
from tracecore.patches.v0_1 import create_object_label_templates
from tracecore.setup import install
from tracecore.setup.label_templates import (
	OBJECT_TEMPLATES,
	ensure_object_templates,
	sample_object_context,
)
from tracecore.tests.utils import IsolatedTestCase
from tracecore.tracecore.doctype.label_template.test_label_template import _text_boxes

OBJECTS = ("Equipment", "Station", "Roll", "Employee Card", "Location")
SCAN_TYPES = {
	"Equipment": "equipment",
	"Station": "station",
	"Roll": "roll",
	"Employee Card": "employee",
	"Location": "location",
}
BODY = "^XA{{ qr(doc.payload, 20, 40, 6) }}^FO220,40^FD{{ text(doc.code) }}^FS^XZ"


def _name(label_object):
	return f"Object label - {label_object}"


def _template(name, label_object="Equipment", **values):
	return frappe.get_doc(
		{
			"doctype": "Label Template",
			"template_name": name,
			"label_object": label_object,
			"language": "ZPL",
			"width_mm": 50,
			"height_mm": 30,
			"dpi": 300,
			"body": BODY,
			**values,
		}
	)


class TestObjectTemplates(IsolatedTestCase):
	def test_object_templates_installed_by_patch_and_install(self):
		self.assertEqual([sample["label_object"] for sample in OBJECT_TEMPLATES], list(OBJECTS))
		for label_object in OBJECTS:
			doc = frappe.get_doc("Label Template", _name(label_object))
			self.assertEqual(
				(doc.label_object, doc.method or None, doc.language, doc.width_mm, doc.height_mm, doc.dpi),
				(label_object, None, "ZPL", 50, 30, 300),
			)
			self.assertTrue(doc.is_active, msg=label_object)
			self.assertIn("qr(", doc.body)
		frappe.db.delete("Label Template", {"name": _name("Equipment")})
		with patch.object(install, "apply_system_settings"):
			install.after_install()
		self.assertTrue(frappe.db.exists("Label Template", _name("Equipment")))
		frappe.db.delete("Label Template", {"name": _name("Station")})
		create_object_label_templates.execute()
		self.assertTrue(frappe.db.get_value("Label Template", _name("Station"), "is_active"))

	def test_object_templates_survive_reinstall(self):
		edited = "^XA{{ qr(doc.payload, 10, 10, 5) }}^FDedited by R10^FS^XZ"
		doc = frappe.get_doc("Label Template", _name("Roll"))
		doc.body = edited
		doc.save()
		self.assertEqual(ensure_object_templates(), [])
		self.assertEqual(frappe.db.get_value("Label Template", _name("Roll"), "body"), edited)

	def test_ensure_object_templates_creates_missing_without_stealing_the_slot(self):
		frappe.db.delete("Label Template", {"name": _name("Location")})
		_template("R10 own location template", label_object="Location").insert()
		self.assertEqual(ensure_object_templates(), [_name("Location")])
		self.assertFalse(frappe.db.get_value("Label Template", _name("Location"), "is_active"))
		self.assertEqual(core_print.active_template("Location", None).name, "R10 own location template")

	def test_one_active_template_per_object(self):
		with self.assertRaises(frappe.ValidationError):
			_template("Second equipment template").insert()
		with self.assertRaises(frappe.ValidationError):
			_template("Second station template", label_object="Station").insert()
		spare = _template("Spare equipment template", is_active=0).insert()
		spare.is_active = 1
		with self.assertRaises(frappe.ValidationError):
			spare.save()
		frappe.db.set_value("Label Template", _name("Equipment"), "is_active", 0)
		spare.reload()
		spare.is_active = 1
		spare.save()
		self.assertTrue(frappe.db.get_value("Label Template", spare.name, "is_active"))
		# đối tượng khác loại không tranh chỗ: các mẫu gói và mẫu đối tượng khác vẫn active
		self.assertTrue(frappe.db.get_value("Label Template", "Pack label - Steam", "is_active"))
		self.assertTrue(frappe.db.get_value("Label Template", _name("Station"), "is_active"))

	def test_one_active_message_names_object_in_vietnamese(self):
		frappe.local.lang = "vi"
		try:
			with self.assertRaises(frappe.ValidationError) as ctx:
				_template("Second roll template", label_object="Roll").insert()
		finally:
			frappe.local.lang = "en"
		self.assertIn("Cuộn nhãn", str(ctx.exception))
		self.assertNotIn("Roll /", str(ctx.exception))

	def test_method_required_only_for_pack(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Label Template",
					"template_name": "Pack without method",
					"label_object": "Pack",
					"language": "ZPL",
					"is_active": 0,
					"width_mm": 60,
					"height_mm": 40,
					"dpi": 300,
					"body": "^XA^FD{{ text(doc.set_name) }}^FS^XZ",
				}
			).insert()
		plain = _template("Equipment without method", is_active=0).insert()
		self.assertFalse(plain.method)
		# phương pháp tiệt khuẩn không có nghĩa với nhãn đối tượng: bị bỏ, mẫu vẫn vào đúng ô (Equipment, rỗng, ZPL)
		stray = _template("Equipment with stray method", is_active=0, method="Steam").insert()
		self.assertFalse(stray.method)
		self.assertFalse(frappe.db.get_value("Label Template", stray.name, "method"))

	def test_broken_object_template_rejected_on_save(self):
		for body in (
			"hello",
			"^XA{{ 1/0 }}^XZ",
			"^XA{{ doc.title.nope.attr }}^XZ",
			"^XA{{ doc.subtitle + 1 }}^XZ",
		):
			with self.assertRaises(frappe.ValidationError, msg=body) as ctx:
				_template("Broken object", is_active=0, body=body).insert()
			self.assertIn("Broken object", str(ctx.exception), msg=body)
		# lỗi dữ liệu mã vạch của dialect giữ nguyên thông điệp (như mẫu gói), vẫn là ValidationError
		for body in (
			"^XA{{ qr(doc.payload, -1, 0) }}^XZ",
			"^XA{{ qr(doc.payload, 0, 0, 99) }}^XZ",
			"^XA{{ qr(doc.title, 0, 0) }}^XZ",  # tên có dấu không đưa được vào QR
		):
			with self.assertRaises(frappe.ValidationError, msg=body) as ctx:
				_template("Broken object", is_active=0, body=body).insert()
			self.assertIn("QR", str(ctx.exception), msg=body)
		self.assertFalse(frappe.db.exists("Label Template", "Broken object"))
		doc = frappe.get_doc("Label Template", _name("Equipment"))
		original = doc.body
		doc.body = "^XA{{ qr(doc.payload, 0, 0, 0) }}^XZ"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertEqual(frappe.db.get_value("Label Template", doc.name, "body"), original)

	def test_trial_render_of_object_template_uses_object_sample(self):
		with patch.object(core_print, "render", wraps=core_print.render) as render:
			_template("Station trial", label_object="Station", is_active=0).insert()
		self.assertTrue(render.call_args_list)
		codes = {call.args[1].get("code") for call in render.call_args_list}
		self.assertIn(sample_object_context("Station")["code"], codes)
		self.assertEqual({call.args[2] for call in render.call_args_list}, {False, True})

	def test_sample_object_context(self):
		for label_object in OBJECTS:
			doc = sample_object_context(label_object)
			self.assertEqual(set(doc), {"code", "title", "subtitle", "payload", "is_test"}, msg=label_object)
			self.assertEqual(doc["payload"], doc["code"])
			self.assertTrue(doc["is_test"])
			self.assertEqual(gs1.parse_scan(doc["code"])["type"], SCAN_TYPES[label_object], msg=label_object)
			self.assertFalse(doc["title"].isascii(), msg=label_object)  # có dấu để thử cả hai chế độ in
		for label_object in ("Pack", "Nope", "", None):
			with self.assertRaises(frappe.ValidationError, msg=repr(label_object)):
				sample_object_context(label_object)

	def test_object_templates_fit_inside_label(self):
		width, height = core_print.mm_to_dots(50, 300), core_print.mm_to_dots(30, 300)
		long_title = "Máy tiệt khuẩn hơi nước hai cửa dung tích lớn khu sạch số một"
		long_subtitle = "Khu đóng gói - tiệt khuẩn, phòng số hai, cạnh cửa ra"
		for label_object in OBJECTS:
			sample = sample_object_context(label_object)
			for unicode in (False, True):
				zpl = core_print.render_object(
					label_object,
					sample["code"],
					long_title,
					long_subtitle,
					printer={"language": "ZPL", "supports_unicode": int(unicode)},
				)
				self.assertIn(f"^PW{width}", zpl)
				self.assertIn(f"^LL{height}", zpl)
				boxes = _text_boxes(zpl, width)
				self.assertGreaterEqual(len(boxes), 3, msg=zpl)
				for x0, _y0, x1, y1, text in boxes:
					# cột chữ nằm bên phải QR (QR 29 module x 6 dot từ x = 20)
					self.assertGreaterEqual(x0, 20 + 29 * 6, msg=text)
					self.assertLessEqual(x1, width, msg=text)
					self.assertLessEqual(y1, height, msg=text)
