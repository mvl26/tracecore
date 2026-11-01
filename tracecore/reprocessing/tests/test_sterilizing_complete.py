from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import client_time, code_registry
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import sterilizing
from tracecore.tests.factories import (
	deactivate_printers,
	make_employee,
	make_label_items,
	make_load,
	make_load_ready_pack,
	make_printer,
	make_sterilize_program,
	make_sterilizer,
)
from tracecore.tests.utils import IsolatedTestCase, bru

STATION = "TR-005"  # T5 Sterilization

test_ignore = ["Employee", "Item", "Batch", "User"]


def complete(machine, program, packs, employee, client_ts=None, is_priority=False):
	return sterilizing.complete(
		machine.name,
		program.name,
		[pack.name if hasattr(pack, "name") else pack for pack in packs],
		STATION,
		client_ts or client_time.utc_now(),
		employee.name,
		is_priority,
	)


class TestSterilizingComplete(FrappeTestCase):
	def setUp(self):
		super().setUp()
		deactivate_printers(STATION)
		self.machine = make_sterilizer()
		self.program = make_sterilize_program(self.machine.name, requires_bi=1)
		self.employee = make_employee()

	def complete(self, packs, **kwargs):
		return complete(self.machine, self.program, packs, self.employee, **kwargs)

	def code_of(self, packs, **kwargs):
		with self.assertRaises(BlockedError) as caught:
			self.complete(packs, **kwargs)
		return caught.exception.block.code

	@bru("BRU-REP-016")
	def test_complete_generates_me_code_and_registers_it(self):
		packs = [make_load_ready_pack(), make_load_ready_pack()]
		result = self.complete(packs, is_priority=True)
		self.assertRegex(result["load"], r"^ME-\d{6}-\d{2}$")
		self.assertEqual(result["packs"], [p.name for p in packs])
		self.assertEqual(result["rejected"], [])
		self.assertTrue(code_registry.is_issued(result["load"]))
		load = frappe.get_doc("Sterilization Load", result["load"])
		self.assertEqual((load.status, load.docstatus), ("Running", 0))
		self.assertEqual(load.operator, self.employee.name)
		self.assertEqual(
			(load.equipment, load.program, load.loaded_by_scan, load.requires_bi, load.is_priority),
			(self.machine.name, self.program.name, 1, 1, 1),
		)
		self.assertEqual(load.started_at, load.load_completed_at)
		self.assertEqual([row.pack for row in load.packs], [p.name for p in packs])
		self.assertEqual([row.set_unit for row in load.packs], [p.set_unit for p in packs])

	def test_complete_moves_packs_to_in_load_without_touching_the_set_gates(self):
		pack = make_load_ready_pack()
		result = self.complete([pack])
		self.assertEqual(
			frappe.db.get_value("Pack", pack.name, ["status", "load"]), ("In Load", result["load"])
		)
		self.assertEqual(frappe.db.count("Step Gate Result", {"set_unit": pack.set_unit, "step": "T5"}), 0)
		self.assertEqual(frappe.db.get_value("Set Unit", pack.set_unit, "status"), "Processing")

	def test_complete_accepts_messy_scan_strings_and_ignores_repeats(self):
		pack = make_load_ready_pack()
		result = self.complete([f"]d2{pack.name}\r\n", pack.name, f"  {pack.name}\t"])
		self.assertEqual(result["packs"], [pack.name])
		self.assertEqual(frappe.db.count("Load Pack", {"parent": result["load"]}), 1)

	@bru("BRU-REP-016")
	def test_complete_requires_at_least_one_pack(self):
		before = frappe.db.count("Sterilization Load")
		self.assertEqual(self.code_of([]), "LOAD_EMPTY")
		# mọi gói đều bị loại cũng là mẻ rỗng: không tạo mẻ, không cấp mã
		self.assertEqual(self.code_of(["CY-991231-0001", "TB-0001"]), "LOAD_EMPTY")
		self.assertEqual(frappe.db.count("Sterilization Load"), before)

	def test_complete_returns_rejected_and_accepts_the_rest(self):
		good1, good2, taken = make_load_ready_pack(), make_load_ready_pack(), make_load_ready_pack()
		busy = make_sterilizer()  # mẻ khác ở máy khác: máy này còn mẻ Running thì không nạp được (A-22)
		other = make_load(busy, make_sterilize_program(busy.name), [taken])
		plasma = make_load_ready_pack(method="Plasma")
		result = self.complete([good1, taken, plasma, "TB-0001", good2])
		self.assertEqual(result["packs"], [good1.name, good2.name])
		rejected = {row["cycle_id"]: row for row in result["rejected"]}
		self.assertEqual(rejected[taken.name]["code"], "PACK_IN_OTHER_LOAD")
		self.assertIn(other.name, rejected[taken.name]["reason"])
		self.assertEqual(rejected[plasma.name]["code"], "PACK_INCOMPATIBLE")
		self.assertEqual(rejected["TB-0001"]["code"], "SCAN_INVALID")

	def test_complete_cuts_packs_over_capacity(self):
		machine = make_sterilizer(capacity="3 gói")
		program = make_sterilize_program(machine.name)
		packs = [make_load_ready_pack() for _i in range(4)]
		result = complete(machine, program, packs, self.employee)
		self.assertEqual(result["packs"], [p.name for p in packs[:3]])
		self.assertEqual(result["rejected"][0]["cycle_id"], packs[3].name)
		self.assertEqual(result["rejected"][0]["code"], "LOAD_CAPACITY_EXCEEDED")
		self.assertEqual(frappe.db.get_value("Pack", packs[3].name, "status"), "Packed")

	@bru("BRU-FLOW-004")
	def test_complete_revalidates_every_pack(self):
		first, second = make_load_ready_pack(), make_load_ready_pack()
		# gói đầu được quét vào danh sách rồi bị hủy trước khi bấm Hoàn thành nạp
		frappe.db.set_value("Pack", first.name, {"status": "Void", "void_reason": "Torn"})
		result = self.complete([first, second])
		self.assertEqual(result["packs"], [second.name])
		self.assertEqual(result["rejected"][0]["code"], "PACK_NOT_LOADABLE")

	def test_second_complete_with_same_pack_rejected(self):
		pack, extra = make_load_ready_pack(), make_load_ready_pack()
		first = self.complete([pack])
		# máy chỉ nạp mẻ mới khi mẻ trước đã dỡ (A-86)
		frappe.db.set_value(
			"Sterilization Load",
			first["load"],
			{"status": "Cycle Complete", "unload_scan_at": frappe.utils.now_datetime()},
		)
		result = self.complete([pack, extra])
		self.assertEqual(result["packs"], [extra.name])
		self.assertEqual(result["rejected"][0]["code"], "PACK_IN_OTHER_LOAD")
		self.assertEqual(frappe.db.get_value("Pack", pack.name, "load"), first["load"])
		frappe.db.set_value(
			"Sterilization Load",
			result["load"],
			{"status": "Cycle Complete", "unload_scan_at": frappe.utils.now_datetime()},
		)
		self.assertEqual(self.code_of([pack]), "LOAD_EMPTY")
		self.assertEqual(frappe.db.count("Load Pack", {"pack": pack.name}), 1)

	def test_complete_rejects_program_of_other_equipment(self):
		other = make_sterilize_program(make_sterilizer().name)
		with self.assertRaises(BlockedError) as caught:
			complete(self.machine, other, [make_load_ready_pack()], self.employee)
		self.assertEqual(caught.exception.block.code, "PROGRAM_INVALID")

	def test_complete_rejects_machine_not_ready(self):
		frappe.db.set_value("Equipment", self.machine.name, "status", "Locked")
		self.assertEqual(self.code_of([make_load_ready_pack()]), "EQUIPMENT_NOT_READY")

	def test_machine_with_a_running_load_takes_no_new_load_until_its_cycle_is_done(self):
		# A-86 (sửa A-22): máy tiệt khuẩn chỉ chạy một mẻ; mẻ trước chưa dỡ thì chặn quét máy, nạp gói và hoàn thành nạp mẻ mới
		first = self.complete([make_load_ready_pack()])["load"]
		waiting = make_load_ready_pack()
		for call in (
			lambda: sterilizing.scan_machine(self.machine.name),
			lambda: sterilizing.admit_pack(waiting.name, self.machine.name, self.program.name),
			lambda: self.complete([waiting]),
		):
			with self.assertRaises(BlockedError) as caught:
				call()
			self.assertEqual(caught.exception.block.code, "EQUIPMENT_BUSY")
			self.assertEqual(caught.exception.block.http_status, 409)
			self.assertIn(first, caught.exception.block.reason)
		self.assertEqual(frappe.db.get_value("Pack", waiting.name, "status"), "Packed")
		frappe.db.set_value("Sterilization Load", first, "status", "Cycle Complete")
		block = sterilizing.check_equipment_ready(self.machine.name)
		self.assertEqual(block.code, "EQUIPMENT_BUSY")  # A-86: có dữ liệu mà chưa dỡ vẫn bận
		frappe.db.set_value("Sterilization Load", first, "unload_scan_at", frappe.utils.now_datetime())
		self.assertTrue(self.complete([waiting])["load"])

	def test_complete_error_rolls_back_everything(self):
		pack = make_load_ready_pack()
		loads = frappe.db.count("Sterilization Load")
		with patch.object(sterilizing, "_queue_label", side_effect=RuntimeError("boom")):
			with self.assertRaises(RuntimeError):
				self.complete([pack])
		self.assertEqual(frappe.db.count("Sterilization Load"), loads)
		self.assertEqual(frappe.db.get_value("Pack", pack.name, ["status", "load"]), ("Packed", None))

	def test_complete_hook_receives_context(self):
		pack = make_load_ready_pack()
		with patch("tracecore.reprocessing.sterilizing.extension.run") as run:
			run.return_value = []
			result = self.complete([pack])
		hook_calls = [c for c in run.call_args_list if c.args[0] == sterilizing.AFTER_COMPLETE_HOOK]
		self.assertEqual(len(hook_calls), 1)
		ctx = hook_calls[0].args[1]
		self.assertEqual(
			ctx,
			{
				"load": result["load"],
				"equipment": self.machine.name,
				"program": self.program.name,
				"packs": [pack.name],
				"sets": [pack.set_unit],
			},
		)

	def test_complete_rejects_skewed_client_ts(self):
		pack = make_load_ready_pack()
		before = frappe.db.count("Sterilization Load")
		skewed = client_time.utc_now() - timedelta(seconds=client_time.max_skew_seconds() + 3600)
		with self.assertRaises(client_time.ClientTimestampError):
			self.complete([pack], client_ts=skewed)
		self.assertEqual(frappe.db.count("Sterilization Load"), before)


