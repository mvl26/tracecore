"""RPC tracecore.v1.laundry.* (FEAT-034): phiên trạm thẻ, bước LIN, mã HTTP theo loại lỗi, replay idempotent."""

import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe

from tracecore.tests import factories
from tracecore.tests.factories import LINEN_STATION, make_linen_station, make_user
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import laundry as laundry_api
from tracecore.v1._common import BadRequestError
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
TOKENS = {}
DISINFECTANT = "HC-F34-DIS"


def now_ts():
	return datetime.now(TIME_ZONE).isoformat(timespec="seconds")


def call(fn, key=None, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	kwargs.setdefault("station", LINEN_STATION)
	kwargs.setdefault("token", TOKENS.get((frappe.session.user, kwargs["station"])))
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": kwargs["station"]}):
		return fn(**kwargs)


def http_status():
	return frappe.local.response.get("http_status_code")


class LaundryApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		TOKENS.clear()
		self.addCleanup(TOKENS.clear)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		make_linen_station()
		TOKENS[("Administrator", LINEN_STATION)] = make_station_session(
			"Administrator", station=LINEN_STATION
		)["token"]
		self.washer = factories.make_equipment(
			equipment_type="Laundry Washer",
			serial="LW-" + frappe.generate_hash(length=8),
			zone_in="ZONE-DIRTY",
			zone_out=None,
			capacity_kg=30,
		)
		self.dryer = factories.make_equipment(
			equipment_type="Dryer",
			serial="DR-" + frappe.generate_hash(length=8),
			zone_in="ZONE-DIRTY",
			zone_out=None,
		)
		factories.make_item(DISINFECTANT, "Chemical")
		self.program = factories.make_program(
			self.washer.name,
			code="MG-" + frappe.generate_hash(length=6).upper(),
			minutes=45,
			kwh=2,
			water=100,
			temperature=75,
		)

	def start(self, **kwargs):
		values = {
			"loads": [{"kg": 10, "contaminated": 1}],
			"equipment": self.washer.name,
			"program": self.program.name,
		}
		return call(laundry_api.start, **{**values, **kwargs})

	def complete(self, batch, **kwargs):
		values = {
			"dryer": self.dryer.name,
			"dry_temp_c": 70,
			"dry_minutes": 40,
			"clean_ok": 1,
			"dry_ok": 1,
		}
		return call(laundry_api.complete, **{"batch": batch, **values, **kwargs})

	def assert_rejection(self, result, code, status=422):
		self.assertIs(result["ok"], False, msg=result)
		self.assertEqual(result["error"]["code"], code)
		self.assertEqual(http_status(), status)
		for key in ("title", "reason", "action"):
			self.assertTrue(result["error"][key], msg=key)


class TestStart(LaundryApiCase):
	@bru("BRU-LIN-001")
	def test_start_creates_a_running_batch(self):  # FR-M3-03
		result = self.start()
		self.assertIs(result["ok"], True, msg=result)
		view = result["batch"]
		self.assertRegex(view["name"], r"^LG-\d{6}-\d{2}$")
		self.assertEqual((view["status"], view["weight_kg"], view["contaminated"]), ("Running", 10, 1))
		doc = frappe.get_doc("Laundry Batch", view["name"])
		self.assertEqual((doc.docstatus, doc.station, doc.equipment), (0, LINEN_STATION, self.washer.name))
		self.assertTrue(doc.operator)

	def test_replay_with_the_same_key_does_not_create_two_batches(self):
		key, stamp = str(uuid.uuid4()), now_ts()
		first = self.start(key=key, client_ts=stamp)
		again = self.start(key=key, client_ts=stamp)
		self.assertEqual(first["batch"]["name"], again["batch"]["name"])
		self.assertEqual(frappe.db.count("Laundry Batch", {"equipment": self.washer.name}), 1)

	def test_loads_and_chemicals_may_be_json_strings(self):
		result = self.start(
			loads=json.dumps([{"kg": 4, "contaminated": 1}, {"kg": 6, "contaminated": 1}]),
			chemicals=json.dumps([{"item": DISINFECTANT, "qty": 1}]),
		)
		self.assertIs(result["ok"], True, msg=result)
		self.assertEqual(result["batch"]["weight_kg"], 10)

	@bru("BRU-LIN-003")
	def test_mixed_flags_are_rejected(self):
		result = self.start(loads=[{"kg": 4, "contaminated": 1}, {"kg": 6, "contaminated": 0}])
		self.assert_rejection(result, "LAUNDRY_MIXED")
		self.assertEqual(frappe.db.count("Laundry Batch", {"equipment": self.washer.name}), 0)

	@bru("BRU-EQP-002")
	def test_locked_washer_is_rejected_with_423(self):
		frappe.db.set_value("Equipment", self.washer.name, "status", "Locked")
		self.assert_rejection(self.start(), "EQUIPMENT_NOT_READY", 423)

	@bru("BRU-LIN-001")
	def test_over_capacity_and_bad_weight_are_rejected(self):
		self.assert_rejection(self.start(loads=[{"kg": 31, "contaminated": 1}]), "LAUNDRY_OVER_CAPACITY")
		self.assert_rejection(self.start(loads=[{"kg": 0, "contaminated": 1}]), "LAUNDRY_WEIGHT_INVALID")

	def test_wrong_station_step_is_rejected(self):
		TOKENS[("Administrator", "TR-001")] = make_station_session("Administrator", station="TR-001")["token"]
		self.assert_rejection(self.start(station="TR-001"), "STATION_WRONG_STEP")

	def test_malformed_parameters_are_400(self):
		with self.assertRaises(BadRequestError):
			self.start(loads="không phải json")
		with self.assertRaises(BadRequestError):
			self.start(loads=[1, 2])
		with self.assertRaises(BadRequestError):
			self.start(chemicals="[1]")
		with self.assertRaises(BadRequestError):
			self.start(equipment=["x"])
		with self.assertRaises(BadRequestError):
			self.start(note=5)

	def test_other_roles_cannot_start_and_a_session_is_required(self):
		user = make_user("laundry-r03@example.com", roles=("TC R03",))
		frappe.set_user(user)
		TOKENS[(user, LINEN_STATION)] = make_station_session(user, station=LINEN_STATION)["token"]
		with self.assertRaises(frappe.PermissionError):
			self.start()
		frappe.set_user("Administrator")
		TOKENS.clear()
		self.assert_rejection(self.start(), "SESSION_INVALID", 401)


class TestComplete(LaundryApiCase):
	@bru("BRU-LIN-001")
	def test_complete_passes_the_batch_and_returns_its_cost(self):  # FR-M3-04
		factories.make_cost_rate_version(
			rates=[factories.rate_line(3000, "Electricity"), factories.rate_line(20, "Tap Water")],
			submit=True,
		)
		batch = self.start()["batch"]["name"]
		result = self.complete(batch)
		self.assertIs(result["ok"], True, msg=result)
		view = result["batch"]
		self.assertEqual((view["status"], view["dryer"]), ("Passed", self.dryer.name))
		self.assertEqual((view["cost_electricity"], view["cost_water"]), (6000, 2000))
		self.assertEqual((view["cost_total"], view["cost_per_kg"]), (8000, 800))
		self.assertEqual(frappe.db.get_value("Laundry Batch", batch, "docstatus"), 1)

	def test_failed_checks_fail_the_batch(self):
		batch = self.start()["batch"]["name"]
		self.assertEqual(self.complete(batch, dry_ok=0)["batch"]["status"], "Failed")

	def test_replay_does_not_complete_twice(self):
		batch = self.start()["batch"]["name"]
		key, stamp = str(uuid.uuid4()), now_ts()
		first = self.complete(batch, key=key, client_ts=stamp)
		again = self.complete(batch, key=key, client_ts=stamp)
		self.assertEqual(first["batch"]["name"], again["batch"]["name"])

	def test_completing_twice_is_a_conflict(self):
		batch = self.start()["batch"]["name"]
		self.complete(batch)
		self.assert_rejection(self.complete(batch), "LAUNDRY_NOT_RUNNING", 409)

	def test_unknown_batch_is_404_and_missing_checks_are_422(self):
		self.assert_rejection(self.complete("LG-000000-99"), "LAUNDRY_NOT_FOUND", 404)
		batch = self.start()["batch"]["name"]
		self.assert_rejection(self.complete(batch, clean_ok=None), "LAUNDRY_RESULT_REQUIRED")
		self.assert_rejection(self.complete(batch, dryer=self.washer.name), "LAUNDRY_EQUIPMENT_INVALID")

	def test_malformed_parameters_are_400(self):
		batch = self.start()["batch"]["name"]
		with self.assertRaises(BadRequestError):
			self.complete(["x"])
		with self.assertRaises(BadRequestError):
			self.complete(batch, note=5)
		with self.assertRaises(BadRequestError):
			self.complete(batch, dryer=["x"])


class TestContext(LaundryApiCase):
	def test_context_lists_ready_machines_programs_chemicals_and_running_batches(self):
		running = self.start()["batch"]["name"]
		frappe.db.set_value("Equipment", self.dryer.name, "status", "Locked")
		result = call(laundry_api.context)
		self.assertIs(result["ok"], True, msg=result)
		self.assertIn(self.washer.name, [row["name"] for row in result["washers"]])
		self.assertNotIn(self.dryer.name, [row["name"] for row in result["dryers"]])
		self.assertIn(self.program.name, [row["name"] for row in result["programs"]])
		self.assertIn(DISINFECTANT, [row["name"] for row in result["chemicals"]])
		self.assertIn(running, [row["name"] for row in result["running"]])
