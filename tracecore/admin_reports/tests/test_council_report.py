"""Báo cáo Hội đồng KSNK một trang hằng tháng (FEAT-065 AC-065-07..11; FR-M9-25, FR-M9-25.1, FR-M9-25.2;
BRU-RPT-002, BRU-RPT-003; UC-57 bước 4, A1)."""

import datetime
import io
from unittest.mock import patch

import frappe

from tracecore.admin_reports import council_report, indicator
from tracecore.admin_reports.tests.test_ic_board import YEAR, BoardCase, _value
from tracecore.tests.utils import bru

PERIOD = f"{YEAR}-10"


def _blank_pdf():
	from pypdf import PdfWriter

	writer = PdfWriter()
	writer.add_blank_page(width=595, height=842)
	buffer = io.BytesIO()
	writer.write(buffer)
	return buffer.getvalue()


FAKE_PDF = _blank_pdf()


def _settings_workday(value):
	frappe.db.set_single_value("IC Program Settings", "council_report_workday", value)


class TestWorkingDay(BoardCase):
	def test_fifth_working_day_skips_weekends(self):
		_settings_workday(5)
		# 01/12/2031 là thứ Hai → ngày làm việc thứ 5 là thứ Sáu 05/12
		self.assertEqual(council_report.report_day(2031, 12), datetime.date(2031, 12, 5))
		# 01/11/2031 là thứ Bảy → 03, 04, 05, 06, 07/11
		self.assertEqual(council_report.report_day(2031, 11), datetime.date(2031, 11, 7))

	def test_configured_day_and_holidays(self):
		_settings_workday(2)
		with patch.object(council_report, "_holidays", return_value={datetime.date(2031, 12, 2)}):
			self.assertEqual(council_report.report_day(2031, 12), datetime.date(2031, 12, 3))

	def test_out_of_range_setting_falls_back_to_default(self):
		_settings_workday(0)
		self.assertEqual(council_report.workday(), 5)
		_settings_workday(40)
		self.assertEqual(council_report.workday(), 23)

	def test_holidays_read_from_default_company_list(self):
		company = frappe.defaults.get_global_default("company")
		if not company:
			self.skipTest("site has no default company")
		holiday_list = frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": "KSNK Council Test",
				"from_date": "2031-01-01",
				"to_date": "2031-12-31",
				"holidays": [{"holiday_date": "2031-12-02", "description": "Test"}],
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Company", company, "default_holiday_list", holiday_list.name)
		self.assertIn(datetime.date(2031, 12, 2), council_report._holidays(2031, 12))


