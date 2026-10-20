import io
import json

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from tracecore.core import code_registry, gs1
from tracecore.core import print as core_print
from tracecore.core.errors import BlockedError
from tracecore.setup.label_templates import sample_pack_context
from tracecore.tests.factories import make_item, make_label_items, make_printer, make_roll
from tracecore.tests.utils import IsolatedTestCase, bru


class TestCorePrint(FrappeTestCase):
	def test_render_test_label(self):
		label = core_print.render_test_label("TR-004")
		giai = label["giai"]
		self.assertTrue(giai.startswith(gs1.configured_company_prefix() + "TEST"))
		self.assertEqual(label["hri"], "(8004)" + giai)
		zpl = label["zpl"]
		self.assertTrue(zpl.startswith("^XA"))
		self.assertTrue(zpl.endswith("^XZ"))
		for part in ("^CI28", "^PW590", "^BXN", "^FD_18004" + giai, "TraceCore TEST", "TR-004"):
			self.assertIn(part, zpl)
		image = Image.open(io.BytesIO(label["preview_png"]))
		self.assertEqual(image.size, (590, 354))
		self.assertEqual(gs1.decode_datamatrix_png(label["preview_png"]), "\x1d8004" + giai)

	def test_label_text_fits_inside_label(self):
		from PIL import ImageFont

		giai = gs1.make_giai(gs1.configured_company_prefix(), "TEST" + "9" * 12)
		for x, y, size, text in core_print.label_layout(giai, "TR-004"):
			width = ImageFont.load_default(size=size).getlength(text)
			self.assertLessEqual(x + width, core_print.LABEL_WIDTH_DOTS, msg=text)
			self.assertLessEqual(y + size, core_print.LABEL_HEIGHT_DOTS, msg=text)

	def test_test_label_does_not_consume_codes(self):
		label = core_print.render_test_label("TR-004")
		self.assertFalse(code_registry.is_issued(label["giai"]))

	def test_create_job_and_ack_printed(self):
		job = core_print.create_job("TR-004", "^XA^XZ", {"k": 1}, "test-label")
		doc = frappe.get_doc("Print Job", job)
		self.assertEqual((doc.status, doc.attempts, doc.station), ("Queued", 0, "TR-004"))

		result = core_print.ack(job, "Printed", "File", output_ref="/tmp/1.zpl")
		self.assertEqual(result, {"ok": True, "status": "Printed"})
		doc.reload()
		self.assertEqual(
			(doc.status, doc.output_mode, doc.output_ref, doc.attempts), ("Printed", "File", "/tmp/1.zpl", 1)
		)
		self.assertIsNotNone(doc.printed_at)

	def test_ack_failed_records_error(self):
		job = core_print.create_job("TR-004", "^XA^XZ")
		core_print.ack(job, "Failed", "Printer", error="timeout")
		doc = frappe.get_doc("Print Job", job)
		self.assertEqual((doc.status, doc.error, doc.attempts), ("Failed", "timeout", 1))
		self.assertIsNone(doc.printed_at)

	def test_ack_rejects_invalid_values(self):
		job = core_print.create_job("TR-004", "^XA^XZ")
		with self.assertRaises(frappe.ValidationError):
			core_print.ack(job, "Weird", "File")
		with self.assertRaises(frappe.ValidationError):
			core_print.ack(job, "Printed", "Fax")

	def test_ack_unknown_job(self):
		with self.assertRaises(frappe.DoesNotExistError):
			core_print.ack("987654321", "Printed", "File")


