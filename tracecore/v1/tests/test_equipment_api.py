"""RPC tracecore.v1.equipment.get (FEAT-038 Task 4): tra máy theo mã QR, chương trình đang dùng, cảnh báo ngừng sử dụng."""

import inspect

import frappe

from tracecore.equipment.status import set_status
from tracecore.tests.factories import make_equipment, make_program, make_user
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import equipment as equipment_api

test_ignore = ["Asset", "Item", "User"]


def get(qr):
	frappe.local.response.pop("http_status_code", None)
	with request_headers({}):
		return equipment_api.get(qr=qr)


def http_status():
	return frappe.local.response.get("http_status_code")


class TestEquipmentApi(IsolatedTestCase):
	@bru("BRU-EQP-003")
	def test_get_returns_equipment_and_programs(self):
		equipment = make_equipment(name="Máy hấp 1", serial="SN-API1", capacity="300 L")
		other = make_equipment(name="Máy hấp 2", serial="SN-API2")
		make_program(equipment.name, code="API-1")
		make_program(other.name, code="API-2")
		result = get(equipment.name)
		self.assertTrue(result["ok"])
		self.assertIsNone(result["warning"])
		self.assertEqual(
			result["equipment"],
			{
				"name": equipment.name,
				"equipment_name": "Máy hấp 1",
				"equipment_type": "Steam Sterilizer",
				"status": "Ready",
				"zone_in": "ZONE-CLEAN",
				"zone_out": "ZONE-STERILE",
				"is_connected": 0,
				"has_printout": 0,
				"capacity": "300 L",
			},
		)
		self.assertEqual([p["program_code"] for p in result["programs"]], ["API-1"])
		self.assertIsNone(http_status())

	def test_get_rejects_non_equipment_code(self):
		before = frappe.db.count("Audit Log", {"action": "Reject"})
		result = get("XYZ-123")
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "SCAN_INVALID")
		self.assertIn("XYZ-123", result["error"]["reason"])
		self.assertEqual(http_status(), 422)
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Reject"}), before + 1)

	def test_get_unknown_equipment_404_with_audit(self):
		result = get("TB-9999")
		self.assertEqual(result["error"]["code"], "EQUIPMENT_NOT_FOUND")
		self.assertIn("TB-9999", result["error"]["reason"])
		self.assertEqual(http_status(), 404)
		log = frappe.get_all(
			"Audit Log",
			filters={"action": "Reject", "reason": "EQUIPMENT_NOT_FOUND"},
			fields=["ref_doctype", "ref_name", "new_value"],
		)
		self.assertEqual(len(log), 1)
		self.assertEqual(frappe.parse_json(log[0].new_value)["raw"], "TB-9999")

	@bru("BRU-EQP-003")
	def test_get_retired_equipment_warns_without_programs(self):
		equipment = make_equipment(name="Máy cũ", serial="SN-OLD")
		make_program(equipment.name, code="OLD-1")
		set_status(equipment.name, "Retired", "Hết khấu hao")
		result = get(equipment.name)
		self.assertTrue(result["ok"])
		self.assertEqual(result["programs"], [])
		self.assertEqual(result["equipment"]["status"], "Retired")
		warning = result["warning"]
		self.assertEqual(warning["code"], "EQUIPMENT_RETIRED")
		self.assertTrue(warning["title"] and warning["reason"] and warning["action"])
		self.assertIn(equipment.name, warning["reason"])
		self.assertIsNone(http_status())

	def test_get_requires_read_permission(self):
		before = frappe.db.count("Audit Log", {"action": "Reject"})
		frappe.set_user(make_user("eq-nobody@example.com"))
		try:
			with self.assertRaises(frappe.PermissionError):
				get("TB-9999")
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Reject"}), before)

	def test_get_is_whitelisted_post_only_and_not_idempotent(self):
		self.assertEqual(frappe.get_attr("tracecore.v1.equipment.get"), equipment_api.get)
		self.assertIn(equipment_api.get, frappe.whitelisted)
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[equipment_api.get], ["POST"])
		# đọc thuần: không bọc @idempotent (không cần X-Idempotency-Key)
		self.assertNotIn("@idempotent", inspect.getsource(equipment_api.get))
