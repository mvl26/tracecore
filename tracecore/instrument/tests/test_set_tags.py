"""Ngữ cảnh và bản in thẻ kim loại / nhãn khay của Set Unit (FEAT-016 Task 3, G3, G8; FR-M1-05; BRU-ID-001)."""

import base64
import datetime
import io
import os
import time
from unittest.mock import patch

import frappe
import frappe.utils.data
from PIL import Image

from tracecore.core import gs1
from tracecore.core.errors import BlockedError
from tracecore.core.tests.test_code_registry import production_site
from tracecore.instrument import set_tags
from tracecore.tests.factories import make_department, make_set_type, make_set_unit
from tracecore.tests.utils import IsolatedTestCase, bru

# Set Unit liên kết Department, Zone Station, Instrument Set Type (→ Item) và User; CI chưa có Setup Wizard
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

ASCII = {"language": "ZPL", "supports_unicode": 0}
UNICODE = {"language": "ZPL", "supports_unicode": 1}
REAL_PREFIX = "8931234"  # dải 893 (Việt Nam), không phải demo 952


def _unit(type_code="TAG", set_type_name="Bộ khám tổng quát", is_implant=0, method="Steam"):
	set_type = make_set_type(type_code, set_type_name=set_type_name, is_implant=is_implant, method=method)
	return make_set_unit(set_type.name, department=make_department())


