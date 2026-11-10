"""PDA theo dõi NKVM sau ra viện — chức năng trạm SSI_FOLLOWUP, RPC tracecore.v1.hai.ssi_* (FEAT-064; SCR-57 PDA;
FR-M13-08; BRU-HAI-005; A-147 k): phiên thẻ, idempotent, chỉ mã BN che, chức năng trạm đã đăng ký."""

import os
import uuid
from datetime import timedelta

import frappe
from frappe.utils import add_days, now_datetime, today

from tracecore.core import zones
from tracecore.hai_surveillance import ssi
from tracecore.hai_surveillance.tests import factories as f
from tracecore.hai_surveillance.tests import ssi_fixtures as s
from tracecore.tests.factories import make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.ui import station_help
from tracecore.v1 import hai as api
from tracecore.v1 import navigation
from tracecore.v1 import station as station_api

CARD = "SSI-R11-CARD"
STATION = "TR-SSI-PDA"
TS = "2026-11-10T09:00:00+07:00"


def make_ssi_station():
	if not frappe.db.exists("Zone Station", STATION):
		zone = frappe.get_doc(
			{
				"doctype": "Zone Station",
				"zone_station_name": "SSI zone",
				"is_zone": 1,
				"zone_type": "Department",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Zone Station",
				"is_zone": 0,
				"is_active": 1,
				"zone_station_name": "SSI PDA",
				"parent_zone": zone.name,
				"functions": [{"station_function": "SSI_FOLLOWUP"}],
			}
		).insert(ignore_permissions=True, set_name=STATION)
	return STATION


class TestSSIStation(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		self.ward = f.make_ward("KSNK SSI PDA")
		self.group = s.make_group("T-APPY", name="Cắt ruột thừa test", t=60)
		self.doc = s.make_ssi(
			self.ward, self.group.name, surgery=add_days(today(), -10), discharge_date=add_days(today(), -8)
		)
		self.r11 = make_user("ssi-pda-r11@example.com", [f.R11])
		self.station = make_ssi_station()
		employee = make_employee(
			card=CARD,
			first_name="SSI PDA",
			user_id=self.r11,
			company=frappe.db.get_value("Company", {}, "name"),
		).name
		now = now_datetime()
		frappe.get_doc(
			{
				"doctype": "Station Competency",
				"employee": employee,
				"station": self.station,
				"valid_from": now - timedelta(hours=1),
				"valid_until": now + timedelta(hours=8),
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		self.token = station_api.login(CARD, self.station, client_ts=TS)["session"]["token"]

	def call(self, fn, key=None, **kwargs):
		frappe.local.response.pop("http_status_code", None)
		kwargs.setdefault("station", self.station)
		kwargs.setdefault("client_ts", TS)
		kwargs.setdefault("token", self.token)
		with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": self.station}):
			return fn(**kwargs)

	@bru("BRU-HAI-005")
	def test_list_and_record(self):
		listed = self.call(api.ssi_followups)
		self.assertTrue(listed["ok"], listed)
		row = next(item for item in listed["due"] if item["name"] == self.doc.name)
		self.assertEqual(row["patient_code_masked"], "***6612")
		self.assertNotIn("BN-0000006612", frappe.as_json(listed))
		key = str(uuid.uuid4())
		result = self.call(api.ssi_record, key, surveillance=self.doc.name, row=row["row"], result="Negative")
		self.assertTrue(result["ok"], result)
		self.assertNotIn(row["row"], [item["row"] for item in result["due"]])
		again = self.call(api.ssi_record, key, surveillance=self.doc.name, row=row["row"], result="Negative")
		self.assertTrue(again["ok"])  # cùng khóa → phát lại response đã lưu, không ghi lần hai
		self.assertEqual(len(again["due"]), len(result["due"]))
		line = frappe.get_doc(ssi.DOCTYPE, self.doc.name).followups[0]
		self.assertEqual((line.result, line.done_by), ("Negative", self.r11))

	def test_bad_result_is_inline_block(self):
		row = self.call(api.ssi_followups)["due"][0]
		result = self.call(api.ssi_record, surveillance=row["name"], row=row["row"], result="Maybe")
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "SSI_VALUE_INVALID")

	def test_function_registered(self):
		self.assertEqual(frappe.db.get_value("Station Function", "SSI_FOLLOWUP", "screen_key"), "ssi")
		self.assertIn("SSI_FOLLOWUP", zones.allowed_functions("Department"))
		self.assertEqual(navigation.FUNCTION_ROLES["SSI_FOLLOWUP"], {"TC R01", "TC R11"})
		self.assertIn("SSI_FOLLOWUP", station_help.STATION_KEYS)
		self.assertEqual(len(station_help.DEFAULT_STEPS["SSI_FOLLOWUP"]), 3)
		self.assertIn("public/js/station_ssi.js", frappe.get_hooks("page_js")["station"])
		path = os.path.join(frappe.get_app_path("tracecore"), "public", "js", "station_ssi.js")
		code = open(path, encoding="utf-8").read()
		self.assertNotIn("TcOutbox", code)  # chỉ online: không xếp hàng dữ liệu người bệnh
