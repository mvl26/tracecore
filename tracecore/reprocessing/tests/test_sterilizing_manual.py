from datetime import timedelta

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from tracecore.core import client_time
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import sterilizing
from tracecore.tests.factories import (
	make_employee,
	make_load,
	make_load_ready_pack,
	make_sterilize_program,
	make_sterilizer,
)
from tracecore.tests.utils import bru

STATION = "TR-005"  # T5 Sterilization
EXIT_STATION = "TR-006"  # T6, khu vô khuẩn = khu cửa ra của máy hai cửa
OTHER_STATION = "TR-004"  # T4, khu sạch = cửa vào của máy
PARAMETERS = [
	{"parameter_name": "Temperature", "unit": "°C", "min_value": 132, "max_value": 138, "required": 1},
	{"parameter_name": "Pressure", "unit": "bar", "min_value": 0, "max_value": 2.3, "required": 1},
	{"parameter_name": "Hold time", "unit": "min", "min_value": 3, "max_value": 0, "required": 0},
]

test_ignore = ["Employee", "Item", "Batch", "User"]


class TestSterilizingManual(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.machine = make_sterilizer()
		self.program = make_sterilize_program(self.machine.name, parameters=PARAMETERS)
		self.pack = make_load_ready_pack()
		self.employee = make_employee()
		self.load = make_load(self.machine, self.program, [self.pack], operator=self.employee.name)

	def values(self, **overrides):
		data = {"Temperature": "134", "Pressure": "2,1", "Hold time": "4"}
		data.update(overrides)
		return [{"parameter_name": key, "value": value} for key, value in data.items() if value is not None]

	def save(self, **overrides):
		args = {
			"load": self.load.name,
			"equipment_raw": self.machine.name,
			"load_raw": self.load.name,
			"values": self.values(),
			"started_at": str(add_to_date(now_datetime(), hours=-1)),
			"ended_at": str(now_datetime()),
			"machine_alerts": None,
			"machine_report": "/files/printout.png",
			"reason": None,
			"confirmed": True,
			"card": self.employee.tc_card_id,
			"client_ts": client_time.utc_now(),
			"employee": self.employee.name,
			"station": STATION,
		}
		args.update(overrides)
		return sterilizing.save_manual_data(**args)

	def code_of(self, call):
		with self.assertRaises(BlockedError) as caught:
			call()
		return caught.exception.block

	def stored(self):
		return frappe.db.get_value(
			"Sterilization Load",
			self.load.name,
			["status", "data_complete", "params", "data_source", "manual_confirmed_by"],
			as_dict=True,
		)

	# --- không lưu khi thiếu (FR-M2-10.1, .2, .4) ---------------------------------------------------------

	@bru("BRU-REP-015")
	def test_manual_data_not_saved_when_required_missing(self):
		cases = {
			"parameter": {"values": self.values(Pressure=None)},
			"ended_at": {"ended_at": None},
			"confirmation": {"confirmed": False},
			"card": {"card": ""},
		}
		for item, overrides in cases.items():
			block = self.code_of(lambda overrides=overrides: self.save(**overrides))
			self.assertEqual(block.code, "DATA_INCOMPLETE", msg=item)
			self.assertEqual(block.http_status, 422)
			stored = self.stored()
			self.assertEqual(
				(stored.status, stored.data_complete, stored.params), ("Running", 0, None), msg=item
			)
		missing = self.code_of(lambda: self.save(values=[], confirmed=False, card="", ended_at=None)).items
		self.assertEqual(missing, ["Temperature", "Pressure", "ended_at", "confirmation", "card"])

	@bru("BRU-REP-015")
	def test_ended_at_must_not_precede_started_at(self):
		block = self.code_of(
			lambda: self.save(
				started_at=str(now_datetime()), ended_at=str(add_to_date(now_datetime(), hours=-2))
			)
		)
		self.assertIn("ended_at", block.items)

	@bru("BRU-REP-015")
	def test_printout_required_only_when_machine_has_printout(self):
		frappe.db.set_value("Equipment", self.machine.name, "has_printout", 1)
		block = self.code_of(lambda: self.save(machine_report=None))
		self.assertEqual(block.items, ["printout"])
		frappe.db.set_value("Equipment", self.machine.name, "has_printout", 0)
		self.assertTrue(self.save(machine_report=None)["data_complete"])

	def test_connected_machine_needs_reason(self):
		frappe.db.set_value("Equipment", self.machine.name, "is_connected", 1)
		block = self.code_of(lambda: self.save())
		self.assertEqual(block.items, ["reason"])
		self.assertTrue(self.save(reason="Mất kết nối trong chu trình")["data_complete"])
		self.assertEqual(
			frappe.db.get_value("Sterilization Load", self.load.name, "manual_reason"),
			"Mất kết nối trong chu trình",
		)

	def test_card_must_match_session_employee(self):
		other = make_employee()
		block = self.code_of(lambda: self.save(card=other.tc_card_id))
		self.assertEqual((block.code, block.http_status), ("CARD_MISMATCH", 403))
		self.assertEqual(self.stored().status, "Running")
		# mã quét có tiền tố AIM, chữ thường và CR/LF vẫn là thẻ của chính người đó
		self.assertTrue(self.save(card=f"]d2{self.employee.tc_card_id.lower()}\r\n")["data_complete"])

	# --- lưu thành công --------------------------------------------------------------------------------

	@bru("BRU-REP-015")
	def test_manual_data_saved_with_source_person_time(self):
		result = self.save(machine_alerts="Cảnh báo áp suất thoáng qua")
		self.assertEqual(
			(result["data_complete"], result["needs_review"], result["status"]), (1, 0, "Cycle Complete")
		)
		load = frappe.get_doc("Sterilization Load", self.load.name)
		self.assertEqual(load.data_source, "Manual Default")
		self.assertEqual(load.manual_confirmed_by, self.employee.name)
		self.assertIsNotNone(load.manual_confirmed_at)
		self.assertEqual(load.machine_report, "/files/printout.png")
		self.assertEqual(frappe.parse_json(load.machine_alerts), {"text": "Cảnh báo áp suất thoáng qua"})
		by_name = {row["parameter_name"]: row for row in frappe.parse_json(load.params)}
		self.assertEqual(by_name["Pressure"]["value"], 2.1)  # dấu phẩy thập phân
		self.assertEqual(by_name["Temperature"]["unit"], "°C")
		self.assertEqual((load.docstatus, load.status), (0, "Cycle Complete"))

	@bru("BRU-REP-015")
	def test_parameter_range_zero_is_unset_and_one_sided(self):
		# Pressure: min 0 (không đặt) + max 2,3; Hold time: min 3 + max 0 (không đặt)
		result = self.save(values=self.values(Pressure="0.1", **{"Hold time": "500"}))
		self.assertEqual(result["needs_review"], 0)
		self.assertFalse(any(row["outside_range"] for row in result["params"]))
		result = self.save(values=self.values(Pressure="2.4"))
		self.assertEqual(result["needs_review"], 1)
		self.assertEqual([r["parameter_name"] for r in result["params"] if r["outside_range"]], ["Pressure"])
		result = self.save(values=self.values(**{"Hold time": "2"}))
		self.assertEqual([r["parameter_name"] for r in result["params"] if r["outside_range"]], ["Hold time"])
		result = self.save(values=self.values(Temperature="140"))
		self.assertEqual(
			[r["parameter_name"] for r in result["params"] if r["outside_range"]], ["Temperature"]
		)

	@bru("BRU-REP-015")
	def test_out_of_range_value_is_saved_and_flags_review(self):
		result = self.save(values=self.values(Temperature="120"))
		self.assertEqual(
			(result["data_complete"], result["needs_review"], result["status"]), (1, 1, "Cycle Complete")
		)
		self.assertEqual(frappe.db.get_value("Sterilization Load", self.load.name, "needs_review"), 1)

	def test_manual_data_can_be_corrected_before_release(self):
		self.save(values=self.values(Temperature="120"))
		self.save(values=self.values(Temperature="134"))
		stored = self.stored()
		self.assertEqual(stored.status, "Cycle Complete")
		self.assertEqual(frappe.db.get_value("Sterilization Load", self.load.name, "needs_review"), 0)

	def test_manual_data_not_saved_for_closed_load(self):
		frappe.db.set_value("Sterilization Load", self.load.name, "status", "Released")
		block = self.code_of(lambda: self.save())
		self.assertEqual((block.code, block.http_status), ("LOAD_ALREADY_RELEASED", 409))
		frappe.db.set_value("Sterilization Load", self.load.name, "status", "Failed")
		block = self.code_of(lambda: self.save())
		self.assertEqual((block.code, block.http_status), ("LOAD_NOT_OPEN", 409))

	def test_skewed_client_ts_is_rejected(self):
		skewed = client_time.utc_now() - timedelta(seconds=client_time.max_skew_seconds() + 3600)
		with self.assertRaises(client_time.ClientTimestampError):
			self.save(client_ts=skewed)
		self.assertEqual(self.stored().status, "Running")

	# --- quét máy và mẻ khi nhập dữ liệu (Q10) -----------------------------------------------------------

	@bru("BRU-REP-016")
	def test_data_requires_both_codes_and_matching_machine(self):
		other = make_sterilizer()
		self.assertEqual(self.code_of(lambda: self.save(equipment_raw=other.name)).code, "EQUIPMENT_MISMATCH")
		self.assertEqual(self.code_of(lambda: self.save(equipment_raw="")).code, "SCAN_INVALID")
		self.assertEqual(self.code_of(lambda: self.save(load_raw="")).code, "SCAN_INVALID")
		self.assertEqual(self.code_of(lambda: self.save(load_raw="ME-991231-99")).code, "SCAN_INVALID")
		self.assertEqual(self.code_of(lambda: self.save(equipment_raw=self.load.name)).code, "SCAN_INVALID")
		self.assertEqual(self.stored().status, "Running")

	@bru("BRU-REP-016")
	def test_scan_for_data_checks_one_code_at_a_time(self):
		self.assertEqual(
			sterilizing.scan_for_data(self.load.name, self.machine.name, STATION),
			{"ok": True, "kind": "equipment"},
		)
		self.assertEqual(
			sterilizing.scan_for_data(self.load.name, f"]Q1{self.load.name}\r\n", STATION),
			{"ok": True, "kind": "load"},
		)
		other = make_sterilizer()
		block = self.code_of(lambda: sterilizing.scan_for_data(self.load.name, other.name, STATION))
		self.assertEqual((block.code, block.http_status), ("EQUIPMENT_MISMATCH", 409))
		self.assertEqual(
			self.code_of(lambda: sterilizing.scan_for_data(self.load.name, "ME-991231-99", STATION)).code,
			"SCAN_INVALID",
		)
		frappe.db.set_value("Sterilization Load", self.load.name, "status", "Released")
		self.assertEqual(
			self.code_of(lambda: sterilizing.scan_for_data(self.load.name, self.machine.name, STATION)).code,
			"LOAD_ALREADY_RELEASED",
		)
		self.assertEqual(
			self.code_of(lambda: sterilizing.scan_for_data("ME-991231-99", self.machine.name, STATION)).code,
			"LOAD_NOT_FOUND",
		)

	def test_data_station_t5_or_exit_zone(self):
		self.assertTrue(self.save(station=STATION)["data_complete"])
		self.assertTrue(self.save(station=EXIT_STATION)["data_complete"])
		block = self.code_of(lambda: self.save(station=OTHER_STATION))
		self.assertEqual(block.code, "STATION_WRONG_STEP")
		self.assertEqual(self.code_of(lambda: self.save(station=None)).code, "STATION_WRONG_STEP")

	def test_data_context_returns_parameter_schema(self):
		context = sterilizing.data_context(self.load.name, self.machine.name, self.load.name, STATION)
		self.assertEqual(
			[row.parameter_name for row in context["parameter_schema"]],
			["Temperature", "Pressure", "Hold time"],
		)
		self.assertEqual(context["load"], self.load.name)
		self.assertEqual(
			self.code_of(
				lambda: sterilizing.data_context(self.load.name, self.machine.name, "", STATION)
			).code,
			"SCAN_INVALID",
		)

	# --- tra cứu (FR-M2-09.2) -----------------------------------------------------------------------

	def test_lookup_shows_packs_program_indicators(self):
		result = sterilizing.lookup(f" {self.load.name}\r\n")
		self.assertEqual(result["load"], self.load.name)
		self.assertEqual(result["program"]["name"], self.program.name)
		self.assertEqual(result["equipment"]["name"], self.machine.name)
		self.assertEqual(result["indicators"], ["chemical_class_5", "bowie_dick"])
		self.assertEqual(
			[(p["cycle_id"], p["set_id"], p["method"]) for p in result["packs"]],
			[(self.pack.name, self.pack.set_unit, "Steam")],
		)
		self.assertEqual((result["status"], result["data_complete"]), ("Running", 0))

	def test_lookup_rejects_non_load_code_and_unknown_load(self):
		self.assertEqual(self.code_of(lambda: sterilizing.lookup("LR-261023-01")).code, "SCAN_INVALID")
		self.assertEqual(self.code_of(lambda: sterilizing.lookup("ME-991231-99")).code, "LOAD_NOT_FOUND")
