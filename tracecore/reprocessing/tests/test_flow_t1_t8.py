"""Một bộ dụng cụ đi trọn T1 đến T8 qua các dịch vụ thật (không dựng thẳng trạng thái): kiểm các điểm bàn giao giữa bước.

Chỉ máy móc, danh mục và người dùng dựng bằng factory; mọi chuyển trạng thái của bộ/gói do dịch vụ T1..T8 và
`core.step_gate` thực hiện. Mục tiêu là bắt lỗi tích hợp khi gộp các FEAT (016, 019, 020, 021, 018, 022, 023, 025, 026, 027, 040).
"""

import uuid
from datetime import timedelta

import frappe
from frappe.utils import add_to_date, now_datetime, today

from tracecore.core import client_time, station_auth
from tracecore.instrument import set_units
from tracecore.reprocessing import (
	assembly,
	issuing,
	packing,
	receiving,
	releasing,
	sterilizing,
	storage,
	usage,
	washing,
)
from tracecore.reprocessing.tests.test_washing_result import GOOD_VALUES, PARAMETERS, PRINTOUT
from tracecore.tests.factories import (
	T4_STATION,
	deactivate_printers,
	make_bom,
	make_chemical_batch,
	make_ci_batch,
	make_department,
	make_employee,
	make_label_items,
	make_pack_type,
	make_printer,
	make_set_type,
	make_sterile_location,
	make_sterilize_program,
	make_sterilizer,
	make_user,
	make_wash_machine,
	make_wash_program,
)
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

T1, T2, T3, T5, T6, T7, T8 = "TR-001", "TR-002", "TR-003", "TR-005", "TR-006", "TR-007", "TR-008"
BOM = [("FL-KEO", 2), ("FL-KEP", 1), ("FL-DAO", 3)]
CHEMICAL = "HC-ENZ-01"
STERILIZE_PARAMETERS = [
	{"parameter_name": "Temperature", "unit": "°C", "min_value": 132, "max_value": 138, "required": 1},
	{"parameter_name": "Pressure", "unit": "bar", "min_value": 0, "max_value": 2.3, "required": 1},
]


def _ts():
	return client_time.utc_now()