class TestDialect(FrappeTestCase):
	def test_dialect_registry(self):
		self.assertEqual(set(core_print.DIALECTS), {"ZPL"})
		self.assertEqual(core_print.DIALECTS["ZPL"].name, "ZPL")
		for doctype in ("Printer", "Label Template"):
			options = frappe.get_meta(doctype).get_field("language").options
			self.assertEqual(options, "\n".join(core_print.DIALECTS), msg=doctype)

	def test_get_dialect_rejects_unknown_language(self):
		self.assertIs(core_print.get_dialect("ZPL"), core_print.DIALECTS["ZPL"])
		with self.assertRaises(frappe.ValidationError):
			core_print.get_dialect("TSPL")

	def test_zpl_sanitize_removes_command_characters(self):
		zpl = core_print.DIALECTS["ZPL"]
		self.assertEqual(zpl.sanitize("a^FO~JA b"), "aFOJA b")
		self.assertEqual(zpl.sanitize("line1\r\nline2\tx"), "line1  line2 x")
		# GS (FNC1) của payload DataMatrix phải còn nguyên
		self.assertEqual(zpl.sanitize("\x1d01"), "\x1d01")

	def test_zpl_validate_requires_xa_to_xz_frame(self):
		zpl = core_print.DIALECTS["ZPL"]
		zpl.validate("^XA^FDx^FS^XZ")
		zpl.validate("\n^XA^XZ\n")
		for bad in ("", "^FDx^FS", "^XA^FDx^FS", "x^XA^XZ", "^XA^XZx"):
			with self.assertRaises(frappe.ValidationError, msg=repr(bad)):
				zpl.validate(bad)

	def test_zpl_datamatrix_delegates_to_gs1(self):
		zpl = core_print.DIALECTS["ZPL"]
		self.assertEqual(zpl.datamatrix("\x1d01", 10, 20), gs1.zpl_datamatrix("\x1d01", 10, 20))
		self.assertIn("^BXN,8,", zpl.datamatrix("A", 1, 1, module=8))
		with self.assertRaises(frappe.ValidationError):
			zpl.datamatrix("ab^cd", 1, 2)
		with self.assertRaises(frappe.ValidationError):
			zpl.datamatrix("", 1, 2)

	def test_fold(self):
		self.assertEqual(core_print.fold("Đường hấp 134°C"), "Duong hap 134C")
		self.assertEqual(core_print.fold("đ Đ ốộ ứ"), "d D oo u")
		self.assertEqual(core_print.fold(None), "")

	def test_mm_to_dots_at_300_dpi(self):
		self.assertEqual((core_print.mm_to_dots(60, 300), core_print.mm_to_dots(40, 300)), (709, 472))
		self.assertEqual((core_print.mm_to_dots(50, 203), core_print.mm_to_dots(30, 203)), (400, 240))


