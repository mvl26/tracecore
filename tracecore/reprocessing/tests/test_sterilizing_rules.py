from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import gs1, step_gate
from tracecore.core.errors import Block, BlockedError
from tracecore.reprocessing import sterilizing
from tracecore.tests.factories import (
	make_equipment,
	make_load,
	make_load_ready_pack,
	make_pack_type,
	make_sterilize_program,
	make_sterilizer,
	make_wash_machine,
)
from tracecore.tests.utils import bru

test_ignore = ["Employee", "Item", "Batch", "User"]


class TestSterilizingRules(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.machine = make_sterilizer()
		self.program = make_sterilize_program(self.machine.name)

	def admit(self, pack, queued=None, machine=None, program=None):
		return sterilizing.admit_pack(
			pack.name if hasattr(pack, "name") else pack,
			(machine or self.machine).name,
			(program or self.program).name,
			queued or [],
		)

	def blocked(self, call, code):
		with self.assertRaises(BlockedError) as caught:
			call()
		self.assertEqual(caught.exception.block.code, code)
		return caught.exception.block

	# --- máy -----------------------------------------------------------------------------------------

	@bru("BRU-REP-016")
	def test_scan_machine_returns_programs_of_that_machine_only(self):
		other = make_sterilizer()
		make_sterilize_program(other.name)
		inactive = make_sterilize_program(self.machine.name, is_active=0)
		result = sterilizing.scan_machine(self.machine.name)
		self.assertEqual(result["equipment"]["name"], self.machine.name)
		self.assertEqual(result["equipment"]["method"], "Steam")
		self.assertEqual(
			[p["program_code"] for p in result["programs"]],
			[self.program.name],
			msg=f"{inactive.name} đã ngừng dùng",
		)
		self.assertEqual(result["programs"][0]["indicators"], ["chemical_class_5", "bowie_dick"])

	def test_scan_machine_adds_biological_indicator_and_schema(self):
		program = make_sterilize_program(
			self.machine.name,
			requires_bi=1,
			parameters=[{"parameter_name": "Temperature", "unit": "°C", "min_value": 132, "required": 1}],
		)
		by_code = {p["program_code"]: p for p in sterilizing.scan_machine(self.machine.name)["programs"]}
		self.assertIn("biological", by_code[program.name]["indicators"])
		self.assertEqual(by_code[program.name]["parameters"][0]["parameter_name"], "Temperature")
		plasma = make_sterilizer("Plasma Sterilizer")
		make_sterilize_program(plasma.name)
		result = sterilizing.scan_machine(plasma.name)
		self.assertEqual(result["equipment"]["method"], "Plasma")
		self.assertEqual(result["programs"][0]["indicators"], ["chemical_plasma"])

	def test_scan_machine_rejects_washer_and_non_equipment(self):
		washer = make_wash_machine()
		self.blocked(lambda: sterilizing.scan_machine(washer.name), "EQUIPMENT_NOT_STERILIZER")
		self.blocked(lambda: sterilizing.scan_machine("LR-261023-01"), "SCAN_INVALID")
		self.blocked(lambda: sterilizing.scan_machine("TB-9999"), "EQUIPMENT_NOT_FOUND")

	@bru("BRU-EQP-001")
	def test_check_equipment_ready_status_and_hook(self):
		self.assertIsNone(sterilizing.check_equipment_ready(self.machine.name))
		retired = make_sterilizer()
		frappe.db.set_value("Equipment", retired.name, "status", "Repair")
		self.assertEqual(sterilizing.check_equipment_ready(retired.name).code, "EQUIPMENT_NOT_READY")
		daily_test = Block("DAILY_TEST_MISSING", "t", "r", "a")
		with patch("tracecore.reprocessing.sterilizing.extension.run", return_value=[daily_test]):
			self.assertIs(sterilizing.check_equipment_ready(self.machine.name), daily_test)

	@bru("BRU-EQP-002")
	def test_not_ready_machine_is_refused_when_scanned(self):
		frappe.db.set_value("Equipment", self.machine.name, "status", "Locked")
		block = self.blocked(lambda: sterilizing.scan_machine(self.machine.name), "EQUIPMENT_NOT_READY")
		self.assertEqual(block.http_status, 423)

	def test_program_must_belong_to_machine(self):
		other = make_sterilize_program(make_sterilizer().name)
		pack = make_load_ready_pack()
		self.blocked(lambda: self.admit(pack, program=other), "PROGRAM_INVALID")

	def test_capacity_of_reads_first_integer(self):
		for text, expected in (
			("3 gói", 3),
			("12", 12),
			("600 STU", 600),
			("", None),
			("STU", None),
			("0", None),
		):
			machine = make_sterilizer(capacity=text)
			self.assertEqual(sterilizing.capacity_of(machine.name), expected, msg=text)

	# --- nhận gói ------------------------------------------------------------------------------------

	def test_admit_accepts_packed_pack_with_t4_pass(self):
		pack = make_load_ready_pack()
		result = self.admit(pack)
		self.assertEqual(result["cycle_id"], pack.name)
		self.assertEqual(result["set_id"], pack.set_unit)
		self.assertEqual(result["method"], "Steam")
		self.assertFalse(result["duplicate"])
		self.assertEqual(result["count"], 1)
		self.assertIsNone(result["capacity"])

	def test_admit_returns_gate_panel_data(self):
		result = self.admit(make_load_ready_pack())
		self.assertEqual([g["step"] for g in result["gates"]], list(step_gate.STEPS))
		self.assertEqual(
			{g["step"]: g["result"] for g in result["gates"]},
			{"T1": "Pass", "T2": "Pass", "T3": "Pass", "T4": "Pass", "T5": "Pending"},
		)

	@bru("BRU-FLOW-004")
	def test_admit_rejects_pack_without_t4_pass(self):
		pack = make_load_ready_pack(passed=("T1", "T2", "T3"))
		block = self.blocked(lambda: self.admit(pack), "GATE_PREV_NOT_PASSED")
		self.assertEqual(block.redo_step, "T4")

	@bru("BRU-REP-004")
	def test_admit_rejects_method_mismatch(self):
		plasma_pack = make_load_ready_pack(method="Plasma")
		block = self.blocked(lambda: self.admit(plasma_pack), "PACK_INCOMPATIBLE")
		self.assertEqual(block.http_status, 422)
		plasma = make_sterilizer("Plasma Sterilizer")
		plasma_program = make_sterilize_program(plasma.name)
		self.assertTrue(self.admit(plasma_pack, machine=plasma, program=plasma_program))
		steam_pack = make_load_ready_pack(method="Steam")
		self.blocked(
			lambda: self.admit(steam_pack, machine=plasma, program=plasma_program), "PACK_INCOMPATIBLE"
		)

	@bru("BRU-REP-004")
	def test_admit_rejects_pack_type_not_in_program(self):
		accepted = make_pack_type("Giấy crepe")
		other = make_pack_type("Túi hàn")
		program = make_sterilize_program(self.machine.name, pack_types=[accepted])
		self.assertTrue(self.admit(make_load_ready_pack(pack_type=accepted), program=program))
		self.blocked(
			lambda: self.admit(make_load_ready_pack(pack_type=other), program=program), "PACK_INCOMPATIBLE"
		)
		# chương trình không khai loại gói: chỉ xét phương pháp
		self.assertTrue(self.admit(make_load_ready_pack(pack_type=other)))

	def test_admit_rejects_pack_in_other_load(self):
		pack = make_load_ready_pack()
		busy = make_sterilizer()  # mẻ ở máy khác: máy này còn mẻ Running thì không nạp được (A-22)
		load = make_load(busy, make_sterilize_program(busy.name), [pack])
		block = self.blocked(lambda: self.admit(pack), "PACK_IN_OTHER_LOAD")
		self.assertIn(load.name, block.reason)

	@bru("BRU-FLOW-002")
	def test_admit_rejects_void_or_stale_pack(self):
		void = make_load_ready_pack(status="Void", void_reason="Torn")
		self.blocked(lambda: self.admit(void), "PACK_NOT_LOADABLE")
		stale = make_load_ready_pack()
		step_gate.release_cycle(stale.set_unit)  # gói không còn là Cycle ID hiện hành của bộ
		self.blocked(lambda: self.admit(stale), "PACK_NOT_LOADABLE")

	def test_admit_rejects_expired_pack(self):
		pack = make_load_ready_pack(expiry_days=-1)
		self.blocked(lambda: self.admit(pack), "PACK_EXPIRED")
		self.assertTrue(self.admit(make_load_ready_pack(expiry_days=0)))  # hết hạn đúng hôm nay vẫn nạp được

	def test_admit_rejects_unknown_pack_and_non_pack_code(self):
		self.blocked(lambda: self.admit("CY-991231-0001"), "PACK_NOT_FOUND")
		self.blocked(lambda: self.admit("LR-261023-01"), "SCAN_INVALID")
		self.blocked(lambda: self.admit("TB-0001"), "SCAN_INVALID")

	def test_admit_duplicate_scan_is_not_an_error(self):
		pack = make_load_ready_pack()
		for raw in (pack.name, f"]d2{pack.name}\r\n", f" {pack.name}\t"):
			result = self.admit(raw, queued=[pack.name])
			self.assertTrue(result["duplicate"], msg=repr(raw))
			self.assertEqual(result["count"], 1)

	def test_admit_accepts_gs1_payload_of_the_pack(self):
		pack = make_load_ready_pack()
		payload = frappe.db.get_value("Pack", pack.name, "barcode_payload")
		if payload and gs1.parse_scan(payload)["type"] == "pack":
			self.assertEqual(self.admit(payload)["cycle_id"], pack.name)

	@bru("BRU-REP-004")
	def test_admit_capacity(self):
		machine = make_sterilizer(capacity="2 gói")
		program = make_sterilize_program(machine.name)
		first, second, third = (make_load_ready_pack() for _i in range(3))
		self.assertEqual(self.admit(first, machine=machine, program=program)["capacity"], 2)
		queued = [first.name, second.name]
		block = self.blocked(
			lambda: self.admit(third, queued=queued, machine=machine, program=program),
			"LOAD_CAPACITY_EXCEEDED",
		)
		self.assertEqual(block.http_status, 409)
		# quét lặp gói đã có khi đủ chỗ vẫn không lỗi
		self.assertTrue(self.admit(second, queued=queued, machine=machine, program=program)["duplicate"])

	def test_admit_without_t5_gate_change(self):
		pack = make_load_ready_pack()
		self.admit(pack)
		self.assertEqual(frappe.db.count("Step Gate Result", {"set_unit": pack.set_unit, "step": "T5"}), 0)
		self.assertEqual(frappe.db.get_value("Set Unit", pack.set_unit, "status"), "Processing")

	def test_running_loads_lists_open_loads_with_packs(self):
		pack = make_load_ready_pack()
		load = make_load(self.machine, self.program, [pack])
		rows = {row["load"]: row for row in sterilizing.running_loads()}
		self.assertEqual(rows[load.name]["packs"], [pack.name])
		self.assertEqual(rows[load.name]["status"], "Running")
		frappe.db.set_value("Sterilization Load", load.name, "status", "Released")
		self.assertNotIn(load.name, [row["load"] for row in sterilizing.running_loads()])

	def test_other_equipment_type_is_not_a_sterilizer(self):
		sealer = make_equipment(
			name="Máy hàn", equipment_type="Sealer", serial="SE-" + frappe.generate_hash(length=6)
		)
		self.assertEqual(sterilizing.check_equipment_ready(sealer.name).code, "EQUIPMENT_NOT_STERILIZER")
