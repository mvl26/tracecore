"""Kiểm đếm theo BOM tại T3 (FEAT-020, UC-07): mở bộ, ghi dòng, xác nhận thiếu của R02, ghi sổ và cổng T3."""

from unittest.mock import patch

import frappe

from tracecore.core import client_time, extension, gs1, station_auth, step_gate
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import assembly
from tracecore.tests.factories import (
	make_cycle,
	make_set_type,
	make_set_unit,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-003"  # T3 Assembly, khu sạch
T4_STATION = "TR-004"
BOM = [("T3-KEO", 2), ("T3-KEP", 1), ("T3-DAO", 3)]
PIN = "135790"
PHOTO = "/files/t3-damaged.png"


def _code(fn, *args, **kwargs):
	try:
		fn(*args, **kwargs)
	except BlockedError as error:
		return error.block.code
	return None


def _hook_calls(hook):
	"""Bao `extension.run` để ghi lại ctx của `hook`; trả (patcher, list ctx)."""
	calls = []
	real = extension.run

	def spy(name, *args, **kwargs):
		if name == hook:
			calls.append(args[0])
		return real(name, *args, **kwargs)

	return patch.object(assembly.extension, "run", side_effect=spy), calls


class AssemblyCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.ts = client_time.utc_now()

	def washed_set(self, code="T3A", passed=("T1", "T2")):
		unit = make_set_unit(make_set_type(code, bom=BOM).name)
		make_cycle(unit, passed=passed)
		return unit.name

	def open(self, set_id, station=STATION):
		return assembly.open_set(set_id, station, self.ts)

	def line(self, name, **fields):
		return assembly.line(name, STATION, self.ts, **fields)

	def count_all(self, name, **short):
		"""Đếm đủ mọi dòng BOM, trừ các dòng trong `short` ({mã: số lượng thực tế})."""
		for code, qty in BOM:
			self.line(name, instrument=code, actual_qty=short.get(code, qty))

	def r02_proof(self, email="t3-r02@test.local"):
		"""(session, proof) của R02 đã nhập đúng PIN tại trạm T3."""
		user = make_user(email, roles=("TC R02",))
		login = make_station_session(user, station=STATION)
		employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
		station_auth.set_pin(employee, PIN)
		self.addCleanup(station_auth.clear_pin_rate_limit, employee)
		proof = station_auth.create_pin_proof(login["token"], PIN)["proof"]
		return login["session"], proof, user


class TestOpen(AssemblyCase):
	@bru("BRU-FLOW-002")
	def test_open_shows_bom_with_photos_gates_and_creates_a_draft(self):
		su = self.washed_set()
		ctx = self.open(su)
		self.assertEqual((ctx["set"]["set_id"], ctx["cycle_no"], ctx["docstatus"]), (su, 1, 0))
		self.assertEqual([line["instrument"] for line in ctx["lines"]], [code for code, _q in BOM])
		self.assertEqual([line["bom_qty"] for line in ctx["lines"]], [2, 1, 3])
		self.assertTrue(all(not line["counted"] for line in ctx["lines"]))
		self.assertEqual(ctx["bom_version"], 1)
		self.assertIn("thumbnail", ctx["lines"][0])
		self.assertIn("tray_images", ctx)
		self.assertEqual(ctx["receipt_notes"], [])
		self.assertEqual([g["step"] for g in ctx["gates"]], list(step_gate.STEPS))
		self.assertEqual(ctx["gates"][1]["result"], "Pass")
		self.assertTrue(ctx["pack_locked"])
		draft = frappe.get_doc("Assembly Record", ctx["assembly"])
		self.assertEqual((draft.docstatus, draft.station, draft.bom_version), (0, STATION, 1))

	def test_open_again_resumes_the_same_draft_and_counts(self):
		su = self.washed_set()
		name = self.open(su)["assembly"]
		self.line(name, instrument="T3-KEO", actual_qty=2)
		again = self.open(su)
		self.assertEqual(again["assembly"], name)
		self.assertTrue(next(l for l in again["lines"] if l["instrument"] == "T3-KEO")["counted"])
		self.assertEqual(frappe.db.count("Assembly Record", {"set_unit": su}), 1)

	@bru("BRU-FLOW-004")
	def test_set_without_passed_wash_is_blocked(self):
		su = self.washed_set(passed=("T1",))
		self.assertEqual(_code(self.open, su), "GATE_PREV_NOT_PASSED")
		self.assertEqual(frappe.db.count("Assembly Record", {"set_unit": su}), 0)

	def test_set_that_failed_wash_is_blocked_too(self):
		su = self.washed_set(passed=("T1",))
		step_gate.record(su, "T2", "Fail")
		self.assertEqual(_code(self.open, su), "GATE_PREV_NOT_PASSED")

	@bru("BRU-FLOW-002")
	def test_wrong_station_and_bad_codes(self):
		su = self.washed_set()
		self.assertEqual(_code(self.open, su, T4_STATION), "STATION_WRONG_STEP")
		self.assertEqual(_code(self.open, su, "ZONE-CLEAN"), "STATION_WRONG_STEP")
		self.assertEqual(_code(self.open, "XYZ-123"), "SCAN_INVALID")
		self.assertEqual(_code(self.open, "TB-0001"), "SCAN_INVALID")
		self.assertEqual(_code(self.open, gs1.make_giai(gs1.configured_company_prefix(), "S-999999")), "SET_NOT_FOUND")

	def test_set_that_already_passed_t3_is_blocked(self):
		su = self.washed_set()
		name = self.open(su)["assembly"]
		self.count_all(name)
		assembly.submit(name, STATION, self.ts)
		self.assertEqual(_code(self.open, su), "STEP_ALREADY_PASSED")

	def test_set_without_bom_is_blocked(self):
		unit = make_set_unit()
		make_cycle(unit, passed=("T1", "T2"))
		self.assertEqual(_code(self.open, unit.name), "BOM_INCOMPLETE")

	def test_end_of_life_set_is_blocked(self):
		su = self.washed_set()
		step_gate.end_of_life(su, "Par Exceeded")
		self.assertEqual(_code(self.open, su), "SET_END_OF_LIFE")

	@bru("BRU-PAR-003")
	def test_par_warning_is_read_only_and_does_not_block(self):
		su = self.washed_set()
		frappe.db.set_value("Set Unit", su, {"max_cycles": 100}, update_modified=False)
		frappe.db.set_value("Set Unit", su, "cycles_used", 95, update_modified=False)
		ctx = self.open(su)
		self.assertEqual(ctx["par"]["state"], "warn")
		self.assertTrue(ctx["pack_locked"])  # chưa đếm: khóa vì chưa ghi sổ, không phải vì cơ số

	def test_foreign_cycle_draft_is_not_reused(self):
		su = self.washed_set()
		first = self.open(su)["assembly"]
		step_gate.start_cycle(su)
		step_gate.record(su, "T1", "Pass")
		step_gate.record(su, "T2", "Pass")
		second = self.open(su)
		self.assertNotEqual(second["assembly"], first)
		self.assertEqual(second["cycle_no"], 2)


class TestLine(AssemblyCase):
	@bru("BRU-REP-003")
	def test_line_status_enough_short_over(self):
		name = self.open(self.washed_set())["assembly"]
		self.line(name, instrument="T3-KEO", actual_qty=1)
		self.line(name, instrument="T3-KEP", actual_qty=1)
		ctx = self.line(name, instrument="T3-DAO", actual_qty=4)
		status = {l["instrument"]: (l["line_status"], l["missing_qty"]) for l in ctx["lines"]}
		self.assertEqual(status, {"T3-KEO": ("Short", 1), "T3-KEP": ("Enough", 0), "T3-DAO": ("Over", 0)})
		self.assertTrue(ctx["has_shortage"])
		self.assertEqual([i["instrument"] for i in ctx["shortage_items"]], ["T3-KEO"])
		self.assertTrue(ctx["pack_locked"])

	def test_all_ok_counts_every_pending_line_at_bom_quantity(self):
		name = self.open(self.washed_set())["assembly"]
		self.line(name, instrument="T3-KEO", actual_qty=1)
		ctx = self.line(name, all_ok=True)
		self.assertEqual(
			{l["instrument"]: l["actual_qty"] for l in ctx["lines"]},
			{"T3-KEO": 1, "T3-KEP": 1, "T3-DAO": 3},  # dòng đã đếm giữ nguyên
		)
		self.assertTrue(all(l["counted"] for l in ctx["lines"]))

	@bru("BRU-REP-003")
	def test_damaged_and_replaced_from_spare_stock(self):
		name = self.open(self.washed_set())["assembly"]
		ctx = self.line(
			name,
			instrument="T3-KEO",
			actual_qty=2,
			damaged_qty=1,
			replaced_qty=1,
			disposition="Repair",
			note="Gãy khớp",
		)
		keo = next(l for l in ctx["lines"] if l["instrument"] == "T3-KEO")
		self.assertEqual((keo["line_status"], keo["damaged_qty"], keo["replaced_qty"]), ("Enough", 1, 1))
		self.assertEqual((keo["disposition"], keo["replacement_instrument"]), ("Repair", "T3-KEO"))
		self.assertEqual(self.line(name, instrument="T3-KEO", replacement_instrument="T3-KEP")["lines"][0]["replacement_instrument"], "T3-KEP")

	def test_invalid_quantities_are_rejected_without_writing(self):
		name = self.open(self.washed_set())["assembly"]
		for bad in ({"actual_qty": -1}, {"actual_qty": "x"}, {"actual_qty": 10000}, {"actual_qty": True}):
			self.assertEqual(_code(self.line, name, instrument="T3-KEO", **bad), "QTY_INVALID", bad)
		self.assertEqual(
			_code(self.line, name, instrument="T3-KEO", actual_qty=1, damaged_qty=1, replaced_qty=2, disposition="Repair"),
			"QTY_INVALID",
		)
		self.assertEqual(_code(self.line, name, instrument="T3-KEO", actual_qty=1, damaged_qty=1), "QTY_INVALID")
		self.assertEqual(_code(self.line, name, instrument="T3-KEO", actual_qty=1, disposition="Burn"), "QTY_INVALID")
		self.assertEqual(_code(self.line, name, instrument="T3-LA", actual_qty=1), "INSTRUMENT_NOT_FOUND")
		self.assertFalse(frappe.db.get_value("Assembly Line", {"parent": name, "instrument": "T3-KEO"}, "counted"))

	def test_photo_must_be_an_uploaded_file(self):
		name = self.open(self.washed_set())["assembly"]
		self.assertEqual(_code(self.line, name, instrument="T3-KEO", actual_qty=1, photo="/files/none.png"), "PHOTO_INVALID")
		frappe.get_doc({"doctype": "File", "file_name": "t3-damaged.png", "file_url": PHOTO, "content": b"x", "is_private": 0}).insert(ignore_permissions=True)
		ctx = self.line(name, instrument="T3-KEO", actual_qty=1, photo=PHOTO)
		self.assertEqual(ctx["lines"][0]["photo"], PHOTO)

	def test_unknown_or_closed_assembly(self):
		su = self.washed_set()
		self.assertEqual(_code(self.line, "AS-2026-99999", instrument="T3-KEO", actual_qty=1), "ASSEMBLY_NOT_FOUND")
		name = self.open(su)["assembly"]
		self.assertEqual(_code(assembly.line, name, T4_STATION, self.ts, instrument="T3-KEO", actual_qty=1), "STATION_WRONG_STEP")
		self.count_all(name)
		assembly.submit(name, STATION, self.ts)
		self.assertEqual(_code(self.line, name, instrument="T3-KEO", actual_qty=1), "ASSEMBLY_CLOSED")

	@bru("BRU-REP-003")
	def test_shortage_flags_nc_once_and_clears_when_fixed(self):
		name = self.open(self.washed_set())["assembly"]
		patcher, calls = _hook_calls(assembly.NC_HOOK)
		with patcher:
			self.line(name, instrument="T3-KEO", actual_qty=0)
			self.line(name, instrument="T3-KEP", actual_qty=0)  # vẫn thiếu: không bắn hook lần hai
		self.assertEqual(len(calls), 1)
		self.assertEqual((calls[0]["assembly"], calls[0]["kind"]), (name, "Shortage"))
		self.assertEqual(frappe.db.get_value("Assembly Record", name, "nc_pending"), 1)
		self.assertTrue(
			frappe.db.exists("Audit Log", {"ref_doctype": "Assembly Record", "ref_name": name, "reason": "AssemblyShortage"})
		)
		self.line(name, instrument="T3-KEO", actual_qty=2)
		self.line(name, instrument="T3-KEP", actual_qty=1)
		self.assertEqual(frappe.db.get_value("Assembly Record", name, "nc_pending"), 0)


class TestScanInstrument(AssemblyCase):
	def setUp(self):
		super().setUp()
		prefix = gs1.configured_company_prefix()
		self.codes = {code: gs1.make_instrument_giai(prefix, 90001 + i) for i, (code, _q) in enumerate(BOM)}
		self.foreign = gs1.make_instrument_giai(prefix, 90099)
		self.name = self.open(self.washed_set())["assembly"]
		for code, giai in self.codes.items():
			frappe.db.set_value("Instrument", code, "giai_code", giai, update_modified=False)
		make_set_type("T3X", bom=[("T3-LA", 1)])
		frappe.db.set_value("Instrument", "T3-LA", "giai_code", self.foreign, update_modified=False)
		self.set_flag(1)

	def set_flag(self, on):
		frappe.db.set_single_value("TraceCore Settings", "enable_instrument_giai", on)

	@bru("BRU-ID-004")
	def test_scan_ticks_the_matching_bom_line(self):
		ctx = self.line(self.name, raw=self.codes["T3-KEO"])
		keo = next(l for l in ctx["lines"] if l["instrument"] == "T3-KEO")
		self.assertEqual((keo["counted"], keo["actual_qty"]), (1, 1))
		self.assertEqual(ctx["scanned"]["instrument"], "T3-KEO")
		again = self.line(self.name, raw=self.codes["T3-KEO"])
		self.assertEqual(next(l for l in again["lines"] if l["instrument"] == "T3-KEO")["line_status"], "Enough")

	@bru("BRU-ID-004")
	def test_foreign_instrument_warns_and_flags_nc(self):
		patcher, calls = _hook_calls(assembly.NC_HOOK)
		with patcher:
			ctx = self.line(self.name, raw=self.foreign)
		self.assertEqual(ctx["warning"]["code"], "FOREIGN_INSTRUMENT")
		self.assertEqual(ctx["foreign_instruments"], ["T3-LA"])
		self.assertEqual((calls[0]["kind"], calls[0]["items"]), ("Foreign Instrument", ["T3-LA"]))
		self.assertEqual(frappe.db.get_value("Assembly Record", self.name, "nc_pending"), 1)
		self.assertFalse(any(l["counted"] for l in ctx["lines"]))

	def test_scan_rejections(self):
		self.assertEqual(_code(self.line, self.name, raw=gs1.make_instrument_giai(gs1.configured_company_prefix(), 90555)), "INSTRUMENT_NOT_FOUND")
		self.assertEqual(_code(self.line, self.name, raw="XYZ-123"), "SCAN_INVALID")
		self.assertEqual(_code(self.line, self.name, raw=frappe.db.get_value("Assembly Record", self.name, "set_unit")), "SCAN_INVALID")
		self.set_flag(0)
		self.assertEqual(_code(self.line, self.name, raw=self.codes["T3-KEO"]), "FEATURE_DISABLED")


class TestConfirmShortage(AssemblyCase):
	def short_draft(self):
		su = self.washed_set()
		name = self.open(su)["assembly"]
		self.count_all(name, **{"T3-KEO": 0})
		return su, name

	def confirm(self, name, reason="Ca mổ gấp", proof=None, session=None):
		return assembly.confirm_shortage(name, reason, STATION, proof, session, self.ts)

	@bru("BRU-REP-003")
	def test_confirm_needs_a_shortage_a_reason_and_an_r02_pin_proof(self):
		su = self.washed_set()
		whole = self.open(su)["assembly"]
		self.count_all(whole)
		session, proof, _user = self.r02_proof()
		self.assertEqual(_code(self.confirm, whole, proof=proof, session=session), "NO_SHORTAGE")
		_su, name = self.short_draft()
		session, proof, _user = self.r02_proof("t3-r02b@test.local")
		self.assertEqual(_code(self.confirm, name, reason="  ", proof=proof, session=session), "REASON_REQUIRED")
		self.assertEqual(_code(self.confirm, name, reason="x" * 501, proof=proof, session=session), "REASON_REQUIRED")
		self.assertEqual(_code(self.confirm, name, proof=None, session=session), "R02_CONFIRM_REQUIRED")
		self.assertEqual(_code(self.confirm, name, proof="not-a-proof", session=session), "R02_CONFIRM_REQUIRED")
		self.assertEqual(frappe.db.get_value("Assembly Record", name, "shortage_confirmed"), 0)

	def test_proof_of_a_non_r02_user_is_refused(self):
		_su, name = self.short_draft()
		user = make_user("t3-r04@test.local", roles=("TC R04",))
		login = make_station_session(user, station=STATION)
		employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
		station_auth.set_pin(employee, PIN)
		proof = station_auth.create_pin_proof(login["token"], PIN)["proof"]
		self.assertEqual(_code(self.confirm, name, proof=proof, session=login["session"]), "R02_CONFIRM_REQUIRED")

	@bru("BRU-REP-003")
	def test_confirmed_shortage_unlocks_packing_and_lists_missing_instruments(self):
		su, name = self.short_draft()
		self.assertEqual(_code(assembly.submit, name, STATION, self.ts), "SHORTAGE_UNCONFIRMED")
		session, proof, user = self.r02_proof()
		ctx = self.confirm(name, "Ca mổ gấp, bổ sung sau", proof, session)
		self.assertTrue(ctx["shortage_confirmed"])
		self.assertEqual((ctx["shortage_confirmed_by"], ctx["shortage_reason"]), (user, "Ca mổ gấp, bổ sung sau"))
		self.assertTrue(ctx["ready_to_submit"])  # đã đủ điều kiện ghi sổ; Đóng gói mở khi cổng T3 Đạt
		done = assembly.submit(name, STATION, self.ts)
		self.assertEqual((done["result"], done["pack_locked"]), ("Pass", False))
		self.assertIsNone(step_gate.check(su, "T4"))
		self.assertIn("T3-KEO", frappe.db.get_value("Assembly Record", name, "shortage_summary"))

	@bru("BRU-REP-003")
	def test_pin_proof_is_single_use_and_wrong_pin_locks_for_five_minutes(self):
		_su, name = self.short_draft()
		session, proof, _user = self.r02_proof()
		self.confirm(name, proof=proof, session=session)
		self.assertEqual(_code(self.confirm, name, proof=proof, session=session), "R02_CONFIRM_REQUIRED")  # dùng lại proof
		user = make_user("t3-lock@test.local", roles=("TC R02",))
		login = make_station_session(user, station=STATION)
		employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
		station_auth.set_pin(employee, PIN)
		self.addCleanup(station_auth.clear_pin_rate_limit, employee)
		codes = [_code(station_auth.create_pin_proof, login["token"], "000000") for _i in range(3)]
		self.assertEqual(codes, ["PIN_INVALID", "PIN_INVALID", "PIN_LOCKED"])
		self.assertEqual(_code(station_auth.create_pin_proof, login["token"], PIN), "PIN_LOCKED")
		self.assertEqual(_code(self.confirm, name, proof=None, session=login["session"]), "R02_CONFIRM_REQUIRED")

	def test_changing_counts_after_confirmation_withdraws_it(self):
		_su, name = self.short_draft()
		session, proof, _user = self.r02_proof()
		self.confirm(name, proof=proof, session=session)
		ctx = self.line(name, instrument="T3-KEO", actual_qty=1)  # vẫn thiếu nhưng khác lúc xác nhận
		self.assertFalse(ctx["shortage_confirmed"])
		self.assertEqual(_code(assembly.submit, name, STATION, self.ts), "SHORTAGE_UNCONFIRMED")


class TestSubmit(AssemblyCase):
	@bru("BRU-FLOW-004")
	def test_submit_whole_count_records_t3_pass_and_opens_t4(self):
		su = self.washed_set()
		name = self.open(su)["assembly"]
		self.assertEqual(step_gate.check(su, "T4").code, "GATE_PREV_NOT_PASSED")
		self.count_all(name)
		done = assembly.submit(name, STATION, self.ts, notes="Đủ")
		self.assertEqual((done["result"], done["docstatus"]), ("Pass", 1))
		doc = frappe.get_doc("Assembly Record", name)
		self.assertEqual((doc.docstatus, doc.result, doc.notes, doc.assembled_by_user), (1, "Pass", "Đủ", "Administrator"))
		self.assertIsNotNone(doc.assembled_at)
		gate = frappe.get_doc("Step Gate Result", f"{su}-C1-T3")
		self.assertEqual((gate.result, gate.ref_name, gate.station), ("Pass", name, STATION))
		self.assertIsNone(step_gate.check(su, "T4"))
		self.assertFalse(done["pack_locked"])
		self.assertEqual(done["next_station"], T4_STATION)

	def test_submit_requires_every_line_counted(self):
		su = self.washed_set()
		name = self.open(su)["assembly"]
		self.line(name, instrument="T3-KEO", actual_qty=2)
		block = None
		try:
			assembly.submit(name, STATION, self.ts)
		except BlockedError as error:
			block = error.block
		self.assertEqual(block.code, "LINES_NOT_COUNTED")
		self.assertEqual(block.items, ["T3-KEP", "T3-DAO"])
		self.assertEqual(step_gate.gates(su)[2]["result"], "Pending")
		self.assertEqual(frappe.db.get_value("Assembly Record", name, "docstatus"), 0)

	@bru("BRU-FLOW-003")
	def test_branch_sends_set_to_repair_or_disposal_via_failed_t3(self):
		su = self.washed_set()
		name = self.open(su)["assembly"]
		self.line(name, instrument="T3-KEO", actual_qty=0, damaged_qty=2, disposition="Dispose")
		self.assertEqual(_code(assembly.submit, name, STATION, self.ts, branch="Burn", branch_reason="x"), "BRANCH_INVALID")
		self.assertEqual(_code(assembly.submit, name, STATION, self.ts, branch="Repair", branch_reason=" "), "REASON_REQUIRED")
		patcher, calls = _hook_calls(assembly.AFTER_HOOK)
		with patcher:
			done = assembly.submit(name, STATION, self.ts, branch="Disposal", branch_reason="Hỏng nặng, không sửa được")
		self.assertEqual((done["result"], done["branch"]), ("Fail", "Disposal"))
		self.assertEqual(step_gate.gates(su)[2], {"step": "T3", "result": "Fail", "redo_count": 1})
		self.assertEqual(frappe.db.get_value("Set Unit", su, "status"), "Reprocess")
		self.assertEqual(step_gate.check(su, "T4").code, "GATE_PREV_NOT_PASSED")
		self.assertEqual((calls[0]["branch"], calls[0]["result"], calls[0]["damaged"][0]["instrument"]), ("Disposal", "Fail", "T3-KEO"))
		self.assertTrue(
			frappe.db.exists("Audit Log", {"ref_doctype": "Assembly Record", "ref_name": name, "reason": "AssemblyBranch"})
		)

	def test_after_assembly_hook_runs_on_pass(self):
		su = self.washed_set()
		name = self.open(su)["assembly"]
		self.count_all(name)
		patcher, calls = _hook_calls(assembly.AFTER_HOOK)
		with patcher:
			assembly.submit(name, STATION, self.ts)
		self.assertEqual((calls[0]["assembly"], calls[0]["result"], calls[0]["branch"]), (name, "Pass", None))

	def test_failed_submit_leaves_gate_and_draft_untouched(self):
		su = self.washed_set()
		name = self.open(su)["assembly"]
		self.count_all(name)
		with patch.object(step_gate, "record", side_effect=RuntimeError("boom")), self.assertRaises(RuntimeError):
			assembly.submit(name, STATION, self.ts)
		self.assertEqual(frappe.db.get_value("Assembly Record", name, "docstatus"), 0)
		self.assertEqual(step_gate.gates(su)[2]["result"], "Pending")

	def test_submit_rechecks_the_previous_gate(self):
		su = self.washed_set()
		name = self.open(su)["assembly"]
		self.count_all(name)
		step_gate.record(su, "T2", "Fail")
		self.assertEqual(_code(assembly.submit, name, STATION, self.ts), "GATE_PREV_NOT_PASSED")
		self.assertEqual(frappe.db.get_value("Assembly Record", name, "docstatus"), 0)

	def test_t4_context_still_reads_the_assembly_record(self):
		from tracecore.reprocessing import packing

		su = self.washed_set()
		name = self.open(su)["assembly"]
		self.count_all(name)
		assembly.submit(name, STATION, self.ts)
		unit = frappe.db.get_value("Set Unit", su, ["name", "current_cycle_no"], as_dict=True)
		self.assertEqual(packing._assembly(unit), name)
