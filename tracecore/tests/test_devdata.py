import os

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import code_registry, gs1, print_server, step_gate
from tracecore.core import print as core_print
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import packing
from tracecore.setup import devdata
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, allow_local_printers

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

	def test_t2_station_user_bootstrap_has_r03_and_otp(self):
		import secrets

		from frappe.twofactor import get_default
		from frappe.utils.password import decrypt

		frappe.get_doc("User", "Administrator").remove_roles("TC R10")
		before = self.admin_roles()
		users = devdata.ensure_t2_e2e_user("TR-002", secrets.token_urlsafe(24))
		self.assertEqual(self.admin_roles(), before)
		self.assertEqual(set(users), {"t2_user", "t2_otp_secret"})
		self.assertIn("TC R03", frappe.get_roles(users["t2_user"]))
		self.assertEqual(decrypt(get_default(users["t2_user"] + "_otpsecret")), users["t2_otp_secret"])
		self.assertEqual(users, devdata.ensure_t2_e2e_user("TR-002", secrets.token_urlsafe(24)))

	def test_desk_users_bootstrap_adds_otp_extra_roles_and_restores_administrator_roles(self):
		import secrets

		frappe.get_doc("User", "Administrator").remove_roles("TC R10")
		before = self.admin_roles()
		specs = [
			{"key": "codes", "role": "TC R10", "name": "r10-codes-e2e", "extra_roles": ["Stock User"]},
			{"key": "instr", "role": "TC R02", "name": "r02-instr-e2e"},
		]
		password = secrets.token_urlsafe(24)
		users = devdata.ensure_desk_users(password, specs)
		self.assertEqual(self.admin_roles(), before)
		self.assertEqual(set(users), {"codes_user", "codes_otp_secret", "instr_user", "instr_otp_secret"})
		self.assertTrue({"TC R10", "Stock User"} <= set(frappe.get_roles(users["codes_user"])))
		self.assertIn("TC R02", frappe.get_roles(users["instr_user"]))
		from frappe.twofactor import get_default
		from frappe.utils.password import decrypt

		for key in ("codes", "instr"):
			self.assertEqual(
				decrypt(get_default(users[key + "_user"] + "_otpsecret")), users[key + "_otp_secret"]
			)
			self.assertTrue(get_default(users[key + "_user"] + "_otplogin"))
		self.assertEqual(users, devdata.ensure_desk_users(password, specs))

	def test_t6_station_user_bootstrap_has_r06_and_otp(self):
		import secrets

		from frappe.twofactor import get_default
		from frappe.utils.password import decrypt

		frappe.get_doc("User", "Administrator").remove_roles("TC R10")
		before = self.admin_roles()
		users = devdata.ensure_t6_e2e_user("TR-006", secrets.token_urlsafe(24))
		self.assertEqual(self.admin_roles(), before)
		self.assertEqual(set(users), {"t6_user", "t6_otp_secret"})
		self.assertIn("TC R06", frappe.get_roles(users["t6_user"]))
		self.assertEqual(decrypt(get_default(users["t6_user"] + "_otpsecret")), users["t6_otp_secret"])
		self.assertEqual(users, devdata.ensure_t6_e2e_user("TR-006", secrets.token_urlsafe(24)))

	def test_t1_station_user_bootstrap_has_r03_and_otp(self):
		import secrets

		from frappe.twofactor import get_default
		from frappe.utils.password import decrypt

		frappe.get_doc("User", "Administrator").remove_roles("TC R10")
		before = self.admin_roles()
		users = devdata.ensure_t1_e2e_user("TR-001", secrets.token_urlsafe(24))
		self.assertEqual(self.admin_roles(), before)
		self.assertEqual(set(users), {"t1_user", "t1_otp_secret"})
		self.assertIn("TC R03", frappe.get_roles(users["t1_user"]))
		self.assertEqual(decrypt(get_default(users["t1_user"] + "_otpsecret")), users["t1_otp_secret"])
		self.assertEqual(users, devdata.ensure_t1_e2e_user("TR-001", secrets.token_urlsafe(24)))

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
	"set_offline_1",
	"set_offline_2",
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
		sets = ("set_steam", "set_maint", "set_plasma", "set_gate_fail", "set_offline_1", "set_offline_2")
		self.assertEqual(len({first[key] for key in sets}), 6)
		# FEAT-009: hai bộ hấp riêng cho e2e offline, không dùng chung bộ của test_station_t4.py
		for key in ("set_offline_1", "set_offline_2"):
			self.assertEqual(_gates(first[key])["T3"], "Pass", msg=key)
			set_type = frappe.db.get_value("Set Unit", first[key], "set_type")
			self.assertEqual(frappe.db.get_value("Instrument Set Type", set_type, "method"), "Steam")

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
		# FEAT-014 I11/I12: ảnh demo riêng tư, trạm T4 dùng thumbnail
		for line in steam["bom"] + plasma["bom"]:
			self.assertTrue(line["image"].startswith("/private/files/"), msg=line)
			self.assertTrue(line["thumbnail"].startswith("/private/files/"), msg=line)
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


T2_KEYS = {
	"machine",
	"machine_two_door",
	"machine_locked",
	"machine_connected",
	"program",
	"sets",
	"set_no_t1",
	"set_redo",
	"chemical_lot_ok",
	"chemical_lot_expired",
	"batch_running",
}


