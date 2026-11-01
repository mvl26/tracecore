"""RPC tracecore.v1.wash.* (FEAT-021 Task 5): phiên trạm thẻ, quyền, mã HTTP theo loại lỗi, replay idempotent."""

import base64
import io
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime
from pypdf import PdfReader

from tracecore.core import gs1, qr, station_auth, step_gate
from tracecore.tests.factories import (
	deactivate_printers,
	make_chemical_batch,
	make_set_unit,
	make_user,
	make_wash_machine,
	make_wash_program,
	make_wash_ready_set,
)
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import wash as wash_api
from tracecore.v1._common import BadRequestError
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-002"
CLEAN_STATION = "TR-003"
CHEMICAL = "HC-ENZ-01"
TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
PARAMETERS = [{"parameter_name": "Nhiệt độ", "unit": "°C", "min_value": 90, "max_value": 95, "required": 1}]
TOKENS = {}


def now_ts():
	return datetime.now(TIME_ZONE).isoformat(timespec="seconds")


def call(fn, key=None, station_header=STATION, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	kwargs.setdefault("token", TOKENS.get((frappe.session.user, kwargs.get("station"))))
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": station_header}):
		return fn(**kwargs)


def http_status():
	return frappe.local.response.get("http_status_code")


def counts():
	return tuple(frappe.db.count(d) for d in ("Audit Log", "Idempotency Key", "Wash Batch"))


class WashApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		TOKENS.clear()
		self.addCleanup(TOKENS.clear)
		self.login("Administrator", STATION)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		deactivate_printers(STATION)
		self.machine = make_wash_machine(has_printout=1)
		self.lot = make_chemical_batch(CHEMICAL)
		self.program = make_wash_program(self.machine.name, chemical=CHEMICAL, parameters=PARAMETERS)

	def login(self, user, station):
		TOKENS[(user, station)] = make_station_session(user, station=station)["token"]
		return TOKENS[(user, station)]

	def as_user(self, email, roles, station=STATION):
		user = make_user(email, roles=roles)
		self.login(user, station)
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		return user

	def complete(self, sets, key=None, program=None, machine=None, station=STATION):
		return call(
			wash_api.complete,
			key=key,
			equipment=(machine or self.machine).name,
			program=(program or self.program).name,
			sets=sets,
			chemicals=[{"item": CHEMICAL, "lot": self.lot.name}],
			station=station,
		)

	def spare_washer(self):
		"""Máy rửa và chương trình khác: máy còn lô `Running` chưa dỡ thì không nạp tiếp được (A-73)."""
		machine = make_wash_machine(has_printout=1)
		return machine, make_wash_program(machine.name, chemical=CHEMICAL, parameters=PARAMETERS)

	def complete_elsewhere(self, sets, washer=None):
		machine, program = washer or self.spare_washer()
		return self.complete(sets, program=program, machine=machine)

	def unload_args(self, batch, machine=None, station=STATION):
		return {
			"batch": batch,
			"equipment_raw": (machine or self.machine).name,
			"batch_raw": batch,
			"station": station,
		}

	def manual_data(self, batch, machine=None, station=STATION, key=None):
		return call(
			wash_api.manual_data,
			key=key,
			values=[{"parameter_name": "Nhiệt độ", "value": "93"}],
			started_at=str(add_to_date(now_datetime(), hours=-1)),
			ended_at=str(now_datetime()),
			confirmed=1,
			machine_file="/files/printout.png",
			reported_result="Pass",
			**self.unload_args(batch, machine, station),
		)

	def assert_rejection(self, result, code, status):
		self.assertIs(result["ok"], False, msg=result)
		self.assertEqual(result["error"]["code"], code)
		self.assertEqual(http_status(), status)
		for key in ("title", "reason", "action"):
			self.assertTrue(result["error"][key], msg=key)


class TestWashLoadApi(WashApiCase):
	@bru("BRU-REP-016")
	def test_start_then_add_set_then_complete_happy_path(self):
		started = call(wash_api.start, raw=f"]Q1{self.machine.name}\r\n", station=STATION)
		self.assertIs(started["ok"], True)
		self.assertEqual(started["equipment"]["name"], self.machine.name)
		self.assertEqual([p["program_code"] for p in started["programs"]], [self.program.name])
		self.assertTrue(any(lot["batch_no"] == self.lot.name for lot in started["chemical_lots"]))

		unit = make_wash_ready_set()
		added = call(
			wash_api.add_set, raw=unit.name, equipment=self.machine.name, queued="[]", station=STATION
		)
		self.assertIs(added["ok"], True)
		self.assertEqual((added["set_id"], added["duplicate"]), (unit.name, False))
		self.assertEqual([g["step"] for g in added["gates"]], list(step_gate.STEPS))
		again = call(
			wash_api.add_set, raw=unit.name, equipment=self.machine.name, queued=[unit.name], station=STATION
		)
		self.assertIs(again["duplicate"], True)

		done = self.complete([unit.name])
		self.assertIs(done["ok"], True)
		self.assertRegex(done["batch"], r"^LR-\d{6}-\d{2}$")
		self.assertEqual((done["sets"], done["rejected"]), ([unit.name], []))
		self.assertEqual(done["print"]["status"], "Waiting")
		employee = frappe.db.get_value("Employee", {"user_id": "Administrator"}, "name")
		self.assertEqual(frappe.db.get_value("Wash Batch", done["batch"], "operator"), employee)

	@bru("BRU-FLOW-004")
	def test_add_set_rejection_writes_audit_and_409(self):
		unit = make_set_unit()
		step_gate.start_cycle(unit.name)  # chưa qua T1
		before = frappe.db.count("Audit Log", {"action": "Reject"})
		result = call(
			wash_api.add_set, raw=unit.name, equipment=self.machine.name, queued=[], station=STATION
		)
		self.assert_rejection(result, "GATE_PREV_NOT_PASSED", 409)
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Reject"}), before + 1)
		row = frappe.get_all(
			"Audit Log",
			filters={"action": "Reject"},
			fields=["ref_doctype", "ref_name", "reason", "station"],
			order_by="creation desc, name desc",
			limit=1,
		)[0]
		self.assertEqual(
			(row.ref_doctype, row.ref_name, row.reason, row.station),
			("Set Unit", unit.name, "GATE_PREV_NOT_PASSED", STATION),
		)

	def test_add_set_and_complete_need_a_t2_station(self):
		self.login("Administrator", CLEAN_STATION)
		result = call(wash_api.start, raw=self.machine.name, station=CLEAN_STATION)
		self.assert_rejection(result, "STATION_WRONG_STEP", 422)

	def test_complete_replay_same_key_returns_same_batch(self):
		unit = make_wash_ready_set()
		key, ts = str(uuid.uuid4()), now_ts()
		first = call(
			wash_api.complete,
			key=key,
			client_ts=ts,
			equipment=self.machine.name,
			program=self.program.name,
			sets=[unit.name],
			chemicals=[{"item": CHEMICAL, "lot": self.lot.name}],
			station=STATION,
		)
		second = call(
			wash_api.complete,
			key=key,
			client_ts=ts,
			equipment=self.machine.name,
			program=self.program.name,
			sets=[unit.name],
			chemicals=[{"item": CHEMICAL, "lot": self.lot.name}],
			station=STATION,
		)
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("Wash Batch Set Unit", {"set_unit": unit.name}), 1)

	def test_complete_with_new_key_for_same_sets_rejected(self):
		unit = make_wash_ready_set()
		self.complete([unit.name])
		result = self.complete_elsewhere([unit.name])
		self.assert_rejection(result, "BATCH_EMPTY", 422)
		self.assertEqual(result["error"]["items"][0]["code"], "SET_IN_OTHER_BATCH")

	def test_http_status_by_error_code(self):
		self.assert_rejection(
			call(wash_api.lookup, raw="LR-000101-99", station=STATION), "WASH_BATCH_NOT_FOUND", 404
		)
		other_program = make_wash_program(make_wash_machine().name, chemical=CHEMICAL)
		self.assert_rejection(
			self.complete([make_wash_ready_set().name], program=other_program), "PROGRAM_INVALID", 422
		)
		retired = make_wash_machine()
		frappe.db.set_value("Equipment", retired.name, "status", "Retired")
		self.assert_rejection(
			call(wash_api.start, raw=retired.name, station=STATION), "EQUIPMENT_NOT_READY", 423
		)
		batch = self.complete([make_wash_ready_set().name])["batch"]
		other = make_wash_machine()
		self.assert_rejection(
			call(wash_api.unload, batch=batch, raw=other.name, station=STATION), "EQUIPMENT_MISMATCH", 409
		)

	def test_bad_parameters_are_400(self):
		with self.assertRaises(BadRequestError):
			call(wash_api.add_set, raw="x", equipment=self.machine.name, queued="not json", station=STATION)
		with self.assertRaises(BadRequestError):
			call(
				wash_api.complete,
				equipment=self.machine.name,
				program=self.program.name,
				sets=[1, 2],
				chemicals=[],
				station=STATION,
			)
		with self.assertRaises(BadRequestError):
			call(
				wash_api.complete,
				equipment=self.machine.name,
				program=self.program.name,
				sets=[],
				chemicals=["lot"],
				station=STATION,
			)

	def test_roles_complete_allows_r03_r05_denies_r06(self):
		for role in ("TC R03", "TC R05"):
			unit = make_wash_ready_set()
			washer = self.spare_washer()  # tạo bằng Administrator trước khi đổi sang user vai trò
			self.as_user(f"wash-{role[-3:].lower()}@test.local", (role,))
			self.assertIs(self.complete_elsewhere([unit.name], washer)["ok"], True, msg=role)
			frappe.set_user("Administrator")
		unit = make_wash_ready_set()
		self.as_user("wash-r06@test.local", ("TC R06",))
		before = counts()
		with self.assertRaises(frappe.PermissionError):
			self.complete([unit.name])
		self.assertEqual(counts(), before)

	def test_session_station_mismatch(self):
		token = TOKENS[("Administrator", STATION)]
		result = call(wash_api.start, raw=self.machine.name, station="TR-004", token=token)
		self.assertEqual(result["error"]["code"], "SESSION_STATION_MISMATCH")
		result = call(wash_api.start, raw=self.machine.name, station=STATION, token="bad")
		self.assertEqual(result["error"]["code"], "SESSION_INVALID")

	def test_lookup_does_not_write(self):
		batch = self.complete([make_wash_ready_set().name])["batch"]
		before = counts()
		info = call(wash_api.lookup, raw=batch, station=STATION)
		self.assertIs(info["ok"], True)
		self.assertEqual(info["batch"]["batch"], batch)
		self.assertEqual(counts(), before)

	@bru("BRU-FLOW-004")
	def test_redo_queue_endpoint_lists_failed_sets(self):
		unit = make_wash_ready_set()
		batch = self.complete([unit.name])["batch"]
		self.manual_data(batch)
		call(wash_api.result, result="Fail", clean_test="Fail", **self.unload_args(batch))
		before = counts()
		queue = call(wash_api.redo_queue, station=STATION)
		self.assertIs(queue["ok"], True)
		self.assertIn(
			{"set_id": unit.name, "set_name": queue["sets"][0]["set_name"], "redo_count": 1}, queue["sets"]
		)
		self.assertEqual(counts(), before)

	def test_redo_queue_endpoint_also_lists_running_batches(self):
		batch = self.complete([make_wash_ready_set().name])["batch"]
		queue = call(wash_api.redo_queue, station=STATION)
		self.assertIn(batch, [row["batch"] for row in queue["running"]])

	def test_redo_queue_endpoint_also_lists_sets_waiting_to_wash(self):
		waiting, loaded = make_wash_ready_set(), make_wash_ready_set()
		self.complete([loaded.name])
		before = counts()
		queue = call(wash_api.redo_queue, station=STATION)
		names = [row["set_id"] for row in queue["waiting"]]
		self.assertIn(waiting.name, names)
		self.assertNotIn(loaded.name, names)
		self.assertEqual(counts(), before)


