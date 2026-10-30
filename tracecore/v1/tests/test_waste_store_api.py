"""RPC kho lưu giữ tạm chất thải (FEAT-048, UC-35, FR-M10-03, A-61): phiên thẻ R07, idempotent, Audit từ chối."""

import uuid
from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from tracecore.tests.factories import (
	make_department,
	make_employee,
	make_user,
	make_waste_location,
	make_waste_station,
	make_waste_type,
	make_waste_zone,
)
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import station as station_api
from tracecore.v1 import waste as api

CARD = "STORE-R07-CARD"
GIVER = "STORE-R08-CARD"
TS = "2026-10-30T09:00:00+07:00"


class TestWasteStoreApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.station = make_waste_station()
		self.user = make_user("store-r07@example.com", ["TC R07"])
		self.collector = make_employee(
			card=CARD,
			first_name="Kho",
			user_id=self.user,
			company=frappe.db.get_value("Company", {}, "name"),
		).name
		make_employee(card=GIVER, department=make_department("Khoa Store API"), first_name="Giao")
		self.waste = make_waste_type().name
		self.location = make_waste_location([self.waste], default=True)
		now = now_datetime()
		frappe.get_doc(
			{
				"doctype": "Station Competency",
				"employee": self.collector,
				"station": self.station,
				"valid_from": now - timedelta(hours=1),
				"valid_until": now + timedelta(hours=8),
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		self.token = station_api.login(CARD, self.station, client_ts=TS)["session"]["token"]

	def call(self, fn, key=None, **kwargs):
		frappe.local.response.pop("http_status_code", None)
		kwargs.setdefault("station", self.station)
		kwargs.setdefault("client_ts", TS)
		kwargs.setdefault("token", self.token)
		with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": self.station}):
			return fn(**kwargs)

	def collect(self):
		lines = [{"waste_type": self.waste, "qty": 1, "weight_kg": 1, "weight_source": "Scale"}]
		return self.call(api.collect, card=GIVER, lines=lines)["collection"]

	def test_store_bag_and_read_stock(self):
		bag = self.collect()["containers"][0]["name"]
		result = self.call(api.store, location=self.location, container=bag)
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["container"]["location"], self.location)
		stock = self.call(api.stock)
		self.assertTrue(stock["ok"])
		self.assertIn(bag, [row["name"] for row in stock["containers"]])

	def test_store_whole_collection(self):
		collection = self.collect()["name"]
		result = self.call(api.store, collection=collection)
		self.assertEqual((result["ok"], result["stored"]), (True, 1))

	def test_store_replay_is_recorded_once(self):
		bag = self.collect()["containers"][0]["name"]
		key = str(uuid.uuid4())
		first = self.call(api.store, key=key, location=self.location, container=bag)
		second = self.call(api.store, key=key, location=self.location, container=bag)
		self.assertEqual(first["container"]["name"], second["container"]["name"])
		self.assertEqual(str(first["container"]["storage_due"]), str(second["container"]["storage_due"]))
		self.assertEqual(
			frappe.db.count(
				"Audit Log", {"ref_doctype": "Waste Container", "ref_name": bag, "action": "Update"}
			),
			1,
		)

	def test_wrong_location_is_refused_and_logged(self):
		bag = self.collect()["containers"][0]["name"]
		other = make_waste_location([make_waste_type().name])
		result = self.call(api.store, location=other, container=bag)
		self.assertEqual((result["ok"], result["error"]["code"]), (False, "WASTE_WRONG_LOCATION"))
		self.assertTrue(
			frappe.db.exists(
				"Audit Log", {"action": "Reject", "station": self.station, "reason": "WASTE_WRONG_LOCATION"}
			)
		)

	def test_check_location_reports_the_location(self):
		result = self.call(api.check_location, location=self.location)
		self.assertEqual((result["ok"], result["location"]["name"]), (True, self.location))
		self.assertEqual(
			self.call(api.check_location, location="KE-0000")["error"]["code"], "WASTE_LOCATION_INVALID"
		)

	def test_record_temperature_runs_as_r07(self):
		cold = make_waste_location([self.waste], is_cold=1, zone=make_waste_zone(monitored=True))
		result = self.call(api.record_temperature, location=cold, temperature="5")
		self.assertTrue(result["ok"], result)
		self.assertEqual(frappe.db.get_value("Environment Log", result["log"], "recorded_by"), self.user)

	def test_thresholds_are_for_r02_and_r10(self):
		r02 = make_user("store-r02@example.com", ["TC R02"])
		frappe.set_user(self.user)
		with self.assertRaises(frappe.PermissionError):
			api.set_thresholds(70, 8, 2)
		frappe.set_user(r02)
		self.assertEqual(api.set_thresholds(70, 8, 2)["thresholds"]["warn_percent"], 70)
		self.assertEqual(api.thresholds()["warn_percent"], 70)
		self.assertEqual(api.set_thresholds(0, 8, 2)["error"]["code"], "WASTE_THRESHOLD_INVALID")

	def test_stock_report_shows_remaining_time(self):
		from tracecore.waste.report.waste_storage_stock.waste_storage_stock import execute

		bag = self.collect()["containers"][0]["name"]
		columns, rows = execute({})
		self.assertIn("remaining", [column["fieldname"] for column in columns])
		row = next(row for row in rows if row["container"] == bag)
		self.assertEqual(row["state"], "OK")
		self.assertRegex(row["remaining"], r"^\d+ h \d+ min$")

	def test_permission_matrix(self):
		self.assertTrue(frappe.has_permission("Waste Storage Location", "read", user=self.user))
		self.assertFalse(frappe.has_permission("Waste Storage Location", "write", user=self.user))
		self.assertTrue(
			frappe.has_permission(
				"Waste Storage Location", "write", user=make_user("store-r10@example.com", ["TC R10"])
			)
		)
