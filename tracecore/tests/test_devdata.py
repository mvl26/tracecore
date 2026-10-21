import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import code_registry, gs1, step_gate
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import packing
from tracecore.setup import devdata
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase

test_dependencies = ["Company"]


class TestStationDemoData(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.get_doc("User", "Administrator").add_roles("TC R10")
		self.user = make_user("station-demo@example.test", ("TC R04",))

	def seed(self, **kwargs):
		return devdata.ensure_station_demo("TR-004", self.user, **kwargs)

	def admin_roles(self):
		return set(
			frappe.get_all(
				"Has Role", filters={"parent": "Administrator", "parenttype": "User"}, pluck="role"
			)
		)

	def test_legacy_user_factory_restores_explicit_roles_on_success_and_failure(self):
		from unittest.mock import patch

		frappe.get_doc("User", "Administrator").remove_roles("TC R10")
		before = self.admin_roles()
		self.assertTrue(make_user("legacy-fixture@example.test"))
		self.assertEqual(self.admin_roles(), before)
		with patch("frappe.core.doctype.user.user.User.insert", side_effect=RuntimeError("fixture failure")):
			with self.assertRaisesRegex(RuntimeError, "fixture failure"):
				make_user("failed-fixture@example.test")
		self.assertEqual(self.admin_roles(), before)

	def test_e2e_user_bootstrap_restores_administrator_roles(self):
		import secrets

		admin = frappe.get_doc("User", "Administrator")
		admin.remove_roles("TC R10")
		before = self.admin_roles()
		users = devdata.ensure_e2e_users(
			"TR-003", "TR-004", secrets.token_urlsafe(24), secrets.token_urlsafe(24)
		)
		self.assertEqual(self.admin_roles(), before)
		self.assertEqual(
			set(users), {"user", "t4_user", "r10_user", "otp_secret", "t4_otp_secret", "r10_otp_secret"}
		)
		self.assertIn("TC R04", frappe.get_roles(users["t4_user"]))
		self.assertIn("TC R10", frappe.get_roles(users["r10_user"]))
		from frappe.twofactor import get_default
		from frappe.utils.password import decrypt

		for prefix in ("", "t4_", "r10_"):
			stored = get_default(users[prefix + "user"] + "_otpsecret")
			self.assertNotEqual(stored, users[prefix + "otp_secret"])
			self.assertEqual(decrypt(stored), users[prefix + "otp_secret"])
			self.assertTrue(get_default(users[prefix + "user"] + "_otplogin"))
		self.assertEqual(
			users,
			devdata.ensure_e2e_users(
				"TR-003", "TR-004", secrets.token_urlsafe(24), secrets.token_urlsafe(24)
			),
		)

	def test_e2e_user_bootstrap_restores_roles_after_failure_and_preserves_existing_r10(self):
		from unittest.mock import patch

		admin = frappe.get_doc("User", "Administrator")
		for already_r10 in (False, True):
			admin.reload()
			(admin.add_roles if already_r10 else admin.remove_roles)("TC R10")
			before = self.admin_roles()
			with patch(
				"tracecore.setup.provision.station_user", side_effect=RuntimeError("injected failure")
			):
				with self.assertRaisesRegex(RuntimeError, "injected failure"):
					devdata.ensure_e2e_users("TR-003", "TR-004", "unused", "unused")
			self.assertEqual(self.admin_roles(), before)

	def test_e2e_user_bootstrap_refuses_production_before_role_grant(self):
		from unittest.mock import patch

		frappe.get_doc("User", "Administrator").remove_roles("TC R10")
		before = self.admin_roles()
		with (
			patch.dict(frappe.conf, {"developer_mode": 0, "allow_tests": 0}),
			patch.dict(frappe.flags, {"in_test": False}),
		):
			with self.assertRaises(frappe.ValidationError):
				devdata.ensure_e2e_users("TR-003", "TR-004", "unused", "unused")
		self.assertEqual(self.admin_roles(), before)

	def test_card_employee_and_competencies_are_reusable_and_can_login(self):
		from tracecore.core import station_auth

		first = self.seed(second_station="TR-005")
		self.assertEqual(first, self.seed(second_station="TR-005"))
		self.assertTrue(first["card_id"].startswith("E2E-"))
		self.assertEqual(frappe.db.count("Employee", {"user_id": self.user}), 1)
		self.assertEqual(frappe.db.count("Station Competency", {"employee": first["employee"]}), 2)
		self.assertEqual(frappe.db.get_value("Employee", first["employee"], "status"), "Active")
		self.assertFalse(
			frappe.utils.password.get_decrypted_password(
				"Employee", first["employee"], "tc_pin_hash", raise_exception=False
			)
		)
		for station in ("TR-004", "TR-005"):
			login = station_auth.login(first["card_id"], station)
			self.assertEqual(login["user"], self.user)
			self.assertEqual(login["roles"], ["TC R04"])

	def test_supplied_card_is_normalized_and_stale_competency_is_renewed(self):
		first = self.seed(card_id=" e2e-explicit-card ")
		self.assertEqual(first["card_id"], "E2E-EXPLICIT-CARD")
		name = frappe.db.get_value("Station Competency", {"employee": first["employee"]}, "name")
		frappe.db.set_value("Station Competency", name, {"valid_until": "2000-01-01", "is_active": 0})
		self.assertEqual(first, self.seed(card_id="E2E-EXPLICIT-CARD"))
		self.assertEqual(frappe.db.count("Station Competency", {"employee": first["employee"]}), 1)
		self.assertTrue(frappe.db.get_value("Station Competency", name, "is_active"))

	def test_production_guard_runs_before_any_seed(self):
		from unittest.mock import patch

		with (
			patch.dict(frappe.conf, {"developer_mode": 0, "allow_tests": 0}),
			patch.dict(frappe.flags, {"in_test": False}),
		):
			with self.assertRaises(frappe.ValidationError):
				self.seed()
		self.assertFalse(frappe.db.exists("Employee", {"user_id": self.user}))

	def test_disabled_users_and_inactive_stations_are_rejected(self):
		frappe.db.set_value("User", self.user, "enabled", 0)
		with self.assertRaises(frappe.ValidationError):
			self.seed()
		frappe.db.set_value("User", self.user, "enabled", 1)
		frappe.db.set_value("Zone Station", "TR-004", "is_active", 0)
		with self.assertRaises(frappe.ValidationError):
			self.seed()


class TestDevData(FrappeTestCase):
	def test_ensure_demo_set_is_idempotent(self):
		first = devdata.ensure_demo_set()
		second = devdata.ensure_demo_set()
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.get_value("Set Unit", first, "set_type"), "DEMO")
		self.assertEqual(gs1.parse_scan(first)["type"], "set")

	def _with_conf(self, developer_mode, allow_tests):
		original = (frappe.conf.get("developer_mode"), frappe.conf.get("allow_tests"))
		frappe.flags.in_test = False
		frappe.conf.developer_mode, frappe.conf.allow_tests = developer_mode, allow_tests
		try:
			return devdata.ensure_demo_set()
		finally:
			frappe.conf.developer_mode, frappe.conf.allow_tests = original
			frappe.flags.in_test = True

	def test_refused_outside_developer_or_test_site(self):
		with self.assertRaises(frappe.ValidationError):
			self._with_conf(developer_mode=0, allow_tests=0)

	def test_allowed_on_test_site(self):
		self.assertEqual(gs1.parse_scan(self._with_conf(developer_mode=0, allow_tests=1))["type"], "set")


