"""Dỡ mẻ, chỉ thị, giải phóng bằng PIN R02, cách ly chờ BI, mẻ Không đạt (FEAT-023; FR-M2-11, FR-M2-12.2, FR-M2-25;
UC-10; BRU-REP-005, BRU-REP-006, BRU-REP-007, BRU-REP-015, BRU-REP-016, BRU-FLOW-004)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime, today

from tracecore.core import client_time, station_auth, step_gate
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import releasing, sterilizing
from tracecore.tests.factories import (
	make_employee,
	make_load,
	make_load_ready_pack,
	make_sterilize_program,
	make_sterilizer,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-005"  # T5 Sterilization
PARAMETERS = [
	{"parameter_name": "Temperature", "unit": "°C", "min_value": 132, "max_value": 138, "required": 1},
	{"parameter_name": "Pressure", "unit": "bar", "min_value": 0, "max_value": 2.3, "required": 1},
]


def blocked(case, fn, *args, **kwargs):
	with case.assertRaises(BlockedError) as raised:
		fn(*args, **kwargs)
	return raised.exception.block


class ReleaseCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.machine = make_sterilizer()
		self.program = make_sterilize_program(self.machine.name, parameters=PARAMETERS)
		self.employee = make_employee()
		self.packs = [make_load_ready_pack(), make_load_ready_pack()]
		self.load = make_load(self.machine, self.program, self.packs, operator=self.employee.name)
		self.r02 = make_user("rel-r02@test.local", roles=("TC R02",))
		self.r01 = make_user("rel-r01@test.local", roles=("TC R01",))
		self.r05 = make_user("rel-r05@test.local", roles=("TC R05",))

	def save_data(self, **overrides):
		values = {"Temperature": "134", "Pressure": "2,1", **overrides}
		return sterilizing.save_manual_data(
			load=self.load.name,
			equipment_raw=self.machine.name,
			load_raw=self.load.name,
			values=[{"parameter_name": key, "value": value} for key, value in values.items()],
			# không lùi qua 00:00 hôm nay: mẻ lấy test hằng ngày theo ngày bắt đầu, chạy test lúc 00:30 vẫn đúng ngày
			started_at=str(max(add_to_date(now_datetime(), hours=-1), get_datetime(today()))),
			ended_at=str(now_datetime()),
			machine_alerts=None,
			machine_report="/files/printout.png",
			reason=None,
			confirmed=True,
			card=self.employee.tc_card_id,
			client_ts=client_time.utc_now(),
			employee=self.employee.name,
			station=STATION,
		)

	def scans(self, **extra):
		return {
			"load": self.load.name,
			"station": STATION,
			"equipment_raw": self.machine.name,
			"load_raw": self.load.name,
			**extra,
		}

	def result(self, result="Pass", confirmed=True):
		return releasing.set_cycle_result(
			**self.scans(), result=result, confirmed=confirmed, employee=self.employee.name
		)

	def indicator(self, indicator, result="Pass", **extra):
		return releasing.record_indicator(
			**self.scans(), indicator=indicator, result=result, employee=self.employee.name, **extra
		)

	def good_steam_indicators(self):
		self.indicator("chemical_class_5")
		self.indicator("bowie_dick", test_date=today())

	def ready(self):
		self.save_data()
		self.result()
		self.good_steam_indicators()

	def proof_of(self, user, pin="246810"):
		session = make_station_session(user, station=STATION)
		employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
		frappe.db.set_value("Employee", employee, "tc_pin_reset_required", 0)
		station_auth.set_pin(employee, pin)
		proof = station_auth.create_pin_proof(session["token"], pin)["proof"]
		return session["session"], proof

	def release(self, user=None, **extra):
		session, proof = self.proof_of(user or self.r02)
		return releasing.release(**self.scans(), session=session, pin_proof=proof, **extra)

	def statuses(self):
		return [frappe.db.get_value("Pack", p.name, "status") for p in self.packs]

	def unit_state(self, pack):
		return frappe.db.get_value("Set Unit", pack.set_unit, ["status", "cycles_used"], as_dict=True)


class TestCycleResultAndIndicators(ReleaseCase):
	@bru("BRU-REP-015")
	def test_cycle_result_needs_complete_data_and_confirmation(self):
		self.assertEqual(blocked(self, self.result).code, "DATA_INCOMPLETE")
		self.save_data()
		self.assertEqual(blocked(self, self.result, confirmed=False).code, "DATA_INCOMPLETE")
		self.assertEqual(blocked(self, self.result, result="Maybe").code, "RESULT_INVALID")
		done = self.result("Pass")
		self.assertEqual(done["cycle_result"], "Pass")
		self.assertEqual(frappe.db.get_value("Sterilization Load", self.load.name, "result_source"), "Manual")

	@bru("BRU-REP-016")
	def test_wrong_machine_scan_blocks_unload(self):
		other = make_sterilizer()
		self.save_data()
		args = self.scans(equipment_raw=other.name)
		self.assertEqual(
			blocked(
				self, releasing.set_cycle_result, **args, result="Pass", confirmed=True, employee=None
			).code,
			"EQUIPMENT_MISMATCH",
		)

	@bru("BRU-REP-006")
	def test_indicator_rules(self):
		self.save_data()
		self.assertEqual(
			blocked(self, self.indicator, "chemical_plasma").code, "INDICATOR_INVALID"
		)  # máy hơi nước
		self.assertEqual(blocked(self, self.indicator, "bowie_dick").code, "INDICATOR_INVALID")  # thiếu ngày
		self.assertEqual(
			blocked(self, self.indicator, "bowie_dick", test_date=add_to_date(today(), days=-1)).code,
			"INDICATOR_INVALID",
		)  # Bowie-Dick phải là hôm nay
		self.assertEqual(
			blocked(self, self.indicator, "chemical_class_5", result="Pending").code, "INDICATOR_INVALID"
		)
		self.assertEqual(
			blocked(self, self.indicator, "biological").code, "INDICATOR_INVALID"
		)  # mẻ không cần BI
		row = self.indicator("chemical_class_5", pack=self.packs[0].name)
		self.assertEqual(
			frappe.db.get_value("Load Indicator Result", row["indicator_result"], ["pack", "result"]),
			(self.packs[0].name, "Pass"),
		)
		self.assertEqual(
			blocked(self, self.indicator, "chemical_class_5", pack="CY-990101-0001").code, "INDICATOR_INVALID"
		)  # gói không thuộc mẻ


class TestRelease(ReleaseCase):
	@bru("BRU-REP-005", "BRU-FLOW-004")
	def test_release_pass_releases_packs_makes_sets_sterile_and_counts_the_cycle(self):
		self.ready()
		before = [self.unit_state(pack).cycles_used for pack in self.packs]
		with patch("tracecore.reprocessing.releasing.extension.run", return_value=[]) as run:
			result = self.release()
		self.assertEqual(result["status"], "Released")
		self.assertEqual(self.statuses(), ["Released", "Released"])
		for pack, count in zip(self.packs, before, strict=True):
			state = self.unit_state(pack)
			self.assertEqual((state.status, state.cycles_used), ("Sterile", count + 1))
		doc = frappe.get_doc("Sterilization Load", self.load.name)
		self.assertEqual((doc.docstatus, doc.status), (1, "Released"))
		self.assertTrue(doc.released_at and doc.released_by)
		release_hooks = [c.args[1] for c in run.call_args_list if c.args[0] == "tracecore_after_release"]
		self.assertCountEqual([c["cycle_id"] for c in release_hooks], [p.name for p in self.packs])
		# chỉ xét hook của mẻ: hook trạng thái bộ của step_gate (FEAT-016) cũng đi qua extension.run
		load_hooks = [c.args[0] for c in run.call_args_list if c.args[0].startswith("tracecore_after_load_")]
		self.assertEqual(load_hooks, ["tracecore_after_load_release"])

	def test_release_second_time_is_blocked_and_counts_once(self):
		self.ready()
		self.release()
		self.assertEqual(blocked(self, self.release).code, "LOAD_NOT_OPEN")
		self.assertEqual(self.unit_state(self.packs[0]).cycles_used, 1)

	@bru("BRU-REP-005")
	def test_release_needs_result_and_every_required_indicator(self):
		# máy chưa có test hằng ngày hôm nay: Bowie-Dick phải ghi theo mẻ (A-23)
		frappe.db.delete("Daily Test", {"equipment": self.machine.name})
		self.save_data()
		block = blocked(self, self.release)
		self.assertEqual(block.code, "LOAD_NOT_RELEASABLE")
		self.assertCountEqual(block.items, ["cycle_result", "chemical_class_5", "bowie_dick"])
		self.result()
		self.indicator("chemical_class_5")
		self.assertEqual(blocked(self, self.release).items, ["bowie_dick"])
		self.assertEqual(self.statuses(), ["In Load", "In Load"])  # không đổi gì

	def test_only_r02_with_a_valid_proof_releases(self):
		self.ready()
		session, _proof = self.proof_of(self.r02)
		self.assertEqual(
			blocked(self, releasing.release, **self.scans(), session=session, pin_proof="sai").code,
			"R02_CONFIRM_REQUIRED",
		)
		self.assertEqual(blocked(self, self.release, self.r05).code, "R02_CONFIRM_REQUIRED")
		self.assertEqual(
			blocked(self, self.release, self.r01).code, "R02_CONFIRM_REQUIRED"
		)  # R01 cần lý do khẩn
		self.assertEqual(self.statuses(), ["In Load", "In Load"])

	@bru("BRU-REP-015")
	def test_review_flag_needs_r02_confirmation(self):
		self.save_data(Temperature="150")  # ngoài dải: lưu, đánh dấu Cần xem xét
		self.result()
		self.good_steam_indicators()
		self.assertEqual(frappe.db.get_value("Sterilization Load", self.load.name, "needs_review"), 1)
		self.assertEqual(blocked(self, self.release).items, ["review"])
		self.assertEqual(self.release(review_confirmed=True)["status"], "Released")

	@bru("BRU-REP-005")
	def test_r01_emergency_release_needs_a_reason(self):
		self.ready()
		self.assertEqual(
			blocked(self, self.release, self.r01, emergency_reason=" ").code, "R02_CONFIRM_REQUIRED"
		)
		done = self.release(self.r01, emergency_reason="Ca mổ khẩn không chờ được")
		self.assertEqual(done["status"], "Released")
		self.assertIn(
			"Ca mổ khẩn", frappe.db.get_value("Sterilization Load", self.load.name, "release_reason")
		)
		audit = frappe.get_all(
			"Audit Log", filters={"ref_name": self.load.name, "action": "Override"}, pluck="reason"
		)
		self.assertIn("EmergencyRelease", audit)


class TestRejectAndBi(ReleaseCase):
	@bru("BRU-REP-007")
	def test_failed_indicator_blocks_release_and_reject_returns_sets_to_reprocess(self):
		self.save_data()
		self.result()
		self.indicator("chemical_class_5", result="Fail")
		self.indicator("bowie_dick", test_date=today())
		self.assertEqual(blocked(self, self.release).code, "LOAD_NOT_RELEASABLE")
		done = releasing.reject(
			**self.scans(), reason="Chỉ thị hóa học không đạt", employee=self.employee.name
		)
		self.assertEqual(done["status"], "Failed")
		doc = frappe.get_doc("Sterilization Load", self.load.name)
		self.assertEqual((doc.docstatus, doc.status, doc.redo_from), (1, "Failed", "T4"))
		for pack in self.packs:
			values = frappe.db.get_value("Pack", pack.name, ["status", "void_reason"], as_dict=True)
			self.assertEqual((values.status, values.void_reason), ("Void", "Load Failed"))
			self.assertEqual(self.unit_state(pack).status, "Reprocess")
			self.assertEqual(self.unit_state(pack).cycles_used, 0)

	def test_reject_can_send_sets_back_to_t2(self):
		self.save_data()
		self.result("Fail")
		releasing.reject(**self.scans(), redo_from="T2", employee=self.employee.name)
		for pack in self.packs:
			t2 = next(g for g in step_gate.gates(pack.set_unit) if g["step"] == "T2")
			self.assertEqual((t2["result"], t2["redo_count"]), ("Fail", 1))
		self.assertEqual(frappe.db.get_value("Sterilization Load", self.load.name, "redo_from"), "T2")

	@bru("BRU-REP-006")
	def test_bi_load_waits_in_quarantine_then_negative_bi_releases(self):
		frappe.db.set_value("Sterilization Load", self.load.name, "requires_bi", 1)
		self.ready()
		self.indicator("biological", result="Pending", lot="BI-001", incubator="TU-1")
		done = self.release()
		self.assertEqual(done["status"], "Quarantine")
		self.assertEqual(self.statuses(), ["Quarantine", "Quarantine"])
		self.assertEqual(
			self.unit_state(self.packs[0]).status, "Processing"
		)  # chưa Vô khuẩn, chưa đếm chu trình
		self.assertEqual(self.unit_state(self.packs[0]).cycles_used, 0)
		finished = releasing.bi_result(self.load.name, "Pass", STATION, employee=self.employee.name)
		self.assertEqual(finished["status"], "Released")
		self.assertEqual(self.statuses(), ["Released", "Released"])
		self.assertEqual(self.unit_state(self.packs[0]).status, "Sterile")
		self.assertEqual(self.unit_state(self.packs[0]).cycles_used, 1)

	@bru("BRU-REP-007")
	def test_positive_bi_in_quarantine_fails_the_load(self):
		frappe.db.set_value("Sterilization Load", self.load.name, "requires_bi", 1)
		self.ready()
		self.indicator("biological", result="Pending", lot="BI-002", incubator="TU-1")
		self.release()
		with patch("tracecore.reprocessing.releasing.extension.run", return_value=[]) as run:
			done = releasing.bi_result(self.load.name, "Fail", STATION, employee=self.employee.name)
		self.assertEqual(done["status"], "Failed")
		self.assertEqual(self.statuses(), ["Void", "Void"])
		self.assertIn("tracecore_bi_positive", [c.args[0] for c in run.call_args_list])

	def test_bi_result_without_pending_indicator_is_blocked(self):
		self.ready()
		self.assertEqual(
			blocked(self, releasing.bi_result, self.load.name, "Pass", STATION).code, "BI_NOT_PENDING"
		)

	@bru("BRU-REP-007")
	def test_positive_bi_after_release_runs_the_recall_hook_and_audits(self):
		frappe.db.set_value("Sterilization Load", self.load.name, "requires_bi", 1)
		self.ready()
		self.indicator("biological", result="Pending", lot="BI-003", incubator="TU-1")
		self.release(self.r01, emergency_reason="Ca khẩn")  # R01 giải phóng khẩn, không chờ BI
		self.assertEqual(frappe.db.get_value("Sterilization Load", self.load.name, "status"), "Released")
		with patch("tracecore.reprocessing.releasing.extension.run", return_value=[]) as run:
			done = releasing.bi_result(self.load.name, "Fail", STATION, employee=self.employee.name)
		self.assertEqual(
			done["status"], "Released"
		)  # mẻ đã giải phóng: không đổi trạng thái, chờ thu hồi (FEAT-029)
		self.assertTrue(done["recall_needed"])
		payload = next(c.args[1] for c in run.call_args_list if c.args[0] == "tracecore_bi_positive")
		self.assertEqual(payload["load"], self.load.name)
		self.assertCountEqual([p["cycle_id"] for p in payload["packs"]], [p.name for p in self.packs])
		self.assertEqual(frappe.db.get_value("Sterilization Load", self.load.name, "bi_result"), "Fail")
		self.assertTrue(
			frappe.db.exists(
				"Audit Log", {"ref_name": self.load.name, "action": "Override", "reason": "BIPositive"}
			)
		)

	@bru("BRU-REP-007")
	def test_positive_bi_after_release_opens_a_recall_order(self):
		# FEAT-029, FR-M2-11.7: hook thật lập lệnh thu hồi gồm mọi gói của mẻ, bi_result trả mã lệnh
		frappe.db.set_value("Sterilization Load", self.load.name, "requires_bi", 1)
		self.ready()
		self.indicator("biological", result="Pending", lot="BI-004", incubator="TU-1")
		self.release(self.r01, emergency_reason="Ca khẩn")
		done = releasing.bi_result(self.load.name, "Fail", STATION, employee=self.employee.name)
		order = frappe.get_doc("Recall Order", done["recall"])
		self.assertEqual((order.trigger, order.sterilization_load), ("BI Positive", self.load.name))
		self.assertCountEqual([row.pack for row in order.packs], [p.name for p in self.packs])
		self.assertEqual({frappe.db.get_value("Pack", p.name, "status") for p in self.packs}, {"Recalled"})


class TestBowieDickFromDailyTest(ReleaseCase):
	"""A-23: Bowie-Dick của mẻ lấy từ test hằng ngày Đạt của máy trong ngày chạy mẻ (FEAT-040), không nhập lại ở T5b."""

	def daily(self, result):
		row = frappe.get_doc(
			{
				"doctype": "Daily Test",
				"equipment": self.machine.name,
				"test_type": "bowie_dick",
				"result": result,
				"test_date": today(),
				"lot": "BD-LOT",
				"lot_expiry": add_to_date(today(), days=30),
				"tested_at": now_datetime(),
			}
		)
		row.flags.tc_daily_test = True
		return row.insert(ignore_permissions=True)

	def test_todays_daily_test_fills_the_bowie_dick_and_is_kept_at_release(self):
		ctx = releasing.context(self.load.name, self.machine.name, self.load.name, STATION)
		self.assertEqual(ctx["indicator_state"]["bowie_dick"], "Pass")
		self.assertEqual(ctx["daily_indicators"]["bowie_dick"]["result"], "Pass")
		self.save_data()
		self.result()
		self.indicator("chemical_class_5")  # chỉ còn chỉ thị hóa học của mẻ phải ghi
		self.assertEqual(self.release()["status"], "Released")
		rows = frappe.get_all(
			"Load Indicator Result",
			filters={"load": self.load.name, "indicator": "bowie_dick"},
			fields=["result", "test_date"],
		)
		self.assertEqual([(row.result, str(row.test_date)) for row in rows], [("Pass", today())])

	def test_without_a_daily_test_the_bowie_dick_must_be_recorded(self):
		frappe.db.delete("Daily Test", {"equipment": self.machine.name})
		ctx = releasing.context(self.load.name, self.machine.name, self.load.name, STATION)
		self.assertEqual(ctx["indicator_state"]["bowie_dick"], "Missing")
		self.assertNotIn("bowie_dick", ctx["daily_indicators"])

	def test_latest_failed_daily_test_fails_the_indicator(self):
		self.daily("Fail")
		ctx = releasing.context(self.load.name, self.machine.name, self.load.name, STATION)
		self.assertEqual(ctx["indicator_state"]["bowie_dick"], "Fail")
