"""Giao diện FEAT-062: màn PDA SCR-55 (Page station, chức năng CENSUS), trang Cổng khoa `/ksnk-khoa/mau-so`, chọn đợt
thiết bị trên phiếu gói dự phòng (SCR-52) (UC-47; FR-M13-02, FR-M13-04, FR-M12-07; FR-M9-14; A-141 f, Q4; design.md)."""

import os
import re

import frappe

from tracecore.hai_surveillance.tests import factories as f
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import navigation

APP = frappe.get_app_path("tracecore")
STATION_JS = os.path.join(APP, "public", "js", "station_census.js")
AUDIT_JS = os.path.join(APP, "public", "js", "station_audit.js")
PORTAL = os.path.join(APP, "www", "ksnk_khoa")
VIETNAMESE = re.compile(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.IGNORECASE)
HEX_OR_PX = re.compile(r"#[0-9a-fA-F]{3,6}\b|\d+px")


def _read(path):
	with open(path, encoding="utf-8") as handle:
		return handle.read()


def _code(text):
	"""Bỏ chú thích để kiểm chuỗi mã (chú thích tiếng Việt được phép)."""
	text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
	text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
	return "\n".join(line.split("//", 1)[0] if "://" not in line else line for line in text.splitlines())


class TestStationScreen(IsolatedTestCase):
	def test_station_function_and_wiring(self):
		self.assertEqual(frappe.db.get_value("Station Function", "CENSUS", "screen_key"), "census")
		self.assertEqual(navigation.FUNCTION_ROLES["CENSUS"], {"TC R08", "TC R11", "TC R12"})
		self.assertIn("public/js/station_census.js", frappe.get_hooks("page_js")["station"])
		station = _read(os.path.join(APP, "ui", "page", "station", "station.js"))
		self.assertIn('case "census"', station)
		self.assertIn('method.startsWith("tracecore.v1.hai.")', station)
		outbox = _read(os.path.join(APP, "public", "js", "tc_outbox.js"))
		self.assertIn('"tracecore.v1.hai.census_upsert"', outbox)
		self.assertIn('"tracecore.v1.hai.device_episode"', outbox)

	def test_pda_screen_states_offline_and_privacy(self):
		code = _code(_read(STATION_JS))
		for marker in (
			"renderLoading()",
			'"offline"',
			'"empty"',
			'"error"',
			"queueCall(",
			"uuid4()",
			"t8Encrypt(",
		):
			self.assertIn(marker, code, marker)
		self.assertIn('type="password"', code)
		self.assertIn("patient_code_masked", code)
		self.assertNotIn("frappe.call(", code)
		self.assertIsNone(VIETNAMESE.search(code))
		self.assertNotRegex(code, re.compile(r"patient_name|full_name", re.I))  # BRU-HAI-005

	def test_station_css_block_uses_tokens(self):
		css = _read(os.path.join(APP, "ui", "page", "station", "station.css"))
		start = css.index("FEAT-062 SCR-55")
		block = css[start : css.index(".tc-danger-zone", start)]
		self.assertIsNone(HEX_OR_PX.search(block))

	def test_bundle_audit_picks_episode(self):
		code = _code(_read(AUDIT_JS))
		self.assertIn('"aud-episode"', code)
		self.assertIn("device_episode:", code)
		self.assertIn('"AUDIT_EPISODE_REQUIRED"', code)


class TestPortalPage(IsolatedTestCase):
	def test_route_rule_and_assets(self):
		rules = frappe.get_hooks("website_route_rules")
		self.assertIn({"from_route": "/ksnk-khoa/mau-so", "to_route": "ksnk_khoa/mau_so"}, rules)
		js = _code(_read(os.path.join(PORTAL, "mau_so.js")))
		self.assertIsNone(VIETNAMESE.search(js))
		self.assertIn("X-Idempotency-Key", js)
		self.assertIn("tracecore.v1.hai.census_upsert_portal", js)
		self.assertIn("offline_title", js)
		self.assertIsNone(HEX_OR_PX.search(_code(_read(os.path.join(PORTAL, "mau_so.css")))))
		html = _code(_read(os.path.join(PORTAL, "mau_so.html")))
		self.assertIsNone(VIETNAMESE.search(html))
		self.assertIn("templates/includes/ksnk_khoa_nav.html", html)
		self.assertIn(
			"templates/includes/ksnk_khoa_nav.html", _read(os.path.join(PORTAL, "bao_phoi_nhiem.html"))
		)

	def test_nav_marks_current_page(self):
		html = frappe.render_template("templates/includes/ksnk_khoa_nav.html", {"ksnk_nav": "mau-so"})
		self.assertIn('href="/ksnk-khoa/mau-so" aria-current="page"', html)
		self.assertIn('href="/ksnk-khoa/bao-phoi-nhiem"', html)
		self.assertIsNone(HEX_OR_PX.search(html))

	def test_context_requires_login_and_scopes_department(self):
		from tracecore.www.ksnk_khoa import mau_so as page

		self.addCleanup(frappe.set_user, "Administrator")
		ward = f.make_ward("MS Portal Khoa")
		user = f.make_dept_user("ms-portal-r12@example.com", f.R12, ward)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.Redirect):
			page.get_context(frappe._dict())
		frappe.set_user(user)
		context = page.get_context(frappe._dict())
		self.assertEqual(context.boot["data"]["department"], ward)
		self.assertEqual(context.ksnk_nav, "mau-so")
		self.assertEqual(
			set(context.boot["labels"]["devices"]), {"Ventilator", "Central Line", "Urinary Catheter"}
		)
		self.assertNotIn('patient_code"', frappe.as_json(context.boot["data"]))