class TestSterilizingLabel(IsolatedTestCase):
	"""Mỗi test đổi trạng thái mẫu nhãn/máy in nên chạy trong savepoint riêng."""

	def setUp(self):
		super().setUp()
		deactivate_printers(STATION)
		self.machine = make_sterilizer()
		self.program = make_sterilize_program(self.machine.name)
		self.employee = make_employee()
		self.pack = make_load_ready_pack()

	def complete(self):
		return complete(self.machine, self.program, [self.pack], self.employee)

	@bru("BRU-REP-016")
	def test_complete_creates_print_job_with_qr_of_load_code(self):
		steam, _plasma = make_label_items()
		printer = make_printer(STATION, steam, host="10.0.0.7")
		result = self.complete()
		label = result["print"]
		self.assertEqual((label["status"], label["printer"], label["warning"]), ("Queued", printer, None))
		self.assertIn(f"^FDMA,{result['load']}^FS", label["zpl"])
		job = frappe.get_doc("Print Job", label["print_job"])
		self.assertEqual(
			(job.status, job.station, job.ref_doctype, job.ref_name),
			("Queued", STATION, "Sterilization Load", result["load"]),
		)
		self.assertEqual(job.payload, label["zpl"])
		self.assertTrue(result["qr_png_b64"])

	def test_label_waits_when_station_has_no_printer_but_load_code_is_kept(self):
		result = self.complete()
		label = result["print"]
		self.assertEqual((label["status"], label["printer"], label["zpl"]), ("Waiting", None, None))
		self.assertEqual(label["warning"]["code"], "NO_PRINTER_AT_STATION")
		self.assertTrue(frappe.db.exists("Sterilization Load", result["load"]))
		job = frappe.get_doc("Print Job", label["print_job"])
		self.assertEqual((job.status, job.ref_name), ("Waiting", result["load"]))

	def test_label_waits_when_template_is_missing_or_broken(self):
		steam, _plasma = make_label_items()
		make_printer(STATION, steam)
		frappe.db.set_value("Label Template", {"label_object": "Sterilization Load"}, "is_active", 0)
		label = self.complete()["print"]
		self.assertEqual((label["status"], label["warning"]["code"]), ("Waiting", "LABEL_RENDER_FAILED"))
		self.assertIn("Sterilization Load", label["warning"]["reason"])
