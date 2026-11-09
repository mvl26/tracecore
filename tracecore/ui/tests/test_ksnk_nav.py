"""Menu màn quản lý KSNK toàn viện `tc-ksnk` (FEAT-056 AC-13, AC-14; A-131 b, e)."""

from unittest.mock import patch

import frappe

from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase
from tracecore.ui import ksnk
from tracecore.v1 import ksnk as api


def _slugs(nav):
	return [item["slug"] for group in nav["groups"] for item in group["items"]]


class TestKsnkNav(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.users = {
			code: factories.make_user(f"ksnk-nav-{code.lower()}@example.com", [f"TC {code}"])
			for code in ("R01", "R02", "R10", "R11", "R12", "R13")
		}

	def test_registry_screens_have_known_groups_and_scripts(self):
		groups = {key for key, _label in ksnk.GROUPS}
		slugs = set()
		for screen in ksnk.SCREENS:
			self.assertIn(screen["group"], groups)
			self.assertTrue(screen["script"].startswith("/assets/tracecore/js/ksnk/"))
			self.assertRegex(screen["scr"], r"^SCR-\d+$")
			self.assertNotIn(screen["slug"], slugs)
			slugs.add(screen["slug"])
		self.assertIn("chi-so", slugs)

	def test_r11_sees_indicator_board_grouped(self):
		frappe.set_user(self.users["R11"])
		nav = api.nav()
		self.assertEqual(nav["home"], "chi-so")
		self.assertIn("chi-so", _slugs(nav))
		first = nav["groups"][0]
		self.assertEqual(first["key"], "program")
		self.assertFalse(nav["read_only"])
		self.assertFalse(nav["dept_only"])

	def test_r13_is_read_only_with_indicator_board_home(self):
		frappe.set_user(self.users["R13"])
		nav = api.nav()
		self.assertEqual(nav["home"], "chi-so")
		self.assertTrue(nav["read_only"])

	def test_r12_goes_to_department_portal(self):
		frappe.set_user(self.users["R12"])
		nav = api.nav()
		self.assertTrue(nav["dept_only"])
		self.assertEqual(nav["groups"], [])

	def test_role_without_ksnk_access_is_rejected(self):
		frappe.set_user(self.users["R02"])
		with self.assertRaises(frappe.PermissionError):
			api.nav()

	def test_screen_hidden_when_role_not_allowed(self):
		screens = [
			*ksnk.SCREENS,
			{
				"slug": "test-only-r01",
				"scr": "SCR-99",
				"uc": "UC-99",
				"label": "Test",
				"group": "program",
				"roles": ("TC R01",),
				"script": "/assets/tracecore/js/ksnk/test.js",
			},
		]
		with patch("tracecore.ui.ksnk.SCREENS", screens):
			frappe.set_user(self.users["R01"])
			self.assertIn("test-only-r01", _slugs(api.nav()))
			frappe.set_user(self.users["R11"])
			self.assertNotIn("test-only-r01", _slugs(api.nav()))

	def test_badges_come_from_hook_in_one_call(self):
		with patch(
			"tracecore.ui.ksnk.extension.run", return_value=[{"chi-so": 3}, {"chi-so": 2, "other": 9}]
		):
			frappe.set_user(self.users["R01"])
			nav = api.nav()
		item = next(i for g in nav["groups"] for i in g["items"] if i["slug"] == "chi-so")
		self.assertEqual(item["badge"], 5)

	def test_structure_screen_scr47_for_office_roles_with_missing_badge(self):
		"""FEAT-057 AC-11: SCR-47 trong nhóm program; badge = số thành phần cơ cấu thiếu (hook thật)."""
		screen = next(s for s in ksnk.SCREENS if s["slug"] == "co-cau")
		self.assertEqual((screen["scr"], screen["uc"], screen["group"]), ("SCR-47", "UC-40", "program"))
		self.assertEqual(screen["script"], "/assets/tracecore/js/ksnk/scr_47_co_cau.js")
		self.assertIn(
			"tracecore.infection_program.structure.badges", frappe.get_hooks("tracecore_ksnk_badges")
		)
		frappe.db.sql("update `tabDepartment` set tc_ic_network_required = 0")
		settings = frappe.get_single("IC Program Settings")
		settings.update({"bed_count": 420, "facility_level": "Specialized Level", "has_inpatient": 1})
		settings.set("ic_department", None)
		settings.set("surveillance_staff", [])
		settings.save(ignore_permissions=True)
		for code in ("R01", "R10", "R11", "R13"):
			frappe.set_user(self.users[code])
			nav = api.nav()
			self.assertIn("co-cau", _slugs(nav), code)
			self.assertEqual(nav["home"], "chi-so", code)
		item = next(i for g in nav["groups"] for i in g["items"] if i["slug"] == "co-cau")
		self.assertGreaterEqual(
			item["badge"], 3
		)  # Hội đồng (nếu chưa có), khoa KSNK, mạng lưới, giám sát viên

	def test_departments_listed_for_filter(self):
		department = factories.make_department("KSNK Nav Ward")
		frappe.set_user(self.users["R11"])
		names = [row["name"] for row in api.nav()["departments"]]
		self.assertIn(department, names)