class TestCouncilReport(BoardCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("IC Council Report")
		self.pdf = patch.object(council_report, "_pdf", return_value=FAKE_PDF)
		self.pdf.start()
		self.addCleanup(self.pdf.stop)
		self.emit = patch("tracecore.core.notification.emit")
		self.emitted = self.emit.start()
		self.addCleanup(self.emit.stop)

	def test_runs_only_on_report_day_for_previous_month(self):
		_settings_workday(5)
		self.assertIsNone(council_report.run_daily(datetime.date(2031, 11, 6)))
		name = council_report.run_daily(datetime.date(2031, 11, 7))
		doc = frappe.get_doc("IC Council Report", name)
		self.assertEqual(doc.period, PERIOD)
		self.assertEqual(doc.name, f"BCHD-{PERIOD}")
		self.assertTrue(doc.pdf)
		self.emitted.assert_called_once()
		self.assertEqual(self.emitted.call_args.args[0], council_report.EVENT)

	def test_running_twice_does_not_duplicate(self):
		_settings_workday(5)
		council_report.run_daily(datetime.date(2031, 11, 7))
		self.assertIsNone(council_report.run_daily(datetime.date(2031, 11, 7)))
		self.assertEqual(frappe.db.count("IC Council Report"), 1)
		self.emitted.assert_called_once()

	def test_locked_period_gives_official_report(self):
		doc = frappe.get_doc("IC Council Report", council_report.generate(PERIOD))
		self.assertEqual(doc.report_status, council_report.OFFICIAL)

	def test_unlocked_period_is_provisional_then_official_on_lock(self):
		period = f"{YEAR}-11"
		_value("FB-HH", period, 90, 100, locked=0)
		with patch("tracecore.core.indicators.registry", return_value={}):
			name = council_report.generate(period)
			self.assertEqual(
				frappe.db.get_value("IC Council Report", name, "report_status"), council_report.PROVISIONAL
			)
			indicator.lock_period(period)
		self.assertEqual(
			frappe.db.get_value("IC Council Report", name, "report_status"), council_report.OFFICIAL
		)
		self.assertEqual(self.emitted.call_count, 2)

	def test_lock_without_provisional_report_does_nothing(self):
		with patch("tracecore.core.indicators.registry", return_value={}):
			indicator.lock_period(f"{YEAR}-12")
		self.assertFalse(frappe.db.exists("IC Council Report", f"BCHD-{YEAR}-12"))

	def test_context_lists_plan_indicators_with_status_text(self):
		self.approved_plan([("FB-HH", 70, 82), ("FB-VAP", 9, 7)])
		name = council_report.generate(PERIOD)
		context = council_report.tc_ic_council_context(name)
		self.assertEqual(context["period_label"], f"10/{YEAR}")
		self.assertFalse(context["provisional"])
		self.assertEqual([row["code"] for row in context["rows"]], ["FB-HH", "FB-VAP"])
		self.assertEqual(context["rows"][0]["values"][-1], "84 %")
		self.assertEqual(context["rows"][0]["status_label"], "Met")
		self.assertEqual(context["rows"][1]["values"][-1], "Not calculated")

	@bru("BRU-RPT-002")
	def test_report_holds_aggregates_only(self):
		def todo(user, department):
			return [
				{
					"key": "x",
					"severity": "error",
					"title": "2 new MDRO isolates",
					"count": 2,
					"detail": "Patient BN-0012345 bed 7",
				}
			]

		with patch("tracecore.admin_reports.ic_board._todo_paths", return_value=[todo]):
			name = council_report.generate(PERIOD)
			html = council_report.render_html(name)
		self.assertIn("2 new MDRO isolates", html)
		self.assertNotIn("BN-0012345", html)
		self.assertNotIn("Patient", html)

	@bru("BRU-RPT-003")
	def test_locked_values_unchanged_after_source_change(self):
		frappe.db.set_value("IC Indicator", "FB-HH", "national_target", 99)
		with patch("tracecore.core.indicators.registry", side_effect=AssertionError("no recompute")):
			name = council_report.generate(PERIOD)
		context = council_report.tc_ic_council_context(name)
		hh = next(row for row in context["rows"] if row["code"] == "FB-HH")
		self.assertEqual(hh["values"][-1], "84 %")

	def test_html_renders_with_print_format(self):
		name = council_report.generate(PERIOD)
		html = council_report.render_html(name)
		self.assertIn("FB-HH", html)
		self.assertIn("10/" + str(YEAR), html)

	def test_only_r01_can_regenerate_from_screen(self):
		from tracecore.v1 import indicator as api

		frappe.set_user(self.r13)
		with self.assertRaises(frappe.PermissionError):
			api.council_generate(PERIOD)
		frappe.set_user(self.r01)
		result = api.council_generate(PERIOD)
		self.assertEqual(result["period"], PERIOD)
		frappe.set_user(self.r13)
		self.assertEqual(api.council_reports()[0]["period"], PERIOD)

	def test_latest_report_is_an_info_todo_for_hospital_only(self):
		council_report.generate(PERIOD)
		items = council_report.todos("Administrator", None)
		self.assertEqual(items[0]["severity"], "info")
		self.assertEqual(council_report.todos("Administrator", self.dept_a), [])
