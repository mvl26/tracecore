"""Giai đoạn 2 (nhóm B) — SCR-53/54/56/57 bám bố cục ảnh duyệt docs/design-refs/v1.12."""

from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js

SHELL = "public/js/ksnk/ksnk_shell.js"
S53 = "public/js/ksnk/scr_53_tuan_thu.js"
S54 = "public/js/ksnk/scr_54_hoa_chat.js"
S56 = "public/js/ksnk/scr_56_ca_nkbv.js"
S57 = "public/js/ksnk/scr_57_nkvm.js"

HEAD = """
frappe.user = {has_role: () => true};
frappe.datetime = {get_today: () => "2026-11-11"};
const esc = TcKsnk.esc;
"""


class TestScr53(FrappeTestCase):
	def run53(self, script):
		return run_js(self, [SHELL, S53], [["TcKsnk"], ["TcKsnkScr53"]], HEAD + script)

	def test_filters_select_and_actions_share_row(self):
		out = self.run53('emit({h: TcKsnkScr53.filtersHtml({period: "2026-10"}, esc)});')["h"]
		self.assertIn("tc-ksnk-headrow", out)
		self.assertNotIn('type="month"', out)
		self.assertIn('<select class="form-control" data-filter="period">', out)
		self.assertIn("Month 10/2026", out)
		self.assertIn("Export Excel", out)
		self.assertIn("Export PDF", out)
		self.assertIn("btn btn-primary", out)

	def test_empty_tables_keep_frame(self):
		out = self.run53(
			"emit({r: TcKsnkScr53.rowsHtml({rows: []}, esc), c: TcKsnkScr53.recentHtml({recent: []}, esc)});"
		)
		self.assertIn("<table", out["r"])
		self.assertIn("No posted audit in this period.", out["r"])
		self.assertIn("<table", out["c"])
		self.assertIn("No audit to show.", out["c"])


class TestScr54(FrappeTestCase):
	def run54(self, script):
		return run_js(self, [SHELL, S54], [["TcKsnk"], ["TcKsnkScr54"]], HEAD + script)

	def test_toolbar_headrow(self):
		out = self.run54(
			'emit({h: TcKsnkScr54.toolbarHtml({year: 2026, quarter: 3, report: "/app/r", can_import: true, can_write: true}, esc)});'
		)["h"]
		self.assertIn("tc-ksnk-headrow", out)
		self.assertIn("tc-ksnk-headactions", out)
		self.assertLess(out.index('data-input="quarter"'), out.index('data-action="import"'))

	def test_empty_tables_keep_frame(self):
		out = self.run54(
			'emit({c: TcKsnkScr54.chemicalsHtml({summary: {departments: [], total: {litres: {}}}}, esc),'
			" v: TcKsnkScr54.vendorsHtml({vendors: []}, esc)});"
		)
		self.assertIn("<th", out["c"])
		self.assertIn("No infection control chemical recorded in this quarter.", out["c"])
		self.assertIn("<th", out["v"])
		self.assertIn("No outsourced vendor yet.", out["v"])


class TestScr56(FrappeTestCase):
	def run56(self, script):
		return run_js(self, [SHELL, S56], [["TcKsnk"], ["TcKsnkScr56"]], HEAD + script)

	def test_empty_list_detail_and_periods_keep_frame(self):
		out = self.run56(
			"const data = {can_create: false, can_decide: false, can_lock: false};"
			"emit({l: TcKsnkScr56.listHtml([], esc, null, data),"
			" d: TcKsnkScr56.detailHtml(null, data, esc),"
			" p: TcKsnkScr56.periodsHtml([], data, esc)});"
		)
		self.assertIn("<table", out["l"])
		self.assertIn("No HAI cases yet.", out["l"])
		self.assertIn("tc-ksnk-facts", out["d"])
		self.assertIn("Choose a case to see its record.", out["d"])
		self.assertIn("<table", out["p"])
		self.assertIn("No reporting period yet.", out["p"])

	def test_masked_patient_code_only(self):
		out = self.run56(
			'const rows = [{name: "CA-1", patient_code_masked: "••••4821", status: "Suspected"}];'
			"emit({l: TcKsnkScr56.listHtml(rows, esc, null, {can_create: false})});"
		)["l"]
		self.assertIn("••••4821", out)
		self.assertIn("tc-ksnk-badge", out)


class TestScr57(FrappeTestCase):
	def run57(self, script):
		return run_js(self, [SHELL, S57], [["TcKsnk"], ["TcKsnkScr57"]], HEAD + script)

	def test_empty_tables_keep_frame(self):
		out = self.run57(
			"emit({f: TcKsnkScr57.followupsHtml({followups: [], name: 'PT-1'}, {}, esc),"
			" d: TcKsnkScr57.followupsHtml(null, {due: []}, esc),"
			" r: TcKsnkScr57.recentHtml([], null, esc)});"
		)
		self.assertIn("<th", out["f"])
		self.assertIn("The schedule is created when the discharge date is entered.", out["f"])
		self.assertIn("<th", out["d"])
		self.assertIn("No follow-up due today.", out["d"])
		self.assertIn("<th", out["r"])
		self.assertIn("No surgery under surveillance yet.", out["r"])
