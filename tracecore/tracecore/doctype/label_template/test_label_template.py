import re
from unittest.mock import patch

import frappe
from PIL import ImageFont

from tracecore.core import print as core_print
from tracecore.patches.v0_1 import create_sample_label_templates
from tracecore.setup import install
from tracecore.setup.label_templates import SAMPLE_TEMPLATES, ensure_sample_templates, sample_pack_context
from tracecore.tests.utils import IsolatedTestCase

BODY = "^XA^FD{{ text(doc.set_name) }}^FS^XZ"
# ^FO x,y [^A0N h,w] [^FB width,lines,spacing,justify,indent] ^FD text ^FS
FIELD = re.compile(r"\^FO(\d+),(\d+)(?:\^A0N,(\d+),(\d+))?(?:\^FB(\d+),(\d+),(\d+),[LCRJ],\d+)?\^FD(.*?)\^FS")
# DataMatrix ECC200 lớn nhất mà payload Cycle ID có thể chọn: 26 x 26 module, module 6 dot
DATAMATRIX_BOX = (24, 24, 24 + 26 * 6, 24 + 26 * 6)


def _template(name, **values):
	return frappe.get_doc(
		{
			"doctype": "Label Template",
			"template_name": name,
			"label_object": "Pack",
			"method": "Steam",
			"language": "ZPL",
			"width_mm": 60,
			"height_mm": 40,
			"dpi": 300,
			"body": BODY,
			**values,
		}
	)


def _text_boxes(zpl, width_dots):
	"""[(x0, y0, x1, y1, text)] của từng ô chữ trong ZPL, ước lượng bề rộng bằng phông Pillow."""
	boxes = []
	for x, y, height, _width, block, lines, spacing, text in FIELD.findall(zpl):
		if not height:
			continue  # DataMatrix
		x, y, height = int(x), int(y), int(height)
		font = ImageFont.load_default(size=height)
		estimated = font.getlength(text)
		if block:
			lines, spacing = int(lines), int(spacing)
			assert estimated <= int(block) * lines, f"text clipped by ^FB: {text!r}"
			right, bottom = x + int(block), y + lines * height + (lines - 1) * spacing
		else:
			right, bottom = x + estimated, y + height
		boxes.append((x, y, right, bottom, text))
	return boxes


