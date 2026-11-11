"""Màn SCR-60 Lệnh cách ly & phòng cách ly — WEB trong Page tc-ksnk và Cổng khoa (FEAT-068; UC-52; A-131, A-146)."""

import os

import frappe

from tracecore.microbiology.tests.test_isolation import make_clinical, make_dept_user
from tracecore.tests.factories import make_user
from tracecore.tests.js_harness import run_js
from tracecore.tests.utils import IsolatedTestCase
from tracecore.ui import ksnk

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR60 = "public/js/ksnk/scr_60_cach_ly.js"
SCR59 = "public/js/ksnk/scr_59_vi_sinh.js"

DATA = """
const data = {
	ok: true, can_write: true, can_read_orders: true, mdro_close: false, can_cancel: false, can_edit_rooms: true,
	room_form: "/app/isolation-room/new",
	departments: [{name: "D1", label: "Hồi sức"}, {name: "D2", label: "Nội"}],
	precautions: ["Contact", "Droplet", "Airborne", "Combined"],
	reasons: ["Multidrug-Resistant Organism", "Communicable Disease", "Suspected Infection"],
	prefill: {isolate: "VS-2026-01204", department: "D1", patient_code_masked: "***4821", mdro_flags: "CRE",
		reason: "Multidrug-Resistant Organism", precaution_type: "Contact"},
	orders: [
		{name: "CL-2026-00141", patient_code_masked: "***7730", department: "D1", department_name: "Hồi sức <b>",
		 precaution_type: "Contact", room_code: "PCL-HSTC-01", start_at: "2026-10-30 08:00:00", days: 4,
		 is_mdro: 1, mdro_history: ["CRE"]},
		{name: "CL-2026-00139", patient_code_masked: "***1049", department: "D2", department_name: "Nội",
		 precaution_type: "Droplet", room_code: null, start_at: "2026-10-28 08:00:00", days: 6, is_mdro: 0,
		 mdro_history: []},
	],
	rooms: [
		{name: "PCL-0001", room_code: "PCL-HSTC-01", department: "D1", department_name: "Hồi sức",
		 room_type: "Single Room", beds: 1, negative_pressure: 0, has_hand_sink: 1, has_anteroom: 1,
		 meets_standard: 1, checked_on: "2026-10-01", occupied: 1, free: 0},
		{name: "PCL-0002", room_code: "PCL-CC-01", department: "D2", department_name: "Nội",
		 room_type: "Single Room", beds: 1, negative_pressure: 0, has_hand_sink: 0, has_anteroom: 0,
		 meets_standard: 0, checked_on: "2026-10-01", standard_note: "thiếu bồn rửa tay", occupied: 0, free: 1},
	],
	coverage: {total: 30, covered: 27, rate: 90.0, missing: [{department: "D3", department_name: "Nội thận"}]},
};
const esc = TcKsnk.esc;
"""


def _read(path):
	with open(os.path.join(frappe.get_app_path("tracecore"), *path.split("/")), encoding="utf-8") as handle:
		return handle.read()