class TestT2DemoData(FrappeTestCase):
	def test_ensure_t2_demo_idempotent(self):
		from frappe.utils import getdate, today

		from tracecore.reprocessing import washing

		first = devdata.ensure_t2_demo()
		second = devdata.ensure_t2_demo()
		self.assertEqual(first, second)
		self.assertEqual(set(first), T2_KEYS)
		self.assertEqual(len(set(first["sets"])), 3)
		for set_id in first["sets"]:
			self.assertEqual(_gates(set_id)["T1"], "Pass")
			self.assertEqual(_gates(set_id)["T2"], "Pending")
			washing.admit_set(set_id, first["machine"])  # nạp được, không ném
		self.assertNotEqual(_gates(first["set_no_t1"])["T1"], "Pass")
		self.assertIn(first["set_redo"], [row["set_id"] for row in washing.redo_queue()])
		self.assertEqual(frappe.db.get_value("Equipment", first["machine_locked"], "status"), "Retired")
		self.assertEqual(frappe.db.get_value("Equipment", first["machine_connected"], "is_connected"), 1)
		self.assertEqual(frappe.db.get_value("Equipment", first["machine"], "has_printout"), 1)
		self.assertTrue(frappe.db.get_value("Equipment", first["machine_two_door"], "zone_out"))
		self.assertEqual(
			frappe.db.get_value("Process Program", first["program"], "equipment"), first["machine"]
		)
		self.assertIsNone(washing.check_chemical_lot("DEMO-T2-ENZ", first["chemical_lot_ok"]))
		expiry = frappe.db.get_value("Batch", first["chemical_lot_expired"], "expiry_date")
		self.assertLess(getdate(expiry), getdate(today()))
		batch = frappe.get_doc("Wash Batch", first["batch_running"])
		self.assertEqual((batch.status, batch.equipment), ("Running", first["machine_two_door"]))

	def test_t2_demo_refused_outside_developer_or_test_site(self):
		original = (frappe.conf.get("developer_mode"), frappe.conf.get("allow_tests"))
		frappe.flags.in_test = False
		frappe.conf.developer_mode, frappe.conf.allow_tests = 0, 0
		try:
			with self.assertRaises(frappe.ValidationError):
				devdata.ensure_t2_demo()
		finally:
			frappe.conf.developer_mode, frappe.conf.allow_tests = original
			frappe.flags.in_test = True


T5_KEYS = {
	"machine",
	"machine_plasma",
	"machine_locked",
	"program",
	"program_plasma",
	"packs",
	"pack_plasma",
	"pack_no_t4",
	"load_running",
	"machine_running",
}


class TestT5DemoData(FrappeTestCase):
	def test_ensure_t5_demo_idempotent(self):
		from tracecore.reprocessing import sterilizing

		first = devdata.ensure_t5_demo()
		second = devdata.ensure_t5_demo()
		self.assertEqual(first, second)
		self.assertEqual(set(first), T5_KEYS)
		self.assertEqual(len(set(first["packs"])), 3)
		for cycle_id in first["packs"]:
			result = sterilizing.admit_pack(
				cycle_id, first["machine"], first["program"]
			)  # nạp được, không ném
			self.assertEqual(result["method"], "Steam")
		with self.assertRaises(BlockedError) as plasma:
			sterilizing.admit_pack(first["pack_plasma"], first["machine"], first["program"])
		self.assertEqual(plasma.exception.block.code, "PACK_INCOMPATIBLE")
		self.assertTrue(
			sterilizing.admit_pack(first["pack_plasma"], first["machine_plasma"], first["program_plasma"])
		)
		with self.assertRaises(BlockedError) as no_t4:
			sterilizing.admit_pack(first["pack_no_t4"], first["machine"], first["program"])
		self.assertEqual(no_t4.exception.block.code, "GATE_PREV_NOT_PASSED")
		self.assertEqual(frappe.db.get_value("Equipment", first["machine_locked"], "status"), "Retired")
		self.assertEqual(frappe.db.get_value("Equipment", first["machine"], "has_printout"), 1)
		self.assertEqual(sterilizing.capacity_of(first["machine"]), 12)
		self.assertEqual(
			frappe.db.get_value("Process Program", first["program"], "equipment"), first["machine"]
		)
		load = frappe.get_doc("Sterilization Load", first["load_running"])
		self.assertEqual(
			(load.status, load.equipment, load.docstatus), ("Running", first["machine_running"], 0)
		)
		# máy dùng cho test nạp không có mẻ đang chạy (A-22)
		self.assertIsNone(sterilizing.check_equipment_ready(first["machine"]))

	def test_t5_demo_refused_outside_developer_or_test_site(self):
		original = (frappe.conf.get("developer_mode"), frappe.conf.get("allow_tests"))
		frappe.flags.in_test = False
		frappe.conf.developer_mode, frappe.conf.allow_tests = 0, 0
		try:
			with self.assertRaises(frappe.ValidationError):
				devdata.ensure_t5_demo()
		finally:
			frappe.conf.developer_mode, frappe.conf.allow_tests = original
			frappe.flags.in_test = True


T6_KEYS = {"location", "location_2", "pack_released", "pack_not_released", "pack_stored", "pack_expiring"}


class TestT6DemoData(FrappeTestCase):
	def _pack(self, name):
		return frappe.db.get_value("Pack", name, ["status", "location", "expiry", "docstatus"], as_dict=True)

	def test_ensure_t6_demo_idempotent(self):
		from frappe.utils import add_days, getdate, today

		first = devdata.ensure_t6_demo()
		second = devdata.ensure_t6_demo()
		self.assertEqual(first, second)
		self.assertEqual(set(first), T6_KEYS)
		for key in ("location", "location_2"):
			self.assertTrue(first[key].startswith("KE-"), msg=first[key])
			self.assertEqual(
				frappe.db.get_value("Sterile Location", first[key], ["zone_station", "is_active"]),
				("TR-006", 1),
			)
		released = self._pack(first["pack_released"])
		self.assertEqual((released.status, released.location, released.docstatus), ("Released", None, 1))
		self.assertGreater(getdate(released.expiry), getdate(add_days(today(), 7)))
		self.assertEqual(self._pack(first["pack_not_released"]).status, "Packed")
		stored = self._pack(first["pack_stored"])
		self.assertEqual((stored.status, stored.location), ("In Sterile Stock", first["location"]))
		self.assertGreater(getdate(stored.expiry), getdate(add_days(today(), 7)))
		expiring = self._pack(first["pack_expiring"])
		self.assertEqual((expiring.status, expiring.location), ("In Sterile Stock", first["location_2"]))
		self.assertLessEqual(getdate(expiring.expiry), getdate(add_days(today(), 7)))
		self.assertGreaterEqual(getdate(expiring.expiry), getdate(today()))

	def test_t6_demo_packs_follow_putaway_rules_and_consumed_ones_are_replaced(self):
		from tracecore.reprocessing import storage

		first = devdata.ensure_t6_demo()
		with self.assertRaises(BlockedError) as raised:
			storage.putaway(first["pack_not_released"], first["location"], "TR-006")
		self.assertEqual(raised.exception.block.code, "PACK_NOT_RELEASED")
		storage.putaway(first["pack_released"], first["location"], "TR-006")
		storage.mark_damaged(first["pack_stored"], "demo torn", "TR-006")
		second = devdata.ensure_t6_demo()
		self.assertNotEqual(second["pack_released"], first["pack_released"])
		self.assertNotEqual(second["pack_stored"], first["pack_stored"])
		self.assertEqual(second["pack_not_released"], first["pack_not_released"])
		self.assertEqual(second["pack_expiring"], first["pack_expiring"])

	def test_t6_demo_refused_outside_developer_or_test_site(self):
		original = (frappe.conf.get("developer_mode"), frappe.conf.get("allow_tests"))
		frappe.flags.in_test = False
		frappe.conf.developer_mode, frappe.conf.allow_tests = 0, 0
		try:
			with self.assertRaises(frappe.ValidationError):
				devdata.ensure_t6_demo()
		finally:
			frappe.conf.developer_mode, frappe.conf.allow_tests = original
			frappe.flags.in_test = True


