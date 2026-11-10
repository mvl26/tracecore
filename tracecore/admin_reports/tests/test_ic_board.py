"""Bảng chỉ số KSNK toàn viện và Cổng khoa (FEAT-065 AC-065-01..06, 11..13; FR-M9-24, FR-M9-26; BRU-RPT-001,
BRU-RPT-003; NFR-PERF-05)."""

import time
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime

from tracecore.admin_reports import ic_board, indicator
from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1 import indicator as api

YEAR = 2031  # năm không đụng dữ liệu thật của site test


def _value(code, period, numerator, denominator, department=None, locked=1, kind_scale=100):
	frappe.get_doc(
		{
			"doctype": "IC Indicator Value",
			"indicator": code,
			"period": period,
			"department": department,
			"numerator": numerator,
			"denominator": denominator,
			"sample_size": denominator,
			"value": numerator / denominator * kind_scale if denominator else 0,
			"sample_note": "" if denominator else indicator.NOT_CALCULATED,
			"locked": locked,
		}
	).insert(ignore_permissions=True)


def _dept_user(email, role, department):
	user = factories.make_user(email, [role])
	if not frappe.db.exists(
		"User Permission", {"user": user, "allow": "Department", "for_value": department}
	):
		frappe.get_doc(
			{"doctype": "User Permission", "user": user, "allow": "Department", "for_value": department}
		).insert(ignore_permissions=True)
	return user


class BoardCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.delete("IC Indicator Value")
		frappe.db.set_value("IC Indicator", {"is_active": 1}, "is_active", 0)
		fx.clear_plans(YEAR)
		self.dept_a = factories.make_department("KSNK Board A")
		self.dept_b = factories.make_department("KSNK Board B")
		self.hh = fx.indicator("FB-HH", target=80)
		self.vap = fx.indicator("FB-VAP", kind="Rate per 1000", direction="Lower is better", target=7)
		self.other = fx.indicator("FB-OTHER", target=90)
		frappe.db.set_value("IC Indicator", {"name": ("in", ["FB-HH", "FB-VAP", "FB-OTHER"])}, "is_active", 1)
		frappe.db.set_value("IC Indicator", "FB-VAP", "measure_group", "Invasive Procedure")
		for period, hh, vap in ((f"{YEAR}-08", 75, 8), (f"{YEAR}-09", 78, 7), (f"{YEAR}-10", 84, 0)):
			_value("FB-HH", period, hh, 100)
			_value("FB-HH", period, hh - 10, 100, department=self.dept_a)
			_value("FB-HH", period, hh + 5, 100, department=self.dept_b)
			_value("FB-VAP", period, vap, 1000 if vap else 0, kind_scale=1000)
		self.r01 = fx.user("R01", prefix="ksnk-board")
		self.r13 = fx.user("R13", prefix="ksnk-board")

	def approved_plan(self, indicators):
		doc = fx.plan(YEAR, indicators=indicators)
		return fx.approve(doc, self.r13)


