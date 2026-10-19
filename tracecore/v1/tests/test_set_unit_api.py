import time
import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import code_registry
from tracecore.tests.factories import make_set_type, make_set_unit, make_user
from tracecore.tests.utils import bru, request_headers
from tracecore.v1 import set_unit as api

TS = "2026-10-19T09:00:00+07:00"


def scan(raw, key=None):
	headers = {"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": "TR-004"}
	with request_headers(headers):
		return api.get(set_id=raw, client_ts=TS)


class TestSetUnitApi(FrappeTestCase):
	def test_get_returns_set_unit_under_1s(self):
		su = make_set_unit(set_type=make_set_type("API", set_type_name="API set").name, max_cycles=300)
		started = time.perf_counter()
		result = scan("]d2\x1d8004" + su.name + "\r\n")
		elapsed = time.perf_counter() - started
		self.assertTrue(result["ok"])
		data = result["set_unit"]
		self.assertEqual(data["set_id"], su.name)
		self.assertEqual(data["set_type"], "API")
		self.assertEqual(data["set_type_name"], "API set")
		self.assertEqual(data["method"], "Steam")
		self.assertEqual(data["status"], "New")
		self.assertEqual((data["cycles_used"], data["max_cycles"]), (0, 300))
		self.assertLess(elapsed, 1.0)

	@bru("BRU-ID-006")
	def test_get_unknown_code_vietnamese_error_and_audit(self):
		frappe.local.lang = "vi"
		try:
			result = scan("XYZ-123")
		finally:
			frappe.local.lang = "en"
		self.assertFalse(result["ok"])
		error = result["error"]
		self.assertEqual(error["code"], "SCAN_INVALID")
		self.assertEqual(error["title"], "Mã không hợp lệ")
		self.assertIn("XYZ-123", error["reason"])
		self.assertTrue(error["action"])
		log = frappe.get_all(
			"Audit Log",
			filters={"action": "Reject", "reason": "SCAN_INVALID"},
			fields=["station", "new_value"],
			order_by="timestamp desc, name desc",
			limit=1,
		)[0]
		self.assertEqual(log.station, "TR-004")
		self.assertEqual(frappe.parse_json(log.new_value)["raw"], "XYZ-123")

	def test_get_wrong_type(self):
		result = scan("TR-004")
		self.assertEqual(result["error"]["code"], "SCAN_WRONG_TYPE")

	def test_get_not_found(self):
		result = scan(code_registry.company_prefix() + "NOPE000001")
		self.assertEqual(result["error"]["code"], "SET_NOT_FOUND")

	def test_get_requires_read_permission(self):
		su = make_set_unit()
		frappe.set_user(make_user("api-noperm@example.com"))
		try:
			with self.assertRaises(frappe.PermissionError):
				scan(su.name)
		finally:
			frappe.set_user("Administrator")

	def test_get_allowed_for_station_role(self):
		su = make_set_unit()
		frappe.set_user(make_user("api-r04@example.com", roles=["TC R04"]))
		try:
			self.assertTrue(scan(su.name)["ok"])
		finally:
			frappe.set_user("Administrator")

	def test_get_replay_same_key(self):
		su = make_set_unit()
		key = str(uuid.uuid4())
		self.assertEqual(scan(su.name, key), scan(su.name, key))
