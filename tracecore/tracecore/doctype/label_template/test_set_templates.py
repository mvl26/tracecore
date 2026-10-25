"""Mẫu thẻ kim loại `Set Tag` và nhãn khay `Set Tray Label` (FEAT-016 Task 3, G8; FR-M1-05; BRU-ID-001)."""

from unittest.mock import patch

import frappe

from tracecore.core import gs1
from tracecore.core import print as core_print
from tracecore.patches.v0_1 import create_set_label_templates
from tracecore.setup import install
from tracecore.setup.label_templates import (
	SET_TEMPLATES,
	ensure_set_templates,
	sample_context,
	sample_set_context,
)
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.tracecore.doctype.label_template.test_label_template import _text_boxes

# Label Template → Printer/Print Job không liên quan, nhưng giữ cùng danh sách với các test in khác (CI không có Setup Wizard)
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

SIZES = {"Set Tag": ("Set tag", 50, 30), "Set Tray Label": ("Set tray label", 60, 40)}
CONTEXT_KEYS = {
	"set_id",
	"payload",
	"hri",
	"type_code",
	"set_type_name",
	"department",
	"method",
	"is_implant",
	"issued_on",
	"is_test",
}
BODY = "^XA{{ datamatrix(doc.payload, 24, 24, 6) }}^FO200,30^FD{{ text(doc.set_id) }}^FS^XZ"
# GIAI dài nhất có thể của Set ID: tiền tố 12 số + mã loại bộ 8 ký tự + 6 số (26 ký tự)
LONGEST_SET_ID = "123456789012ABCDEFGH123456"


def _template(name, label_object="Set Tag", **values):
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


def _datamatrix_box(payload, x=24, y=24, module=6):
	"""Ô DataMatrix (x0, y0, x1, y1) theo số module thật của payload (pylibdmtx), module `module` dot."""
	from io import BytesIO

	from PIL import Image

	margin = 12
	size = Image.open(BytesIO(gs1.encode_datamatrix_png(payload, module_px=1, margin_px=margin))).size[0]
	modules = size - 2 * margin
	return x, y, x + modules * module, y + modules * module


