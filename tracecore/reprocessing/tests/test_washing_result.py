"""Dỡ lô rửa, dữ liệu chu trình nhập tay có xác nhận, kết luận áp cho mọi bộ (FEAT-021 Task 4, UC-06 bước 5 đến 7)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from tracecore.core import client_time, station_auth, step_gate
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import washing
from tracecore.tests.factories import (
	deactivate_printers,
	make_chemical_batch,
	make_employee,
	make_user,
	make_wash_machine,
	make_wash_program,
	make_wash_ready_set,
)
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

CHEMICAL = "HC-ENZ-01"
STATION = "TR-002"  # T2 Washing, khu bẩn
CLEAN_STATION = "TR-003"  # T3 Assembly, khu sạch
STERILE_STATION = "TR-006"  # khu vô khuẩn
PARAMETERS = [
	{"parameter_name": "Nhiệt độ khử khuẩn", "unit": "°C", "min_value": 90, "max_value": 95, "required": 1},
	{"parameter_name": "Thời gian giữ", "unit": "phút", "min_value": 0, "max_value": 10, "required": 1},
	{"parameter_name": "Áp lực nước", "unit": "bar", "min_value": 0, "max_value": 0, "required": 0},
]
GOOD_VALUES = [
	{"parameter_name": "Nhiệt độ khử khuẩn", "value": 93},
	{"parameter_name": "Thời gian giữ", "value": 5},
]
PRINTOUT = "/files/wash-printout.png"


def _code(fn, *args, **kwargs):
	try:
		fn(*args, **kwargs)
	except BlockedError as error:
		return error.block.code
	return None


class WashResultCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		deactivate_printers(STATION)
		self.machine = self.make_machine(has_printout=1)
		self.lot = make_chemical_batch(CHEMICAL)
		self.program = make_wash_program(self.machine.name, chemical=CHEMICAL, parameters=PARAMETERS)
		self.employee = make_employee()

	def make_machine(self, **kwargs):
		return make_wash_machine(**kwargs)

	def load(self, count=2, machine=None, program=None):
		units = [make_wash_ready_set() for _ in range(count)]
		machine = machine or self.machine
		result = washing.start(
			machine.name,
			(program or self.program).name,
			[u.name for u in units],
			[{"item": CHEMICAL, "lot": self.lot.name}] if (program or self.program).chemical else [],
			STATION,
			client_time.utc_now(),
			self.employee.name,
		)
		return result["batch"], [u.name for u in units]

	def save_data(self, batch, machine=None, values=None, confirmed=True, machine_file=PRINTOUT, **kwargs):
		machine = machine or self.machine
		args = {
			"batch": batch,
			"equipment_raw": machine.name,
			"batch_raw": batch,
			"values": GOOD_VALUES if values is None else values,
			"reported_result": "Pass",
			"started_at": str(add_to_date(now_datetime(), hours=-1)),
			"ended_at": str(now_datetime()),
			"machine_alerts": None,
			"machine_file": machine_file,
			"confirmed": confirmed,
			"client_ts": client_time.utc_now(),
			"employee": self.employee.name,
			"station": STATION,
			**kwargs,
		}
		return washing.save_manual_data(**args)

	def close(self, batch, result="Pass", clean_test="Pass", machine=None, **kwargs):
		machine = machine or self.machine
		args = {
			"batch": batch,
			"result": result,
			"station": STATION,
			"equipment_raw": machine.name,
			"batch_raw": batch,
			"clean_test": clean_test,
			"client_ts": client_time.utc_now(),
			**kwargs,
		}
		return washing.set_result(**args)


class TestWashUnload(WashResultCase):
	@bru("BRU-REP-016")
	def test_unload_requires_matching_machine_qr(self):
		batch, _sets = self.load()
		other = make_wash_machine()
		self.assertEqual(_code(washing.scan_unload, batch, other.name, STATION), "EQUIPMENT_MISMATCH")
		self.assertEqual(
			_code(self.close, batch, machine=other), "EQUIPMENT_MISMATCH"
		)  # cũng chặn ở kết luận
		self.save_data(batch)
		self.close(batch)
		self.assertEqual(_code(washing.scan_unload, batch, self.machine.name, STATION), "BATCH_NOT_RUNNING")
		self.assertEqual(_code(washing.scan_unload, batch, batch, STATION), "BATCH_NOT_RUNNING")

	def test_unload_scan_wrong_machine_rejected_immediately(self):
		batch, _sets = self.load()
		self.assertEqual(
			washing.scan_unload(batch, f"]Q1{self.machine.name}\r\n", STATION),
			{"ok": True, "kind": "equipment"},
		)
		self.assertEqual(washing.scan_unload(batch, batch, STATION), {"ok": True, "kind": "wash_batch"})
		elsewhere = make_wash_machine(has_printout=1)
		other_batch, _ = self.load(
			machine=elsewhere,
			program=make_wash_program(elsewhere.name, chemical=CHEMICAL, parameters=PARAMETERS),
		)
		self.assertEqual(_code(washing.scan_unload, batch, other_batch, STATION), "SCAN_INVALID")
		self.assertEqual(_code(washing.scan_unload, batch, "TR-002", STATION), "SCAN_INVALID")
		self.assertEqual(
			_code(washing.scan_unload, "LR-000101-99", self.machine.name, STATION), "WASH_BATCH_NOT_FOUND"
		)

	def test_unload_at_exit_door_station_of_two_door_machine(self):
		two_door = make_wash_machine(zone_out="ZONE-CLEAN", has_printout=1)
		program = make_wash_program(two_door.name, chemical=CHEMICAL, parameters=PARAMETERS)
		batch, _sets = self.load(machine=two_door, program=program)
		self.assertEqual(
			washing.scan_unload(batch, two_door.name, CLEAN_STATION), {"ok": True, "kind": "equipment"}
		)
		self.assertEqual(
			_code(washing.scan_unload, batch, two_door.name, STERILE_STATION), "STATION_WRONG_STEP"
		)
		# máy một cửa: trạm khu sạch không dỡ được
		one_door, _ = self.load()
		self.assertEqual(
			_code(washing.scan_unload, one_door, self.machine.name, CLEAN_STATION), "STATION_WRONG_STEP"
		)
		self.save_data(batch, machine=two_door, station=CLEAN_STATION)
		result = self.close(batch, machine=two_door, station=CLEAN_STATION)
		self.assertEqual(result["result"], "Pass")

	def test_server_revalidates_scanned_codes(self):
		batch, _sets = self.load()
		other = make_wash_machine()
		self.assertEqual(_code(self.save_data, batch, equipment_raw=other.name), "EQUIPMENT_MISMATCH")
		self.assertEqual(_code(self.save_data, batch, equipment_raw=""), "SCAN_INVALID")
		self.assertEqual(_code(self.save_data, batch, batch_raw=""), "SCAN_INVALID")
		self.assertEqual(_code(washing.unload_context, batch, self.machine.name, "", STATION), "SCAN_INVALID")
		self.save_data(batch)
		self.assertEqual(_code(self.close, batch, batch_raw=self.machine.name), "SCAN_INVALID")
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, "status"), "Running")

	def test_unload_context_returns_parameter_schema(self):
		batch, sets = self.load()
		context = washing.unload_context(batch, self.machine.name, batch, STATION)
		self.assertEqual(context["batch"], batch)
		self.assertEqual([s["set_id"] for s in context["sets"]], sets)
		self.assertEqual(
			[(p["parameter_name"], p["required"]) for p in context["parameter_schema"]],
			[("Nhiệt độ khử khuẩn", 1), ("Thời gian giữ", 1), ("Áp lực nước", 0)],
		)
		self.assertEqual(context["equipment"]["has_printout"], 1)

	def test_running_batches_list_open_batches_only(self):
		closed, _ = self.load()
		self.save_data(closed)
		self.close(closed)
		batch, sets = self.load()  # máy chỉ nhận lô mới sau khi lô trước đã dỡ (A-73)
		rows = {row["batch"]: row for row in washing.running_batches()}
		self.assertIn(batch, rows)
		self.assertNotIn(closed, rows)
		row = rows[batch]
		self.assertEqual((row["equipment"], row["program"]), (self.machine.name, self.program.name))
		self.assertEqual((row["sets"], row["data_complete"]), (sets, 0))
		self.assertEqual(row["equipment_name"], self.machine.equipment_name)

	def test_start_returns_qr_png_of_batch_code(self):
		import base64

		units = [make_wash_ready_set()]
		result = washing.start(
			self.machine.name,
			self.program.name,
			[u.name for u in units],
			[{"item": CHEMICAL, "lot": self.lot.name}],
			STATION,
			client_time.utc_now(),
			self.employee.name,
		)
		self.assertTrue(base64.b64decode(result["qr_png_b64"]).startswith(b"\x89PNG"))

	def test_lookup_shows_sets_chemicals_and_people(self):
		batch, sets = self.load()
		info = washing.lookup(f"]Q1{batch}\r\n")
		self.assertEqual((info["batch"], info["status"]), (batch, "Running"))
		self.assertEqual(info["equipment"]["name"], self.machine.name)
		self.assertEqual(info["program"]["name"], self.program.name)
		self.assertEqual(info["operator"]["name"], self.employee.name)
		self.assertTrue(info["load_completed_at"])
		self.assertEqual([s["set_id"] for s in info["sets"]], sets)
		self.assertEqual([(c["item"], c["lot"]) for c in info["chemicals"]], [(CHEMICAL, self.lot.name)])
		self.assertEqual((info["data_complete"], info["needs_review"]), (0, 0))
		self.assertEqual(_code(washing.lookup, "LR-000101-99"), "WASH_BATCH_NOT_FOUND")
		self.assertEqual(_code(washing.lookup, self.machine.name), "SCAN_INVALID")


class TestWashManualData(WashResultCase):
	@bru("BRU-REP-015")
	def test_pass_blocked_until_data_complete(self):
		batch, _sets = self.load()
		saved = self.save_data(batch, confirmed=False)
		self.assertEqual(saved["data_complete"], 0)
		self.assertIn("confirmation", saved["missing"])
		with self.assertRaises(BlockedError) as caught:
			self.close(batch)
		self.assertEqual(caught.exception.block.code, "DATA_INCOMPLETE")
		self.assertTrue(caught.exception.block.items)

		saved = self.save_data(batch, values=GOOD_VALUES[:1])
		self.assertEqual(saved["data_complete"], 0)
		self.assertEqual(saved["missing"], ["Thời gian giữ"])

		saved = self.save_data(batch, machine_file=None)
		self.assertEqual((saved["data_complete"], saved["missing"]), (0, ["printout"]))
		self.assertEqual(_code(self.close, batch), "DATA_INCOMPLETE")

		saved = self.save_data(batch)
		self.assertEqual((saved["data_complete"], saved["missing"]), (1, []))
		doc = frappe.get_doc("Wash Batch", batch)
		self.assertEqual((doc.data_source, doc.manual_confirmed_by), ("Manual", self.employee.name))
		self.assertTrue(doc.manual_confirmed_at)
		self.assertEqual(doc.machine_files, PRINTOUT)
		self.assertEqual(self.close(batch)["result"], "Pass")

	@bru("BRU-REP-015")
	def test_close_blocked_without_data_even_for_fail(self):
		batch, _sets = self.load()
		self.assertEqual(_code(self.close, batch, result="Fail"), "DATA_INCOMPLETE")
		self.assertEqual(_code(self.close, batch, result="Pass"), "DATA_INCOMPLETE")
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, "docstatus"), 0)

	@bru("BRU-REP-015")
	def test_pass_requires_clean_test_pass(self):
		batch, _sets = self.load()
		self.save_data(batch, reported_result="Fail")  # kết quả máy báo chỉ là thông tin (Q14)
		self.assertEqual(_code(self.close, batch, clean_test="Fail"), "RESULT_INVALID")
		self.assertEqual(_code(self.close, batch, result="Maybe"), "RESULT_INVALID")
		result = self.close(batch, result="Fail", clean_test="Fail")
		self.assertEqual(result["result"], "Fail")
		doc = frappe.get_doc("Wash Batch", batch)
		self.assertEqual((doc.clean_test_result, doc.cycle_result), ("Fail", "Fail"))

	def test_reported_result_does_not_block_pass(self):
		batch, _sets = self.load()
		self.save_data(batch, reported_result="Fail")
		self.assertEqual(self.close(batch)["result"], "Pass")
		data = frappe.parse_json(frappe.db.get_value("Wash Batch", batch, "machine_data"))
		self.assertEqual(data["reported_result"], "Fail")

	def test_parameter_range_one_sided_and_zero_is_unset(self):
		batch, _sets = self.load()
		values = [
			{"parameter_name": "Nhiệt độ khử khuẩn", "value": 93},
			{"parameter_name": "Thời gian giữ", "value": 0},  # min=0 không đặt: 0 không ngoài dải
			{"parameter_name": "Áp lực nước", "value": 999},  # min=max=0: không đặt dải
		]
		saved = self.save_data(batch, values=values)
		self.assertEqual((saved["data_complete"], saved["needs_review"]), (1, 0))
		values[1]["value"] = 12  # chỉ max=10 đặt: vượt max
		saved = self.save_data(batch, values=values, machine_alerts="Cảnh báo áp lực thấp")
		self.assertEqual((saved["data_complete"], saved["needs_review"]), (1, 1))
		data = frappe.parse_json(frappe.db.get_value("Wash Batch", batch, "machine_data"))
		flags = {row["parameter_name"]: row["outside_range"] for row in data["parameters"]}
		self.assertEqual(flags, {"Nhiệt độ khử khuẩn": False, "Thời gian giữ": True, "Áp lực nước": False})
		self.assertEqual(data["alerts"], "Cảnh báo áp lực thấp")
		self.assertEqual(data["parameters"][1]["unit"], "phút")
		values[0]["value"] = 89  # dưới min
		self.assertEqual(self.save_data(batch, values=values)["needs_review"], 1)
		self.assertEqual(_code(self.close, batch), "CYCLE_DATA_OUT_OF_RANGE")  # A-89 sửa Q8

	def test_end_time_and_times_are_saved(self):
		batch, _sets = self.load()
		start = add_to_date(now_datetime(), hours=-2).replace(microsecond=0)
		end = add_to_date(now_datetime(), hours=-1).replace(microsecond=0)
		self.save_data(batch, started_at=str(start), ended_at=str(end))
		doc = frappe.get_doc("Wash Batch", batch)
		self.assertEqual((get_datetime(doc.started_at), get_datetime(doc.ended_at)), (start, end))
		saved = self.save_data(batch, started_at=str(end), ended_at=str(start))
		self.assertEqual((saved["data_complete"], saved["missing"]), (0, ["ended_at"]))
		saved = self.save_data(batch, ended_at=None)
		self.assertEqual(saved["missing"], ["ended_at"])

	def test_manual_data_rejected_after_close(self):
		batch, _sets = self.load()
		self.save_data(batch)
		self.close(batch)
		self.assertEqual(_code(self.save_data, batch), "BATCH_NOT_RUNNING")


class TestWashOldMachine(WashResultCase):
	def setUp(self):
		super().setUp()
		self.old = make_wash_machine()  # không kết nối, không bản in (Q7)
		self.old_program = make_wash_program(self.old.name, chemical=CHEMICAL, parameters=PARAMETERS)
		self.r02 = make_user("wash-r02@test.local", roles=("TC R02",))
		self.r03 = make_user("wash-r03@test.local", roles=("TC R03",))

	def proof_of(self, user, pin="246810"):
		session = make_station_session(user, station=STATION)
		employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
		frappe.db.set_value("Employee", employee, "tc_pin_reset_required", 0)
		station_auth.set_pin(employee, pin)
		proof = station_auth.create_pin_proof(session["token"], pin)["proof"]
		return session["session"], proof

	@bru("BRU-REP-015")
	def test_old_machine_pass_requires_r02_proof(self):
		batch, _sets = self.load(machine=self.old, program=self.old_program)
		saved = self.save_data(batch, machine=self.old, machine_file=None)
		self.assertEqual(saved["data_complete"], 1)  # không bản in: không đòi ảnh
		self.assertEqual(_code(self.close, batch, machine=self.old), "R02_CONFIRM_REQUIRED")
		session, _proof = self.proof_of(self.r02)
		self.assertEqual(
			_code(self.close, batch, machine=self.old, reviewer_proof="sai", session=session),
			"R02_CONFIRM_REQUIRED",
		)
		r03_session, r03_proof = self.proof_of(self.r03)
		self.assertEqual(
			_code(self.close, batch, machine=self.old, reviewer_proof=r03_proof, session=r03_session),
			"R02_CONFIRM_REQUIRED",
		)
		session, proof = self.proof_of(self.r02)
		result = self.close(batch, machine=self.old, reviewer_proof=proof, session=session)
		self.assertEqual(result["result"], "Pass")
		doc = frappe.get_doc("Wash Batch", batch)
		self.assertEqual(doc.reviewer, self.r02)
		self.assertTrue(doc.reviewed_at)

	def test_old_machine_fail_needs_no_proof(self):
		batch, _sets = self.load(machine=self.old, program=self.old_program)
		self.save_data(batch, machine=self.old, machine_file=None)
		self.assertEqual(self.close(batch, machine=self.old, result="Fail")["result"], "Fail")


class TestWashResult(WashResultCase):
	@bru("BRU-REP-002")
	def test_result_applies_to_every_set_at_once(self):
		batch, sets = self.load(count=3)
		self.save_data(batch)
		result = self.close(batch, note="Lô đẹp")
		self.assertEqual(result["batch"], batch)
		self.assertEqual([s["set_id"] for s in result["sets"]], sorted(sets))
		for set_id in sets:
			gate = frappe.get_doc("Step Gate Result", step_gate.result_name(set_id, 1, "T2"))
			self.assertEqual((gate.result, gate.ref_doctype, gate.ref_name), ("Pass", "Wash Batch", batch))
			self.assertEqual(gate.station, STATION)
		doc = frappe.get_doc("Wash Batch", batch)
		self.assertEqual((doc.status, doc.docstatus, doc.cycle_result), ("Passed", 1, "Pass"))
		self.assertEqual((doc.result_source, doc.unload_scan_equipment), ("Manual", self.machine.name))
		self.assertTrue(doc.unload_scan_at)
		self.assertEqual(doc.result_note, "Lô đẹp")
		self.assertEqual(result["incident_id"], None)

	@bru("BRU-REP-002")
	def test_result_is_all_or_nothing(self):
		batch, sets = self.load(count=3)
		self.save_data(batch)
		second = sorted(sets)[1]
		real_record = step_gate.record

		def flaky(set_unit, *args, **kwargs):
			if set_unit == second:
				raise frappe.ValidationError("boom")
			return real_record(set_unit, *args, **kwargs)

		with patch.object(step_gate, "record", side_effect=flaky):
			with self.assertRaises(frappe.ValidationError):
				self.close(batch)
		for set_id in sets:
			self.assertFalse(frappe.db.exists("Step Gate Result", step_gate.result_name(set_id, 1, "T2")))
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, ["status", "docstatus"]), ("Running", 0))

	@bru("BRU-REP-002", "BRU-FLOW-004")
	def test_fail_sends_all_sets_to_reprocess_and_flags_nc(self):
		batch, sets = self.load(count=2)
		self.save_data(batch)
		result = self.close(batch, result="Fail", clean_test="Fail")
		self.assertEqual({s["status"] for s in result["sets"]}, {"Reprocess"})
		self.assertEqual({s["redo_count"] for s in result["sets"]}, {1})
		# FEAT-030, FR-M2-04.4 / FR-M2-21.1: lô Không đạt tự tạo NC loại Wash Failed gắn lô và máy
		incident = frappe.get_doc("Incident CAPA", result["incident_id"])
		self.assertEqual(
			(incident.incident_type, incident.wash_batch, incident.equipment, incident.is_auto),
			("Wash Failed", batch, self.machine.name, 1),
		)
		for set_id in sets:
			gates = {g["step"]: g for g in step_gate.gates(set_id)}
			self.assertEqual((gates["T2"]["result"], gates["T2"]["redo_count"]), ("Fail", 1))
			self.assertEqual(gates["T3"]["result"], "Pending")
		doc = frappe.get_doc("Wash Batch", batch)
		self.assertEqual((doc.status, doc.nc_pending, doc.docstatus), ("Failed", 1, 1))
		self.assertTrue(
			frappe.db.exists(
				"Audit Log", {"ref_doctype": "Wash Batch", "ref_name": batch, "reason": "WashFailed"}
			)
		)
		self.assertEqual({row["set_id"] for row in washing.redo_queue()} & set(sets), set(sets))

	def test_failed_set_can_be_readmitted_then_passes(self):
		batch, sets = self.load(count=1)
		self.save_data(batch)
		self.close(batch, result="Fail", clean_test="Fail")
		again = washing.start(
			self.machine.name,
			self.program.name,
			sets,
			[{"item": CHEMICAL, "lot": self.lot.name}],
			STATION,
			client_time.utc_now(),
			self.employee.name,
		)
		self.assertEqual(again["sets"], sets)
		self.save_data(again["batch"])
		result = self.close(again["batch"])
		self.assertEqual(result["sets"], [{"set_id": sets[0], "status": "Processing", "redo_count": 1}])

	def test_set_result_twice_rejected(self):
		batch, _sets = self.load()
		self.save_data(batch)
		self.close(batch)
		self.assertEqual(_code(self.close, batch), "BATCH_NOT_RUNNING")
		self.assertEqual(_code(self.close, batch, result="Fail"), "BATCH_NOT_RUNNING")

	def test_hooks_are_called_with_context(self):
		calls = []
		batch, sets = self.load()
		self.save_data(batch)
		with patch.object(washing.extension, "run", side_effect=lambda hook, ctx: calls.append((hook, ctx))):
			self.close(batch)
		self.assertEqual(
			[hook for hook, _ctx in calls if hook != "tracecore_after_set_status"],
			["tracecore_after_wash_complete"],
		)
		ctx = next(c for h, c in calls if h == "tracecore_after_wash_complete")
		self.assertEqual(
			(ctx["batch"], ctx["equipment"], ctx["program"]), (batch, self.machine.name, self.program.name)
		)
		self.assertEqual((sorted(ctx["sets"]), ctx["result"]), (sorted(sets), "Pass"))
		self.assertEqual(ctx["chemicals"], [{"item": CHEMICAL, "lot": self.lot.name, "qty": 0.0}])

		calls.clear()
		batch, _sets = self.load()
		self.save_data(batch)
		with patch.object(washing.extension, "run", side_effect=lambda hook, ctx: calls.append((hook, ctx))):
			self.close(batch, result="Fail", clean_test="Fail")
		self.assertEqual(
			[hook for hook, _ctx in calls if hook != "tracecore_after_set_status"],
			["tracecore_after_wash_failed"],
		)

	def test_result_rejects_client_clock_far_from_server(self):
		batch, _sets = self.load()
		self.save_data(batch)
		with self.assertRaises(client_time.ClientTimestampError):
			self.close(batch, client_ts=add_to_date(client_time.utc_now(), hours=-2))
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, "status"), "Running")