class TestRender(IsolatedTestCase):
	"""Mẫu nhãn mẫu (Pack label - Steam/Plasma) do `migrate` hoặc `after_install` tạo."""

	def setUp(self):
		super().setUp()
		self.body = core_print.pack_template("Steam")
		self.assertTrue(self.body, "Pack label - Steam chưa được cài (bench migrate)")

	def test_render_pack_label(self):
		zpl = core_print.render(self.body, sample_pack_context())
		self.assertTrue(zpl.startswith("^XA"))
		self.assertTrue(zpl.endswith("^XZ"))
		for part in (
			"^BXN",
			"_10109520000000011",
			"(01)09520000000011(11)261020(17)261119(21)CY-261020-0001",
			"HAN SU DUNG / EXP: 19/11/2026",
			"^PW709",
			"^LL472",
		):
			self.assertIn(part, zpl)
		self.assertNotIn("\n", zpl)

	def test_render_prints_test_line_only_for_test_labels(self):
		self.assertIn("TEST", core_print.render(self.body, sample_pack_context(is_test=True)))
		self.assertNotIn("TEST", core_print.render(self.body, sample_pack_context(is_test=False)))

	def test_render_sanitizes_zpl_and_respects_unicode_flag(self):
		plain = core_print.render(self.body, sample_pack_context(set_name="Bo mo tim"))
		hostile = sample_pack_context(set_name="Bộ mổ ^FO tim ~JA")
		folded = core_print.render(self.body, hostile, unicode=False)
		kept = core_print.render(self.body, hostile, unicode=True)
		self.assertIn("Bo mo FO tim JA", folded)
		self.assertIn("Bộ mổ FO tim JA", kept)
		for zpl in (folded, kept):
			self.assertEqual(zpl.count("^FO"), plain.count("^FO"))
			self.assertNotIn("~", zpl)

	def test_render_without_unicode_is_pure_ascii(self):
		zpl = core_print.render(self.body, sample_pack_context(), unicode=False)
		self.assertTrue(zpl.isascii(), msg=zpl)
		kept = core_print.render(self.body, sample_pack_context(), unicode=True)
		self.assertIn("HẠN SỬ DỤNG / EXP: 19/11/2026", kept)
		self.assertIn("Hấp hơi nước 134°C", kept)

	def test_render_prints_blank_for_none_and_missing_values(self):
		doc = sample_pack_context(dept=None, ci_lot=None, warning=None)
		del doc["packer"]
		zpl = core_print.render(self.body, doc)
		self.assertNotIn("None", zpl)
		self.assertNotIn("Undefined", zpl)

	def test_render_cleans_nested_values(self):
		doc = {"lines": ["a^b", ("c~d", None)], "nested": {"x": "e^f"}}
		template = (
			"^XA^FD{{ doc.lines[0] }}|{{ doc.lines[1][0] }}|{{ doc.lines[1][1] }}|{{ doc.nested.x }}^FS^XZ"
		)
		self.assertEqual(core_print.render(template, doc), "^XA^FDab|cd||ef^FS^XZ")

	def test_render_exposes_label_size(self):
		template = "^XA^PW{{ width_dots }}^LL{{ height_dots }}^FD{{ dpi }}^FS^XZ"
		self.assertEqual(core_print.render(template, {}), "^XA^PW709^LL472^FD300^FS^XZ")
		sized = core_print.render(template, {}, dpi=203, width_mm=50, height_mm=30)
		self.assertEqual(sized, "^XA^PW400^LL240^FD203^FS^XZ")

	def test_render_rejects_output_that_is_not_a_zpl_format(self):
		with self.assertRaises(frappe.ValidationError):
			core_print.render("^FDno frame^FS", {})
		with self.assertRaises(frappe.ValidationError):
			core_print.render("^XA{{ doc.x }", {})
		with self.assertRaises(frappe.ValidationError):
			core_print.render("^XA^XZ", {}, language="TSPL")

	def test_pack_template_is_none_without_active_template(self):
		self.assertIsNone(core_print.pack_template("Steam", "TSPL"))
		frappe.db.set_value("Label Template", "Pack label - Plasma", "is_active", 0)
		self.assertIsNone(core_print.pack_template("Plasma"))
		self.assertIsNotNone(core_print.pack_template("Steam"))

	def test_render_pack_uses_template_size_and_method(self):
		zpl = core_print.render_pack("Plasma", sample_pack_context())
		self.assertIn("Plasma label", zpl)
		self.assertIn("^PW709^LL472", zpl)
		frappe.db.set_value("Label Template", "Pack label - Plasma", {"width_mm": 50, "height_mm": 30})
		self.assertIn("^PW591^LL354", core_print.render_pack("Plasma", sample_pack_context()))
		frappe.db.set_value("Label Template", "Pack label - Plasma", "is_active", 0)
		self.assertIsNone(core_print.render_pack("Plasma", sample_pack_context()))