class TestBoard(BoardCase):
	def _row(self, data, code):
		return next(row for row in data["rows"] if row["code"] == code)

	def test_rows_follow_approved_plan_order_and_plan_target(self):
		self.approved_plan([("FB-VAP", 9, 6), ("FB-HH", 70, 82)])
		frappe.set_user(self.r13)
		data = api.board(year=YEAR)
		self.assertEqual([row["code"] for row in data["rows"]], ["FB-VAP", "FB-HH"])
		self.assertEqual(data["plan"]["name"][:3], "KH-")
		hh = self._row(data, "FB-HH")
		self.assertEqual(hh["target"], 82)
		self.assertEqual(hh["latest"]["value"], 84)
		self.assertEqual(hh["status"], "Met")
		self.assertEqual(data["period"], f"{YEAR}-10")
		self.assertEqual(len(data["periods"]), 12)
		self.assertEqual(data["table_periods"], [f"{YEAR}-08", f"{YEAR}-09", f"{YEAR}-10"])
		self.assertEqual(data["kpis"], ["FB-VAP", "FB-HH"])
		self.assertEqual(hh["values"][f"{YEAR}-09"]["status"], "Not met")

	def test_without_plan_lists_active_indicators_with_national_target(self):
		data = api.board(year=YEAR)
		self.assertIsNone(data["plan"])
		codes = [row["code"] for row in data["rows"]]
		self.assertEqual(sorted(codes), ["FB-HH", "FB-OTHER", "FB-VAP"])
		self.assertEqual(self._row(data, "FB-HH")["target"], 80)
		self.assertEqual(self._row(data, "FB-OTHER")["status"], ic_board.NO_DATA)

	def test_plan_target_zero_falls_back_to_national_target(self):
		self.approved_plan([("FB-HH", 0, 0)])
		self.assertEqual(self._row(api.board(year=YEAR), "FB-HH")["target"], 80)

	@bru("BRU-RPT-001")
	def test_zero_denominator_shows_not_calculated_never_zero(self):
		vap = self._row(api.board(year=YEAR), "FB-VAP")
		self.assertIsNone(vap["latest"]["value"])
		self.assertEqual(vap["status"], indicator.NOT_CALCULATED)
		self.assertEqual(vap["values"][f"{YEAR}-09"]["value"], 7)
		self.assertEqual(vap["values"][f"{YEAR}-09"]["status"], "Met")

	def test_opening_the_board_never_recalculates(self):
		with patch("tracecore.core.indicators.registry", side_effect=AssertionError("no recompute")):
			data = api.board(year=YEAR, period=f"{YEAR}-10")
		self.assertTrue(data["rows"])

	def test_department_filter_reads_department_values(self):
		data = api.board(year=YEAR, department=self.dept_a)
		self.assertEqual(self._row(data, "FB-HH")["latest"]["value"], 74)
		self.assertIsNone(data["chart"])

	def test_department_chart_defaults_to_hand_hygiene_sorted_by_value(self):
		chart = api.board(year=YEAR)["chart"]
		self.assertEqual(chart["indicator"], "FB-HH")
		self.assertEqual([row["department"] for row in chart["rows"]], [self.dept_b, self.dept_a])
		self.assertEqual(chart["rows"][1]["status"], "Not met")

	def test_provisional_period_is_flagged(self):
		_value("FB-HH", f"{YEAR}-11", 90, 100, locked=0)
		data = api.board(year=YEAR)
		self.assertEqual(data["period"], f"{YEAR}-11")
		self.assertFalse(data["locked"])
		self.assertEqual(self._row(data, "FB-HH")["latest"]["locked"], 0)

	@bru("BRU-RPT-003")
	def test_locked_value_stays_when_source_changes(self):
		with patch("tracecore.core.indicators.registry", return_value={}):
			indicator.compute_period(f"{YEAR}-10")  # kỳ đã khóa: không ghi đè
		self.assertEqual(self._row(api.board(year=YEAR), "FB-HH")["latest"]["value"], 84)

	def test_roles(self):
		users = {
			role: fx.user(role, prefix="ksnk-board-role")
			for role in ("R01", "R10", "R11", "R13", "R02", "R12")
		}
		for role in ("R01", "R10", "R11", "R13"):
			frappe.set_user(users[role])
			self.assertTrue(api.board(year=YEAR)["rows"])
		for role in ("R02", "R12"):
			frappe.set_user(users[role])
			with self.assertRaises(frappe.PermissionError):
				api.board(year=YEAR)

	def test_todos_are_collected_sorted_and_failures_isolated(self):
		def good(user, department):
			return [
				{"key": "a", "severity": "info", "title": "Info", "count": 2},
				{"key": "b", "severity": "error", "title": "Error", "count": 1, "link": "/x"},
				{"key": "c", "severity": "warn", "title": "Zero", "count": 0},
			]

		def bad(user, department):
			raise ValueError("boom")

		with (
			patch.object(ic_board, "_todo_paths", return_value=[good, bad]),
			patch("frappe.log_error") as log_error,
		):
			items = ic_board.todos("Administrator", None)
		self.assertEqual([item["key"] for item in items], ["b", "a"])
		log_error.assert_called_once()


class TestDepartmentPortal(BoardCase):
	def test_r12_sees_own_department_next_to_hospital(self):
		frappe.set_user(_dept_user("ksnk-board-r12a@example.com", "TC R12", self.dept_a))
		data = ic_board.department_view()
		self.assertEqual(data["department"], self.dept_a)
		self.assertEqual([row["name"] for row in data["departments"]], [self.dept_a])
		hh = next(row for row in data["rows"] if row["code"] == "FB-HH")
		self.assertEqual(hh["department_value"]["value"], 74)
		self.assertEqual(hh["hospital_value"]["value"], 84)
		self.assertEqual(hh["status"], "Not met")

	def test_r12_cannot_open_other_department(self):
		frappe.set_user(_dept_user("ksnk-board-r12a@example.com", "TC R12", self.dept_a))
		with self.assertRaises(frappe.PermissionError):
			ic_board.department_view(self.dept_b)

	def test_r08_head_of_department_is_limited_too(self):
		frappe.set_user(_dept_user("ksnk-board-r08b@example.com", "TC R08", self.dept_b))
		self.assertEqual(ic_board.department_view()["department"], self.dept_b)

	def test_r11_chooses_any_ward(self):
		frappe.set_user(fx.user("R11", prefix="ksnk-board"))
		data = ic_board.department_view(self.dept_b)
		names = [row["name"] for row in data["departments"]]
		self.assertIn(self.dept_a, names)
		self.assertEqual(data["department"], self.dept_b)

	def test_roles_without_portal_are_rejected(self):
		frappe.set_user(fx.user("R13", prefix="ksnk-board-portal"))
		with self.assertRaises(frappe.PermissionError):
			ic_board.department_view()

	def test_todos_receive_department(self):
		seen = []

		def todo(user, department):
			seen.append(department)
			return [{"key": "x", "severity": "warn", "title": "T", "count": 1}]

		frappe.set_user(_dept_user("ksnk-board-r12a@example.com", "TC R12", self.dept_a))
		with patch.object(ic_board, "_todo_paths", return_value=[todo]):
			data = ic_board.department_view()
		self.assertEqual(seen, [self.dept_a])
		self.assertEqual(data["todos"][0]["title"], "T")


