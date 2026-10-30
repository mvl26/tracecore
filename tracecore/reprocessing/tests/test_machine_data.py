"""Dữ liệu máy tự động qua station agent (FEAT-024, A-39, ADR-007; FR-M2-24, EI-SW-001, UC-06 bước 4, UC-09 A3)."""

import json
import uuid
from datetime import timedelta

import frappe
from frappe.utils import get_datetime

from tracecore.core.errors import BlockedError
from tracecore.reprocessing import machine_data
from tracecore.tests import factories
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import load as load_api

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
WASH_STATION = "TR-002"
LOAD_STATION = "TR-005"
WASH_PARAMS = [
	{"parameter_name": "Nhiệt độ rửa", "unit": "°C", "min_value": 90, "max_value": 95, "required": 1},
	{"parameter_name": "A0", "unit": "", "min_value": 3000, "max_value": 0, "required": 1},
]
LOAD_PARAMS = [
	{"parameter_name": "Nhiệt độ", "unit": "°C", "min_value": 134, "max_value": 137, "required": 1},
	{"parameter_name": "Áp suất", "unit": "bar", "min_value": 2, "max_value": 2.3, "required": 1},
]


def blocked(case, code, fn, *args, **kwargs):
	with case.assertRaises(BlockedError) as caught:
		fn(*args, **kwargs)
	case.assertEqual(caught.exception.block.code, code)


def iso(value):
	return f"{get_datetime(value).isoformat(timespec='seconds')}+07:00"


class MachineCase(IsolatedTestCase):
	def washer_batch(self, connected=1):
		washer = factories.make_wash_machine(is_connected=connected)
		program = factories.make_wash_program(washer.name, parameters=WASH_PARAMS)
		unit = factories.make_wash_ready_set()
		batch = factories.make_wash_batch(washer, program, [unit], operator=factories.make_employee().name)
		return washer.name, batch

	def sterilizer_load(self, connected=1):
		machine = factories.make_sterilizer(is_connected=connected)
		program = factories.make_sterilize_program(machine.name, parameters=LOAD_PARAMS)
		pack = factories.make_load_ready_pack()
		load = factories.make_load(machine, program, [pack], operator=factories.make_employee().name)
		return machine.name, load

	def cycle(self, doc, load_id=None, minutes=5, params=None, result="Pass", ref=None, alerts=None):
		started = get_datetime(doc.started_at) + timedelta(minutes=minutes)
		return {
			"cycle_ref": ref or f"C-{frappe.generate_hash(length=6)}",
			"load_id": load_id,
			"program": None,
			"started_at": iso(started),
			"ended_at": iso(started + timedelta(minutes=40)),
			"parameters": params or [],
			"alerts": alerts or [],
			"result": result,
			"driver": "csv_generic",
		}


class TestIngestWash(MachineCase):
	def test_exact_match_by_batch_code_fills_auto_data(self):
		washer, batch = self.washer_batch()
		params = [{"parameter_name": "Nhiệt độ rửa", "value": 93}, {"parameter_name": "A0", "value": 3200}]
		result = machine_data.ingest(WASH_STATION, washer, self.cycle(batch, batch.name, params=params))
		self.assertEqual(
			(result["doctype"], result["name"], result["matched_by"]), ("Wash Batch", batch.name, "load_id")
		)
		doc = frappe.get_doc("Wash Batch", batch.name)
		self.assertEqual((doc.data_source, doc.data_complete, doc.needs_review), ("Auto", 1, 0))
		self.assertEqual(doc.status, "Running")
		self.assertTrue(doc.ended_at)
		data = json.loads(doc.machine_data)
		self.assertEqual(data["source"]["driver"], "csv_generic")
		self.assertEqual(data["reported_result"], "Pass")
		self.assertEqual({row["parameter_name"] for row in data["parameters"]}, {"Nhiệt độ rửa", "A0"})

	def test_missing_or_out_of_range_parameters(self):
		washer, batch = self.washer_batch()
		params = [{"parameter_name": "Nhiệt độ rửa", "value": 99}]
		result = machine_data.ingest(WASH_STATION, washer, self.cycle(batch, batch.name, params=params))
		self.assertEqual(result["missing"], ["A0"])
		doc = frappe.get_doc("Wash Batch", batch.name)
		self.assertEqual((doc.data_complete, doc.needs_review), (0, 1))


