import frappe
from frappe.tests.utils import FrappeTestCase

EXPECTED_MODULES = (
	"TraceCore",
	"Instrument",
	"Reprocessing",
	"Linen",
	"Equipment",
	"Inventory",
	"Costing",
	"Par",
	"Admin Reports",
	"Waste",
	"UI",
	# A-113 (FEAT-056): 7 module KSNK toàn viện M11-M17
	"Infection Program",
	"Compliance Audit",
	"HAI Surveillance",
	"Microbiology",
	"Environmental Hygiene",
	"Occupational Safety",
	"Food Safety",
)


class TestInstall(FrappeTestCase):
	def test_module_defs_registered(self):
		for module in EXPECTED_MODULES:
			self.assertEqual(frappe.db.get_value("Module Def", module, "app_name"), "tracecore", msg=module)
		# "Core" thuộc frappe, "HR" thuộc hrms — tracecore không được chiếm (amendment 2026-10-19)
		self.assertEqual(frappe.db.get_value("Module Def", "Core", "app_name"), "frappe")
		self.assertNotEqual(frappe.db.get_value("Module Def", "HR", "app_name"), "tracecore")

	def test_roles_exist(self):
		# A-113 (FEAT-056): thêm R11 Giám sát viên KSNK, R12 Mạng lưới viên KSNK, R13 Hội đồng KSNK & BGĐ
		expected = [f"TC R{n:02d}" for n in range(1, 14)] + ["TC Agent"]
		for role in expected:
			self.assertTrue(frappe.db.exists("Role", role), msg=role)

	def test_ksnk_roles_two_factor_and_profiles(self):
		"""A-113 a, D4: 2FA cho R11, R13; R12 như R08 (không 2FA); mỗi vai trò mới có Role Profile cùng tên."""
		self.assertEqual(frappe.db.get_value("Role", "TC R11", "two_factor_auth"), 1)
		self.assertEqual(frappe.db.get_value("Role", "TC R12", "two_factor_auth"), 0)
		self.assertEqual(frappe.db.get_value("Role", "TC R13", "two_factor_auth"), 1)
		for code in ("R11", "R12", "R13"):
			profile = frappe.get_doc("Role Profile", f"TC {code}")
			self.assertEqual([row.role for row in profile.roles], [f"TC {code}"])

	def test_system_settings_localized(self):
		settings = frappe.get_single("System Settings")
		self.assertEqual(settings.language, "vi")
		self.assertEqual(settings.time_zone, "Asia/Ho_Chi_Minh")
		self.assertEqual(settings.date_format, "dd/mm/yyyy")
		self.assertEqual(settings.time_format, "HH:mm")
