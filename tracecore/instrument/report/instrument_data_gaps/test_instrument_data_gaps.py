"""Báo cáo Instrument Data Gaps (FR-M1-01.2, A-06 I4): dụng cụ Đang dùng thiếu cơ số/ảnh/IFU/Spaulding/phương pháp."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.instrument.report.instrument_data_gaps.instrument_data_gaps import execute
from tracecore.tests.factories import make_instrument, make_user

test_ignore = ["Item", "User", "Batch"]


def _rows(filters=None):
	columns, data = execute(filters)
	return columns, {row["instrument"]: row for row in data}


class TestInstrumentDataGaps(FrappeTestCase):
	def test_data_gaps_report_lists_undefined_and_missing_media(self):
		complete = make_instrument(
			"DG-FULL", max_cycles=500, image="/files/dg-full.png", ifu="/files/dg-full.pdf", group="DG-GRP"
		)
		no_cycles = make_instrument(
			"DG-NOCYC", image="/files/dg-nocyc.png", ifu="/files/dg-nocyc.pdf", group="DG-GRP"
		)
		no_media = make_instrument("DG-NOMEDIA", max_cycles=300, group="DG-OTHER")
		retired = make_instrument("DG-RET")
		retired.db_set("status", "Retired")

		columns, rows = _rows({})
		self.assertEqual(
			[column["fieldname"] for column in columns],
			[
				"instrument",
				"instrument_name",
				"instrument_group",
				"max_cycles",
				"image",
				"ifu",
				"spaulding_class",
				"compatible_methods",
			],
		)
		self.assertNotIn(complete.name, rows)
		self.assertNotIn(retired.name, rows)  # mặc định chỉ Đang dùng

		cyc = rows[no_cycles.name]
		self.assertEqual(cyc["max_cycles"], "Undefined")
		self.assertEqual(
			(cyc["image"], cyc["ifu"], cyc["spaulding_class"], cyc["compatible_methods"]), ("",) * 4
		)
		self.assertEqual(
			(cyc["instrument_name"], cyc["instrument_group"]), (no_cycles.instrument_name, "DG-GRP")
		)

		media = rows[no_media.name]
		self.assertEqual(media["max_cycles"], "")
		self.assertTrue(media["image"])
		self.assertTrue(media["ifu"])
		self.assertEqual(media["image"], media["ifu"])

		_columns, retired_rows = _rows({"status": "Retired"})
		self.assertIn(retired.name, retired_rows)
		self.assertNotIn(no_cycles.name, retired_rows)

		_columns, grouped = _rows({"instrument_group": "DG-GRP"})
		self.assertIn(no_cycles.name, grouped)
		self.assertNotIn(no_media.name, grouped)

	def test_report_definition_and_roles(self):
		report = frappe.get_doc("Report", "Instrument Data Gaps")
		self.assertEqual(
			(report.report_type, report.ref_doctype, report.module, report.is_standard),
			("Script Report", "Instrument", "Instrument", "Yes"),
		)
		self.assertEqual({row.role for row in report.roles}, {"TC R01", "TC R02", "TC R10", "System Manager"})
		for role, allowed in (("TC R01", True), ("TC R02", True), ("TC R10", True), ("TC R04", False)):
			user = make_user(f"dg-{role[-3:].lower()}@example.com", roles=[role])
			frappe.set_user(user)
			try:
				self.assertEqual(bool(report.is_permitted()), allowed, msg=role)
				if allowed:
					self.assertTrue(frappe.has_permission("Instrument", "report"), msg=role)
			finally:
				frappe.set_user("Administrator")
