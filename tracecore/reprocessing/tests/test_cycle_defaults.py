"""Điền sẵn dữ liệu chu trình từ chương trình và chặn Đạt khi ngoài dải (A-89, #1815; D4; FR-M2-10.3, Q8, BRU-REP-015)."""

import json

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from tracecore.core import client_time
from tracecore.core.errors import HTTP_STATUS, BlockedError
from tracecore.reprocessing import cycle_defaults, machine_data, releasing, sterilizing, washing
from tracecore.reprocessing.tests.test_washing_result import STATION as WASH_STATION
from tracecore.reprocessing.tests.test_washing_result import WashResultCase
from tracecore.tests.factories import (
	make_employee,
	make_load,
	make_load_ready_pack,
	make_program,
	make_sterilize_program,
	make_sterilizer,
	make_wash_machine,
	make_wash_program,
)
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

LOAD_STATION = "TR-005"
CONFIGURED = [
	{"parameter_name": "Nhiệt độ khử khuẩn", "unit": "°C", "min_value": 90, "max_value": 95, "required": 1},
	{
		"parameter_name": "Thời gian giữ",
		"unit": "phút",
		"min_value": 0,
		"max_value": 15,
		"required": 1,
		"default_value": "12",
	},
	{"parameter_name": "Áp lực nước", "unit": "bar", "min_value": 0, "max_value": 0, "required": 0},
]
STERILE = [
	{"parameter_name": "Temperature", "unit": "°C", "min_value": 132, "max_value": 138, "required": 1},
	{"parameter_name": "Pressure", "unit": "bar", "min_value": 0, "max_value": 2.3, "required": 1},
]


class TestProgramDefaultValue(IsolatedTestCase):
	def test_default_must_be_a_number_inside_the_range(self):
		machine = make_wash_machine()
		bad_range = [{"parameter_name": "T", "min_value": 90, "max_value": 95, "default_value": "80"}]
		with self.assertRaises(frappe.ValidationError):
			make_wash_program(machine.name, parameters=bad_range)
		bad_text = [{"parameter_name": "T", "default_value": "abc"}]
		with self.assertRaises(frappe.ValidationError):
			make_program(machine.name, code="MR-BADTXT", parameters=bad_text)