T7_KEYS = {
	"dept",
	"dept_name",
	"dept_tight",
	"dept_tight_name",
	"dept_open",
	"dept_open_name",
	"dept_other",
	"dept_other_name",
	"recipient_card",
	"stranger_card",
	"approver_card",
	"approver_pin",
	"pack_1",
	"pack_2",
	"pack_3",
	"pack_4",
	"pack_5",
	"pack_6",
	"pack_fefo_near",
	"pack_fefo_far",
	"pack_released",
}


class TestT7DemoData(FrappeTestCase):
	def test_t7_station_user_bootstrap_has_r06_r02_approver_and_otp(self):
		import secrets

		from frappe.twofactor import get_default
		from frappe.utils.password import decrypt

		frappe.get_doc("User", "Administrator").remove_roles("TC R10")
		users = devdata.ensure_t7_e2e_user("TR-007", secrets.token_urlsafe(24))
		self.assertEqual(set(users), {"t7_user", "t7_otp_secret", "t7_approver_user"})
		self.assertIn("TC R06", frappe.get_roles(users["t7_user"]))
		self.assertIn("TC R02", frappe.get_roles(users["t7_approver_user"]))
		self.assertEqual(decrypt(get_default(users["t7_user"] + "_otpsecret")), users["t7_otp_secret"])

	def test_ensure_t7_demo_idempotent_and_ready_to_issue(self):
		from frappe.utils import getdate, today

		approver = devdata.ensure_t7_e2e_user("TR-007", "Tc-demo-Pass-1!")["t7_approver_user"]
		first = devdata.ensure_t7_demo(approver_user=approver)
		second = devdata.ensure_t7_demo(approver_user=approver)
		self.assertEqual(set(first), T7_KEYS)
		self.assertEqual(first, second)
		packs = [first[f"pack_{i}"] for i in range(1, 7)] + [first["pack_fefo_near"], first["pack_fefo_far"]]
		expiries = [getdate(frappe.db.get_value("Pack", name, "expiry")) for name in packs]
		self.assertEqual(expiries, sorted(expiries))  # hạn sớm trước: FEFO không đòi ghi chú
		self.assertLess(expiries[-2], expiries[-1])
		for name in packs:
			self.assertEqual(frappe.db.get_value("Pack", name, "status"), "In Sterile Stock")
			self.assertGreaterEqual(getdate(frappe.db.get_value("Pack", name, "expiry")), getdate(today()))
		self.assertEqual(frappe.db.get_value("Pack", first["pack_released"], "status"), "Released")
		self.assertEqual(
			frappe.db.get_value(
				"Par Level", {"department": first["dept_tight"], "par_kind": "Department Stock"}, "max_qty"
			),
			1,
		)
		self.assertFalse(
			frappe.db.exists("Par Level", {"department": first["dept_open"], "par_kind": "Department Stock"})
		)

	def test_t7_demo_recipient_card_is_issuable_and_consumed_pack_is_replaced(self):
		from tracecore.reprocessing import issuing

		approver = devdata.ensure_t7_e2e_user("TR-007", "Tc-demo-Pass-1!")["t7_approver_user"]
		first = devdata.ensure_t7_demo(approver_user=approver)
		note = issuing.create(first["dept"], "TR-007")["issue_note"]
		issuing.add_pack(note, first["pack_1"], "TR-007")
		issuing.sign(note, first["recipient_card"], "TR-007")
		issuing.submit(note, "TR-007")
		second = devdata.ensure_t7_demo(approver_user=approver)
		# gói đã cấp rời kho: danh sách hạn sớm trước dồn lên và được bù một gói mới ở cuối
		self.assertEqual(second["pack_1"], first["pack_2"])
		self.assertNotIn(first["pack_1"], [value for key, value in second.items() if key.startswith("pack_")])

	def test_t7_demo_refused_outside_developer_or_test_site(self):
		original = (frappe.conf.get("developer_mode"), frappe.conf.get("allow_tests"))
		frappe.flags.in_test = False
		frappe.conf.developer_mode, frappe.conf.allow_tests = 0, 0
		try:
			with self.assertRaises(frappe.ValidationError):
				devdata.ensure_t7_demo()
		finally:
			frappe.conf.developer_mode, frappe.conf.allow_tests = original
			frappe.flags.in_test = True


T3_KEYS = {"set_full", "set_short", "set_branch", "set_no_wash", "short_instrument"}


