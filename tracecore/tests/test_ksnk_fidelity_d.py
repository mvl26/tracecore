"""Giai đoạn 2 (nhóm D) — SCR-62, SCR-64, SCR-65 bám bố cục ảnh duyệt docs/design-refs/v1.12:
bộ lọc dạng select, khung bảng luôn hiện khi chưa có dữ liệu, thẻ mã DocType, thứ tự khối."""

from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js
from tracecore.tests.test_ksnk_page import SHELL

SCR62 = "public/js/ksnk/scr_62_moi_truong.js"
SCR64 = "public/js/ksnk/scr_64_phoi_nhiem.js"
SCR65 = "public/js/ksnk/scr_65_attp.js"

HEAD = """
frappe.user = {has_role: () => true};
const esc = TcKsnk.esc;
"""


class TestScr62Fidelity(FrappeTestCase):
	def run62(self, script):
		return run_js(self, [SHELL, SCR62], [["TcKsnk"], ["TcKsnkScr62"]], HEAD + script)

	def test_month_filter_is_select_and_tabs_follow_it(self):
		out = self.run62(
			'TcKsnkScr62.tab = "overview";'
			'emit({h: TcKsnkScr62.pageHtml({month: "2026-10", kpis: {}, perms: {}}, esc)});'
		)["h"]
		self.assertNotIn('type="month"', out)
		self.assertIn('<select class="form-control" data-filter="month">', out)
		self.assertIn('<option value="2026-10" selected>Month 10/2026</option>', out)
		self.assertIn("tc-ksnk-headrow", out)
		self.assertLess(out.index('data-filter="month"'), out.index('role="tablist"'))

	def test_empty_overview_keeps_table_frames(self):
		out = self.run62(
			'TcKsnkScr62.tab = "overview";'
			'emit({h: TcKsnkScr62.pageHtml({month: "2026-10", kpis: {}, perms: {}}, esc)});'
		)["h"]
		self.assertIn("tc-ksnk-kpis", out)
		self.assertEqual(out.count("<table"), 3)  # mẫu, vùng, hạ tầng đều giữ khung bảng
		self.assertIn("Environmental Sample · XN-", out)
		self.assertIn("Environment Zone · VV-", out)
		self.assertIn("No environmental sample posted this month.", out)
		self.assertIn('<tr class="is-empty">', out)

	def test_primary_action_is_pda_form_then_result_and_report(self):
		out = self.run62("emit({a: TcKsnkScr62.actionsHtml(esc)});")["a"]
		pda = out.index("Record surface cleaning form (PDA)")
		result = out.index("Record test result")
		report = out.index("Monthly/quarterly environment report")
		self.assertTrue(pda < result < report)
		self.assertIn('class="btn btn-primary" href="/app/station"', out)

	def test_decision_buttons_come_before_record_actions(self):
		out = self.run62(
			'const d = {can_decide: true, perms: {}, pending_nc: [{name: "XN-1", environment_zone: "VV-1",'
			' environment_zone_name: "Z", sample_type: "Air", result_value: 24, unit: "u", limit_applied: "L"}]};'
			"emit({h: TcKsnkScr62.pendingHtml(d, esc)});"
		)["h"]
		self.assertLess(out.index('data-action="open-nc"'), out.index('data-region="nc-alert"'))
		self.assertLess(out.index("Record resample"), out.index('data-region="nc-alert"'))


class TestScr64Fidelity(FrappeTestCase):
	def run64(self, script):
		return run_js(self, [SHELL, SCR64], [["TcKsnk"], ["TcKsnkScr64"]], HEAD + script)

	DATA = (
		"const data = {is_manager: true, perms: {}, records: [], immunizations: [], pep_alerts: [],"
		" kpis: {year: 2026, year_total: 0, late: 0, following: 0, immunization: {}, thresholds: {}}};"
	)

	def test_empty_page_keeps_frames_and_doctype_tags(self):
		out = self.run64(self.DATA + "emit({h: TcKsnkScr64.pageHtml(data, esc, null)});")["h"]
		self.assertEqual(out.count("<table"), 3)  # hồ sơ, lịch theo dõi, tiêm chủng
		self.assertIn("Occupational Exposure · PN-", out)
		self.assertIn("Exposure Follow-up Template", out)
		self.assertIn("Staff Immunization · TCH-", out)
		self.assertIn("No exposure records yet.", out)
		self.assertIn("Choose a record to see its follow-up schedule.", out)

	def test_following_up_badge_is_info_with_text(self):
		out = self.run64('emit({b: TcKsnkScr64.statusBadge("Following Up", esc)});')["b"]
		self.assertIn("is-info", out)
		self.assertIn("Following Up", out)


class TestScr65Fidelity(FrappeTestCase):
	def run65(self, script):
		return run_js(self, [SHELL, SCR65], [["TcKsnk"], ["TcKsnkScr65"]], HEAD + script)

	DATA = (
		"const data = {perms: {}, kpis: {}, quarter: {}, pending_events: [], handlers: [], sessions: [],"
		" food_audits: [], food_samples: [], materials: []};"
	)

	def test_two_columns_are_handlers_and_sessions_then_kitchen_block(self):
		out = self.run65(self.DATA + "emit({h: TcKsnkScr65.pageHtml(data, esc)});")["h"]
		handlers = out.index("Food Handler Health Check · SKTP-")
		sessions = out.index("IC Education Session · GDS-")
		kitchen = out.index("Kitchen and catering audits")
		materials = out.index("Communication materials for patients and families")
		self.assertTrue(handlers < sessions < kitchen < materials)

	def test_doctype_tags_use_tag_class(self):
		out = self.run65(self.DATA + "emit({h: TcKsnkScr65.pageHtml(data, esc)});")["h"]
		self.assertIn('<span class="tc-ksnk-tag">Food Handler Health Check · SKTP-</span>', out)
		self.assertIn('<span class="tc-ksnk-tag">IC Education Session · GDS-</span>', out)

	def test_empty_kitchen_block_keeps_table_frames(self):
		out = self.run65(self.DATA + "emit({h: TcKsnkScr65.foodHtml(data, esc)});")["h"]
		self.assertEqual(out.count("<table"), 2)
		self.assertIn("No food safety audit in the last 90 days.", out)
		self.assertIn("No food samples yet.", out)