class TestPrefill(WashResultCase):
	def setUp(self):
		super().setUp()
		self.program = make_wash_program(
			self.machine.name,
			chemical="HC-ENZ-01",
			parameters=CONFIGURED,
			temperature=93,
			pressure=2,
			minutes=10,
		)

	def context(self, batch):
		return washing.unload_context(batch, self.machine.name, batch, WASH_STATION)

	def test_form_is_prefilled_from_the_program(self):
		batch, _sets = self.load()
		prefill = self.context(batch)["prefill"]
		self.assertEqual(prefill["values"]["Thời gian giữ"], 12)  # default_value thắng
		self.assertEqual(prefill["values"]["Nhiệt độ khử khuẩn"], 93)  # từ `temperature`
		self.assertEqual(prefill["values"]["Áp lực nước"], 2)  # từ `pressure`
		doc = frappe.get_doc("Wash Batch", batch)
		self.assertEqual(
			get_datetime(prefill["ended_at"]), add_to_date(get_datetime(doc.started_at), minutes=10)
		)
		self.assertEqual(prefill["chemical"], "HC-ENZ-01")

	def test_header_value_outside_the_range_is_not_offered(self):
		self.program = make_wash_program(
			self.machine.name, chemical="HC-ENZ-01", parameters=CONFIGURED, temperature=60
		)
		batch, _sets = self.load()
		self.assertNotIn("Nhiệt độ khử khuẩn", self.context(batch)["prefill"]["values"])

	def test_header_values_without_a_parameter_row_get_their_own_field(self):
		self.program = make_wash_program(self.machine.name, chemical="HC-ENZ-01", temperature=93)
		batch, _sets = self.load()
		context = self.context(batch)
		self.assertEqual(len(context["parameter_schema"]), 1)
		self.assertEqual(list(context["prefill"]["values"].values()), [93])

	def test_machine_data_wins(self):
		batch, _sets = self.load()
		frappe.db.set_value("Wash Batch", batch, "data_source", "Auto")
		self.assertIsNone(self.context(batch)["prefill"])

	@bru("BRU-REP-015")
	def test_edit_is_stored_with_the_default_and_marked(self):
		batch, _sets = self.load()
		values = [
			{"parameter_name": "Nhiệt độ khử khuẩn", "value": 93},
			{"parameter_name": "Thời gian giữ", "value": 14},
			{"parameter_name": "Áp lực nước", "value": 2},
		]
		started = frappe.db.get_value("Wash Batch", batch, "started_at")
		ended = add_to_date(get_datetime(started), minutes=10)
		saved = self.save_data(batch, values=values, started_at=str(started), ended_at=str(ended))
		self.assertEqual(saved["data_complete"], 1)
		doc = frappe.get_doc("Wash Batch", batch)
		self.assertEqual(doc.data_source, "Manual Default")
		self.assertEqual(doc.manual_confirmed_by, self.employee.name)
		self.assertTrue(doc.manual_confirmed_at)
		data = json.loads(doc.machine_data)
		rows = {row["parameter_name"]: row for row in data["parameters"]}
		self.assertEqual((rows["Thời gian giữ"]["value"], rows["Thời gian giữ"]["default_value"]), (14, 12))
		self.assertTrue(rows["Thời gian giữ"]["edited"])
		self.assertFalse(rows["Nhiệt độ khử khuẩn"]["edited"])
		self.assertEqual(data["edited_fields"], ["Thời gian giữ"])
		self.assertEqual(data["defaults"]["values"]["Thời gian giữ"], 12)

	def test_edited_end_time_is_marked(self):
		batch, _sets = self.load()
		values = [{"parameter_name": "Nhiệt độ khử khuẩn", "value": 93}, {"parameter_name": "Thời gian giữ", "value": 12}, {"parameter_name": "Áp lực nước", "value": 2}]  # fmt: skip
		saved_at = frappe.db.get_value("Wash Batch", batch, "started_at")
		self.save_data(
			batch,
			values=values,
			started_at=str(saved_at),
			ended_at=str(add_to_date(get_datetime(saved_at), minutes=30)),
		)
		data = json.loads(frappe.db.get_value("Wash Batch", batch, "machine_data"))
		self.assertEqual(data["edited_fields"], ["ended_at"])

	def test_no_defaults_keeps_plain_manual_source(self):
		self.program = make_wash_program(
			self.machine.name,
			chemical="HC-ENZ-01",
			parameters=[{"parameter_name": "A0", "min_value": 0, "max_value": 0, "required": 1}],
		)
		batch, _sets = self.load()
		self.save_data(batch, values=[{"parameter_name": "A0", "value": 3000}])
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, "data_source"), "Manual")

	def test_auto_data_cannot_overwrite_confirmed_defaults(self):
		batch, _sets = self.load()
		values = [{"parameter_name": "Nhiệt độ khử khuẩn", "value": 93}, {"parameter_name": "Thời gian giữ", "value": 12}]  # fmt: skip
		self.save_data(batch, values=values)
		doc = frappe.get_doc("Wash Batch", batch)
		self.assertEqual(doc.data_source, "Manual Default")
		self.assertIn(doc.data_source, machine_data.MANUAL_SOURCES)


class TestWashOutOfRange(WashResultCase):
	@bru("BRU-REP-015")
	def test_pass_is_blocked_when_a_value_is_outside_the_range(self):
		batch, units = self.load()
		values = [
			{"parameter_name": "Nhiệt độ khử khuẩn", "value": 89},
			{"parameter_name": "Thời gian giữ", "value": 5},
		]
		self.assertEqual(self.save_data(batch, values=values)["needs_review"], 1)
		with self.assertRaises(BlockedError) as caught:
			self.close(batch)
		block = caught.exception.block
		self.assertEqual(block.code, "CYCLE_DATA_OUT_OF_RANGE")
		self.assertEqual(block.items, ["Nhiệt độ khử khuẩn"])
		self.assertEqual(frappe.db.get_value("Wash Batch", batch, "status"), "Running")
		self.assertEqual(self.close(batch, result="Fail", clean_test="Fail")["result"], "Fail")
		self.assertTrue(units)

	def test_correcting_the_value_allows_pass(self):
		batch, _sets = self.load()
		bad = [{"parameter_name": "Nhiệt độ khử khuẩn", "value": 89}, {"parameter_name": "Thời gian giữ", "value": 5}]  # fmt: skip
		self.save_data(batch, values=bad)
		good = [{"parameter_name": "Nhiệt độ khử khuẩn", "value": 93}, {"parameter_name": "Thời gian giữ", "value": 5}]  # fmt: skip
		self.save_data(batch, values=good)
		self.assertEqual(self.close(batch)["result"], "Pass")

	def test_incident_review_flag_alone_does_not_block_pass(self):
		batch, _sets = self.load()
		self.save_data(batch)
		frappe.db.set_value("Wash Batch", batch, "needs_review", 1)  # sự cố máy, không phải ngoài dải
		self.assertEqual(self.close(batch)["result"], "Pass")

	def test_out_of_range_block_has_a_status_and_an_error_code(self):
		self.assertEqual(HTTP_STATUS.get("CYCLE_DATA_OUT_OF_RANGE"), 422)