class TestPrinterSelection(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.steam, self.plasma = make_label_items()
		frappe.db.set_value("Printer", {"station": ["in", ["TR-004", "TR-005"]]}, "is_active", 0)

	@bru("BRU-REP-011")
	def test_select_printer_by_method(self):
		p1 = make_printer("TR-004", self.steam, host="10.0.0.5", name="Steam printer")
		p2 = make_printer("TR-004", self.plasma, host="10.0.0.6", name="Plasma printer", supports_unicode=1)
		self.assertEqual(
			core_print.select_printer("TR-004", "Plasma"),
			{
				"name": p2,
				"host": "10.0.0.6",
				"port": 9100,
				"language": "ZPL",
				"supports_unicode": 1,
				"label_type": self.plasma,
			},
		)
		self.assertEqual(core_print.select_printer("TR-004", "Steam")["name"], p1)
		frappe.db.set_value("Printer", p2, "is_active", 0)
		self.assertIsNone(core_print.select_printer("TR-004", "Plasma"))

	@bru("BRU-REP-011")
	def test_no_printer_for_method_without_matching_label_roll_at_station(self):
		make_printer("TR-004", self.steam)
		make_printer("TR-005", self.plasma)
		self.assertIsNone(core_print.select_printer("TR-004", "Plasma"))
		self.assertIsNone(core_print.select_printer("TR-006", "Steam"))

	def test_printer_without_loaded_label_is_never_selected(self):
		frappe.get_doc({"doctype": "Printer", "printer_name": "Bare", "station": "TR-004"}).insert()
		self.assertIsNone(core_print.select_printer("TR-004", "Steam"))

	def test_select_printer_prefers_lowest_name(self):
		first = make_printer("TR-004", self.steam, name="Z created first")
		make_printer("TR-004", self.steam, name="A created second")
		self.assertEqual(core_print.select_printer("TR-004", "Steam")["name"], first)

	def test_station_printers_for_agent(self):
		p1 = make_printer("TR-004", self.steam, host="10.0.0.5")
		p2 = make_printer("TR-004", self.plasma)
		bare = (
			frappe.get_doc({"doctype": "Printer", "printer_name": "Bare", "station": "TR-004"}).insert().name
		)
		inactive = make_printer("TR-004", self.steam)
		frappe.db.set_value("Printer", inactive, "is_active", 0)
		make_printer("TR-005", self.steam)
		common = {"port": 9100, "language": "ZPL"}
		self.assertEqual(
			core_print.station_printers("TR-004"),
			[
				{"name": p1, "host": "10.0.0.5", "label_type": self.steam, "method": "Steam", **common},
				{"name": p2, "host": "", "label_type": self.plasma, "method": "Plasma", **common},
				{"name": bare, "host": "", "label_type": None, "method": None, **common},
			],
		)


class TestCreateJob(IsolatedTestCase):
	def test_create_job_backward_compatible(self):
		job = core_print.create_job("TR-003", "^XA^XZ")
		doc = frappe.get_doc("Print Job", job)
		self.assertEqual(
			(doc.status, doc.template, doc.payload, doc.attempts, doc.printer, doc.station),
			("Queued", "test-label", "^XA^XZ", 0, None, "TR-003"),
		)
		job = core_print.create_job("TR-004", "^XA^XZ", {"k": 1}, "test-label")
		self.assertEqual(json.loads(frappe.db.get_value("Print Job", job, "data")), {"k": 1})

	def test_create_job_with_printer_and_reference(self):
		printer = make_printer("TR-004", make_label_items()[0])
		job = core_print.create_job(
			"TR-004",
			"^XA^XZ",
			printer=printer,
			ref_doctype="Zone Station",
			ref_name="TR-004",
			reprint_reason="Nhãn mờ",
		)
		doc = frappe.get_doc("Print Job", job)
		self.assertEqual(
			(doc.printer, doc.ref_doctype, doc.ref_name, doc.reprint_reason),
			(printer, "Zone Station", "TR-004", "Nhãn mờ"),
		)

	def test_waiting_job_has_no_payload(self):
		data = {"method": "Steam", "label_object": "Pack", "label_context": {"cycle_id": "CY-261020-0001"}}
		job = core_print.create_job("TR-004", None, data, "pack-label", status="Waiting")
		doc = frappe.get_doc("Print Job", job)
		self.assertEqual(doc.status, "Waiting")
		self.assertFalse(doc.payload)
		self.assertEqual(json.loads(doc.data), data)

	def test_create_job_rejects_unknown_status_and_empty_queued_job(self):
		with self.assertRaises(frappe.ValidationError):
			core_print.create_job("TR-004", "^XA^XZ", status="Printed")
		with self.assertRaises(frappe.ValidationError):
			core_print.create_job("TR-004", None)

	def test_print_job_meta(self):
		meta = frappe.get_meta("Print Job")
		self.assertEqual(
			(meta.get_field("printer").fieldtype, meta.get_field("printer").options), ("Link", "Printer")
		)
		self.assertIn("Waiting", meta.get_field("status").options.split("\n"))
		self.assertEqual(meta.get_field("ref_name").fieldtype, "Dynamic Link")


class TestSetRoll(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.steam, self.plasma = make_label_items()
		frappe.db.set_value("Printer", {"station": "TR-004"}, "is_active", 0)
		frappe.db.set_value("Print Job", {"station": "TR-004", "status": "Waiting"}, "status", "Failed")
		self.p1 = make_printer("TR-004", self.steam, host="10.0.0.5")

	def _waiting_job(self, method="Plasma", station="TR-004", context=None):
		data = {
			"method": method,
			"label_object": "Pack",
			"label_context": context or sample_pack_context(),
		}
		return core_print.create_job(station, None, data, "pack-label", status="Waiting")

	@bru("BRU-REP-011")
	def test_set_roll_updates_label_type_and_renders_waiting_jobs(self):
		roll = make_roll(self.plasma)
		job = self._waiting_job("Plasma")
		result = core_print.set_roll(self.p1, roll)

		printer = frappe.get_doc("Printer", self.p1)
		self.assertEqual(
			(printer.label_type_loaded, printer.roll_code, printer.roll_loaded_by),
			(self.plasma, roll, frappe.session.user),
		)
		self.assertIsNotNone(printer.roll_loaded_on)
		self.assertEqual(
			(result["printer"], result["label_type"], result["method"]), (self.p1, self.plasma, "Plasma")
		)
		released = {row["print_job"]: row for row in result["released_jobs"]}
		self.assertIn(job, released)
		zpl = released[job]["zpl"]
		self.assertTrue(zpl.startswith("^XA"))
		self.assertIn("Plasma label", zpl)
		self.assertEqual(released[job]["printer"], self.p1)
		doc = frappe.get_doc("Print Job", job)
		self.assertEqual((doc.status, doc.printer, doc.payload), ("Queued", self.p1, zpl))
		self.assertEqual(doc.template, "Pack label - Plasma")

		audit = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Printer", "ref_name": self.p1, "action": "Update"},
			fields=["old_value", "new_value"],
			order_by="creation desc",
			limit=1,
		)[0]
		old, new = json.loads(audit.old_value), json.loads(audit.new_value)
		self.assertEqual((old["label_type_loaded"], new["label_type_loaded"]), (self.steam, self.plasma))
		self.assertEqual(new["roll_code"], roll)

	def test_set_roll_releases_jobs_in_creation_order(self):
		first, second = self._waiting_job(), self._waiting_job()
		result = core_print.set_roll(self.p1, make_roll(self.plasma))
		self.assertEqual([row["print_job"] for row in result["released_jobs"]], [first, second])

	def test_set_roll_leaves_waiting_jobs_that_do_not_match(self):
		steam_job = self._waiting_job("Steam")
		other_station = self._waiting_job("Plasma", station="TR-005")
		result = core_print.set_roll(self.p1, make_roll(self.plasma))
		self.assertEqual(result["released_jobs"], [])
		for job in (steam_job, other_station):
			self.assertEqual(frappe.db.get_value("Print Job", job, ["status", "printer"]), ("Waiting", None))

	def test_set_roll_for_same_label_type_still_releases_jobs(self):
		job = self._waiting_job("Steam")
		result = core_print.set_roll(self.p1, make_roll(self.steam))
		self.assertEqual([row["print_job"] for row in result["released_jobs"]], [job])

	def test_set_roll_keeps_job_waiting_without_active_template(self):
		frappe.db.set_value("Label Template", "Pack label - Plasma", "is_active", 0)
		job = self._waiting_job("Plasma")
		result = core_print.set_roll(self.p1, make_roll(self.plasma))
		self.assertEqual(result["released_jobs"], [])
		self.assertEqual(frappe.db.get_value("Print Job", job, "status"), "Waiting")
		self.assertEqual(frappe.db.get_value("Printer", self.p1, "label_type_loaded"), self.plasma)

	def test_set_roll_renders_with_printer_unicode_flag(self):
		unicode_printer = make_printer("TR-004", self.steam, name="Unicode", supports_unicode=1)
		job = self._waiting_job("Steam")
		released = core_print.set_roll(unicode_printer, make_roll(self.steam))["released_jobs"]
		self.assertIn("HẠN SỬ DỤNG / EXP: 19/11/2026", released[0]["zpl"])
		self.assertEqual(released[0]["print_job"], job)

	def test_set_roll_rejects_unknown_or_non_label_code(self):
		with self.assertRaises(BlockedError) as unknown:
			core_print.set_roll(self.p1, "CN-99999")
		self.assertEqual(unknown.exception.block.code, "ROLL_NOT_FOUND")
		self.assertEqual(unknown.exception.block.http_status, 404)
		packaging = make_item("VT-BAO-GOI", "Packaging", method="Steam").name
		with self.assertRaises(BlockedError) as not_label:
			core_print.set_roll(self.p1, make_roll(packaging))
		self.assertEqual(not_label.exception.block.code, "ROLL_NOT_LABEL")
		self.assertEqual(not_label.exception.block.http_status, 422)
		self.assertEqual(frappe.db.get_value("Printer", self.p1, "label_type_loaded"), self.steam)
		self.assertFalse(frappe.db.get_value("Printer", self.p1, "roll_code"))

	def test_set_roll_rejects_disabled_and_untyped_roll_codes(self):
		disabled = make_roll(self.plasma)
		frappe.db.set_value("Code Registry", disabled, "status", "Disabled")
		with self.assertRaises(BlockedError) as ctx:
			core_print.set_roll(self.p1, disabled)
		self.assertEqual(ctx.exception.block.code, "ROLL_NOT_FOUND")
		code_registry.register("CN-88888", "CN")
		with self.assertRaises(BlockedError) as ctx:
			core_print.set_roll(self.p1, "CN-88888")
		self.assertEqual(ctx.exception.block.code, "ROLL_NOT_LABEL")
		no_method = make_item("VT-NHAN-KHONG-PP", "Label").name
		with self.assertRaises(BlockedError) as ctx:
			core_print.set_roll(self.p1, make_roll(no_method))
		self.assertEqual(ctx.exception.block.code, "ROLL_NOT_LABEL")

	def test_set_roll_skips_waiting_job_whose_data_is_not_an_object(self):
		job = self._waiting_job("Plasma")
		frappe.db.set_value("Print Job", job, "data", "[1, 2]")
		result = core_print.set_roll(self.p1, make_roll(self.plasma))
		self.assertEqual(result["released_jobs"], [])
		self.assertEqual(frappe.db.get_value("Print Job", job, "status"), "Waiting")

	def test_set_roll_unknown_printer(self):
		with self.assertRaises(frappe.DoesNotExistError):
			core_print.set_roll("PRN-9999", make_roll(self.steam))

	def test_roll_label_item(self):
		roll = make_roll(self.steam)
		self.assertEqual(code_registry.roll_label_item(roll), self.steam)
		self.assertIsNone(code_registry.roll_label_item("CN-99999"))
		code_registry.register("XX-00001", "XX", "Item", self.steam)
		self.assertIsNone(code_registry.roll_label_item("XX-00001"))
		code_registry.register("CN-88888", "CN")
		self.assertIsNone(code_registry.roll_label_item("CN-88888"))
		frappe.db.set_value("Code Registry", roll, "status", "Disabled")
		self.assertIsNone(code_registry.roll_label_item(roll))