class TestWashUnloadApi(WashApiCase):
	def test_unload_then_manual_data_then_result(self):
		units = [make_wash_ready_set(), make_wash_ready_set()]
		batch = self.complete([u.name for u in units])["batch"]
		self.assertEqual(
			call(wash_api.unload, batch=batch, raw=self.machine.name, station=STATION),
			{"ok": True, "kind": "equipment"},
		)
		self.assertEqual(
			call(wash_api.unload, batch=batch, raw=batch, station=STATION), {"ok": True, "kind": "wash_batch"}
		)
		context = call(wash_api.unload_context, **self.unload_args(batch))
		self.assertEqual(context["batch"]["parameter_schema"][0]["parameter_name"], "Nhiệt độ")
		saved = self.manual_data(batch)
		self.assertEqual((saved["ok"], saved["data_complete"], saved["missing"]), (True, 1, []))
		employee = frappe.db.get_value("Employee", {"user_id": "Administrator"}, "name")
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, "manual_confirmed_by"), employee)
		result = call(wash_api.result, result="Pass", clean_test="Pass", note="ok", **self.unload_args(batch))
		self.assertIs(result["ok"], True)
		self.assertEqual({s["status"] for s in result["sets"]}, {"Processing"})
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, "status"), "Passed")

	def test_result_replay_does_not_double_count_redo(self):
		unit = make_wash_ready_set()
		batch = self.complete([unit.name])["batch"]
		self.manual_data(batch)
		key, ts = str(uuid.uuid4()), now_ts()
		args = {
			"key": key,
			"client_ts": ts,
			"result": "Fail",
			"clean_test": "Fail",
			**self.unload_args(batch),
		}
		first = call(wash_api.result, **args)
		second = call(wash_api.result, **args)
		self.assertEqual(first, second)
		self.assertEqual(first["sets"][0]["redo_count"], 1)
		self.assertEqual(step_gate.gates(unit.name)[1]["redo_count"], 1)
		again = call(wash_api.result, result="Fail", clean_test="Fail", **self.unload_args(batch))
		self.assert_rejection(again, "BATCH_NOT_RUNNING", 409)

	def test_unload_allows_r04_at_exit_door(self):
		two_door = make_wash_machine(zone_out="ZONE-CLEAN", has_printout=1)
		program = make_wash_program(two_door.name, chemical=CHEMICAL, parameters=PARAMETERS)
		batch = self.complete([make_wash_ready_set().name], program=program, machine=two_door)["batch"]
		self.as_user("wash-r04@test.local", ("TC R04",), station=CLEAN_STATION)
		result = call(wash_api.unload, batch=batch, raw=two_door.name, station=CLEAN_STATION)
		self.assertEqual(result, {"ok": True, "kind": "equipment"})
		self.assertIs(self.manual_data(batch, machine=two_door, station=CLEAN_STATION)["ok"], True)
		done = call(
			wash_api.result,
			result="Pass",
			clean_test="Pass",
			**self.unload_args(batch, two_door, CLEAN_STATION),
		)
		self.assertIs(done["ok"], True, msg=done)
		# R04 không được nạp lô
		with self.assertRaises(frappe.PermissionError):
			call(wash_api.redo_queue, station=CLEAN_STATION)

	@bru("BRU-REP-015")
	def test_old_machine_pass_with_r02_pin_proof(self):
		old = make_wash_machine()
		program = make_wash_program(old.name, chemical=CHEMICAL, parameters=PARAMETERS)
		batch = self.complete([make_wash_ready_set().name], program=program, machine=old)["batch"]
		user = self.as_user("wash-api-r02@test.local", ("TC R02",))
		self.assertIs(self.manual_data(batch, machine=old)["ok"], True)
		denied = call(wash_api.result, result="Pass", clean_test="Pass", **self.unload_args(batch, old))
		self.assert_rejection(denied, "R02_CONFIRM_REQUIRED", 409)
		employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
		station_auth.set_pin(employee, "135790")
		token = TOKENS[(user, STATION)]
		proof = station_auth.create_pin_proof(token, "135790")["proof"]
		done = call(
			wash_api.result,
			result="Pass",
			clean_test="Pass",
			reviewer_proof=proof,
			**self.unload_args(batch, old),
		)
		self.assertIs(done["ok"], True, msg=done)
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, "reviewer"), user)


