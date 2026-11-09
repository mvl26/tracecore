"""Giao diện M16: màn PDA SCR-63, trang Cổng khoa, màn SCR-64 trong tc-ksnk (FEAT-071; FR-M16-01, FR-M16-06; A-131,
A-137 Q2, Q4; FR-M9-14; design.md)."""

import os
import re

import frappe

from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase
from tracecore.ui import ksnk
from tracecore.v1 import navigation

APP = frappe.get_app_path("tracecore")
STATION_JS = os.path.join(APP, "public", "js", "station_exposure.js")
SCR64_JS = os.path.join(APP, "public", "js", "ksnk", "scr_64_phoi_nhiem.js")
PORTAL = os.path.join(APP, "www", "ksnk_khoa")
VIETNAMESE = re.compile(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.IGNORECASE)
HEX_OR_PX = re.compile(r"#[0-9a-fA-F]{3,6}\b|\d+px")


def _read(path):
	with open(path, encoding="utf-8") as handle:
		return handle.read()


def _code(text):
	"""Bỏ chú thích để kiểm chuỗi mã (chú thích tiếng Việt được phép)."""
	text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
	return "\n".join(line.split("//", 1)[0] if "://" not in line else line for line in text.splitlines())


class TestStationScreen(IsolatedTestCase):
	def test_station_function_and_wiring(self):
		self.assertEqual(frappe.db.get_value("Station Function", "EXPOSURE", "screen_key"), "exposure")
		self.assertIn("EXPOSURE", navigation.FUNCTION_ROLES)
		self.assertIn("public/js/station_exposure.js", frappe.get_hooks("page_js")["station"])
		station = _read(os.path.join(APP, "ui", "page", "station", "station.js"))
		self.assertIn('case "exposure"', station)
		self.assertIn('method.startsWith("tracecore.v1.exposure.")', station)
		self.assertIn(
			'"tracecore.v1.exposure.report"', _read(os.path.join(APP, "public", "js", "tc_outbox.js"))
		)

	def test_pda_screen_three_steps_four_states_no_result_field(self):
		js = _read(STATION_JS)
		code = _code(js)
		for marker in ("renderLoading()", '"offline"', '"empty"', '"error"', "queueCall(", "uuid4()"):
			self.assertIn(marker, code, marker)
		for step in ("Step 1: type of exposure", "Step 2: what happened", "Step 3: check and send"):
			self.assertIn(f'__("{step}")', code)
		self.assertIn('type="password"', code)
		self.assertNotIn("frappe.call(", code)
		self.assertIsNone(VIETNAMESE.search(code))
		self.assertNotRegex(code, re.compile(r"diagnos|test_result|lab_result", re.I))  # FR-M16-06
		# mã BN rõ không vào hàng đợi IndexedDB
		self.assertIn("source_patient_code: code, ...rest", code)

	def test_station_css_block_uses_tokens(self):
		css = _read(os.path.join(APP, "ui", "page", "station", "station.css"))
		block = css[css.index("FEAT-071 SCR-63") :]
		self.assertIsNone(HEX_OR_PX.search(block))


class TestPortalPage(IsolatedTestCase):
	def test_route_rule_and_assets(self):
		rules = frappe.get_hooks("website_route_rules")
		self.assertIn(
			{"from_route": "/ksnk-khoa/bao-phoi-nhiem", "to_route": "ksnk_khoa/bao_phoi_nhiem"}, rules
		)
		js = _code(_read(os.path.join(PORTAL, "bao_phoi_nhiem.js")))
		self.assertIsNone(VIETNAMESE.search(js))
		self.assertIn("X-Idempotency-Key", js)
		self.assertIn("source_patient_code: _code, ...rest", js)  # mã BN không lưu trong trình duyệt
		for state in ('"loading"', '"empty"', '"error"', '"offline"'):
			self.assertIn(state, js)
		self.assertIsNone(HEX_OR_PX.search(_read(os.path.join(PORTAL, "bao_phoi_nhiem.css"))))
		self.assertIsNone(VIETNAMESE.search(_read(os.path.join(PORTAL, "bao_phoi_nhiem.html"))))

	def test_context_requires_login_and_has_translated_labels(self):
		from tracecore.www.ksnk_khoa import bao_phoi_nhiem as page

		self.addCleanup(frappe.set_user, "Administrator")
		user = factories.make_user("os-portal-r08@example.com", roles=["TC R08"])
		department = factories.make_department("PN Portal Khoa")
		factories.make_employee(first_name="PN Portal", department=department, user_id=user)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.Redirect):
			page.get_context(frappe._dict())
		frappe.set_user(user)
		context = page.get_context(frappe._dict())
		self.assertEqual(context.department, department)
		self.assertEqual(set(context.boot["labels"]["types"]), set(page.api.config.EXPOSURE_TYPES))
		self.assertTrue(context.boot["data"]["employee"])


class TestScr64(IsolatedTestCase):
	def test_registry_entry(self):
		screen = next(s for s in ksnk.SCREENS if s["slug"] == "phoi-nhiem")
		self.assertEqual((screen["scr"], screen["uc"], screen["group"]), ("SCR-64", "UC-55", "environment"))
		self.assertEqual(set(screen["roles"]), {"TC R01", "TC R11", "TC R13", "System Manager"})
		self.assertTrue(
			os.path.exists(os.path.join(APP, "public", screen["script"].split("/assets/tracecore/")[1]))
		)

	def test_r11_sees_screen_r02_does_not(self):
		r11 = factories.make_user("os-ksnk-r11@example.com", roles=["TC R11"])
		r02 = factories.make_user("os-ksnk-r02@example.com", roles=["TC R02"])
		slugs = [item["slug"] for group in ksnk.nav(r11)["groups"] for item in group["items"]]
		self.assertIn("phoi-nhiem", slugs)
		with self.assertRaises(frappe.PermissionError):
			ksnk.nav(r02)

	def test_script_contract(self):
		js = _read(SCR64_JS)
		code = _code(js)
		self.assertIn('window.TcKsnkScreens["phoi-nhiem"]', code)
		self.assertNotIn("frappe.call(", code)
		self.assertNotIn("msgprint", code)
		self.assertIsNone(VIETNAMESE.search(code))
		self.assertIsNone(re.search(r"#[0-9a-fA-F]{6}", code))
		# RPC GET chỉ đọc qua ctx.get, ghi qua tracecore.desk_call (POST)
		self.assertIn("ctx.get(TC_EXP_DASHBOARD", code)
		self.assertIn("tracecore.desk_call", code)
		css = _read(os.path.join(APP, "ui", "page", "tc_ksnk", "tc_ksnk.css"))
		block = css[css.index("FEAT-071 SCR-64") :]
		self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,6}\b|\d+px(?![^@]*\{)", block.split("@media")[0]))