class TestT3DemoData(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def test_ensure_t3_demo_idempotent_and_sets_open_at_t3(self):
		from tracecore.reprocessing import assembly

		first = devdata.ensure_t3_demo()
		second = devdata.ensure_t3_demo()
		self.assertEqual(first, second)
		self.assertEqual(set(first), T3_KEYS)
		sets = [first["set_full"], first["set_short"], first["set_branch"]]
		self.assertEqual(len(set(sets)), 3)
		for set_id in sets:
			gates = _gates(set_id)
			self.assertEqual((gates["T1"], gates["T2"], gates["T3"]), ("Pass", "Pass", "Pending"))
			opened = assembly.open_set(set_id, "TR-003")
			self.assertGreaterEqual(len(opened["lines"]), 3)
			self.assertTrue(any(line["thumbnail"] or line["image"] for line in opened["lines"]))
			self.assertTrue(opened["tray_images"])
		with self.assertRaises(BlockedError) as raised:
			assembly.open_set(first["set_no_wash"], "TR-003")
		self.assertEqual(raised.exception.block.code, "GATE_PREV_NOT_PASSED")
		self.assertIn(first["short_instrument"], [line["instrument"] for line in opened["lines"]])

	def test_t3_demo_replaces_a_set_that_was_counted(self):
		from tracecore.core import client_time
		from tracecore.reprocessing import assembly

		first = devdata.ensure_t3_demo()
		name = assembly.open_set(first["set_full"], "TR-003")["assembly"]
		assembly.line(name, "TR-003", client_time.utc_now(), all_ok=True)
		assembly.submit(name, "TR-003", client_time.utc_now())
		second = devdata.ensure_t3_demo()
		ready = {second[key] for key in devdata.T3_READY}
		self.assertNotIn(first["set_full"], ready)  # bộ đã ghi sổ được thay bằng bộ mới
		self.assertLessEqual({first["set_short"], first["set_branch"]}, ready)  # bộ chưa dùng giữ nguyên
		self.assertEqual(second["set_no_wash"], first["set_no_wash"])

	def test_t3_users_bootstrap_has_r04_otp_and_r02(self):
		import secrets

		from frappe.twofactor import get_default
		from frappe.utils.password import decrypt

		def admin_roles():
			return set(frappe.get_all("Has Role", filters={"parent": "Administrator"}, pluck="role"))

		frappe.get_doc("User", "Administrator").remove_roles("TC R10")
		before = admin_roles()
		users = devdata.ensure_t3_e2e_users("TR-003", secrets.token_urlsafe(24))
		self.assertEqual(admin_roles(), before)
		self.assertEqual(set(users), {"t3_user", "t3_otp_secret", "t3_r02_user"})
		self.assertIn("TC R04", frappe.get_roles(users["t3_user"]))
		self.assertIn("TC R02", frappe.get_roles(users["t3_r02_user"]))
		self.assertEqual(decrypt(get_default(users["t3_user"] + "_otpsecret")), users["t3_otp_secret"])

	def test_t3_r02_has_card_competency_and_a_random_working_pin(self):
		from tracecore.core import station_auth

		user = make_user("t3-demo-r02@example.test", ("TC R02",))
		first = devdata.ensure_t3_r02("TR-003", user)
		self.assertEqual(set(first), {"employee", "card_id", "pin"})
		self.assertRegex(first["pin"], r"^\d{6}$")
		self.assertTrue(station_auth.verify_pin(first["employee"], first["pin"]))
		self.addCleanup(station_auth.clear_pin_rate_limit, first["employee"])
		self.assertTrue(
			frappe.db.exists("Station Competency", {"employee": first["employee"], "station": "TR-003"})
		)
		login = station_auth.login(first["card_id"], "TR-003")
		self.assertEqual(login["user"], user)
		self.assertIn("TC R02", login["roles"])

	def test_smoke_station_is_a_clean_zone_station_without_a_step(self):
		name = devdata.ensure_smoke_station("TR-090")
		self.assertEqual(name, devdata.ensure_smoke_station("TR-090"))
		row = frappe.db.get_value(
			"Zone Station", name, ["is_zone", "is_active", "station_step", "zone_type"], as_dict=True
		)
		self.assertEqual((row.is_zone, row.is_active), (0, 1))
		self.assertFalse(row.station_step)
		self.assertEqual(row.zone_type, "Clean")

	def test_t3_demo_refused_outside_developer_or_test_site(self):
		original = (frappe.conf.get("developer_mode"), frappe.conf.get("allow_tests"))
		frappe.flags.in_test = False
		frappe.conf.developer_mode, frappe.conf.allow_tests = 0, 0
		try:
			for fn, args in ((devdata.ensure_t3_demo, ()), (devdata.ensure_smoke_station, ("TR-090",))):
				with self.assertRaises(frappe.ValidationError):
					fn(*args)
		finally:
			frappe.conf.developer_mode, frappe.conf.allow_tests = original
			frappe.flags.in_test = True


T1_KEYS = {
	"department",
	"deliverer_card",
	"deliverer_name",
	"sets",
	"set_new",
	"sets_pda",
	"set_sterile",
	"set_unknown",
}


class TestT1DemoData(FrappeTestCase):
	def _status(self, set_id):
		return frappe.db.get_value("Set Unit", set_id, "status")

	def test_ensure_t1_demo_idempotent(self):
		first = devdata.ensure_t1_demo()
		second = devdata.ensure_t1_demo()
		self.assertEqual(first, second)
		self.assertEqual(set(first), T1_KEYS)
		self.assertEqual(len(first["sets"]), 3)
		self.assertEqual(len(first["sets_pda"]), 2)
		self.assertEqual([self._status(s) for s in first["sets"]], ["Awaiting Receipt"] * 3)
		self.assertEqual([self._status(s) for s in first["sets_pda"]], ["New"] * 2)
		self.assertEqual(self._status(first["set_new"]), "New")
		self.assertEqual(self._status(first["set_sterile"]), "Sterile")

	def test_t1_demo_sets_follow_the_receiving_rules(self):
		demo = devdata.ensure_t1_demo()
		for set_id in (*demo["sets"], demo["set_new"], *demo["sets_pda"]):
			self.assertIsNone(step_gate.check(set_id, "T1"), set_id)
		self.assertEqual(step_gate.check(demo["set_sterile"], "T1").code, "STATUS_INVALID_FOR_STATION")
		self.assertEqual(gs1.parse_scan(demo["set_unknown"])["type"], "set")
		self.assertFalse(frappe.db.exists("Set Unit", demo["set_unknown"]))

	def test_t1_demo_deliverer_card_gives_the_demo_department(self):
		from tracecore.reprocessing import receiving

		demo = devdata.ensure_t1_demo()
		employee = receiving._deliverer_from_card(demo["deliverer_card"])
		self.assertEqual(employee.department, demo["department"])
		self.assertEqual(employee.employee_name, demo["deliverer_name"])

	def test_t1_demo_replaces_consumed_sets(self):
		first = devdata.ensure_t1_demo()
		step_gate.start_cycle(first["sets"][0])
		step_gate.start_cycle(first["set_new"])
		second = devdata.ensure_t1_demo()
		self.assertNotIn(first["sets"][0], second["sets"])
		self.assertTrue(set(first["sets"][1:]) <= set(second["sets"]))
		self.assertNotEqual(second["set_new"], first["set_new"])

	def test_t1_demo_refused_outside_developer_or_test_site(self):
		original = (frappe.conf.get("developer_mode"), frappe.conf.get("allow_tests"))
		frappe.flags.in_test = False
		frappe.conf.developer_mode, frappe.conf.allow_tests = 0, 0
		try:
			with self.assertRaises(frappe.ValidationError):
				devdata.ensure_t1_demo()
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


CODES_KEYS = {"equipment", "equipment_2", "retired", "printer", "printer_port", "label_item"}


class TestCodesDemoData(FrappeTestCase):
	def setUp(self):
		super().setUp()
		allow_local_printers(self)  # máy in demo 127.0.0.1: server chỉ gửi tới khi bật cờ

	def test_ensure_codes_demo_idempotent(self):
		first = devdata.ensure_codes_demo(port=19101)
		printers = frappe.db.count("Printer")
		equipment = frappe.db.count("Equipment")
		second = devdata.ensure_codes_demo(port=19101)
		self.assertEqual(first, second)
		self.assertEqual(set(first), CODES_KEYS)
		self.assertEqual(frappe.db.count("Printer"), printers)
		self.assertEqual(frappe.db.count("Equipment"), equipment)

	def test_codes_demo_printer_is_a_network_printer_on_the_given_port(self):
		demo = devdata.ensure_codes_demo(port=19101)
		printer = frappe.get_doc("Printer", demo["printer"])
		self.assertEqual(
			(printer.station, printer.host, printer.port, printer.is_active, printer.supports_unicode),
			("TR-001", "127.0.0.1", 19101, 1, 0),
		)
		self.assertEqual(demo["printer_port"], 19101)
		self.assertEqual(print_server.printer_address(demo["printer"]), ("127.0.0.1", 19101))
		# đổi cổng: cùng máy in demo, cổng mới (máy in đã bị tắt cũng được bật lại)
		frappe.db.set_value("Printer", demo["printer"], "is_active", 0)
		moved = devdata.ensure_codes_demo(port=19102)
		self.assertEqual(moved["printer"], demo["printer"])
		self.assertEqual(print_server.printer_address(demo["printer"]), ("127.0.0.1", 19102))

	def test_codes_demo_port_defaults_to_environment(self):
		original = os.environ.get("TC_E2E_CODES_PRINTER_PORT")
		os.environ["TC_E2E_CODES_PRINTER_PORT"] = "19103"
		try:
			demo = devdata.ensure_codes_demo()
		finally:
			if original is None:
				os.environ.pop("TC_E2E_CODES_PRINTER_PORT")
			else:
				os.environ["TC_E2E_CODES_PRINTER_PORT"] = original
		self.assertEqual(demo["printer_port"], 19103)
		self.assertEqual(frappe.db.get_value("Printer", demo["printer"], "port"), 19103)

	def test_codes_demo_rejects_invalid_port(self):
		for port in (0, 70000, "abc"):
			with self.subTest(port=port), self.assertRaises(frappe.ValidationError):
				devdata.ensure_codes_demo(port=port)

	def test_codes_demo_objects_are_printable(self):
		demo = devdata.ensure_codes_demo(port=19101)
		equipment = devdata.ensure_equipment_demo()
		self.assertEqual(demo["equipment"], equipment["steam"])
		self.assertEqual(demo["equipment_2"], equipment["steam_copy_target"])
		self.assertEqual(demo["retired"], equipment["retired"])
		for key in ("equipment", "equipment_2"):
			self.assertEqual(frappe.db.get_value("Equipment", demo[key], "status"), "Ready")
			self.assertEqual(frappe.db.get_value("Code Registry", demo[key], "status"), "Active")
		self.assertEqual(frappe.db.get_value("Equipment", demo["retired"], "status"), "Retired")
		self.assertEqual(demo["label_item"], "VT-NHAN-HAP")
		self.assertEqual(frappe.db.get_value("Item", demo["label_item"], "tc_item_group_cssd"), "Label")
		for label_object in ("Equipment", "Roll"):
			self.assertIsNotNone(core_print.active_template(label_object, None), msg=label_object)

	def test_codes_demo_refused_outside_developer_or_test_site(self):
		original = (frappe.conf.get("developer_mode"), frappe.conf.get("allow_tests"))
		frappe.flags.in_test = False
		frappe.conf.developer_mode, frappe.conf.allow_tests = 0, 0
		try:
			with self.assertRaises(frappe.ValidationError):
				devdata.ensure_codes_demo(port=19101)
		finally:
			frappe.conf.developer_mode, frappe.conf.allow_tests = original
			frappe.flags.in_test = True


INSTRUMENT_KEYS = {
	"group",
	"full",
	"no_max",
	"retire",
	"giai",
	"set_type_steam",
	"set_type_plasma",
	"set_type_retire",
	"set_steam",
	"set_plasma",
}


class TestInstrumentDemoData(FrappeTestCase):
	"""Dữ liệu demo e2e Desk SCR-01 (FEAT-014 Task 7): Instrument không xóa được nên dùng lại bản ghi cố định."""

	def test_ensure_instrument_demo_idempotent(self):
		first = devdata.ensure_instrument_demo()
		counts = {doctype: frappe.db.count(doctype) for doctype in ("Instrument", "Set BOM Item", "Set Unit")}
		second = devdata.ensure_instrument_demo()
		self.assertEqual(first, second)
		self.assertEqual(set(first), INSTRUMENT_KEYS)
		self.assertEqual(
			{doctype: frappe.db.count(doctype) for doctype in counts}, counts, msg="gọi lại không tạo thêm"
		)

	def test_instrument_demo_records(self):
		from tracecore.instrument import catalog, thresholds

		demo = devdata.ensure_instrument_demo()
		group = frappe.get_doc("Instrument Group", demo["group"])
		self.assertGreater(group.maint_interval_cycles, 0)
		self.assertTrue(group.maint_type)
		# dụng cụ đủ dữ liệu: ảnh riêng tư + thumbnail, cơ số, giá trị, nhóm, hai phương pháp (hấp + plasma)
		full = frappe.get_doc("Instrument", demo["full"])
		self.assertEqual(full.status, "Active")
		self.assertTrue(full.image.startswith("/private/files/"), msg=full.image)
		self.assertTrue(full.image_thumbnail.startswith("/private/files/"), msg=full.image_thumbnail)
		self.assertGreater(full.max_cycles, 0)
		self.assertEqual(full.max_cycles_status, "Defined")
		self.assertTrue(full.manufacturer and full.model and full.value)
		self.assertEqual(full.instrument_group, demo["group"])
		self.assertEqual({row.method for row in full.compatible_methods}, {"Steam 134", "Plasma"})
		rule = thresholds.effective_rules([full.name])[full.name]
		self.assertEqual((rule["interval"], rule["source"]), (group.maint_interval_cycles, "Group"))
		# trong BOM hiện hành của hai loại bộ demo (hấp, plasma), tương thích với cả hai
		usage = {row["set_type"]: row for row in catalog.bom_usage(full.name)}
		self.assertEqual(set(usage), {demo["set_type_steam"], demo["set_type_plasma"]})
		self.assertTrue(all(row["compatible"] for row in usage.values()))
		self.assertEqual(
			{frappe.db.get_value("Instrument Set Type", key, "method") for key in usage}, {"Steam", "Plasma"}
		)
		# dụng cụ thiếu cơ số: Chưa xác định
		self.assertEqual(frappe.db.get_value("Instrument", demo["no_max"], "max_cycles_status"), "Undefined")
		# dụng cụ để ngừng sử dụng: Đang dùng, trong BOM hiện hành của loại bộ riêng (không đụng BOM T4)
		self.assertEqual(frappe.db.get_value("Instrument", demo["retire"], "status"), "Active")
		self.assertEqual(
			[row["set_type"] for row in catalog.bom_usage(demo["retire"])], [demo["set_type_retire"]]
		)
		# dụng cụ để cấp mã GIAI: chưa có mã
		self.assertFalse(frappe.db.get_value("Instrument", demo["giai"], "giai_code"))
		# bộ demo mở được ở T4 (qua T1-T3, chưa có Cycle ID)
		for key, set_type in (("set_steam", "set_type_steam"), ("set_plasma", "set_type_plasma")):
			self.assertEqual(frappe.db.get_value("Set Unit", demo[key], "set_type"), demo[set_type])
			self.assertEqual(_gates(demo[key])["T3"], "Pass")
		context = packing.get_context(demo["set_steam"], "TR-004")
		line = next(row for row in context["bom"] if row["instrument"] == demo["full"])
		self.assertEqual(line["thumbnail"], full.image_thumbnail)

	def test_consumed_retire_and_giai_candidates_are_replaced(self):
		from tracecore.instrument import catalog

		first = devdata.ensure_instrument_demo()
		catalog.retire(first["retire"], "E2E", confirm=True)
		frappe.db.set_value(
			"Instrument", first["giai"], "giai_code", "9520000I-99999999", update_modified=False
		)
		second = devdata.ensure_instrument_demo()
		self.assertNotEqual(second["retire"], first["retire"])
		self.assertNotEqual(second["giai"], first["giai"])
		self.assertEqual(frappe.db.get_value("Instrument", second["retire"], "status"), "Active")
		self.assertIn(
			second["set_type_retire"], [row["set_type"] for row in catalog.bom_usage(second["retire"])]
		)
		self.assertFalse(frappe.db.get_value("Instrument", second["giai"], "giai_code"))
		self.assertEqual(
			{k: v for k, v in second.items() if k not in ("retire", "giai")},
			{k: v for k, v in first.items() if k not in ("retire", "giai")},
		)

	def test_ensure_bom_line_with_scheduled_version(self):
		# review Task 2 (6): loại bộ có phiên bản đã lên lịch → thêm dòng không bị BOM_EFFECTIVE_DATE_INVALID
		from frappe.utils import add_days, getdate, nowdate

		from tracecore.instrument import bom_versions
		from tracecore.tests import factories

		set_type = factories.make_set_type("DDSCH", bom=[("DD-SCH-1", 1)])
		tomorrow = getdate(add_days(nowdate(), 1))
		factories.make_bom(set_type, [("DD-SCH-2", 1)], version=2, effective_from=tomorrow)
		factories.make_instrument("DD-SCH-3", methods=("Steam 134",))

		devdata._ensure_bom_line(set_type.name, "DD-SCH-3")
		latest = bom_versions.versions(set_type.name)[0]
		self.assertEqual((latest["bom_version"], latest["effective_from"]), (3, tomorrow))
		self.assertIn(
			"DD-SCH-3",
			frappe.get_all(
				"Set BOM Item", filters={"set_type": set_type.name, "bom_version": 3}, pluck="instrument"
			),
		)
		devdata._ensure_bom_line(set_type.name, "DD-SCH-3")  # đã có ở phiên bản mới nhất: không tạo thêm
		self.assertEqual(bom_versions.versions(set_type.name)[0]["bom_version"], 3)

	def test_instrument_demo_refused_outside_developer_or_test_site(self):
		original = (frappe.conf.get("developer_mode"), frappe.conf.get("allow_tests"))
		frappe.flags.in_test = False
		frappe.conf.developer_mode, frappe.conf.allow_tests = 0, 0
		try:
			with self.assertRaises(frappe.ValidationError):
				devdata.ensure_instrument_demo()
		finally:
			frappe.conf.developer_mode, frappe.conf.allow_tests = original
			frappe.flags.in_test = True


INVENTORY_KEYS = {"company", "warehouse", "supplier", "ci", "bi", "pk", "ch"}


class TestInventoryDemoData(FrappeTestCase):
	"""Dữ liệu demo e2e Desk nhập kho SCR-24 (FEAT-041 Task 6): Item không xóa được nên dùng lại mã cố định."""

	def test_ensure_inventory_demo_idempotent(self):
		first = devdata.ensure_inventory_demo()
		counts = {
			doctype: frappe.db.count(doctype)
			for doctype in ("Item", "Item Reorder", "Supplier", "Warehouse", "Company")
		}
		second = devdata.ensure_inventory_demo()
		self.assertEqual(first, second)
		self.assertEqual(set(first), INVENTORY_KEYS)
		self.assertEqual(
			{doctype: frappe.db.count(doctype) for doctype in counts}, counts, msg="gọi lại không tạo thêm"
		)

	def test_inventory_demo_items_follow_group_rules(self):
		from tracecore.inventory import items

		demo = devdata.ensure_inventory_demo()
		self.assertEqual(frappe.db.get_value("Warehouse", demo["warehouse"], "company"), demo["company"])
		self.assertFalse(frappe.db.get_value("Warehouse", demo["warehouse"], "is_group"))
		groups = {
			"ci": "Chemical Indicator",
			"bi": "Biological Indicator",
			"pk": "Packaging",
			"ch": "Chemical",
		}
		for key, group in groups.items():
			item = frappe.get_doc("Item", demo[key])
			self.assertEqual(item.tc_item_group_cssd, group)
			self.assertTrue(item.has_batch_no)
			self.assertEqual(item.valuation_method, items.VALUATION_METHOD)
			self.assertEqual(item.has_expiry_date, 1 if group in items.EXPIRY_REQUIRED_GROUPS else 0, msg=key)
			self.assertEqual(
				[(row.warehouse, row.warehouse_reorder_level) for row in item.reorder_levels],
				[(demo["warehouse"], devdata.INV_MIN_QTY)],
			)
		self.assertEqual(frappe.db.get_value("Item", demo["ci"], "tc_ci_class"), "5")

	def test_inventory_demo_refused_outside_developer_or_test_site(self):
		original = (frappe.conf.get("developer_mode"), frappe.conf.get("allow_tests"))
		frappe.flags.in_test = False
		frappe.conf.developer_mode, frappe.conf.allow_tests = 0, 0
		try:
			with self.assertRaises(frappe.ValidationError):
				devdata.ensure_inventory_demo()
		finally:
			frappe.conf.developer_mode, frappe.conf.allow_tests = original
			frappe.flags.in_test = True


SET_TYPE_DEMO_KEYS = {
	"set_type",
	"set_type_inflight",
	"set_type_edit",
	"effective_version",
	"scheduled_version",
	"set_inflight",
	"inflight_version",
	"inflight_effective",
	"pack_short",
	"pack_long",
	"pack_none",
	"pack_r10",
	"steam_1",
	"steam_2",
	"steam_3",
	"plasma",
	"retired",
	"department",
}


class TestSetTypeDemoData(FrappeTestCase):
	"""Dữ liệu demo e2e Desk SCR-02 (FEAT-015 Task 9): loại bộ/dòng BOM không xóa được nên dùng lại bản ghi cố định."""

	def test_ensure_set_type_demo_idempotent(self):
		first = devdata.ensure_set_type_demo()
		counts = {
			doctype: frappe.db.count(doctype)
			for doctype in ("Instrument", "Instrument Set Type", "Set BOM Item", "Set Unit", "File")
		}
		second = devdata.ensure_set_type_demo()
		self.assertEqual(first, second)
		self.assertEqual(set(first), SET_TYPE_DEMO_KEYS)
		self.assertEqual(
			{doctype: frappe.db.count(doctype) for doctype in counts}, counts, msg="gọi lại không tạo thêm"
		)

	def test_set_type_demo_records(self):
		from frappe.utils import add_days, getdate, nowdate

		from tracecore.instrument import bom_versions, shelf_life

		demo = devdata.ensure_set_type_demo()
		tomorrow = getdate(add_days(nowdate(), 1))
		# loại gói: hai loại có hạn lưu được gợi ý, loại hạn 0 không
		usable = {row["item"] for row in shelf_life.usable_pack_types()}
		self.assertTrue({demo["pack_short"], demo["pack_long"], demo["pack_r10"]} <= usable)
		self.assertNotIn(demo["pack_none"], usable)
		self.assertFalse(frappe.db.get_value("Item", demo["pack_none"], "tc_shelf_life_days"))
		# loại bộ hấp: phiên bản hiệu lực + phiên bản đã lên lịch ngày mai, ba ảnh bộ đã xếp có thumbnail riêng tư
		statuses = {v["bom_version"]: v for v in bom_versions.versions(demo["set_type"])}
		self.assertEqual(statuses[demo["effective_version"]]["status"], "Effective")
		self.assertEqual(statuses[demo["scheduled_version"]]["status"], "Scheduled")
		self.assertEqual(statuses[demo["scheduled_version"]]["effective_from"], tomorrow)
		row = frappe.get_doc("Instrument Set Type", demo["set_type"])
		self.assertEqual(row.method, "Steam")
		for field in ("tray_image", "tray_image_2", "tray_image_3"):
			self.assertTrue(row.get(field).startswith("/private/files/"), msg=field)
			self.assertTrue(row.get(field.replace("image", "thumbnail")), msg=field)
		# dụng cụ chỉ Plasma (lỗi tương thích ở loại bộ hấp) và dụng cụ đã Ngừng sử dụng
		methods = {r.method for r in frappe.get_doc("Instrument", demo["plasma"]).compatible_methods}
		self.assertEqual(methods, {"Plasma"})
		self.assertEqual(frappe.db.get_value("Instrument", demo["retired"], "status"), "Retired")
		for key in ("steam_1", "steam_2", "steam_3"):
			self.assertEqual(frappe.db.get_value("Instrument", demo[key], "status"), "Active")
		# bộ giữa chu trình: ghim phiên bản cũ hơn phiên bản hiệu lực, đã qua T1-T3, chưa có Cycle ID
		self.assertLess(demo["inflight_version"], demo["inflight_effective"])
		self.assertEqual(
			bom_versions.effective_version(demo["set_type_inflight"]), demo["inflight_effective"]
		)
		unit = frappe.db.get_value(
			"Set Unit",
			demo["set_inflight"],
			["set_type", "cycle_bom_version", "status", "active_cycle_id"],
			as_dict=True,
		)
		self.assertEqual(
			(unit.set_type, unit.cycle_bom_version, unit.status, unit.active_cycle_id),
			(demo["set_type_inflight"], demo["inflight_version"], "Processing", None),
		)
		self.assertEqual(_gates(demo["set_inflight"])["T3"], "Pass")
		context = packing.get_context(demo["set_inflight"], "TR-004")
		self.assertEqual(context["bom_version"], demo["inflight_version"])
		# loại bộ để sửa BOM: có phiên bản hiệu lực, không ghi đè hạn lưu
		edit = frappe.db.get_value(
			"Instrument Set Type",
			demo["set_type_edit"],
			["shelf_life_days", "default_pack_type"],
			as_dict=True,
		)
		self.assertEqual((edit.shelf_life_days, edit.default_pack_type), (0, demo["pack_long"]))
		self.assertTrue(bom_versions.effective_version(demo["set_type_edit"]))

	def test_set_type_demo_recreates_consumed_inflight_set_and_scheduled_version(self):
		from frappe.utils import add_days, nowdate

		from tracecore.instrument import bom_versions

		first = devdata.ensure_set_type_demo()
		# bộ giữa chu trình đã được e2e đóng gói: bộ mới ghim phiên bản hiệu lực rồi có phiên bản mới hơn
		frappe.db.set_value("Set Unit", first["set_inflight"], "active_cycle_id", "CY-DEMO-USED")
		second = devdata.ensure_set_type_demo()
		self.assertNotEqual(second["set_inflight"], first["set_inflight"])
		self.assertLess(second["inflight_version"], second["inflight_effective"])
		# ngày sau: phiên bản đã lên lịch thành hiệu lực → lần gọi sau lên lịch phiên bản mới cho ngày mai
		later = add_days(nowdate(), 2)
		with _clock_on(later):
			third = devdata.ensure_set_type_demo()
		self.assertGreater(third["scheduled_version"], second["scheduled_version"])
		statuses = {v["bom_version"]: v["status"] for v in bom_versions.versions(third["set_type"])}
		self.assertEqual(statuses[third["scheduled_version"]], "Scheduled")

	def test_set_type_demo_refused_outside_developer_or_test_site(self):
		original = (frappe.conf.get("developer_mode"), frappe.conf.get("allow_tests"))
		frappe.flags.in_test = False
		frappe.conf.developer_mode, frappe.conf.allow_tests = 0, 0
		try:
			with self.assertRaises(frappe.ValidationError):
				devdata.ensure_set_type_demo()
		finally:
			frappe.conf.developer_mode, frappe.conf.allow_tests = original
			frappe.flags.in_test = True


def _clock_on(day):
	"""Đồng hồ hệ thống đứng ở 10:00 ngày `day` (giờ hệ thống) cho mọi ``nowdate``/``now_datetime`` của Frappe."""
	from datetime import datetime, time
	from unittest.mock import patch

	from frappe.utils import data, getdate

	instant = datetime.combine(getdate(day), time(10, 0))
	return patch.object(data, "convert_utc_to_system_timezone", side_effect=lambda _now: instant)


class TestDemoMachinesDailyTest(FrappeTestCase):
	"""FEAT-040 khóa máy chưa có test hằng ngày Đạt: máy demo T2/T5 tạo từ hôm trước vẫn dùng được hôm nay."""

	def assert_tested_today(self, machines):
		from frappe.utils import today

		from tracecore.equipment import daily_test

		for name in machines:
			kind = frappe.db.get_value("Equipment", name, "equipment_type")
			done = set(
				frappe.get_all(
					"Daily Test",
					filters={"equipment": name, "test_date": today(), "result": "Pass"},
					pluck="test_type",
				)
			)
			self.assertLessEqual(set(daily_test.required_tests(kind)), done, msg=name)

	def age_daily_tests(self, machines):
		from frappe.utils import add_days, today

		for name in machines:
			frappe.db.sql(
				"update `tabDaily Test` set test_date = %s where equipment = %s",
				(add_days(today(), -1), name),
			)

	def test_t5_machines_get_todays_daily_tests(self):
		demo = devdata.ensure_t5_demo()
		machines = (demo["machine"], demo["machine_plasma"], demo["machine_running"])
		self.age_daily_tests(machines)
		devdata.ensure_t5_demo()
		self.assert_tested_today(machines)

	def test_t2_machines_get_todays_daily_tests(self):
		demo = devdata.ensure_t2_demo()
		machines = (demo["machine"], demo["machine_two_door"])
		self.age_daily_tests(machines)
		devdata.ensure_t2_demo()
		self.assert_tested_today(machines)

	def test_t5_machine_left_with_running_load_is_replaced(self):
		"""Lượt e2e trước để lại mẻ đang chạy trên máy demo: lần chuẩn bị sau trả máy trống để nạp (A-22)."""
		from tracecore.core import client_time
		from tracecore.reprocessing import sterilizing

		demo = devdata.ensure_t5_demo()
		sterilizing.complete(
			demo["machine"],
			demo["program"],
			[demo["packs"][0]],
			devdata.T5_STATION,
			client_time.utc_now(),
			devdata._t2_operator(),
		)
		again = devdata.ensure_t5_demo()
		for key in ("machine", "machine_plasma"):
			self.assertFalse(
				frappe.db.exists(
					"Sterilization Load", {"equipment": again[key], "status": "Running", "docstatus": 0}
				),
				msg=key,
			)
		self.assertEqual(devdata.ensure_t5_demo(), again)  # vẫn idempotent khi máy trống