class TestLabelTemplate(IsolatedTestCase):
	def test_one_active_template_per_object_method_language(self):
		# mẫu mẫu đã active cho (Pack, Steam, ZPL) → mẫu thứ hai cùng bộ ba không được active
		self.assertTrue(frappe.db.get_value("Label Template", "Pack label - Steam", "is_active"))
		with self.assertRaises(frappe.ValidationError):
			_template("Second steam template").insert()
		with self.assertRaises(frappe.ValidationError):
			_template("Second plasma template", method="Plasma").insert()
		spare = _template("Spare steam template", is_active=0).insert()
		self.assertFalse(spare.is_active)

	def test_deactivating_the_active_template_frees_the_slot(self):
		frappe.db.set_value("Label Template", "Pack label - Steam", "is_active", 0)
		self.assertTrue(_template("R10 steam template").insert().is_active)

	def test_activating_a_second_template_is_rejected(self):
		spare = _template("Another spare", is_active=0).insert()
		spare.is_active = 1
		with self.assertRaises(frappe.ValidationError):
			spare.save()

	def test_template_can_be_resaved_while_active(self):
		doc = frappe.get_doc("Label Template", "Pack label - Plasma")
		doc.save()  # không tự va chạm với chính nó
		self.assertTrue(frappe.db.get_value("Label Template", doc.name, "is_active"))

	def test_body_must_be_valid_jinja(self):
		with self.assertRaises(frappe.ValidationError):
			_template("Broken template", is_active=0, body="^XA{% if %}^XZ").insert()

	def test_size_and_dpi_must_be_positive(self):
		for field in ("width_mm", "height_mm", "dpi"):
			with self.assertRaises(frappe.ValidationError, msg=field):
				_template(f"Zero {field}", is_active=0, **{field: 0}).insert()

	def test_template_cannot_be_deleted(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Label Template", "Pack label - Steam", ignore_permissions=True)

	def test_audit_log_records_template_edit(self):
		doc = _template("Audited template", is_active=0).insert()
		self.assertTrue(
			frappe.db.exists(
				"Audit Log", {"ref_doctype": "Label Template", "ref_name": doc.name, "action": "Create"}
			)
		)

	def test_permissions(self):
		perms = {
			p.role: p
			for p in frappe.get_all(
				"DocPerm",
				filters={"parent": "Label Template"},
				fields=["role", "read", "write", "create", "delete"],
			)
		}
		self.assertEqual(set(perms), {"System Manager", "TC R10", "TC R01", "TC R02"})
		for role in ("System Manager", "TC R10"):
			self.assertTrue(perms[role].write and perms[role].create, msg=role)
		self.assertFalse(any(p.delete for p in perms.values()))


class TestSampleTemplates(IsolatedTestCase):
	def test_sample_templates_installed(self):
		self.assertEqual(
			[sample["template_name"] for sample in SAMPLE_TEMPLATES],
			["Pack label - Steam", "Pack label - Plasma"],
		)
		for sample in SAMPLE_TEMPLATES:
			doc = frappe.get_doc("Label Template", sample["template_name"])
			self.assertEqual(
				(
					doc.label_object,
					doc.method,
					doc.language,
					doc.width_mm,
					doc.height_mm,
					doc.dpi,
					doc.is_active,
				),
				("Pack", sample["method"], "ZPL", 60, 40, 300, 1),
			)
			self.assertIn("{{", doc.body)

	def test_sample_templates_survive_reinstall(self):
		edited = "^XA^FDedited by R10^FS^XZ"
		frappe.db.set_value("Label Template", "Pack label - Steam", "body", edited)
		self.assertEqual(ensure_sample_templates(), [])
		self.assertEqual(frappe.db.get_value("Label Template", "Pack label - Steam", "body"), edited)

	def test_ensure_sample_templates_creates_missing_ones(self):
		frappe.db.delete("Label Template", {"name": "Pack label - Plasma"})
		self.assertEqual(ensure_sample_templates(), ["Pack label - Plasma"])
		doc = frappe.get_doc("Label Template", "Pack label - Plasma")
		self.assertTrue(doc.is_active)
		self.assertIn("Plasma label", core_print.render(doc.body, sample_pack_context()))

	def test_after_install_and_patch_create_missing_samples(self):
		frappe.db.delete("Label Template", {"name": "Pack label - Plasma"})
		with patch.object(install, "apply_system_settings"):
			install.after_install()
		self.assertTrue(frappe.db.exists("Label Template", "Pack label - Plasma"))
		frappe.db.delete("Label Template", {"name": "Pack label - Steam"})
		create_sample_label_templates.execute()
		self.assertTrue(frappe.db.exists("Label Template", "Pack label - Steam"))

	def test_ensure_sample_templates_does_not_steal_the_active_slot(self):
		frappe.db.delete("Label Template", {"name": "Pack label - Steam"})
		_template("R10 own steam template").insert()
		self.assertEqual(ensure_sample_templates(), ["Pack label - Steam"])
		self.assertFalse(frappe.db.get_value("Label Template", "Pack label - Steam", "is_active"))
		self.assertEqual(core_print.pack_template("Steam"), BODY)

	def test_sample_context_is_complete_and_uses_test_gtin(self):
		doc = sample_pack_context()
		keys = {
			"set_id",
			"cycle_id",
			"set_name",
			"dept",
			"packer",
			"packed_at",
			"expiry",
			"method_label",
			"pack_type",
			"ci_lot",
			"bom_version",
			"is_loaner",
			"is_test",
			"warning",
			"payload",
			"hri",
		}
		self.assertEqual(set(doc), keys)
		self.assertTrue(doc["is_test"])
		self.assertIn("(01)09520000000011(11)261020(17)261119(21)CY-261020-0001", doc["hri"])
		self.assertEqual(sample_pack_context(warning="x")["warning"], "x")
		# tiếng Việt có dấu để thử cả hai chế độ in
		self.assertFalse(doc["set_name"].isascii())

	def test_sample_templates_render_in_both_unicode_modes(self):
		for sample in SAMPLE_TEMPLATES:
			body = frappe.db.get_value("Label Template", sample["template_name"], "body")
			for unicode in (False, True):
				zpl = core_print.render(body, sample_pack_context(), unicode=unicode)
				self.assertTrue(zpl.startswith("^XA") and zpl.endswith("^XZ"), msg=sample["template_name"])
				self.assertEqual(zpl.count("^BXN"), 1)
				self.assertIn("^CI28", zpl)
				self.assertEqual(zpl.isascii(), not unicode)

	def test_sample_templates_name_the_method_on_the_footer(self):
		footers = {"Steam": "Steam label", "Plasma": "Plasma label"}
		for method, footer in footers.items():
			zpl = core_print.render_pack(method, sample_pack_context())
			self.assertTrue(zpl[: -len("^FS^XZ")].endswith(footer), msg=zpl[-60:])
			self.assertNotIn(footers["Plasma" if method == "Steam" else "Steam"], zpl)

	def test_sample_templates_fit_inside_label_without_overlap(self):
		width, height = core_print.mm_to_dots(60, 300), core_print.mm_to_dots(40, 300)
		worst_case = sample_pack_context(
			is_test=True,
			is_loaner=True,
			warning="Cảnh báo: bộ mượn, kiểm tra lại chỉ thị trước khi dùng",
			set_name="Bộ phẫu thuật chấn thương chỉnh hình lớn dùng cho khoa ngoại",
			packer="Nguyễn Thị Hồng Nhung",
			dept="Khoa Phẫu thuật chỉnh hình",
		)
		for sample in SAMPLE_TEMPLATES:
			for unicode in (False, True):
				zpl = core_print.render_pack(sample["method"], worst_case, unicode=unicode)
				boxes = _text_boxes(zpl, width)
				self.assertGreaterEqual(len(boxes), 10, msg=zpl)
				for x0, _y0, x1, y1, text in boxes:
					self.assertGreaterEqual(x0, 0)
					self.assertLessEqual(x1, width, msg=text)
					self.assertLessEqual(y1, height, msg=text)
				occupied = [DATAMATRIX_BOX, *[box[:4] for box in boxes]]
				for index, (ax0, ay0, ax1, ay1) in enumerate(occupied):
					for bx0, by0, bx1, by1 in occupied[index + 1 :]:
						overlap = ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1
						self.assertFalse(
							overlap, msg=f"{(ax0, ay0, ax1, ay1)} overlaps {(bx0, by0, bx1, by1)}"
						)
