from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import client_time, code_registry, step_gate
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import washing
from tracecore.tests.factories import (
	deactivate_printers,
	make_chemical_batch,
	make_employee,
	make_equipment,
	make_label_items,
	make_printer,
	make_wash_machine,
	make_wash_program,
	make_wash_ready_set,
)
from tracecore.tests.utils import IsolatedTestCase, bru

CHEMICAL = "HC-ENZ-01"
STATION = "TR-002"  # T2 Washing


class TestWashingStart(FrappeTestCase):
	def setUp(self):
		super().setUp()
		deactivate_printers(STATION)
		self.machine = make_wash_machine()
		self.lot = make_chemical_batch(CHEMICAL)
		self.program = make_wash_program(self.machine.name, chemical=CHEMICAL)
		self.employee = make_employee()

	def start(self, sets, chemicals=None, program=None, equipment=None, client_ts=None, operator=None):
		if chemicals is None:
			chemicals = [{"item": CHEMICAL, "lot": self.lot.name}]
		return washing.start(
			equipment or self.machine.name,
			program or self.program.name,
			sets,
			chemicals,
			STATION,
			client_ts or client_time.utc_now(),
			operator or self.employee.name,
		)

	def code_of(self, **kwargs):
		with self.assertRaises(BlockedError) as caught:
			self.start(**kwargs)
		return caught.exception.block.code

	def batch_count(self):
		return frappe.db.count("Wash Batch")

	@bru("BRU-REP-016")
	def test_start_generates_lr_code_and_registers_it(self):
		units = [make_wash_ready_set(), make_wash_ready_set()]
		result = self.start([u.name for u in units])
		self.assertRegex(result["batch"], r"^LR-\d{6}-\d{2}$")
		self.assertEqual(result["sets"], [u.name for u in units])
		self.assertEqual(result["rejected"], [])
		self.assertTrue(code_registry.is_issued(result["batch"]))
		batch = frappe.get_doc("Wash Batch", result["batch"])
		self.assertEqual((batch.status, batch.docstatus), ("Running", 0))
		self.assertEqual(batch.operator, self.employee.name)
		self.assertEqual(
			(batch.equipment, batch.program, batch.loaded_by_scan), (self.machine.name, self.program.name, 1)
		)
		self.assertEqual([row.set_unit for row in batch.set_units], [u.name for u in units])
		self.assertEqual([(row.item, row.lot) for row in batch.chemicals], [(CHEMICAL, self.lot.name)])
		self.assertEqual(batch.started_at, batch.load_completed_at)
		self.assertEqual(batch.batch_type, "Machine")

	def test_batch_type_follows_equipment_type(self):
		ultrasonic = make_wash_machine(equipment_type="Ultrasonic Cleaner")
		program = make_wash_program(ultrasonic.name)
		result = self.start(
			[make_wash_ready_set().name], chemicals=[], program=program.name, equipment=ultrasonic.name
		)
		self.assertEqual(frappe.db.get_value("Wash Batch", result["batch"], "batch_type"), "Ultrasonic")

	def test_start_accepts_messy_scan_strings_and_ignores_repeats(self):
		unit = make_wash_ready_set()
		result = self.start(["]d2\x1d8004" + unit.name + "\r\n", unit.name, "  " + unit.name + "\t"])
		self.assertEqual(result["sets"], [unit.name])
		self.assertEqual(result["rejected"], [])
		self.assertEqual(frappe.db.count("Wash Batch Set Unit", {"parent": result["batch"]}), 1)

	@bru("BRU-REP-016")
	def test_start_requires_at_least_one_set(self):
		before = self.batch_count()
		self.assertEqual(self.code_of(sets=[]), "BATCH_EMPTY")
		# mọi bộ đều bị loại cũng là lô rỗng: không tạo lô, không cấp mã
		self.assertEqual(self.code_of(sets=[make_wash_ready_set().name[:-1] + "9", "TB-0001"]), "BATCH_EMPTY")
		self.assertEqual(self.batch_count(), before)

	@bru("BRU-FLOW-004")
	def test_start_returns_rejected_list_and_accepts_the_rest(self):
		good1, good2, taken = make_wash_ready_set(), make_wash_ready_set(), make_wash_ready_set()
		other = self.start([taken.name])["batch"]
		no_t1 = make_wash_ready_set()
		step_gate.start_cycle(no_t1.name)  # chu trình mới, cổng T1 chưa Đạt
		result = self.start([good1.name, taken.name, no_t1.name, "TB-0001", good2.name])
		self.assertEqual(result["sets"], [good1.name, good2.name])
		rejected = {row["set_id"]: row for row in result["rejected"]}
		self.assertEqual(rejected[taken.name]["code"], "SET_IN_OTHER_BATCH")
		self.assertIn(other, rejected[taken.name]["reason"])
		self.assertEqual(rejected[no_t1.name]["code"], "GATE_PREV_NOT_PASSED")
		self.assertEqual(rejected["TB-0001"]["code"], "SCAN_INVALID")
		self.assertEqual(
			frappe.get_all(
				"Wash Batch Set Unit",
				filters={"parent": result["batch"]},
				pluck="set_unit",
				order_by="idx asc",
			),
			[good1.name, good2.name],
		)

	@bru("BRU-FLOW-004")
	def test_start_revalidates_every_set(self):
		first, second = make_wash_ready_set(), make_wash_ready_set()
		# bộ đầu được quét vào danh sách rồi bị đẩy qua T2 trước khi bấm Hoàn thành nạp
		step_gate.record(first.name, "T2", "Pass")
		result = self.start([first.name, second.name])
		self.assertEqual(result["sets"], [second.name])
		self.assertEqual(result["rejected"][0]["set_id"], first.name)
		self.assertEqual(result["rejected"][0]["code"], "STEP_ALREADY_PASSED")

	def test_second_start_with_same_set_rejected(self):
		unit = make_wash_ready_set()
		first = self.start([unit.name])["batch"]
		before = self.batch_count()
		self.assertEqual(
			self.code_of(sets=[unit.name]), "BATCH_EMPTY"
		)  # bộ duy nhất của lô thứ hai đã ở lô đầu
		self.assertEqual(self.batch_count(), before)
		other = make_wash_ready_set()
		result = self.start([unit.name, other.name])
		self.assertEqual(result["sets"], [other.name])
		self.assertEqual(result["rejected"][0]["code"], "SET_IN_OTHER_BATCH")
		self.assertIn(first, result["rejected"][0]["reason"])
		holders = frappe.db.sql(
			"""select count(*) from `tabWash Batch Set Unit` row join `tabWash Batch` batch on batch.name = row.parent
			where row.set_unit = %s and batch.status = 'Running'""",
			unit.name,
		)[0][0]
		self.assertEqual(holders, 1)

	def test_start_rejects_program_of_other_equipment_or_inactive(self):
		other = make_wash_machine()
		foreign = make_wash_program(other.name, chemical=CHEMICAL)
		inactive = make_wash_program(self.machine.name, chemical=CHEMICAL, is_active=0)
		unit = make_wash_ready_set()
		for program in (foreign.name, inactive.name, "NO-SUCH-PROGRAM"):
			self.assertEqual(self.code_of(sets=[unit.name], program=program), "PROGRAM_INVALID", msg=program)

	def test_start_rejects_machine_that_is_not_ready(self):
		unit = make_wash_ready_set()
		frappe.db.set_value("Equipment", self.machine.name, "status", "Locked")
		self.assertEqual(self.code_of(sets=[unit.name]), "EQUIPMENT_NOT_READY")
		steam = make_equipment(
			equipment_type="Steam Sterilizer",
			serial="SS-" + frappe.generate_hash(length=8),
			zone_in="ZONE-CLEAN",
			zone_out="ZONE-STERILE",
		)
		self.assertEqual(self.code_of(sets=[unit.name], equipment=steam.name), "EQUIPMENT_NOT_WASHER")

	@bru("BRU-INV-001")
	def test_start_rejects_expired_chemical_lot(self):
		expired = make_chemical_batch(CHEMICAL, expiry_days=-1)
		unit = make_wash_ready_set()
		code = self.code_of(sets=[unit.name], chemicals=[{"item": CHEMICAL, "lot": expired.name}])
		self.assertEqual(code, "CHEMICAL_LOT_EXPIRED")

	def test_start_requires_chemical_when_program_has_one(self):
		unit = make_wash_ready_set()
		self.assertEqual(self.code_of(sets=[unit.name], chemicals=[]), "CHEMICAL_LOT_INVALID")
		other = make_chemical_batch("HC-OTHER-01")
		wrong = [{"item": "HC-OTHER-01", "lot": other.name}]
		self.assertEqual(self.code_of(sets=[unit.name], chemicals=wrong), "CHEMICAL_LOT_INVALID")
		plain = make_wash_program(self.machine.name)  # chương trình không khai hóa chất
		result = self.start([unit.name], chemicals=[], program=plain.name)
		self.assertEqual(frappe.db.count("Wash Batch Chemical", {"parent": result["batch"]}), 0)

	def test_start_is_atomic_when_labelling_fails(self):
		unit = make_wash_ready_set()
		before = (self.batch_count(), frappe.db.count("Code Registry", {"prefix": "LR"}))
		with patch.object(washing, "_queue_label", side_effect=RuntimeError("boom")):
			with self.assertRaises(RuntimeError):
				self.start([unit.name])
		self.assertEqual((self.batch_count(), frappe.db.count("Code Registry", {"prefix": "LR"})), before)
		self.assertFalse(frappe.db.exists("Wash Batch Set Unit", {"set_unit": unit.name}))

	def test_start_rejects_client_clock_far_from_server_before_writing(self):
		unit = make_wash_ready_set()
		before = self.batch_count()
		skewed = client_time.utc_now() - timedelta(seconds=client_time.max_skew_seconds() + 3600)
		with self.assertRaises(client_time.ClientTimestampError):
			self.start([unit.name], client_ts=skewed)
		self.assertEqual(self.batch_count(), before)