class TestKsnkScr60(IsolatedTestCase):
	def _run(self, code, files=(SHELL, SCR60), names=(["TcKsnk"], ["TcKsnkScr60"])):
		return run_js(self, list(files), list(names), DATA + code)

	def test_registered_in_micro_group_for_office_roles(self):
		screen = next(item for item in ksnk.SCREENS if item["slug"] == "cach-ly")
		self.assertEqual((screen["scr"], screen["uc"], screen["group"]), ("SCR-60", "UC-52", "micro"))
		self.assertEqual(set(screen["roles"]), {"TC R01", "TC R11", "TC R13", "System Manager"})
		self.assertTrue(os.path.exists(os.path.join(frappe.get_app_path("tracecore"), *SCR60.split("/"))))

	def test_form_prefilled_from_isolate_with_required_marks(self):
		out = self._run("""emit({html: TcKsnkScr60.formHtml(data, esc),
			none: TcKsnkScr60.formHtml(Object.assign({}, data, {can_write: false}), esc)});""")
		html = out["html"]
		self.assertIn("***4821 · VS-2026-01204 · CRE", html)
		self.assertNotIn('data-field="patient_code"', html)
		self.assertIn('value="Contact" selected', html)
		self.assertIn('aria-required="true"', html)
		self.assertIn("No room — bedside isolation", html)
		self.assertIn("PCL-HSTC-01 (meets standard, full)", html)
		self.assertNotIn("PCL-CC-01", html)  # phòng khoa khác
		self.assertEqual(out["none"], "")

	def test_open_orders_text_labels_and_mdro_close_rule(self):
		out = self._run("""emit({html: TcKsnkScr60.ordersHtml(data, esc),
			ic: TcKsnkScr60.ordersHtml(Object.assign({}, data, {mdro_close: true, can_cancel: true}), esc)});""")
		html = out["html"]
		self.assertIn("2 patients", html)
		self.assertIn("***7730", html)
		self.assertIn("MDRO</span>", html.replace(": CRE", ""))
		self.assertIn("Bedside", html)
		self.assertIn("Infection control closes", html)  # lệnh đa kháng: khoa không có nút Kết thúc
		self.assertIn('data-action="close" data-name="CL-2026-00139"', html)
		self.assertNotIn('data-name="CL-2026-00141"', html)
		self.assertIn("Hồi sức &lt;b&gt;", html)
		self.assertIn('data-action="close" data-name="CL-2026-00141"', out["ic"])
		self.assertIn('data-action="cancel"', out["ic"])

	def test_rooms_coverage_and_missing_departments(self):
		out = self._run("""emit({html: TcKsnkScr60.roomsHtml(data, esc),
			r13: TcKsnkScr60.pageHtml(Object.assign({}, data, {can_write: false, can_read_orders: false}), esc)});""")
		html = out["html"]
		self.assertIn("27/30", html)
		self.assertIn("90 %", html)
		self.assertIn("Meets standard", html)
		self.assertIn("Not met</span>", html.replace(" — thiếu bồn rửa tay", ""))
		self.assertIn("Nội thận", html)
		self.assertIn("No room meeting the standard", html)
		self.assertIn("In use (1/1)", html)
		self.assertIn("/app/isolation-room/new", html)
		self.assertNotIn("Create isolation order", out["r13"])
		self.assertNotIn("In isolation", out["r13"])

	def test_scr59_mdro_row_links_to_isolation_form(self):
		out = run_js(
			self,
			[SHELL, SCR59],
			[["TcKsnk"], ["TcKsnkScr59"]],
			"""emit({html: TcKsnkScr59.mdroBadge({name: "VS-2026-01204", is_mdro: 1, mdro_flags: "CRE"},
				TcKsnk.esc), none: TcKsnkScr59.mdroBadge({name: "VS-1", is_mdro: 0}, TcKsnk.esc)});""",
		)
		self.assertIn("/app/tc-ksnk/cach-ly?isolate=VS-2026-01204", out["html"])
		self.assertIn("Create isolation order", out["html"])
		self.assertNotIn("cach-ly", out["none"])

	def test_tokens_only_in_css_blocks(self):
		css = _read("www/ksnk_khoa/cach_ly.css")
		self.assertNotRegex(css, r"#[0-9a-fA-F]{3,6}\b")
		self.assertNotRegex(css, r"\d+px")


class TestIsolationPortal(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.ward = make_clinical("CLP Khoa Hồi sức")

	def test_route_rule_nav_and_assets(self):
		rules = frappe.get_hooks("website_route_rules")
		self.assertIn({"from_route": "/ksnk-khoa/cach-ly", "to_route": "ksnk_khoa/cach_ly"}, rules)
		html = frappe.render_template("templates/includes/ksnk_khoa_nav.html", {"ksnk_nav": "cach-ly"})
		self.assertIn('href="/ksnk-khoa/cach-ly" aria-current="page"', html)
		script = _read("www/ksnk_khoa/cach_ly.js")
		self.assertIn("X-Idempotency-Key", script)
		self.assertIn("tracecore.v1.isolation.create_order", script)

	def test_context_login_redirect_and_department_scope(self):
		from tracecore.www.ksnk_khoa import cach_ly as page

		r08 = make_dept_user("clp-r08@example.com", "TC R08", self.ward)
		frappe.set_user("Guest")
		frappe.form_dict.isolate = "VS-1"
		self.addCleanup(frappe.form_dict.pop, "isolate", None)
		with self.assertRaises(frappe.Redirect):
			page.get_context(frappe._dict())
		self.assertIn("redirect-to=", frappe.local.flags.redirect_location)
		frappe.set_user(r08)
		frappe.form_dict.isolate = ""
		context = page.get_context(frappe._dict())
		self.assertEqual([row["name"] for row in context.boot["data"]["departments"]], [self.ward])
		self.assertEqual(context.ksnk_nav, "cach-ly")
		self.assertIn("Contact", context.boot["labels"]["precautions"])

	def test_desk_roles_redirected_to_scr60(self):
		from tracecore.www.ksnk_khoa import cach_ly as page

		r11 = make_user("clp-r11@example.com", ["TC R11"])
		frappe.set_user(r11)
		frappe.form_dict.isolate = "VS-2026-01204"
		self.addCleanup(frappe.form_dict.pop, "isolate", None)
		with self.assertRaises(frappe.Redirect):
			page.get_context(frappe._dict())
		self.assertEqual(frappe.local.flags.redirect_location, "/app/tc-ksnk/cach-ly?isolate=VS-2026-01204")
