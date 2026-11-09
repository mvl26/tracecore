"""Page Desk tc-ksnk — màn quản lý KSNK toàn viện và SCR-66 tối thiểu (FEAT-056 AC-12..AC-15; A-131)."""

import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js

PAGE_DIR = os.path.join(frappe.get_app_path("tracecore"), "ui", "page", "tc_ksnk")
SHELL = "public/js/ksnk/ksnk_shell.js"
SCR66 = "public/js/ksnk/scr_66_chi_so.js"


def _read(path):
	with open(os.path.join(frappe.get_app_path("tracecore"), *path.split("/")), encoding="utf-8") as handle:
		return handle.read()


NAV = """
const nav = {
	home: "chi-so", read_only: false, dept_only: false, departments: [],
	groups: [
		{key: "program", label: "Hospital IC", items: [
			{slug: "chi-so", scr: "SCR-66", uc: "UC-57", label: "IC Indicator Board", badge: 0, script: "/x.js"},
			{slug: "co-cau", scr: "SCR-47", uc: "UC-40", label: "IC Structure", badge: 2, script: "/y.js"},
		]},
		{key: "hai", label: "HAI Surveillance", items: []},
	],
};
"""


class TestKsnkPage(FrappeTestCase):
	def test_page_registered_for_ksnk_roles(self):
		page = frappe.get_doc("Page", "tc-ksnk")
		self.assertEqual(page.module, "UI")
		roles = {row.role for row in page.roles}
		self.assertEqual(roles, {"TC R01", "TC R10", "TC R11", "TC R12", "TC R13", "System Manager"})

	def test_route_and_filters_round_trip(self):
		out = run_js(
			self,
			[SHELL],
			[["TcKsnk"]],
			"""
			const a = TcKsnk.parseRoute(["tc-ksnk", "chi-so"], "?period=2026-10&department=Khoa%20A&x=1");
			const b = TcKsnk.parseRoute(["tc-ksnk"], "");
			emit({a, b, q: TcKsnk.query({period: "2026-10", department: "", year: "2026"})});
			""",
		)
		self.assertEqual(
			out["a"],
			{
				"slug": "chi-so",
				"filters": {"period": "2026-10", "department": "Khoa A", "year": "", "tab": ""},
			},
		)
		self.assertEqual(out["b"]["slug"], "")
		self.assertEqual(out["q"], "period=2026-10&year=2026")

	def test_rail_groups_active_item_and_badge_text(self):
		out = run_js(
			self,
			[SHELL],
			[["TcKsnk"]],
			NAV
			+ """
			emit({html: TcKsnk.railHtml(nav, "co-cau"), pick: TcKsnk.pick(nav, "nope"), ok: TcKsnk.pick(nav, "co-cau").slug});
			""",
		)
		html = out["html"]
		self.assertIn("Hospital IC", html)
		self.assertNotIn("HAI Surveillance", html)  # nhóm chưa có màn không hiện
		self.assertRegex(html, r'class="[^"]*is-active[^"]*"[^>]*data-slug="co-cau"')
		self.assertIn('aria-current="page"', html)
		self.assertIn(">2<", html)  # badge số có chữ số
		self.assertIsNone(out["pick"])
		self.assertEqual(out["ok"], "co-cau")

	def test_four_screen_states(self):
		out = run_js(
			self,
			[SHELL],
			[["TcKsnk"]],
			"""
			emit({
				loading: TcKsnk.stateHtml("loading"),
				empty: TcKsnk.stateHtml("empty", "Nothing yet"),
				error: TcKsnk.stateHtml("error", "Boom"),
				forbidden: TcKsnk.stateHtml("forbidden"),
				offline: TcKsnk.stateHtml("offline"),
			});
			""",
		)
		self.assertIn("aria-busy", out["loading"])
		self.assertIn("Nothing yet", out["empty"])
		self.assertIn('role="alert"', out["error"])
		self.assertIn('data-action="retry"', out["error"])
		self.assertIn("not allowed", out["forbidden"])
		self.assertIn("offline", out["offline"].lower())

	def test_scr66_value_target_and_status_text(self):
		out = run_js(
			self,
			[SHELL, SCR66],
			[["TcKsnk"], ["TcKsnkScr66"]],
			"""
			const s = TcKsnkScr66;
			emit({
				pct: s.formatValue(78.4, "Percentage"),
				rate: s.formatValue(2.1, "Rate per 1000"),
				count: s.formatValue(7, "Count"),
				none: s.formatValue(null, "Rate per 1000"),
				target: s.targetText({national_target: 80, target_direction: "Higher is better", kind: "Percentage"}),
				low: s.targetText({national_target: 3, target_direction: "Lower is better", kind: "Rate per 1000"}),
				noTarget: s.targetText({national_target: null, target_direction: "", kind: "Count"}),
				met: s.statusBadge("Met"), notMet: s.statusBadge("Not met"),
				nc: s.statusBadge("Not calculated"), small: s.statusBadge("Insufficient sample"), blank: s.statusBadge(""),
			});
			""",
		)
		self.assertEqual(out["pct"], "78,4 %")
		self.assertEqual(out["rate"], "2,1 ‰")
		self.assertEqual(out["count"], "7")
		self.assertEqual(out["none"], "—")
		self.assertEqual(out["target"], "≥ 80 %")
		self.assertEqual(out["low"], "≤ 3 ‰")
		self.assertEqual(out["noTarget"], "—")
		# trạng thái luôn có chữ, không chỉ màu
		self.assertEqual(out["met"], {"cls": "is-pass", "label": "Met"})
		self.assertEqual(out["notMet"]["cls"], "is-fail")
		self.assertEqual(out["nc"]["label"], "Not calculated (denominator 0)")
		self.assertEqual(out["small"]["cls"], "is-neutral")
		self.assertEqual(out["blank"]["label"], "—")

	def test_scripts_use_desk_get_and_translations(self):
		for path in (SHELL, SCR66, "ui/page/tc_ksnk/tc_ksnk.js"):
			script = _read(path)
			self.assertNotIn("frappe.call(", script, path)
			self.assertIsNone(re.search(r"\.text\(\s*[\"'][A-Za-zÀ-ỹ]", script), path)
		self.assertIn('"tracecore.v1.ksnk.nav"', _read(SHELL))
		self.assertIn('"tracecore.v1.indicator.values"', _read(SCR66))

	def test_css_scoped_and_tokens_only(self):
		css = re.sub(r"/\*.*?\*/", "", _read("ui/page/tc_ksnk/tc_ksnk.css"), flags=re.DOTALL)
		self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", css))
		body = re.sub(r"@media[^{]*\{", "{", css)
		self.assertIsNone(re.search(r"(?<![\w-])\d+(?:\.\d+)?px\b", body))
		for selector in re.findall(r"(?m)^([^@\s{}][^{]*)\{", css):
			for part in selector.split(","):
				self.assertTrue(part.strip().startswith(".tc-ksnk"), part)