T4_KEYS = {
	"set_steam",
	"set_maint",
	"set_plasma",
	"set_gate_fail",
	"ci_steam",
	"ci_plasma",
	"roll_steam",
	"roll_plasma",
	"printer",
}


def _gates(set_id):
	return {row["step"]: row["result"] for row in step_gate.gates(set_id)}


class TestT4DemoData(FrappeTestCase):
	def test_ensure_t4_demo_idempotent(self):
		first = devdata.ensure_t4_demo()
		second = devdata.ensure_t4_demo()
		self.assertEqual(first, second)
		self.assertEqual(set(first), T4_KEYS)

		self.assertEqual(_gates(first["set_steam"])["T3"], "Pass")
		self.assertEqual(_gates(first["set_plasma"])["T3"], "Pass")
		self.assertNotEqual(_gates(first["set_gate_fail"])["T3"], "Pass")
		self.assertEqual(_gates(first["set_maint"])["T3"], "Pass")
		self.assertEqual(
			len({first["set_steam"], first["set_maint"], first["set_plasma"], first["set_gate_fail"]}), 4
		)

		methods = {}
		for key in ("set_steam", "set_plasma", "set_gate_fail"):
			set_type = frappe.db.get_value("Set Unit", first[key], "set_type")
			gtin, methods[key] = frappe.db.get_value("Instrument Set Type", set_type, ["gtin", "method"])
			self.assertTrue(gs1.is_test_gtin(gtin), msg=(key, gtin))
			self.assertNotEqual(gtin, gs1.make_test_gtin14(1))  # serial 1 là giá trị cố định của test khác
		self.assertEqual(methods, {"set_steam": "Steam", "set_plasma": "Plasma", "set_gate_fail": "Steam"})

		printer = frappe.get_doc("Printer", first["printer"])
		self.assertEqual(
			(printer.station, printer.label_type_loaded, printer.host or "", printer.supports_unicode),
			("TR-004", "VT-NHAN-HAP", "", 0),
		)
		self.assertTrue(printer.is_active)
		self.assertEqual(code_registry.roll_label_item(first["roll_steam"]), "VT-NHAN-HAP")
		self.assertEqual(code_registry.roll_label_item(first["roll_plasma"]), "VT-NHAN-PLASMA")
		for key, method in (("ci_steam", "Steam"), ("ci_plasma", "Plasma")):
			item = frappe.db.get_value("Batch", first[key], "item")
			self.assertEqual(frappe.db.get_value("Item", item, "tc_compatible_method"), method)

	def test_t4_demo_sets_open_at_t4(self):
		demo = devdata.ensure_t4_demo()
		steam = packing.get_context(demo["set_steam"], "TR-004")
		plasma = packing.get_context(demo["set_plasma"], "TR-004")
		maint = packing.get_context(demo["set_maint"], "TR-004")
		# chỉ set_maint có nhắc tra dầu đến hạn; bộ hấp sạch và bộ plasma không có nhắc
		self.assertEqual(
			[(row["maint_type"], row["state"]) for row in maint["maintenance"]], [("Lubrication", "due")]
		)
		self.assertEqual(steam["maintenance"], [])
		self.assertEqual(plasma["maintenance"], [])
		self.assertGreaterEqual(len(steam["bom"]), 3)
		self.assertTrue(all(line["image"] for line in steam["bom"] + plasma["bom"]))
		self.assertEqual(steam["printer"]["name"], demo["printer"])
		self.assertIsNone(plasma["printer"])  # máy in đang lắp nhãn hấp: nhãn plasma chờ đổi cuộn
		self.assertTrue(steam["pack_types"])
		with self.assertRaises(BlockedError) as raised:
			packing.get_context(demo["set_gate_fail"], "TR-004")
		self.assertEqual(raised.exception.block.code, "GATE_PREV_NOT_PASSED")

	def test_t4_demo_replaces_a_set_that_got_a_cycle_id(self):
		first = devdata.ensure_t4_demo()
		step_gate.bind_cycle(first["set_steam"], "CY-DEMO-0001", "TR-004")
		second = devdata.ensure_t4_demo()
		self.assertNotEqual(second["set_steam"], first["set_steam"])
		self.assertEqual(_gates(second["set_steam"])["T3"], "Pass")
		self.assertEqual(second["set_maint"], first["set_maint"])
		self.assertEqual(second["set_plasma"], first["set_plasma"])
		self.assertEqual(second["set_gate_fail"], first["set_gate_fail"])

	def test_t4_demo_refused_outside_developer_or_test_site(self):
		original = (frappe.conf.get("developer_mode"), frappe.conf.get("allow_tests"))
		frappe.flags.in_test = False
		frappe.conf.developer_mode, frappe.conf.allow_tests = 0, 0
		try:
			with self.assertRaises(frappe.ValidationError):
				devdata.ensure_t4_demo()
		finally:
			frappe.conf.developer_mode, frappe.conf.allow_tests = original
			frappe.flags.in_test = True