class TestSetTemplates(IsolatedTestCase):
	@bru("BRU-ID-001")
	def test_set_templates_installed_by_patch_and_install(self):
		self.assertEqual(core_print.SET_LABELS, ("Set Tag", "Set Tray Label"))
		self.assertEqual([row["label_object"] for row in SET_TEMPLATES], list(core_print.SET_LABELS))
		for label_object, (name, width, height) in SIZES.items():
			doc = frappe.get_doc("Label Template", name)
			self.assertEqual(
				(doc.label_object, doc.method or None, doc.language, doc.width_mm, doc.height_mm, doc.dpi),
				(label_object, None, "ZPL", width, height, 300),
			)
			self.assertTrue(doc.is_active, msg=name)
			self.assertIn("datamatrix(", doc.body)
		frappe.db.delete("Label Template", {"name": "Set tag"})
		with patch.object(install, "apply_system_settings"):
			install.after_install()
		self.assertTrue(frappe.db.get_value("Label Template", "Set tag", "is_active"))
		frappe.db.delete("Label Template", {"name": "Set tray label"})
		create_set_label_templates.execute()
		self.assertTrue(frappe.db.get_value("Label Template", "Set tray label", "is_active"))

	def test_set_templates_survive_reinstall(self):
		edited = "^XA{{ datamatrix(doc.payload, 10, 10, 5) }}^FDedited by R10^FS^XZ"
		doc = frappe.get_doc("Label Template", "Set tag")
		doc.body = edited
		doc.save()
		self.assertEqual(ensure_set_templates(), [])
		create_set_label_templates.execute()
		self.assertEqual(frappe.db.get_value("Label Template", "Set tag", "body"), edited)

	def test_ensure_set_templates_creates_missing_without_stealing_the_slot(self):
		frappe.db.delete("Label Template", {"name": "Set tray label"})
		_template("R10 own tray label", label_object="Set Tray Label", width_mm=60, height_mm=40).insert()
		self.assertEqual(ensure_set_templates(), ["Set tray label"])
		self.assertFalse(frappe.db.get_value("Label Template", "Set tray label", "is_active"))
		self.assertEqual(core_print.active_template("Set Tray Label", None).name, "R10 own tray label")

	def test_one_active_template_per_set_label(self):
		for label_object in core_print.SET_LABELS:
			with self.assertRaises(frappe.ValidationError, msg=label_object):
				_template(f"Second {label_object}", label_object=label_object).insert()
		spare = _template("Spare set tag", is_active=0, method="Steam").insert()
		self.assertFalse(spare.method)  # thẻ/nhãn khay không có phương pháp tiệt khuẩn
		spare.is_active = 1
		with self.assertRaises(frappe.ValidationError):
			spare.save()
		frappe.db.set_value("Label Template", "Set tag", "is_active", 0)
		spare.reload()
		spare.is_active = 1
		spare.save()
		# loại khác không tranh chỗ
		self.assertTrue(frappe.db.get_value("Label Template", "Set tray label", "is_active"))
		self.assertTrue(frappe.db.get_value("Label Template", "Object label - Equipment", "is_active"))

	def test_one_active_message_names_set_label_in_vietnamese(self):
		frappe.local.lang = "vi"
		try:
			with self.assertRaises(frappe.ValidationError) as ctx:
				_template("Second tray", label_object="Set Tray Label").insert()
		finally:
			frappe.local.lang = "en"
		self.assertIn("Nhãn khay", str(ctx.exception))

	def test_broken_set_template_rejected_on_save(self):
		for body in (
			"hello",
			"^XA{{ 1/0 }}^XZ",
			"^XA{{ doc.set_type_name.nope.attr }}^XZ",
			"^XA{{ doc.issued_on + 1 }}^XZ",
		):
			with self.assertRaises(frappe.ValidationError, msg=body) as ctx:
				_template("Broken set tag", is_active=0, body=body).insert()
			self.assertIn("Broken set tag", str(ctx.exception), msg=body)
		for body in (
			"^XA{{ datamatrix('', 0, 0) }}^XZ",
			"^XA{{ datamatrix(doc.payload ~ '^XZ', 0, 0) }}^XZ",  # lệnh ZPL không được lọt vào payload
		):
			with self.assertRaises(frappe.ValidationError, msg=body):
				_template("Broken set tag", is_active=0, body=body).insert()
		self.assertFalse(frappe.db.exists("Label Template", "Broken set tag"))
		doc = frappe.get_doc("Label Template", "Set tray label")
		original = doc.body
		doc.body = "^XA{{ doc.department * 'x' }}^XZ"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertEqual(frappe.db.get_value("Label Template", doc.name, "body"), original)

	def test_trial_render_of_set_template_uses_set_sample(self):
		with patch.object(core_print, "render", wraps=core_print.render) as render:
			_template("Tray trial", label_object="Set Tray Label", is_active=0).insert()
		set_ids = {call.args[1].get("set_id") for call in render.call_args_list}
		self.assertIn(sample_set_context("Set Tray Label")["set_id"], set_ids)
		self.assertEqual({call.args[2] for call in render.call_args_list}, {False, True})

	def test_sample_set_context(self):
		for label_object in core_print.SET_LABELS:
			doc = sample_set_context(label_object)
			self.assertEqual(set(doc), CONTEXT_KEYS, msg=label_object)
			self.assertEqual(doc["payload"], gs1.giai_payload(doc["set_id"]))
			self.assertEqual(doc["hri"], gs1.giai_hri(doc["set_id"]))
			self.assertEqual(gs1.split_set_id(doc["set_id"], doc["type_code"])[0], gs1.DEFAULT_COMPANY_PREFIX)
			self.assertTrue(doc["is_test"])
			self.assertTrue(doc["is_implant"])
			self.assertRegex(doc["issued_on"], r"^\d{2}/\d{2}/\d{4}$")
			self.assertFalse(doc["set_type_name"].isascii())  # có dấu để thử cả hai chế độ in
			self.assertEqual(sample_context(label_object), doc)
		for label_object in ("Pack", "Equipment", "Nope", "", None):
			with self.assertRaises(frappe.ValidationError, msg=repr(label_object)):
				sample_set_context(label_object)

	def test_set_templates_fit_inside_label(self):
		long_values = {
			"set_id": LONGEST_SET_ID,
			"payload": gs1.giai_payload(LONGEST_SET_ID),
			"hri": gs1.giai_hri(LONGEST_SET_ID),
			"type_code": "ABCDEFGH",
			"set_type_name": "Bộ phẫu thuật chấn thương chỉnh hình cột sống thắt lưng loại lớn",
			"department": "Khoa Phẫu thuật gây mê hồi sức và chống đau sau mổ",
			"method": "Hấp hơi nước",
		}
		dm_box = _datamatrix_box(long_values["payload"])
		for label_object, (name, width_mm, height_mm) in SIZES.items():
			width, height = core_print.mm_to_dots(width_mm, 300), core_print.mm_to_dots(height_mm, 300)
			for unicode in (False, True):
				doc = {**sample_set_context(label_object), **long_values}
				zpl = core_print.render_label(
					label_object, doc, printer={"language": "ZPL", "supports_unicode": int(unicode)}
				)
				self.assertIn(f"^PW{width}", zpl)
				self.assertIn(f"^LL{height}", zpl)
				boxes = _text_boxes(zpl, width)
				self.assertGreaterEqual(len(boxes), 3, msg=zpl)
				for x0, y0, x1, y1, text in boxes:
					self.assertLessEqual(x1, width, msg=(name, text))
					self.assertLessEqual(y1, height, msg=(name, text))
					# chữ không đè lên DataMatrix
					self.assertTrue(x0 >= dm_box[2] or y0 >= dm_box[3], msg=(name, text, dm_box))
