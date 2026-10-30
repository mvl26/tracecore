"""Sổ tiệt khuẩn điện tử, báo cáo KSNK, dự báo hết vòng đời, xuất PDF nền (FEAT-007, FR-M9-02, FR-M9-02.1, A-57)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_months, add_to_date, getdate, now_datetime, today

from tracecore.admin_reports import sterilization_log as slog
from tracecore.tests import factories as f
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
PARAMS = [{"parameter_name": "Temperature", "unit": "°C", "value": 134, "outside_range": 0}]


def make_released_load(days_ago=1, status="Released", packs=None, equipment=None):
	"""Mẻ dựng thẳng ở trạng thái `status`, bắt đầu `days_ago` ngày trước (không qua dịch vụ T5/T5b)."""
	equipment = equipment or f.make_sterilizer()
	program = f.make_sterilize_program(equipment)
	doc = f.make_load(equipment, program, packs or [f.make_load_ready_pack()])
	start = add_to_date(now_datetime(), days=-days_ago, hours=-3)
	values = {"status": status, "started_at": start, "ended_at": add_to_date(start, hours=1)}
	if status != "Running":
		values.update(params=frappe.as_json(PARAMS), cycle_result="Pass" if status == "Released" else "Fail")
	if status == "Released":
		values.update(released_by="HR-EMP-TEST", released_at=add_to_date(start, hours=2))
	frappe.db.set_value("Sterilization Load", doc.name, values)
	return frappe.get_doc("Sterilization Load", doc.name)


def indicator(load, kind="biological", result="Pass", lot="BI-01"):
	doc = frappe.get_doc(
		{
			"doctype": "Load Indicator Result",
			"load": load.name,
			"indicator": kind,
			"result": result,
			"lot": lot,
		}
	)
	doc.flags.tc_releasing = True
	return doc.insert(ignore_permissions=True)


class ReportCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user("Administrator")
		self.filters = {"from_date": add_days(today(), -7), "to_date": today()}

	def row_of(self, rows, load):
		return next(row for row in rows if row["load"] == load.name)


class TestSterilizationLog(ReportCase):
	def test_row_has_params_indicators_people_and_sets(self):
		load = make_released_load()
		indicator(load, "chemical_class_5", "Pass", "CI-07")
		indicator(load, "biological", "Pass", "BI-01")
		row = self.row_of(slog.log_rows(self.filters), load)
		self.assertEqual(
			(row["equipment"], row["program"], row["result"]), (load.equipment, load.program, "Released")
		)
		self.assertIn("134", row["params"])
		self.assertIn("BI-01", row["indicators"])
		self.assertIn("CI-07", row["indicators"])
		self.assertEqual(row["pack_count"], 1)
		set_id = frappe.db.get_value("Set Unit", load.packs[0].set_unit, "set_id")
		self.assertIn(set_id, row["sets"])
		self.assertEqual((row["operator"], row["released_by"]), ("HR-EMP-TEST", "HR-EMP-TEST"))

	def test_running_loads_and_other_periods_are_left_out(self):
		running = make_released_load(status="Running")
		old = make_released_load(days_ago=30)
		names = {row["load"] for row in slog.log_rows(self.filters)}
		self.assertNotIn(running.name, names)
		self.assertNotIn(old.name, names)

	def test_failed_loads_are_in_the_log(self):
		failed = make_released_load(status="Failed")
		self.assertEqual(self.row_of(slog.log_rows(self.filters), failed)["result"], "Failed")

	def test_filter_by_equipment_and_department(self):
		first, second = make_released_load(), make_released_load()
		rows = slog.log_rows({**self.filters, "equipment": first.equipment})
		self.assertEqual({row["load"] for row in rows}, {first.name})
		department = f.make_department("Khoa báo cáo test")
		frappe.db.set_value("Pack", second.packs[0].pack, "department", department)
		rows = slog.log_rows({**self.filters, "department": department})
		self.assertEqual({row["load"] for row in rows}, {second.name})

	def test_period_is_required_and_ordered(self):
		with self.assertRaises(frappe.ValidationError):
			slog.log_rows({"from_date": today()})
		with self.assertRaises(frappe.ValidationError):
			slog.log_rows({"from_date": today(), "to_date": add_days(today(), -1)})

	def test_script_report(self):
		from tracecore.admin_reports.report.sterilization_log import sterilization_log as report

		load = make_released_load()
		columns, rows = report.execute(self.filters)
		self.assertTrue(columns)
		self.assertIn(load.name, {row["load"] for row in rows})


class TestKsnkSummary(ReportCase):
	def test_loads_by_equipment_with_failure_rate_and_biological_positives(self):
		equipment = f.make_sterilizer()
		passed = make_released_load(equipment=equipment)
		failed = make_released_load(status="Failed", equipment=equipment)
		indicator(passed, "biological", "Pass")
		indicator(failed, "biological", "Fail")
		summary = slog.ksnk_summary(self.filters)
		machine = next(row for row in summary["equipment"] if row["equipment"] == equipment.name)
		self.assertEqual((machine["loads"], machine["passed"], machine["failed"]), (2, 1, 1))
		self.assertEqual(machine["fail_rate"], 50)
		self.assertGreaterEqual(summary["biological"]["tests"], 2)
		self.assertGreaterEqual(summary["biological"]["positive"], 1)
		self.assertGreaterEqual(summary["packs_sterilized"], 1)
		for key in ("wash", "issued", "recalls", "incidents"):
			self.assertIn(key, summary)

	def test_script_report_rows(self):
		from tracecore.admin_reports.report.ksnk_summary_report import ksnk_summary_report as report

		make_released_load()
		columns, rows = report.execute(self.filters)
		self.assertTrue(columns)
		self.assertTrue(rows)


class TestLifeForecast(ReportCase):
	def setUp(self):
		super().setUp()
		f.make_instrument("LF-KEO", value=100000, methods=f.BOM_INSTRUMENT_METHODS)
		f.make_instrument("LF-KEP", value=50000, methods=f.BOM_INSTRUMENT_METHODS)
		self.set_type = f.make_set_type("LFT", bom=[("LF-KEO", 2), ("LF-KEP", 1)]).name

	def unit(self, used, max_cycles=100, uses=3, **fields):
		unit = f.make_set_unit(self.set_type, max_cycles=max_cycles, **fields)
		for i in range(uses):
			pack = f.make_pack(unit, cycle_no=i + 1)
			make_released_load(days_ago=10 + i, packs=[pack])
		frappe.db.set_value("Set Unit", unit.name, "cycles_used", used)
		return unit

	def row(self, unit):
		return next((row for row in slog.life_forecast() if row["set_unit"] == unit.name), None)

	def test_month_from_remaining_cycles_and_recent_rate_with_bom_price(self):
		unit = self.unit(used=94)  # còn 6 chu trình, 3 lần trong 90 ngày = 1 lần/tháng
		row = self.row(unit)
		self.assertEqual(row["remaining"], 6)
		self.assertEqual(row["cycles_per_month"], 1)
		self.assertEqual(row["month"], getdate(add_months(today(), 6)).strftime("%Y-%m"))
		self.assertEqual(row["price"], 250000)

	def test_unused_far_loaner_and_disposed_sets_are_not_forecast(self):
		self.assertIsNone(self.row(self.unit(used=10, uses=0)))  # không dùng 90 ngày: không dự báo
		self.assertIsNone(self.row(self.unit(used=10)))  # 90 chu trình còn lại: ngoài 12 tháng
		self.assertIsNone(self.row(self.unit(used=99, is_loaner=1)))
		disposed = self.unit(used=99)
		frappe.db.set_value("Set Unit", disposed.name, "status", "Disposed")
		self.assertIsNone(self.row(disposed))

	def test_end_of_life_set_is_due_this_month(self):
		unit = self.unit(used=100, uses=1)
		frappe.db.set_value("Set Unit", unit.name, "status", "End of Life")
		self.assertEqual(self.row(unit)["month"], getdate(today()).strftime("%Y-%m"))

	def test_script_report_totals_per_month(self):
		from tracecore.admin_reports.report.instrument_life_forecast import instrument_life_forecast as report

		self.unit(used=94)
		self.unit(used=95)
		_columns, rows = report.execute({})
		month = getdate(add_months(today(), 6)).strftime("%Y-%m")
		total = next(row for row in rows if row.get("is_total") and row["month"] == month)
		self.assertGreaterEqual(total["price"], 250000)


class TestPrintLanguage(ReportCase):
	"""Job RQ chạy không có ngôn ngữ của request: bản PDF phải theo ngôn ngữ người xuất, không ra tiếng Anh."""

	def setUp(self):
		super().setUp()
		import frappe.translate

		frappe.translate.clear_cache()
		lang = frappe.local.lang
		self.addCleanup(setattr, frappe.local, "lang", lang)
		frappe.local.lang = "en"  # như worker RQ

	def export_html(self, kind, lang="vi"):
		import io

		from pypdf import PdfWriter

		writer, blank = PdfWriter(), io.BytesIO()
		writer.add_blank_page(10, 10)
		writer.write(blank)
		with patch("frappe.utils.pdf.get_pdf", return_value=blank.getvalue()) as get_pdf:
			slog.build_export(kind, self.filters, "Administrator", lang=lang)
		return get_pdf.call_args.args[0], get_pdf.call_args.args[1]

	def test_log_is_in_the_language_of_the_requester(self):
		load = make_released_load()
		indicator(load, "chemical_class_5", "Pass", "CI-07")
		html, _options = self.export_html("sterilization_log")
		for text in (
			"Sổ tiệt khuẩn điện tử",
			"TẠM",
			"Hóa học loại 5: Đạt",
			"Người vận hành",
			"Máy",
			"Kết quả",
		):
			self.assertIn(text, html)
		for text in (
			"Electronic Sterilization Log",
			"PROVISIONAL",
			"Vượt qua",
			"Máy móc",
			"Operator",
			"Released By",
		):
			self.assertNotIn(text, html)

	def test_other_prints_are_in_vietnamese(self):
		make_released_load()
		html, _options = self.export_html("ksnk_summary")
		self.assertIn("Báo cáo tổng hợp kiểm soát nhiễm khuẩn", html)
		self.assertNotIn("Sterilization loads by machine", html)
		html, _options = self.export_html("life_forecast")
		self.assertIn("Dự báo bộ dụng cụ hết vòng đời", html)
		self.assertNotIn("Prepared by", html)

	def test_wide_prints_are_scaled_to_fit_the_page(self):
		_html, options = self.export_html("sterilization_log")
		self.assertEqual(options["orientation"], "Landscape")
		self.assertTrue(options["zoom"])

	def test_real_pdf_keeps_the_result_column_on_the_page(self):
		import io

		from pypdf import PdfReader

		make_released_load()
		frappe.local.lang = "vi"
		pdf = slog.render_pdf("sterilization_log", self.filters)
		page = PdfReader(io.BytesIO(pdf)).pages[0]
		found = []

		def visit(text, cm, tm, _font, _size):
			if text.strip():
				found.append((text.strip(), cm[0] * tm[4] + cm[4]))

		page.extract_text(visitor_text=visit)
		result_x = [x for text, x in found if "Kết quả" in text]
		self.assertTrue(result_x, found)
		# chữ của cột cuối phải nằm trong khổ giấy, không bị cắt
		self.assertLess(max(x for _text, x in found), float(page.mediabox.width) - 20)
		self.assertLess(max(result_x), float(page.mediabox.width) - 40)

	def test_rpc_and_archive_pass_the_language_to_the_job(self):
		from tracecore.v1 import report as report_api

		frappe.local.lang = "vi"
		with patch("frappe.enqueue") as enqueue:
			report_api.export("sterilization_log", frappe.as_json(self.filters))
		self.assertEqual(enqueue.call_args.kwargs["lang"], "vi")
		with patch("frappe.enqueue") as enqueue:
			frappe.get_doc(
				{
					"doctype": "Archive Export",
					"scope_type": "Period",
					"from_date": today(),
					"to_date": today(),
				}
			).insert()
		self.assertEqual(enqueue.call_args.kwargs["lang"], "vi")


class TestPrintAndExport(ReportCase):
	def test_provisional_until_the_period_is_locked(self):
		stamp = 'class="tc-provisional"'
		frappe.db.set_single_value("TraceCore Settings", "report_locked_until", None)
		self.assertIn(stamp, slog.render_html("sterilization_log", self.filters))
		frappe.db.set_single_value("TraceCore Settings", "report_locked_until", today())
		self.assertNotIn(stamp, slog.render_html("sterilization_log", self.filters))
		self.assertFalse(slog.is_locked(add_days(today(), 1)))

	def test_lock_status_reports_the_stored_date(self):
		from tracecore.v1 import report as report_api

		frappe.db.set_single_value("TraceCore Settings", "report_locked_until", None)
		self.assertIsNone(report_api.lock_status()["locked_until"])
		report_api.lock_period(add_days(today(), -7))
		self.assertEqual(report_api.lock_status()["locked_until"], add_days(today(), -7))

	def test_future_date_cannot_be_locked(self):
		from tracecore.v1 import report as report_api

		frappe.db.set_single_value("TraceCore Settings", "report_locked_until", None)
		with self.assertRaises(frappe.ValidationError):
			report_api.lock_period(add_days(today(), 1))
		self.assertIsNone(report_api.lock_status()["locked_until"])
		self.assertEqual(report_api.lock_period(today())["locked_until"], today())

	def test_print_has_exporter_time_and_signature(self):
		make_released_load()
		html = slog.render_html("sterilization_log", self.filters)
		self.assertIn(frappe.utils.get_fullname("Administrator"), html)
		self.assertIn("tc-sign", html)
		for kind in ("ksnk_summary", "life_forecast"):
			self.assertIn("tc-sign", slog.render_html(kind, self.filters))

	def test_export_job_saves_a_private_pdf_and_tells_the_user(self):
		import io

		from pypdf import PdfWriter

		writer, blank = PdfWriter(), io.BytesIO()
		writer.add_blank_page(10, 10)
		writer.write(blank)  # File của Frappe kiểm nội dung PDF: cần PDF hợp lệ thay cho wkhtmltopdf
		with patch("frappe.utils.pdf.get_pdf", return_value=blank.getvalue()):
			file_name = slog.build_export("sterilization_log", self.filters, "Administrator")
		file = frappe.get_doc("File", file_name)
		self.assertTrue(file.is_private)
		self.assertTrue(file.file_name.endswith(".pdf"))
		self.assertTrue(
			frappe.db.exists("Notification Log", {"for_user": "Administrator", "link": file.file_url})
		)

	def test_real_pdf(self):
		make_released_load()
		self.assertTrue(slog.render_pdf("sterilization_log", self.filters).startswith(b"%PDF"))

	def test_export_rpc_queues_a_long_job_after_permission_check(self):
		from tracecore.v1 import report as report_api

		with patch("frappe.enqueue") as enqueue:
			result = report_api.export("sterilization_log", frappe.as_json(self.filters))
		self.assertTrue(result["ok"])
		self.assertEqual(enqueue.call_args.kwargs["queue"], "long")
		frappe.set_user(make_user("report-r04@example.com", ["TC R04"]))
		with self.assertRaises(frappe.PermissionError):
			report_api.export("sterilization_log", frappe.as_json(self.filters))
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			report_api.export("nope", "{}")

	def test_only_r01_locks_the_period_with_audit(self):
		from tracecore.v1 import report as report_api

		self.assertTrue(frappe.get_meta("TraceCore Settings").get_field("report_locked_until").read_only)
		frappe.set_user(make_user("report-r10@example.com", ["TC R10"]))
		with self.assertRaises(frappe.PermissionError):
			report_api.lock_period(today())
		frappe.set_user(make_user("report-r01@example.com", ["TC R01"]))
		self.assertEqual(report_api.lock_period(add_days(today(), -1))["locked_until"], add_days(today(), -1))
		frappe.set_user("Administrator")
		self.assertEqual(
			str(frappe.db.get_single_value("TraceCore Settings", "report_locked_until")),
			add_days(today(), -1),
		)
		self.assertTrue(
			frappe.db.exists(
				"Audit Log", {"ref_doctype": "TraceCore Settings", "user": "report-r01@example.com"}
			)
		)
		with self.assertRaises(frappe.ValidationError):
			report_api.lock_period("30/10/2026")