class TestWashRefreshAndDraft(WashApiCase):
	"""Tra lại lô hóa chất và nháp danh sách đang nạp theo phiên trạm (A-72)."""

	def draft_payload(self, sets=("S-1",)):
		return {
			"machine": {"name": self.machine.name},
			"program": self.program.name,
			"lot": self.lot.name,
			"sets": [{"set_id": set_id, "set_name": "Bộ", "gates": []} for set_id in sets],
		}

	def test_refresh_lots_returns_a_lot_received_after_the_scan(self):
		started = call(wash_api.start, raw=self.machine.name, station=STATION)
		new_lot = make_chemical_batch(CHEMICAL, expiry_days=10, qty=3)
		refreshed = call(wash_api.refresh_lots, equipment=self.machine.name, station=STATION)
		self.assertIs(refreshed["ok"], True)
		self.assertIn(new_lot.name, [lot["batch_no"] for lot in refreshed["chemical_lots"]])
		self.assertNotIn(new_lot.name, [lot["batch_no"] for lot in started["chemical_lots"]])
		program = refreshed["programs"][0]
		self.assertEqual(program["chemicals"][0]["item"], CHEMICAL)

	def test_refresh_lots_needs_a_t2_station(self):
		self.login("Administrator", CLEAN_STATION)
		result = call(wash_api.refresh_lots, equipment=self.machine.name, station=CLEAN_STATION)
		self.assert_rejection(result, "STATION_WRONG_STEP", 422)

	def test_draft_survives_between_calls_of_the_same_session(self):
		saved = call(wash_api.save_draft, draft=self.draft_payload(("S-1", "S-2")), station=STATION)
		self.assertIs(saved["ok"], True)
		loaded = call(wash_api.draft, station=STATION)
		self.assertEqual([row["set_id"] for row in loaded["draft"]["sets"]], ["S-1", "S-2"])
		self.assertEqual(loaded["draft"]["machine"]["name"], self.machine.name)

	def test_empty_draft_clears_it(self):
		call(wash_api.save_draft, draft=self.draft_payload(), station=STATION)
		call(wash_api.save_draft, draft=None, station=STATION)
		self.assertIsNone(call(wash_api.draft, station=STATION)["draft"])

	def test_draft_must_be_an_object_with_a_machine_and_a_list_of_sets(self):
		for bad in ("[]", '{"sets": []}', '{"machine": {"name": "x"}, "sets": "S-1"}', "not json"):
			with self.assertRaises(BadRequestError):
				call(wash_api.save_draft, draft=bad, station=STATION)

	def test_complete_clears_the_draft(self):
		unit = make_wash_ready_set()
		call(wash_api.save_draft, draft=self.draft_payload((unit.name,)), station=STATION)
		self.assertIs(self.complete([unit.name])["ok"], True)
		self.assertIsNone(call(wash_api.draft, station=STATION)["draft"])


