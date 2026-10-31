"""RPC bàn giao chất thải (FEAT-049, UC-36, FR-M10-04, A-62) và phiếu in: phiên thẻ R07, idempotent, Audit từ chối."""

import uuid
from datetime import timedelta
from pathlib import Path

import frappe
from frappe.utils import now_datetime

from tracecore.tests.factories import (
	make_department,
	make_employee,
	make_user,
	make_waste_location,
	make_waste_station,
	make_waste_type,
	make_waste_vendor,
)
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.ui.waste_print import tc_waste_handover_context
from tracecore.v1 import station as station_api
from tracecore.v1 import waste as api

CARD = "HAND-R07-CARD"
GIVER = "HAND-R08-CARD"
TS = "2026-10-30T09:00:00+07:00"
JS = Path(__file__).resolve().parents[2] / "public/js/station_waste_handover.js"


class TestWasteHandoverApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.station = make_waste_station()
		self.user = make_user("hand-r07@example.com", ["TC R07"])
		self.employee = make_employee(
			card=CARD,
			first_name="Ban giao",
			user_id=self.user,
			company=frappe.db.get_value("Company", {}, "name"),
		).name
		make_employee(card=GIVER, department=make_department("Khoa Hand API"), first_name="Giao")
		self.waste = make_waste_type(waste_group="General").name
		self.location = make_waste_location([self.waste])
		self.vendor = make_waste_vendor([self.waste])
		now = now_datetime()
		frappe.get_doc(
			{
				"doctype": "Station Competency",
				"employee": self.employee,
				"station": self.station,
				"valid_from": now - timedelta(hours=1),
				"valid_until": now + timedelta(hours=8),
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		self.token = station_api.login(CARD, self.station, client_ts=TS)["session"]["token"]

	def call(self, fn, **kwargs):
		frappe.local.response.pop("http_status_code", None)
		kwargs.setdefault("station", self.station)
		kwargs.setdefault("client_ts", TS)
		kwargs.setdefault("token", self.token)
		with request_headers({"X-Idempotency-Key": str(uuid.uuid4()), "X-TC-Station": self.station}):
			return fn(**kwargs)

	def bag(self, weight=10):
		lines = [{"waste_type": self.waste, "qty": 1, "weight_kg": weight, "weight_source": "Scale"}]
		name = self.call(api.collect, card=GIVER, lines=lines)["collection"]["containers"][0]["name"]
		self.assertTrue(self.call(api.store, location=self.location, container=name)["ok"])
		return name

	def signed(self, bag, kg):
		name = self.call(api.handover_create, vendor=self.vendor)["handover"]["name"]
		self.assertTrue(self.call(api.handover_add, handover_name=name, container=bag)["ok"])
		result = self.call(
			api.handover_sign,
			handover_name=name,
			weights=[{"waste_type": self.waste, "handover_kg": kg, "weight_source": "Scale"}],
			values={"vendor_signer": "A", "vendor_signature": "data:image/png;base64,AA=="},
		)
		self.assertTrue(result["ok"], result)
		return name

	def test_vendors_list_with_fifo(self):
		bag = self.bag()
		result = self.call(api.handover_vendors)
		self.assertIn(self.vendor, [row["name"] for row in result["vendors"]])
		self.assertIn(bag, [row["name"] for row in result["fifo"][self.waste]])

	def test_full_flow_posts_and_prints(self):
		name = self.signed(self.bag(), 10)
		result = self.call(api.handover_submit, handover_name=name)
		self.assertTrue(result["ok"], result)
		self.assertEqual(frappe.db.get_value("Waste Handover", name, "signed_by"), self.employee)
		context = tc_waste_handover_context(name)
		self.assertEqual(context["total_handover"], "10")
		self.assertEqual(context["total_cost"], "10.000")

	def test_variance_without_r02_is_refused_and_logged(self):
		name = self.signed(self.bag(), 8)
		self.assertEqual(
			self.call(api.handover_submit, handover_name=name)["error"]["code"], "WASTE_VARIANCE_REASON"
		)
		self.assertTrue(
			frappe.db.exists(
				"Audit Log", {"action": "Reject", "station": self.station, "reason": "WASTE_VARIANCE_REASON"}
			)
		)

	def test_bad_proof_is_refused(self):
		name = self.signed(self.bag(), 10)
		result = self.call(api.handover_submit, handover_name=name, approver_proof="nope")
		self.assertIs(result["ok"], False)

	def test_remove_and_attach_document(self):
		bag = self.bag()
		name = self.call(api.handover_create, vendor=self.vendor)["handover"]["name"]
		self.call(api.handover_add, handover_name=name, container=bag)
		self.assertEqual(
			self.call(api.handover_remove, handover_name=name, container=bag)["handover"]["containers"], []
		)
		frappe.set_user(self.user)
		self.assertEqual(api.attach_document(name)["error"]["code"], "WASTE_DOCUMENT_REQUIRED")

	def test_permission_matrix(self):
		self.assertTrue(frappe.has_permission("Waste Handover", "submit", user=self.user))
		self.assertFalse(frappe.has_permission("Waste Treatment Vendor", "write", user=self.user))

	def test_screen_uses_handover_rpcs_and_states(self):
		js = JS.read_text(encoding="utf-8")
		for method in (
			"handover_vendors",
			"handover_create",
			"handover_add",
			"handover_sign",
			"handover_submit",
		):
			self.assertIn(f'"tracecore.v1.waste.{method}"', js)
		for marker in ('setState("offline"', "renderLoading()", '"empty"', '"error"', "tc-alert-${variant}"):
			self.assertIn(marker, js)
		self.assertNotIn("frappe.msgprint", js)