class TestSetTags(IsolatedTestCase):
	def test_kinds(self):
		self.assertEqual(set_tags.KINDS, {"tag": "Set Tag", "tray": "Set Tray Label"})
		unit = _unit()
		for kind in ("", "Set Tag", "label", None):
			with self.assertRaises(frappe.ValidationError, msg=repr(kind)):
				set_tags.tag_context(unit.name, kind)
		with self.assertRaises(frappe.DoesNotExistError):
			set_tags.tag_context("9520000TAG999999", "tag")

	@bru("BRU-ID-001")
	def test_tag_context_shape(self):
		unit = _unit("TAGC", is_implant=1)
		context = set_tags.tag_context(unit.name, "tray")
		department = frappe.db.get_value("Department", unit.department, "department_name")
		self.assertEqual(
			context,
			{
				"set_id": unit.name,
				"payload": gs1.giai_payload(unit.name),
				"hri": gs1.giai_hri(unit.name),
				"type_code": "TAGC",
				"set_type_name": "Bộ khám tổng quát",
				"department": department,
				"method": "Steam",
				"is_implant": True,
				"issued_on": frappe.utils.get_datetime(unit.creation).strftime("%d/%m/%Y"),
				"is_test": True,
			},
		)
		self.assertEqual(set_tags.tag_context(unit.name, "tag"), context)
		# bộ không có khoa (dữ liệu trước FEAT-016) → chuỗi rỗng, không "None"
		bare = make_set_unit(unit.set_type)
		self.assertEqual(set_tags.tag_context(bare.name, "tag")["department"], "")

	@bru("BRU-ID-001")
	def test_render_tag_contains_datamatrix_and_hri(self):
		unit = _unit("TAGD")
		for kind in set_tags.KINDS:
			zpl = set_tags.render(unit.name, kind)
			self.assertTrue(zpl.startswith("^XA"), msg=zpl)
			self.assertTrue(zpl.endswith("^XZ"), msg=zpl)
			self.assertEqual(zpl.count("^BXN"), 1, msg=zpl)
			self.assertEqual(zpl.count("^XA"), 1)
			self.assertIn(f"^FD_18004{unit.name}^FS", zpl)
			self.assertIn(f"(8004){unit.name}", zpl)
			self.assertIn("TAGD", zpl)
			self.assertTrue(zpl.isascii(), msg=zpl)  # không truyền máy in → bỏ dấu
		tag = set_tags.render(unit.name, "tag")
		self.assertIn("^PW591", tag)
		self.assertIn("^LL354", tag)
		tray = set_tags.render(unit.name, "tray")
		self.assertIn("^PW709", tray)
		self.assertIn("^LL472", tray)
		self.assertIn("Bo kham tong quat", tray)
		department = frappe.db.get_value("Department", unit.department, "department_name")
		self.assertIn(department, tray)
		self.assertIn("Steam", tray)
		self.assertIn(set_tags.tag_context(unit.name, "tray")["issued_on"], tray)
		self.assertNotIn("CAY GHEP", tray)
		implant = _unit("TAGI", set_type_name="Bộ cấy ghép cột sống", is_implant=1, method="Plasma")
		implant_tray = set_tags.render(implant.name, "tray")
		self.assertIn("CAY GHEP", implant_tray)
		self.assertIn("Plasma", implant_tray)
		zpl, template = set_tags.render(implant.name, "tray", with_template=True)
		self.assertEqual(
			(zpl, template.name, template.label_object), (implant_tray, "Set tray label", "Set Tray Label")
		)

	def test_render_sanitizes_and_folds(self):
		plain = set_tags.render(_unit("TAGP", set_type_name="Bo kham").name, "tray", ASCII)
		unit = _unit("TAGS", set_type_name="Bộ ^FO khám ~JA")
		folded = set_tags.render(unit.name, "tray", ASCII)
		kept = set_tags.render(unit.name, "tray", UNICODE)
		self.assertIn("Bo FO kham JA", folded)
		self.assertIn("Bộ FO khám JA", kept)
		self.assertTrue(folded.isascii(), msg=folded)
		self.assertFalse(kept.isascii())
		for zpl in (folded, kept):
			self.assertEqual(zpl.count("^FO"), plain.count("^FO"))
			self.assertEqual(zpl.count("^XZ"), 1)
			self.assertNotIn("~", zpl)
			self.assertIn(f"^FD_18004{unit.name}^FS", zpl)

	def test_issued_on_timezone(self):
		# tiến trình chạy UTC, lúc 17:01 UTC ngày 14/03 = 00:01 ngày 15/03 giờ Việt Nam (giờ hệ thống)
		utc = datetime.datetime(2026, 3, 14, 17, 1, tzinfo=datetime.timezone.utc)
		local = frappe.utils.convert_utc_to_system_timezone(utc).replace(tzinfo=None)
		self.assertEqual(local.strftime("%d/%m/%Y %H:%M"), "15/03/2026 00:01")
		previous = os.environ.get("TZ")
		os.environ["TZ"] = "UTC"
		time.tzset()

		def restore():
			if previous is None:
				os.environ.pop("TZ", None)
			else:
				os.environ["TZ"] = previous
			time.tzset()

		self.addCleanup(restore)
		with patch.object(frappe.utils.data, "now_datetime", return_value=local):
			unit = _unit("TAGZ")
		self.assertEqual(frappe.utils.get_datetime(unit.creation), local)
		# ngày cấp lấy từ `creation` (giờ hệ thống), không phải hôm nay hay ngày UTC của tiến trình
		self.assertEqual(set_tags.tag_context(unit.name, "tray")["issued_on"], "15/03/2026")
		self.assertIn("15/03/2026", set_tags.render(unit.name, "tray"))

	@bru("BRU-ID-001")
	def test_demo_prefix_prints_test_line(self):
		demo = _unit("TAGT")
		self.assertTrue(gs1.is_demo_prefix(demo.name))
		for kind in set_tags.KINDS:
			self.assertTrue(set_tags.tag_context(demo.name, kind)["is_test"])
			self.assertIn("^FDTEST^FS", set_tags.render(demo.name, kind))
		with patch.dict(frappe.conf, {"tc_gs1_company_prefix": REAL_PREFIX}):
			real = _unit("TAGR")
		self.assertTrue(real.name.startswith(REAL_PREFIX + "TAGR"))
		for kind in set_tags.KINDS:
			self.assertFalse(set_tags.tag_context(real.name, kind)["is_test"])
			self.assertNotIn("TEST", set_tags.render(real.name, kind))
		# site thật: Set ID tiền tố demo (DB dev chép sang) không dựng được thẻ/nhãn/xem trước; tiền tố thật vẫn in
		conf, flags = production_site(tc_gs1_company_prefix=REAL_PREFIX)
		with conf, flags:
			for call in (set_tags.tag_context, set_tags.render, set_tags.preview):
				with self.assertRaises(BlockedError, msg=call.__name__) as raised:
					call(demo.name, "tag")
				self.assertEqual(raised.exception.block.code, "GS1_PREFIX_NOT_CONFIGURED")
			self.assertNotIn("TEST", set_tags.render(real.name, "tag"))
			self.assertTrue(set_tags.preview(real.name, "tray")["zpl"])

	@bru("BRU-ID-001")
	def test_preview_png_decodes_to_payload(self):
		unit = _unit("TAGV", set_type_name="Bộ khám ^tai~")
		for kind, size in (("tag", (591, 354)), ("tray", (709, 472))):
			preview = set_tags.preview(unit.name, kind)
			self.assertEqual(set(preview), {"png_b64", "zpl", "hri"})
			self.assertEqual(preview["hri"], gs1.giai_hri(unit.name))
			self.assertEqual(preview["zpl"], set_tags.render(unit.name, kind, ASCII))
			png = base64.b64decode(preview["png_b64"])
			self.assertEqual(Image.open(io.BytesIO(png)).size, size)
			self.assertEqual(gs1.decode_datamatrix_png(png), gs1.giai_payload(unit.name))