class TestWashingLabel(IsolatedTestCase):
	"""Mỗi test đổi trạng thái mẫu nhãn/máy in nên chạy trong savepoint riêng."""

	def setUp(self):
		super().setUp()
		deactivate_printers(STATION)
		self.machine = make_wash_machine()
		self.lot = make_chemical_batch(CHEMICAL)
		self.program = make_wash_program(self.machine.name, chemical=CHEMICAL)
		self.employee = make_employee()
		self.unit = make_wash_ready_set()

	def start(self):
		return washing.start(
			self.machine.name,
			self.program.name,
			[self.unit.name],
			[{"item": CHEMICAL, "lot": self.lot.name}],
			STATION,
			client_time.utc_now(),
			self.employee.name,
		)

	@bru("BRU-REP-016")
	def test_start_creates_print_job_with_qr_of_batch_code(self):
		steam, _plasma = make_label_items()
		printer = make_printer(STATION, steam, host="10.0.0.7")
		result = self.start()
		label = result["print"]
		self.assertEqual((label["status"], label["printer"], label["warning"]), ("Queued", printer, None))
		self.assertIn(f"^FDMA,{result['batch']}^FS", label["zpl"])
		self.assertIn("May rua test", label["zpl"])  # tên máy, bỏ dấu vì máy in không hỗ trợ Unicode
		job = frappe.get_doc("Print Job", label["print_job"])
		self.assertEqual(
			(job.status, job.station, job.ref_doctype, job.ref_name),
			("Queued", STATION, "Wash Batch", result["batch"]),
		)
		self.assertEqual(job.payload, label["zpl"])

	def test_label_waits_when_station_has_no_printer_but_batch_code_is_kept(self):
		result = self.start()
		label = result["print"]
		self.assertEqual((label["status"], label["printer"], label["zpl"]), ("Waiting", None, None))
		self.assertEqual(label["warning"]["code"], "NO_PRINTER_AT_STATION")
		job = frappe.get_doc("Print Job", label["print_job"])
		self.assertEqual((job.status, job.ref_name), ("Waiting", result["batch"]))
		self.assertTrue(frappe.db.exists("Wash Batch", result["batch"]))

	def test_label_waits_when_template_is_missing_or_broken(self):
		steam, _plasma = make_label_items()
		make_printer(STATION, steam)
		frappe.db.set_value("Label Template", {"label_object": "Wash Batch"}, "is_active", 0)
		label = self.start()["print"]
		self.assertEqual((label["status"], label["warning"]["code"]), ("Waiting", "LABEL_RENDER_FAILED"))
		self.assertIn("Wash Batch", label["warning"]["reason"])
