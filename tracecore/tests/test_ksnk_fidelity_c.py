"""Giai đoạn 2 (nhóm C) — SCR-58..61 bám bố cục ảnh duyệt docs/design-refs/v1.12: khung luôn hiện, hàng lọc + nút."""

from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js
from tracecore.tests.test_ksnk_page import SHELL

SCR58 = "public/js/ksnk/scr_58_bao_cao_nkbv.js"
SCR59 = "public/js/ksnk/scr_59_vi_sinh.js"
SCR60 = "public/js/ksnk/scr_60_cach_ly.js"
SCR61 = "public/js/ksnk/scr_61_o_dich.js"

HEAD = """
frappe.user = {has_role: () => true};
const esc = TcKsnk.esc;
"""


class TestScr58Fidelity(FrappeTestCase):
	def run58(self, script):
		return run_js(self, [SHELL, SCR58], [["TcKsnk"], ["TcKsnkScr58", "TcKsnkPps"]], HEAD + script)

	def test_headrow_filter_left_export_right_then_cluster_slot(self):
		out = self.run58(
			'emit({h: TcKsnkScr58.filtersHtml({period: "2026-10", months: [{month: "2026-10", locked: true}]}, esc)});'
		)["h"]
		self.assertIn("tc-ksnk-headrow", out)
		self.assertIn('data-filter="period"', out)
		self.assertIn("Month 10/2026 (locked)", out)
		self.assertIn('data-action="goto-export"', out)
		self.assertIn("btn btn-primary", out)
		self.assertLess(out.index('data-filter="period"'), out.index('data-action="goto-export"'))
		self.assertLess(out.index('data-action="goto-export"'), out.index('data-region="clusters"'))

	def test_empty_department_and_prevalence_keep_table_frame(self):
		out = self.run58(
			'emit({d: TcKsnkScr58.departmentsHtml({period: "2026-10", departments: []}, esc),'
			' p: TcKsnkPps.tableHtml({departments: [], hospital: {}}, esc)});'
		)
		self.assertIn("<table", out["d"])
		self.assertIn("No census or HAI case in this month.", out["d"])
		self.assertIn("<table", out["p"])
		self.assertIn("No patient surveyed on this day.", out["p"])
		self.assertNotIn("Hospital total", out["p"])


class TestScr59Fidelity(FrappeTestCase):
	def run59(self, script):
		return run_js(self, [SHELL, SCR59], [["TcKsnk"], ["TcKsnkScr59"]], HEAD + script)

	def test_import_stats_frame_always_shown(self):
		out = self.run59(
			'emit({h: TcKsnkScr59.importHtml({can_import: true, profiles: [{name: "P1", file_format: "CSV"}]},'
			' {profile: "P1"}, esc)});'
		)["h"]
		self.assertIn("tc-ksnk-stats", out)
		self.assertIn("—", out)
		self.assertIn("Import Batch · profile P1", out)

	def test_empty_recent_and_antibiogram_keep_table_frame(self):
		out = self.run59(
			'emit({r: TcKsnkScr59.recentHtml([], esc),'
			' a: TcKsnkScr59.antibiogramHtml({year: 2026, quarter: 3, report: "/r", antibiogram: {rows: []}}, esc)});'
		)
		self.assertIn("<table", out["r"])
		self.assertIn("No isolate recorded in the last 7 days.", out["r"])
		self.assertIn("<table", out["a"])
		self.assertIn("No first isolate in this quarter.", out["a"])
		self.assertIn("Quarter 3/2026", out["a"])


class TestScr60Fidelity(FrappeTestCase):
	def run60(self, script):
		return run_js(self, [SHELL, SCR60], [["TcKsnk"], ["TcKsnkScr60"]], HEAD + script)

	def test_empty_orders_and_rooms_keep_frame(self):
		out = self.run60(
			"emit({o: TcKsnkScr60.ordersHtml({can_read_orders: true, orders: []}, esc),"
			" r: TcKsnkScr60.roomsHtml({rooms: [], coverage: {}}, esc)});"
		)
		self.assertIn("<table", out["o"])
		self.assertIn("No patient in isolation.", out["o"])
		self.assertIn("<table", out["r"])
		self.assertNotIn("undefined", out["r"])
		self.assertIn("tc-ksnk-kpi", out["r"])


class TestScr61Fidelity(FrappeTestCase):
	def run61(self, script):
		return run_js(self, [SHELL, SCR61], [["TcKsnk"], ["TcKsnkScr61"]], HEAD + script)

	def test_empty_tables_keep_frame(self):
		out = self.run61(
			"const d = {status: 'Investigating', cases: [], actions: [], incidents: []};"
			"emit({c: TcKsnkScr61.casesHtml(d, {can_work: true}, esc),"
			" a: TcKsnkScr61.actionsHtml(d, {can_work: true}, esc),"
			" l: TcKsnkScr61.listHtml({summary: []}, esc),"
			" n: TcKsnkScr61.reportsHtml({can_work: true, reports: []}, esc)});"
		)
		for key, text in (
			("c", "No case linked yet."),
			("a", "No control action yet."),
			("l", "No outbreak investigation yet."),
			("n", "No report."),
		):
			self.assertIn("<table", out[key])
			self.assertIn(text, out[key])

	def test_footer_update_before_end_before_export(self):
		out = self.run61(
			"const d = {name: 'OD-1', title: 'T', status: 'Investigating', cases: [], actions: [], incidents: []};"
			"emit({h: TcKsnkScr61.detailHtml({current: d, can_own: true, can_work: true, can_edit_outbreak: true,"
			" print_outbreak: '/p?name='}, esc)});"
		)["h"]
		foot = out.split('data-region="footer"')[1]
		self.assertLess(foot.index("btn"), foot.index('data-action="end"'))
		self.assertLess(foot.index('data-action="end"'), foot.index("Export outbreak report form"))
