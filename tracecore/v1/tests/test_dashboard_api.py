"""RPC tracecore.v1.dashboard.* (FEAT-006, FR-M9-01, FR-M9-13, UC-32, SCR-32; A-54 D2, D11, D13)."""

import frappe

from tracecore.core import gs1
from tracecore.tests.factories import make_set_unit, make_user
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import dashboard as api

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
ALL_BLOCKS = {
	"sets",
	"output",
	"failures",
	"sterile",
	"par",
	"overrides",
	"recalls",
	"certificates",
	"equipment",
	"stock",
	"waste",
}


class DashboardCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(api.clear_cache)
		api.clear_cache()

	def summary_as(self, roles, **filters):
		user = make_user(f"dash-{'-'.join(r.split()[-1].lower() for r in roles)}@example.com", roles)
		frappe.set_user(user)
		try:
			return api.summary(**filters)
		finally:
			frappe.set_user("Administrator")


class TestSummaryByRole(DashboardCase):
	def test_r01_and_r02_get_every_block(self):
		for role in ("TC R01", "TC R02"):
			result = self.summary_as([role])
			self.assertTrue(result["ok"])
			self.assertEqual(set(result["blocks"]), ALL_BLOCKS, role)

	def test_r09_gets_sterile_stock_and_par_only(self):
		self.assertEqual(set(self.summary_as(["TC R09"])["blocks"]), {"sterile", "stock", "par"})

	def test_r10_gets_equipment_and_certificates_only(self):
		self.assertEqual(set(self.summary_as(["TC R10"])["blocks"]), {"equipment", "certificates"})

	def test_station_roles_and_guest_are_refused(self):
		for roles in (["TC R04"], ["TC R03", "TC R05"]):
			with self.assertRaises(frappe.PermissionError):
				self.summary_as(roles)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			api.summary()

	def test_block_without_read_permission_is_left_out(self):
		user = make_user("dash-noread@example.com", ["TC R02"])
		frappe.set_user(user)
		original = frappe.has_permission

		def fake(doctype, ptype="read", *args, **kwargs):
			return False if doctype == "Recall Order" else original(doctype, ptype, *args, **kwargs)

		frappe.has_permission = fake
		try:
			blocks = api.summary()["blocks"]
		finally:
			frappe.has_permission = original
		self.assertNotIn("recalls", blocks)
		self.assertIn("sets", blocks)


class TestSummaryContent(DashboardCase):
	def test_shape_counts_and_filters(self):
		result = api.summary(period="week")
		self.assertEqual(result["period"], "week")
		self.assertEqual(len(result["range"]), 2)
		self.assertTrue(result["generated_at"])
		blocks = result["blocks"]
		self.assertEqual([row["status"] for row in blocks["sets"]], list(api.board.SET_STATUSES))
		self.assertEqual(set(blocks["output"]), {"station", "user", "equipment"})
		self.assertEqual(set(blocks["failures"]), {"load", "wash"})
		self.assertEqual(set(blocks["sterile"]), {"total", "by_set_type", "expiring"})
		self.assertEqual(set(blocks["stock"]), {"below_minimum", "expiring"})
		for name in ("par", "overrides", "recalls", "certificates", "equipment"):
			self.assertEqual(set(blocks[name]), {"count", "rows"}, name)
		self.assertIn("ZONE-CLEAN", [row["value"] for row in result["options"]["zones"]])

	def test_new_set_shows_up_after_cache_clear_but_cache_holds_30_seconds(self):
		before = {row["status"]: row["count"] for row in api.summary()["blocks"]["sets"]}
		make_set_unit()
		cached = {row["status"]: row["count"] for row in api.summary()["blocks"]["sets"]}
		self.assertEqual(cached["New"], before["New"])
		api.clear_cache()
		fresh = {row["status"]: row["count"] for row in api.summary()["blocks"]["sets"]}
		self.assertEqual(fresh["New"], before["New"] + 1)

	def test_bad_filters_are_rejected(self):
		with self.assertRaises(api.BadRequestError):
			api.summary(period="year")
		with self.assertRaises(api.BadRequestError):
			api.summary(zone="TR-004")
		with self.assertRaises(api.BadRequestError):
			api.summary(equipment="NO-SUCH")

	def test_query_count_does_not_grow_with_sets(self):
		api.clear_cache()
		with self.assertQueryCount(400):
			api.summary()

	def test_is_get_only(self):
		from frappe import allowed_http_methods_for_whitelisted_func as methods
		from frappe import whitelisted

		self.assertIn(api.summary, whitelisted)
		self.assertEqual(methods[api.summary], ["GET"])
		self.assertEqual(methods[api.find_in_list], ["GET"])


class TestFindInList(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.unit = make_set_unit()

	def test_exact_set_id_and_gs1_scan_open_the_record(self):
		set_id = self.unit.set_id or self.unit.name
		self.assertEqual(
			api.find_in_list("Set Unit", set_id),
			{"ok": True, "name": self.unit.name, "code": set_id, "field": "set_id"},
		)
		scan = gs1.giai_payload(set_id)
		self.assertEqual(api.find_in_list("Set Unit", scan)["name"], self.unit.name)

	def test_unknown_code_returns_no_name_but_the_cleaned_code(self):
		result = api.find_in_list("Set Unit", "  NOTHING-123 \r\n")
		self.assertEqual(result, {"ok": True, "name": None, "code": "NOTHING-123", "field": "set_id"})
		self.assertEqual(api.find_in_list("Wash Batch", "LR-NONE")["field"], "name")

	def test_doctype_outside_the_list_or_without_read_is_refused(self):
		with self.assertRaises(api.BadRequestError):
			api.find_in_list("User", "Administrator")
		with self.assertRaises(api.BadRequestError):
			api.find_in_list("Set Unit", "")
		frappe.set_user(make_user("dash-scan-r08@example.com", ["TC R08"]))
		with self.assertRaises(frappe.PermissionError):
			api.find_in_list("Equipment", "TB-0001")
