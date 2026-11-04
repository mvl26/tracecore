"""RPC `tracecore.v1.station.next_barcode`: mã vạch của trạm kế tiếp cho màn trạm (A-117, FR-M9-22)."""

import base64

import frappe

from tracecore.core import qr
from tracecore.setup.migrate_a64 import apply_yhct
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import station as station_api
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
TS = "2026-11-04T10:00:00+07:00"


def decode(png_b64):
	return qr.decode_png(base64.b64decode(png_b64))


class TestNextBarcode(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		apply_yhct(dry_run=False)
		self.user = make_user("tc-next-barcode@example.com")
		self.session = make_station_session(self.user, "TR-001")

	def call(self, **kwargs):
		frappe.local.response = frappe._dict()
		return station_api.next_barcode(token=self.session["token"], **kwargs)

	def test_returns_next_station_and_a_qr_of_its_code(self):
		result = self.call(step="RECEIVE")
		self.assertTrue(result["ok"])
		self.assertEqual(result["next"]["station"], "TR-003")
		self.assertEqual(decode(result["png_b64"]), "TR-003")

	def test_last_step_returns_no_barcode(self):
		result = self.call(step="USE")
		self.assertTrue(result["ok"])
		self.assertIsNone(result["next"])
		self.assertIsNone(result["png_b64"])

	def test_no_station_for_the_next_step_is_a_clear_block(self):
		for name in frappe.get_all(
			"Zone Station Function", filters={"station_function": "WASH_LOAD"}, pluck="parent"
		):
			frappe.db.set_value("Zone Station", name, "is_active", 0)
		result = self.call(step="RECEIVE")
		self.assertFalse(result["ok"])
		error = result["error"]
		self.assertEqual(error["code"], "NEXT_STATION_NOT_FOUND")
		self.assertTrue(error["title"] and error["reason"] and error["action"])

	def test_unknown_step_is_a_bad_request(self):
		with self.assertRaises(Exception):
			self.call(step="NOT_A_STEP")

	def test_requires_a_valid_session(self):
		frappe.local.response = frappe._dict()
		result = station_api.next_barcode(token="khong-co-phien", step="RECEIVE")
		self.assertFalse(result["ok"])
