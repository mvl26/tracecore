import os

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import code_registry, gs1, print_server, step_gate
from tracecore.core import print as core_print
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import packing
from tracecore.setup import devdata
from tracecore.tests.utils import allow_local_printers


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