class TestFlowT1ToT8(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.dept = make_department("Khoa tích hợp T1-T8")
		self.deliverer_card = "FL-" + uuid.uuid4().hex[:10].upper()
		make_employee(card=self.deliverer_card, department=self.dept, first_name="Người giao")
		self.operator = make_employee(first_name="Kỹ thuật viên").name
		self.nurse = make_employee(first_name="Điều dưỡng", department=self.dept)

	def state(self, set_id):
		return frappe.db.get_value(
			"Set Unit",
			set_id,
			["status", "current_cycle_no", "cycles_used", "active_cycle_id"],
			as_dict=True,
		)

	def gates(self, set_id):
		return {
			row.step: row.result
			for row in frappe.get_all(
				"Step Gate Result",
				filters={"set_unit": set_id},
				fields=["step", "result"],
			)
		}

	def r02_proof(self, station, pin="246810"):
		user = make_user(f"flow-r02-{uuid.uuid4().hex[:6]}@test.local", roles=("TC R02",))
		session = make_station_session(user, station=station)
		employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
		frappe.db.set_value("Employee", employee, "tc_pin_reset_required", 0)
		station_auth.set_pin(employee, pin)
		return session["session"], station_auth.create_pin_proof(session["token"], pin)["proof"]

	@bru("BRU-FLOW-004")
	def test_one_set_walks_t1_to_t8(self):
		# --- Set ID: loại bộ + BOM, rồi cấp bộ qua dịch vụ cấp Set ID (FEAT-016) -----------------------------------------
		pack_type = make_pack_type()
		set_type = make_set_type("FLW1", default_pack_type=pack_type, department=self.dept, bom=BOM)
		set_id = set_units.issue_batch(set_type.name, 1, max_cycles=300)[0]
		self.assertEqual(self.state(set_id).status, "New")

		# --- T1 tiếp nhận (FEAT-019) ---------------------------------------------------------------------------------
		receipt = receiving.open_receipt(T1, self.operator, raw=self.deliverer_card, client_ts=_ts())[
			"receipt"
		]
		receiving.scan_set(receipt, set_id, T1, self.operator, client_ts=_ts())
		receiving.confirm_line(receipt, set_id, T1, self.operator, confirm_all=True, note=None, finalize=True)
		receiving.submit(receipt, T1, self.operator, client_ts=_ts())
		after_t1 = self.state(set_id)
		self.assertEqual((after_t1.status, after_t1.current_cycle_no), ("Processing", 1))
		self.assertEqual(self.gates(set_id), {"T1": "Pass"})

		# --- T2 rửa (FEAT-021) ---------------------------------------------------------------------------------------
		deactivate_printers(T2)
		washer = make_wash_machine(has_printout=1)
		lot = make_chemical_batch(CHEMICAL)
		wash_program = make_wash_program(washer.name, chemical=CHEMICAL, parameters=PARAMETERS)
		started = washing.start(
			washer.name,
			wash_program.name,
			[set_id],
			[{"item": CHEMICAL, "lot": lot.name}],
			T2,
			_ts(),
			self.operator,
		)
		batch = started["batch"]
		self.assertEqual(started["rejected"], [])
		washing.save_manual_data(
			batch=batch,
			equipment_raw=washer.name,
			batch_raw=batch,
			values=GOOD_VALUES,
			reported_result="Pass",
			started_at=str(add_to_date(now_datetime(), hours=-1)),
			ended_at=str(now_datetime()),
			machine_alerts=None,
			machine_file=PRINTOUT,
			confirmed=True,
			client_ts=_ts(),
			employee=self.operator,
			station=T2,
		)
		washing.set_result(
			batch=batch,
			result="Pass",
			station=T2,
			equipment_raw=washer.name,
			batch_raw=batch,
			clean_test="Pass",
			client_ts=_ts(),
		)
		self.assertEqual(self.gates(set_id), {"T1": "Pass", "T2": "Pass"})

		# --- T3 kiểm đếm (FEAT-020) ----------------------------------------------------------------------------------
		record = assembly.open_set(set_id, T3, _ts())["assembly"]
		for code, qty in BOM:
			assembly.line(record, T3, _ts(), instrument=code, actual_qty=qty)
		assembly.submit(record, T3, _ts())
		self.assertEqual(self.gates(set_id), {"T1": "Pass", "T2": "Pass", "T3": "Pass"})

		# --- T4 đóng gói + Cycle ID (FEAT-018) -----------------------------------------------------------------------
		steam_label, _plasma = make_label_items()
		make_printer(T4_STATION, steam_label)
		packed = packing.generate(
			set_id=set_id,
			station=T4_STATION,
			confirmed=[code for code, _qty in BOM],
			ci_batch=make_ci_batch("Steam"),
			pack_type=pack_type,
			maint_actions=[],
			client_ts=_ts(),
		)
		cycle_id = packed["pack"]["cycle_id"]
		self.assertRegex(cycle_id, r"^CY-")
		self.assertEqual(self.state(set_id).active_cycle_id, cycle_id)
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "status"), "Packed")
		self.assertEqual(self.gates(set_id)["T4"], "Pass")

		# --- T5 nạp mẻ tiệt khuẩn (FEAT-022, kèm test hằng ngày FEAT-040) --------------------------------------------
		sterilizer = make_sterilizer()
		program = make_sterilize_program(sterilizer.name, parameters=STERILIZE_PARAMETERS)
		load_result = sterilizing.complete(
			sterilizer.name, program.name, [cycle_id], T5, _ts(), self.operator
		)
		load = load_result["load"]
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "status"), "In Load")

		# --- T5b dỡ mẻ, chỉ thị, giải phóng PIN R02 (FEAT-023) -------------------------------------------------------
		scans = {"load": load, "station": T5, "equipment_raw": sterilizer.name, "load_raw": load}
		sterilizing.save_manual_data(
			load=load,
			equipment_raw=sterilizer.name,
			load_raw=load,
			values=[
				{"parameter_name": "Temperature", "value": "134"},
				{"parameter_name": "Pressure", "value": "2,1"},
			],
			started_at=str(add_to_date(now_datetime(), hours=-1)),
			ended_at=str(now_datetime()),
			machine_alerts=None,
			machine_report="/files/printout.png",
			reason=None,
			confirmed=True,
			card=frappe.db.get_value("Employee", self.operator, "tc_card_id"),
			client_ts=_ts(),
			employee=self.operator,
			station=T5,
		)
		releasing.set_cycle_result(**scans, result="Pass", confirmed=True, employee=self.operator)
		releasing.record_indicator(
			**scans, indicator="chemical_class_5", result="Pass", employee=self.operator
		)
		releasing.record_indicator(
			**scans, indicator="bowie_dick", result="Pass", employee=self.operator, test_date=today()
		)
		session, proof = self.r02_proof(T5)
		releasing.release(**scans, session=session, pin_proof=proof)
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "status"), "Released")
		after_release = self.state(set_id)
		self.assertEqual((after_release.status, after_release.cycles_used), ("Sterile", 1))
		self.assertEqual(self.gates(set_id)["T5"], "Pass")

		# --- T6 nhập kho vô khuẩn (FEAT-025) -------------------------------------------------------------------------
		shelf = make_sterile_location("Kệ tích hợp")
		storage.putaway(cycle_id, shelf.name, T6)
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "status"), "In Sterile Stock")

		# --- T7 cấp phát (FEAT-026) ----------------------------------------------------------------------------------
		note = issuing.create(self.dept, T7)["issue_note"]
		issuing.add_pack(note, cycle_id, T7)
		issuing.sign(note, self.nurse.tc_card_id, T7)
		issuing.submit(note, T7)
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "status"), "Issued")
		self.assertEqual(self.state(set_id).status, "At Department")

		# --- T8 quét sử dụng (FEAT-027) ------------------------------------------------------------------------------
		card = usage.scan(cycle_id, T8, self.nurse.name)
		self.assertFalse(card["department_mismatch"])
		used = usage.confirm(
			cycle_id,
			T8,
			self.nurse.name,
			patient_code="BN12345678",
			surgery_code="CA-FLOW-1",
			surgeon="BS Tích hợp",
			room="P1",
		)
		self.assertTrue(used)
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "status"), "Used")
		final = self.state(set_id)
		self.assertEqual(final.status, "Awaiting Receipt")  # sẵn sàng quay lại T1 cho chu trình kế tiếp

		# T1 lại nhận được bộ vừa dùng xong: vòng khép kín
		self.assertIsNone(__import__("tracecore.core.step_gate", fromlist=["check"]).check(set_id, "T1"))
		_unused = timedelta  # giữ import dùng cho mở rộng (hạn dùng)
