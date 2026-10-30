"""RPC tracecore.v1.waste.* (FEAT-047, UC-34, FR-M10-02, .5, .6, A-59 W4, W14): phiên thẻ R07, idempotent, Audit từ chối."""

import uuid
from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from tracecore.tests.factories import (
	make_department,
	make_employee,
	make_user,
	make_waste_station,
	make_waste_type,
)
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.ui.waste_print import tc_waste_receipt_context
from tracecore.v1 import station as station_api
from tracecore.v1 import waste as api

CARD = "WASTE-R07-CARD"
GIVER = "WASTE-R08-CARD"
TS = "2026-10-30T09:00:00+07:00"


class TestWasteApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.station = make_waste_station()
		self.user = make_user("waste-r07@example.com", ["TC R07"])
		self.collector = make_employee(
			card=CARD,
			first_name="Thu gom",
			user_id=self.user,
			company=frappe.db.get_value("Company", {}, "name"),
		).name
		self.department = make_department("Khoa Waste API")
		self.giver = make_employee(card=GIVER, department=self.department, first_name="Nguoi giao").name
		self.waste = make_waste_type().name
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

	def lines(self, **kwargs):
		return [{"waste_type": self.waste, "qty": 2, "weight_kg": 4, "weight_source": "Scale", **kwargs}]

	def test_catalog_lists_active_types(self):
		frappe.db.set_value("Waste Type", make_waste_type().name, "is_active", 0)
		result = self.call(api.catalog)
		self.assertTrue(result["ok"])
		self.assertIn(self.waste, [row["name"] for row in result["types"]])
		self.assertFalse([row for row in result["types"] if not frappe.db.get_value("Waste Type", row["name"], "is_active")])

	def test_giver_card_shows_department(self):
		result = self.call(api.giver, card=GIVER)
		self.assertEqual((result["ok"], result["giver"]["department"]), (True, self.department))

	def test_bad_giver_card_is_refused_and_logged(self):
		result = self.call(api.giver, card="NOPE")
		self.assertEqual((result["ok"], result["error"]["code"]), (False, "WASTE_GIVER_INVALID"))
		self.assertEqual(frappe.local.response.get("http_status_code"), 403)
		self.assertTrue(
			frappe.db.exists("Audit Log", {"action": "Reject", "station": self.station, "reason": "WASTE_GIVER_INVALID"})
		)

	def test_collect_runs_as_r07_and_returns_containers(self):
		result = self.call(api.collect, card=GIVER, lines=self.lines())
		self.assertTrue(result["ok"], result)
		collection = result["collection"]
		self.assertEqual(len(collection["containers"]), 2)
		doc = frappe.get_doc("Waste Collection", collection["name"])
		self.assertEqual((doc.collected_by, doc.department, doc.owner), (self.collector, self.department, self.user))

	def test_collect_replay_creates_one_collection(self):
		key = str(uuid.uuid4())
		first = self.call(api.collect, key=key, card=GIVER, lines=self.lines())
		second = self.call(api.collect, key=key, card=GIVER, lines=self.lines())
		self.assertEqual(first["collection"]["name"], second["collection"]["name"])
		self.assertEqual(frappe.db.count("Waste Collection", {"delivered_by": self.giver}), 1)

	def test_collect_accepts_json_lines_and_rejects_malformed(self):
		self.assertTrue(self.call(api.collect, card=GIVER, lines=frappe.as_json(self.lines()))["ok"])
		from tracecore.v1._common import BadRequestError

		with self.assertRaises(BadRequestError):
			self.call(api.collect, card=GIVER, lines="not json")

	def test_wrong_station_step_is_refused(self):
		result = self.call(api.catalog, station="TR-004")
		self.assertIs(result["ok"], False)

	def test_acknowledge_records_ward_card(self):
		name = self.call(api.collect, card=GIVER, lines=self.lines())["collection"]["name"]
		result = self.call(api.acknowledge, collection=name, card=GIVER)
		self.assertTrue(result["ok"])
		self.assertEqual(frappe.db.get_value("Waste Collection", name, "acknowledged_by"), self.giver)

	def test_release_held_is_for_r02(self):
		result = self.call(api.collect, card=GIVER, lines=self.lines(misclassified=1, misclass_note="Mixed"))
		container = result["collection"]["containers"][0]["name"]
		frappe.set_user(self.user)
		with self.assertRaises(frappe.PermissionError):
			api.release_held(container, "Sorted")
		frappe.set_user(make_user("waste-r02@example.com", ["TC R02"]))
		self.assertTrue(api.release_held(container, "Sorted")["ok"])
		self.assertEqual(api.release_held(container, "Sorted")["error"]["code"], "WASTE_NOT_HELD")

	def test_receipt_context_formats_numbers_and_checks_permission(self):
		name = self.call(api.collect, card=GIVER, lines=self.lines(weight_kg=4.5))["collection"]["name"]
		context = tc_waste_receipt_context(name)
		self.assertEqual(context["total_weight"], "4,5")
		self.assertEqual(context["items"][0]["qty"], 2)
		frappe.set_user(make_user("waste-r04@example.com", ["TC R04"]))
		with self.assertRaises(frappe.PermissionError):
			tc_waste_receipt_context(name)

	def test_permission_matrix(self):
		self.assertTrue(frappe.has_permission("Waste Collection", "submit", user=self.user))
		self.assertFalse(frappe.has_permission("Waste Type", "write", user=self.user))
		self.assertFalse(frappe.has_permission("Waste Container", "create", user=self.user))