class TestBoardPerformance(IsolatedTestCase):
	"""NFR-PERF-05 (AC-065-03): 24 tháng x 32 khoa x 20 chỉ số, dữ liệu sinh giả, RPC ≤ 3 giây."""

	def test_board_opens_within_three_seconds(self):
		frappe.db.delete("IC Indicator Value")
		frappe.db.set_value("IC Indicator", {"is_active": 1}, "is_active", 0)
		fx.clear_plans(YEAR)
		codes = [fx.indicator(f"FP-{n:02d}") for n in range(20)]
		frappe.db.set_value("IC Indicator", {"name": ("in", codes)}, "is_active", 1)
		departments = [factories.make_department(f"KSNK Perf {n:02d}") for n in range(32)]
		periods = ic_board.previous_months(f"{YEAR}-12", 24)
		stamp = now_datetime()
		fields = [
			"name",
			"creation",
			"modified",
			"owner",
			"modified_by",
			"docstatus",
			"indicator",
			"period",
			"department",
			"numerator",
			"denominator",
			"sample_size",
			"value",
			"sample_note",
			"locked",
		]
		rows = []
		for code in codes:
			for period in periods:
				for department in [None, *departments]:
					rows.append(
						(
							frappe.generate_hash(length=12),
							stamp,
							stamp,
							"Administrator",
							"Administrator",
							0,
							code,
							period,
							department,
							80,
							100,
							100,
							80,
							"",
							1,
						)
					)
		frappe.db.bulk_insert("IC Indicator Value", fields, rows, chunk_size=5000)
		self.assertEqual(len(rows), 20 * 24 * 33)
		frappe.set_user(fx.user("R13", prefix="ksnk-perf"))
		self.addCleanup(frappe.set_user, "Administrator")
		started = time.monotonic()
		data = api.board(year=YEAR)
		elapsed = time.monotonic() - started
		self.assertEqual(len(data["rows"]), 20)
		self.assertEqual(len(data["chart"]["rows"]), 32)
		self.assertLess(elapsed, 3.0)


class TestDepartmentPortalPage(BoardCase):
	"""Trang Portal `/ksnk-khoa/chi-so` (SCR-66 view DEPT, AC-065-12, AC-065-13)."""

	def setUp(self):
		super().setUp()
		from tracecore.www.ksnk_khoa import chi_so

		self.page = chi_so
		self.user = _dept_user("ksnk-board-page-r12@example.com", "TC R12", self.dept_a)
		self.addCleanup(frappe.form_dict.clear)

	def test_guest_is_redirected_to_login(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.Redirect):
			self.page.get_context(frappe._dict())

	def test_r12_page_lists_own_department_values_as_text(self):
		frappe.set_user(self.user)
		context = self.page.get_context(frappe._dict())
		self.assertEqual(context.department, self.dept_a)
		self.assertFalse(context.forbidden)
		self.assertEqual(context.period_label, f"10/{YEAR}")
		hh = next(row for row in context.rows if row["code"] == "FB-HH")
		self.assertEqual((hh["department_value"], hh["hospital_value"]), ("74 %", "84 %"))
		self.assertEqual((hh["target"], hh["status"], hh["badge"]), ("≥ 80 %", "Not met", "tc-badge-r"))
		vap = next(row for row in context.rows if row["code"] == "FB-VAP")
		self.assertEqual(vap["hospital_value"], "Not calculated")
		self.assertEqual(vap["department_value"], "—")

	def test_other_department_shows_inline_error_and_own_data(self):
		frappe.set_user(self.user)
		frappe.form_dict.department = self.dept_b
		context = self.page.get_context(frappe._dict())
		self.assertTrue(context.forbidden)
		self.assertEqual(context.department, self.dept_a)

	def test_nav_has_indicator_page_and_css_uses_tokens_only(self):
		import os
		import re

		html = frappe.render_template("templates/includes/ksnk_khoa_nav.html", {"ksnk_nav": "chi-so"})
		self.assertIn('href="/ksnk-khoa/chi-so" aria-current="page"', html)
		css = open(os.path.join(os.path.dirname(self.page.__file__), "chi_so.css"), encoding="utf-8").read()
		self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,6}\b|\b\d+px\b", css))