class TestLoadDefaults(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.machine = make_sterilizer()
		self.program = make_sterilize_program(
			self.machine.name, parameters=STERILE, temperature=134, pressure=2, minutes=4
		)
		self.employee = make_employee()
		self.load = make_load(
			self.machine, self.program, [make_load_ready_pack()], operator=self.employee.name
		)

	def save(self, temperature="134", pressure="2"):
		return sterilizing.save_manual_data(
			load=self.load.name,
			equipment_raw=self.machine.name,
			load_raw=self.load.name,
			values=[
				{"parameter_name": "Temperature", "value": temperature},
				{"parameter_name": "Pressure", "value": pressure},
			],
			started_at=str(add_to_date(now_datetime(), hours=-1)),
			ended_at=str(now_datetime()),
			machine_alerts=None,
			machine_report="/files/printout.png",
			reason=None,
			confirmed=True,
			card=self.employee.tc_card_id,
			client_ts=client_time.utc_now(),
			employee=self.employee.name,
			station=LOAD_STATION,
		)

	def context(self):
		return sterilizing.data_context(self.load.name, self.machine.name, self.load.name, LOAD_STATION)

	def test_prefill_and_trace(self):
		prefill = self.context()["prefill"]
		self.assertEqual(prefill["values"], {"Temperature": 134, "Pressure": 2})
		self.save(temperature="135")
		doc = frappe.get_doc("Sterilization Load", self.load.name)
		self.assertEqual(doc.data_source, "Manual Default")
		rows = {row["parameter_name"]: row for row in json.loads(doc.params)}
		self.assertTrue(rows["Temperature"]["edited"])
		self.assertEqual(rows["Temperature"]["default_value"], 134)
		trace = json.loads(doc.machine_data)
		self.assertIn("Temperature", trace["edited_fields"])
		self.assertIsNone(self.context()["prefill"])  # đã lưu: form dùng giá trị đã lưu

	@bru("BRU-REP-015")
	def test_cycle_result_pass_blocked_outside_range(self):
		self.save(temperature="120")
		with self.assertRaises(BlockedError) as caught:
			releasing.set_cycle_result(
				self.load.name, LOAD_STATION, self.machine.name, self.load.name, "Pass", True
			)
		self.assertEqual(caught.exception.block.code, "CYCLE_DATA_OUT_OF_RANGE")
		done = releasing.set_cycle_result(
			self.load.name, LOAD_STATION, self.machine.name, self.load.name, "Fail", True
		)
		self.assertEqual(done["cycle_result"], "Fail")

	def test_helper_lists_outside_rows(self):
		rows = [{"parameter_name": "A", "outside_range": True}, {"parameter_name": "B", "outside_range": False}]  # fmt: skip
		self.assertEqual(cycle_defaults.outside_names(rows), ["A"])


class TestAssets(IsolatedTestCase):
	def test_forms_use_the_prefill_and_the_confirm_button(self):
		for name in ("station_t2.js", "station_t5.js"):
			with open(frappe.get_app_path("tracecore", "public", "js", name), encoding="utf-8") as handle:
				script = handle.read()
			self.assertIn("prefill", script, name)
			self.assertIn('__("Confirm cycle data")', script, name)
			self.assertNotIn("Save manual data and confirm", script, name)
		with open(frappe.get_app_path("tracecore", "translations", "vi.csv"), encoding="utf-8") as handle:
			self.assertIn("Xác nhận dữ liệu chu trình", handle.read())