EQUIPMENT_KEYS = {
	"steam",
	"steam_copy_target",
	"washer",
	"retired",
	"program_complete",
	"program_missing",
	"program_inactive",
	"program_outside",
}


class TestEquipmentDemoData(FrappeTestCase):
	def test_ensure_equipment_demo_idempotent(self):
		first = devdata.ensure_equipment_demo()
		equipment_count = frappe.db.count("Equipment")
		program_count = frappe.db.count("Process Program")
		second = devdata.ensure_equipment_demo()
		self.assertEqual(first, second)
		self.assertEqual(set(first), EQUIPMENT_KEYS)
		self.assertEqual(frappe.db.count("Equipment"), equipment_count)
		self.assertEqual(frappe.db.count("Process Program"), program_count)
		self.assertEqual(frappe.db.count("Equipment Type Norm", {"equipment_type": "Washer-Disinfector"}), 1)

	def test_equipment_demo_machines(self):
		demo = devdata.ensure_equipment_demo()
		steam = frappe.get_doc("Equipment", demo["steam"])
		self.assertEqual(
			(steam.equipment_type, steam.serial_no, steam.zone_in, steam.zone_out, steam.status),
			("Steam Sterilizer", "E2E-STEAM-001", "ZONE-CLEAN", "ZONE-STERILE", "Ready"),
		)
		self.assertEqual((steam.safe_temp_min, steam.safe_temp_max, steam.safe_pressure_max), (105, 140, 3.5))
		washer = frappe.get_doc("Equipment", demo["washer"])
		self.assertEqual(
			(washer.equipment_type, washer.serial_no, washer.zone_in, washer.zone_out),
			("Washer-Disinfector", "E2E-WASH-001", "ZONE-DIRTY", "ZONE-CLEAN"),
		)
		# máy đích sao chép: cùng hãng + model với máy hấp; máy ngừng sử dụng cũng cùng model nhưng đã Retired
		target = frappe.get_doc("Equipment", demo["steam_copy_target"])
		self.assertEqual((target.manufacturer, target.model), (steam.manufacturer, steam.model))
		retired = frappe.get_doc("Equipment", demo["retired"])
		self.assertEqual(
			(retired.manufacturer, retired.model, retired.status),
			(steam.manufacturer, steam.model, "Retired"),
		)

	def test_equipment_demo_programs(self):
		demo = devdata.ensure_equipment_demo()
		status = lambda key, *fields: frappe.db.get_value("Process Program", demo[key], list(fields))  # noqa: E731
		self.assertEqual(
			status("program_complete", "norm_status", "outside_safe_range", "is_active"), ("Complete", 0, 1)
		)
		self.assertEqual(status("program_missing", "norm_status", "is_active"), ("Missing", 1))
		self.assertEqual(status("program_outside", "norm_status", "outside_safe_range"), ("Complete", 1))
		self.assertEqual(frappe.db.get_value("Process Program", demo["program_inactive"], "is_active"), 0)
		self.assertEqual(
			frappe.db.get_value("Process Program", demo["program_complete"], "equipment"), demo["steam"]
		)
		self.assertTrue(frappe.db.exists("Equipment Type Norm", "Washer-Disinfector"))

	def test_equipment_demo_refused_outside_developer_or_test_site(self):
		original = (frappe.conf.get("developer_mode"), frappe.conf.get("allow_tests"))
		frappe.flags.in_test = False
		frappe.conf.developer_mode, frappe.conf.allow_tests = 0, 0
		try:
			with self.assertRaises(frappe.ValidationError):
				devdata.ensure_equipment_demo()
		finally:
			frappe.conf.developer_mode, frappe.conf.allow_tests = original
			frappe.flags.in_test = True
