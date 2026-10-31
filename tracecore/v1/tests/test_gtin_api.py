"""RPC tracecore.v1.gtin.* (A-76): trạng thái, xem trước và xác nhận cấp bù, đổi GTIN đã khóa; lỗi trả body có mã."""

import uuid

import frappe

from tracecore.core import gs1
from tracecore.tests.factories import make_pack, make_set_type, make_set_unit, make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import gtin as api
from tracecore.v1 import set_type as set_type_api

SETTINGS = "TraceCore Settings"
SET_TYPE = "Instrument Set Type"
PREFIX = "8930001"
TS = "2026-10-31T10:00:00+07:00"


def call(fn, *args, **kwargs):
	with request_headers({"X-Idempotency-Key": str(uuid.uuid4())}):
		return fn(*args, **kwargs)


class TestGtinApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.set_single_value(SETTINGS, "gs1_company_prefix", PREFIX)
		self.r10 = make_user("gtin-api-r10@example.com", ["TC R10"])
		self.r02 = make_user("gtin-api-r02@example.com", ["TC R02"])

	def test_status_reports_range_and_rights(self):
		frappe.set_user(self.r10)
		self.addCleanup(frappe.set_user, "Administrator")
		result = api.status()
		self.assertTrue(result["ok"])
		self.assertEqual(result["prefix"], PREFIX)
		self.assertEqual(result["range"]["next_ref"], 1)
		self.assertTrue(result["can_manage"])
		frappe.set_user(self.r02)
		self.assertFalse(api.status()["can_manage"])

	def test_status_when_not_declared(self):
		frappe.db.set_single_value(SETTINGS, "gs1_company_prefix", "")
		result = api.status()
		self.assertEqual(result["prefix"], "")
		self.assertIsNone(result["range"])

	def test_preview_block_is_returned_as_body(self):
		frappe.db.set_single_value(SETTINGS, "gs1_company_prefix", "")
		result = api.backfill_preview()
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "GS1_PREFIX_NOT_DECLARED")

	def test_backfill_flow(self):
		name = make_set_type("GTX1", gtin="19520000000063").name
		preview = api.backfill_preview()
		self.assertIn(name, [row["set_type"] for row in preview["rows"]])
		result = call(
			api.backfill,
			[row["set_type"] for row in preview["rows"]],
			preview["next_ref"],
			None,
			client_ts=TS,
		)
		self.assertTrue(result["ok"])
		self.assertTrue(frappe.db.get_value(SET_TYPE, name, "gtin")[1:].startswith(PREFIX))

	def test_backfill_stale_is_rejected_with_code(self):
		make_set_type("GTX2", gtin="19520000000070")
		result = call(api.backfill, ["GTX2"], 999, None, client_ts=TS)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "GTIN_BACKFILL_STALE")

	def test_backfill_accepts_json_list(self):
		make_set_type("GTX3", gtin="19520000000087")
		preview = api.backfill_preview()
		names = frappe.as_json([row["set_type"] for row in preview["rows"]])
		self.assertTrue(call(api.backfill, names, preview["next_ref"], None, client_ts=TS)["ok"])

	def test_backfill_requires_r10(self):
		frappe.set_user(self.r02)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			call(api.backfill, [], 1, None, client_ts=TS)

	def test_change_locked_flow(self):
		doc = make_set_type("GTX4", gtin=None)
		make_pack(make_set_unit(doc.name), gtin=doc.gtin)
		new = gs1.make_gtin14("0", PREFIX, 800)
		result = call(api.change_locked, doc.name, new, "", client_ts=TS)
		self.assertEqual(result["error"]["code"], "REASON_REQUIRED")
		result = call(api.change_locked, doc.name, new, "Nhập sai", client_ts=TS)
		self.assertEqual((result["ok"], result["gtin"]), (True, new))

	def test_form_context_has_gtin_state(self):
		doc = make_set_type("GTX5", gtin=None)
		state = set_type_api.form_context(doc.name)["gtin"]
		self.assertFalse(state["locked"])
		self.assertEqual(state["prefix"], PREFIX)