class TestIngestLoad(MachineCase):
	def test_time_match_is_fuzzy_and_completes_the_load(self):
		machine, load = self.sterilizer_load()
		params = [{"parameter_name": "Nhiệt độ", "value": 134.5}, {"parameter_name": "Áp suất", "value": 2.1}]
		result = machine_data.ingest(
			LOAD_STATION, machine, self.cycle(load, params=params, alerts=["Cửa mở chậm"])
		)
		self.assertEqual((result["name"], result["matched_by"]), (load.name, "time"))
		doc = frappe.get_doc("Sterilization Load", load.name)
		self.assertEqual((doc.data_source, doc.data_complete, doc.needs_review), ("Auto", 1, 1))
		self.assertEqual(
			(doc.status, doc.cycle_result, doc.result_source), ("Cycle Complete", "Pass", "Auto")
		)
		self.assertEqual(len(json.loads(doc.params)), 2)
		self.assertEqual(json.loads(doc.machine_alerts)["text"], "Cửa mở chậm")

	def test_unmatched_cycle_is_rejected_without_writing(self):
		machine, load = self.sterilizer_load()
		blocked(
			self,
			"MACHINE_CYCLE_UNMATCHED",
			machine_data.ingest,
			LOAD_STATION,
			machine,
			self.cycle(load, minutes=300),
		)
		self.assertFalse(frappe.db.get_value("Sterilization Load", load.name, "data_source"))

	def test_machine_must_be_connected_and_at_the_agent_station(self):
		machine, load = self.sterilizer_load(connected=0)
		blocked(
			self,
			"MACHINE_NOT_CONNECTED",
			machine_data.ingest,
			LOAD_STATION,
			machine,
			self.cycle(load, load.name),
		)
		other, load = self.sterilizer_load()
		blocked(
			self,
			"MACHINE_NOT_AT_STATION",
			machine_data.ingest,
			WASH_STATION,
			other,
			self.cycle(load, load.name),
		)

	def test_resend_is_idempotent_and_manual_data_is_kept(self):
		machine, load = self.sterilizer_load()
		params = [{"parameter_name": "Nhiệt độ", "value": 135}, {"parameter_name": "Áp suất", "value": 2.1}]
		cycle = self.cycle(load, load.name, params=params, ref="C-777")
		first = machine_data.ingest(LOAD_STATION, machine, cycle)
		again = machine_data.ingest(LOAD_STATION, machine, cycle)
		self.assertEqual((again["name"], again["duplicate"]), (first["name"], True))
		manual, load2 = self.sterilizer_load()
		frappe.db.set_value(
			"Sterilization Load",
			load2.name,
			{"data_source": "Manual", "data_complete": 1},
			update_modified=False,
		)
		blocked(
			self,
			"MACHINE_DATA_EXISTS",
			machine_data.ingest,
			LOAD_STATION,
			manual,
			self.cycle(load2, load2.name, params=params),
		)


class TestIngestApi(MachineCase):
	def call(self, **kwargs):
		with request_headers({"X-Idempotency-Key": str(uuid.uuid4()), "X-TC-Station": LOAD_STATION}):
			return load_api.ingest_machine_data(client_ts="2026-10-26T09:00:00+07:00", **kwargs)

	def test_agent_of_the_station_posts_cycles(self):
		machine, load = self.sterilizer_load()
		frappe.set_user(make_user("agent-tr-005@tracecore.local", roles=["TC Agent"]))
		self.addCleanup(frappe.set_user, "Administrator")
		params = [{"parameter_name": "Nhiệt độ", "value": 135}, {"parameter_name": "Áp suất", "value": 2.1}]
		result = self.call(
			station=LOAD_STATION,
			equipment=machine,
			cycle=json.dumps(self.cycle(load, load.name, params=params)),
		)
		self.assertEqual((result["ok"], result["name"]), (True, load.name))
		refused = self.call(
			station=LOAD_STATION, equipment=machine, cycle=json.dumps(self.cycle(load, minutes=600))
		)
		self.assertEqual((refused["ok"], refused["error"]["code"]), (False, "MACHINE_CYCLE_UNMATCHED"))
		with self.assertRaises(frappe.PermissionError):
			self.call(station=WASH_STATION, equipment=machine, cycle=json.dumps(self.cycle(load, load.name)))

	def test_cycle_must_be_an_object(self):
		machine, _load = self.sterilizer_load()
		frappe.set_user(make_user("agent-tr-005@tracecore.local", roles=["TC Agent"]))
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.ValidationError):
			self.call(station=LOAD_STATION, equipment=machine, cycle="không phải JSON")
