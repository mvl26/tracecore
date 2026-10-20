import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import code_registry, gs1, step_gate
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import packing
from tracecore.setup import devdata


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
		self.assertEqual(len({first["set_steam"], first["set_plasma"], first["set_gate_fail"]}), 3)

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
		# một nhắc tra dầu đến hạn ở bộ hấp, bộ plasma không có nhắc
		self.assertEqual(
			[(row["maint_type"], row["state"]) for row in steam["maintenance"]], [("Lubrication", "due")]
		)
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