class TestWashLabelPdf(WashApiCase):
	def done_batch(self):
		return self.complete([make_wash_ready_set().name])

	def test_returns_pdf_named_after_the_batch_with_its_qr_and_text(self):
		done = self.done_batch()
		before = frappe.db.count("Print Job")
		result = call(wash_api.label_pdf, batch=done["batch"], station=STATION)
		self.assertIs(result["ok"], True, msg=result)
		self.assertEqual(result["filename"], f"{done['batch']}.pdf")
		pdf = base64.b64decode(result["pdf_b64"])
		self.assertTrue(pdf.startswith(b"%PDF"))
		page = PdfReader(io.BytesIO(pdf)).pages[0]
		decoded = qr.decode_png(page.images[0].data)
		self.assertEqual(decoded, done["batch"])
		self.assertEqual(gs1.parse_scan(decoded)["type"], "wash_batch")
		text = page.extract_text()
		started = frappe.db.get_value("Wash Batch", done["batch"], "started_at")
		self.assertIn(done["batch"], text)
		self.assertIn(get_datetime(started).strftime("%d/%m/%Y %H:%M"), text)
		self.assertEqual(frappe.db.count("Print Job"), before)

	def test_unknown_code_is_not_found(self):
		result = call(wash_api.label_pdf, batch="LR-000000-99", station=STATION)
		self.assertEqual(result["error"]["code"], "WASH_BATCH_NOT_FOUND")
		self.assertEqual(frappe.local.response.get("http_status_code"), 404)

	def test_wrong_session_station_is_refused(self):
		done = self.done_batch()
		token = TOKENS[("Administrator", STATION)]
		result = call(wash_api.label_pdf, batch=done["batch"], station=CLEAN_STATION, token=token)
		self.assertEqual(result["error"]["code"], "SESSION_STATION_MISMATCH")
