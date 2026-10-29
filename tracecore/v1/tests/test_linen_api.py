"""RPC tracecore.v1.linen.* (FEAT-033 Task 4): phiên trạm thẻ, bước LIN, mã HTTP theo loại lỗi, replay idempotent."""

import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe

from tracecore.tests.factories import (
	LINEN_STATION,
	make_department,
	make_linen_station,
	make_linen_type,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import linen as linen_api
from tracecore.v1._common import BadRequestError
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
TOKENS = {}


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


class LinenApiCase(IsolatedTestCase):
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
		self.department = make_department("Test linen ward")
		self.sheet = make_linen_type(std_weight_kg=0.5).name
		self.gown = make_linen_type(std_weight_kg=1.0).name

	def collect(self, lines, **kwargs):
		kwargs.setdefault("department", self.department)
		kwargs.setdefault("delivered_by", "Hộ lý khoa")
		return call(linen_api.collect, lines=lines, **kwargs)

	def assert_rejection(self, result, code, status=422):
		self.assertIs(result["ok"], False, msg=result)
		self.assertEqual(result["error"]["code"], code)
		self.assertEqual(http_status(), status)
		for key in ("title", "reason", "action"):
			self.assertTrue(result["error"][key], msg=key)


class TestCollect(LinenApiCase):
	@bru("BRU-LIN-001")
	def test_collect_records_and_submits_the_collection(self):  # FR-M3-01
		result = self.collect([{"linen_type": self.sheet, "qty": 10, "weight_kg": 5}])
		self.assertIs(result["ok"], True, msg=result)
		view = result["collection"]
		self.assertRegex(view["collection"], r"^LNC-\d{4}-\d{5}$")
		self.assertEqual((view["total_qty"], view["total_weight_kg"]), (10, 5))
		doc = frappe.get_doc("Linen Collection", view["collection"])
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(
			(doc.department, doc.delivered_by, doc.station), (self.department, "Hộ lý khoa", LINEN_STATION)
		)
		self.assertTrue(doc.received_by)

	def test_replay_with_the_same_key_does_not_record_twice(self):
		key, stamp = str(uuid.uuid4()), now_ts()
		lines = [{"linen_type": self.sheet, "qty": 4, "weight_kg": 2}]
		first = self.collect(lines, key=key, client_ts=stamp)
		again = self.collect(lines, key=key, client_ts=stamp)
		self.assertEqual(first["collection"]["collection"], again["collection"]["collection"])
		self.assertEqual(frappe.db.count("Linen Collection", {"department": self.department}), 1)

	def test_lines_may_be_a_json_string(self):
		result = self.collect(json.dumps([{"linen_type": self.sheet, "qty": 2, "weight_kg": 1}]))
		self.assertIs(result["ok"], True, msg=result)

	def test_contaminated_flag_and_scale_source_are_kept(self):
		result = self.collect(
			[
				{
					"linen_type": self.sheet,
					"qty": 10,
					"weight_kg": 5.1,
					"contaminated": 0,
					"weight_source": "Scale",
				},
				{"linen_type": self.gown, "qty": 2, "weight_kg": 2},
			]
		)
		lines = result["collection"]["lines"]
		self.assertEqual(
			[(row["contaminated"], row["weight_source"]) for row in lines], [(0, "Scale"), (1, "Manual")]
		)

	def test_unknown_weight_source_falls_back_to_manual(self):
		result = self.collect(
			[{"linen_type": self.sheet, "qty": 2, "weight_kg": 1, "weight_source": "Magic"}]
		)
		self.assertEqual(result["collection"]["lines"][0]["weight_source"], "Manual")

	@bru("BRU-LIN-002")
	def test_only_pieces_is_converted_to_weight(self):  # FR-M3-01.3
		result = self.collect([{"linen_type": self.sheet, "qty": 12}])
		row = result["collection"]["lines"][0]
		self.assertEqual((row["weight_kg"], row["weight_source"]), (6.0, "Converted"))

	@bru("BRU-LIN-002")
	def test_only_weight_is_converted_to_pieces(self):
		row = self.collect([{"linen_type": self.sheet, "weight_kg": 6.2}])["collection"]["lines"][0]
		self.assertEqual((row["qty"], row["weight_source"]), (12, "Converted"))

	@bru("BRU-LIN-002")
	def test_variance_over_fifteen_percent_needs_a_note(self):  # FR-M3-01.4
		result = self.collect([{"linen_type": self.sheet, "qty": 10, "weight_kg": 8}])
		self.assert_rejection(result, "LINEN_VARIANCE_NOTE_REQUIRED")
		self.assertEqual(frappe.db.count("Linen Collection", {"department": self.department}), 0)

	@bru("BRU-LIN-002")
	def test_variance_with_a_note_is_kept(self):
		result = self.collect(
			[{"linen_type": self.sheet, "qty": 10, "weight_kg": 8, "variance_note": "Vải ướt"}]
		)
		row = result["collection"]["lines"][0]
		self.assertEqual((row["weight_kg"], row["variance_note"]), (8, "Vải ướt"))

	def test_total_weight_of_the_cart_is_shared_by_standard_weight(self):  # UC-16 A1
		result = self.collect(
			[{"linen_type": self.sheet, "qty": 10}, {"linen_type": self.gown, "qty": 5}], total_kg=10
		)
		lines = result["collection"]["lines"]
		self.assertEqual([row["weight_kg"] for row in lines], [5, 5])
		self.assertEqual({row["weight_source"] for row in lines}, {"Converted"})
		self.assertEqual(result["collection"]["total_weight_kg"], 10)

	def test_total_weight_far_from_standard_needs_a_note(self):
		lines = [{"linen_type": self.sheet, "qty": 10}]
		self.assert_rejection(self.collect(lines, total_kg=20), "LINEN_VARIANCE_NOTE_REQUIRED")
		self.assertIs(self.collect(lines, total_kg=20, note="Xe ướt")["ok"], True)

	def test_total_weight_needs_pieces_on_every_line(self):
		result = self.collect([{"linen_type": self.sheet, "weight_kg": 5}], total_kg=10)
		self.assert_rejection(result, "LINEN_TOTAL_INVALID")

	def test_total_weight_must_be_positive(self):
		self.assert_rejection(
			self.collect([{"linen_type": self.sheet, "qty": 3}], total_kg=0), "LINEN_TOTAL_INVALID"
		)


class TestCollectRejections(LinenApiCase):
	@bru("BRU-LIN-001")
	def test_no_lines_is_rejected(self):
		for lines in (None, []):
			self.assert_rejection(self.collect(lines), "LINEN_EMPTY")

	@bru("BRU-LIN-001")
	def test_unknown_or_inactive_type_is_rejected(self):  # UC-16 E2
		self.assert_rejection(self.collect([{"linen_type": "Không có", "qty": 1}]), "LINEN_TYPE_INVALID")
		self.assert_rejection(self.collect([{"qty": 1}]), "LINEN_TYPE_INVALID")
		frappe.db.set_value("Linen Type", self.sheet, "is_active", 0)
		self.assert_rejection(self.collect([{"linen_type": self.sheet, "qty": 1}]), "LINEN_TYPE_INVALID")

	@bru("BRU-LIN-001")
	def test_bad_pieces_or_weight_are_rejected(self):
		for line in (
			{"linen_type": self.sheet},
			{"linen_type": self.sheet, "qty": 0, "weight_kg": 5},
			{"linen_type": self.sheet, "qty": -2},
			{"linen_type": self.sheet, "weight_kg": 0},
			{"linen_type": self.sheet, "qty": 2.5},
			{"linen_type": self.sheet, "qty": "abc"},
			{"linen_type": self.sheet, "qty": True},
			{"linen_type": self.sheet, "weight_kg": 0.1},
		):
			with self.subTest(line=line):
				self.assert_rejection(self.collect([line]), "LINEN_QTY_INVALID")

	@bru("BRU-LIN-001")
	def test_department_must_be_valid(self):
		for department in (None, "", "Không có khoa"):
			with self.subTest(department=department):
				result = self.collect([{"linen_type": self.sheet, "qty": 1}], department=department)
				self.assert_rejection(result, "DEPARTMENT_INVALID")

	@bru("BRU-LIN-001")
	def test_deliverer_name_is_required(self):
		for name in (None, "", "   "):
			result = self.collect([{"linen_type": self.sheet, "qty": 1}], delivered_by=name)
			self.assert_rejection(result, "DELIVERER_NAME_REQUIRED")

	def test_wrong_station_step_is_rejected(self):
		TOKENS[("Administrator", "TR-001")] = make_station_session("Administrator", station="TR-001")["token"]
		result = self.collect([{"linen_type": self.sheet, "qty": 1}], station="TR-001")
		self.assert_rejection(result, "STATION_WRONG_STEP")

	def test_malformed_parameters_are_400(self):
		with self.assertRaises(BadRequestError):
			self.collect("không phải json")
		with self.assertRaises(BadRequestError):
			self.collect([1, 2])
		with self.assertRaises(BadRequestError):
			self.collect([{"linen_type": self.sheet, "qty": 1}], note=5)
		with self.assertRaises(BadRequestError):
			self.collect([{"linen_type": self.sheet, "qty": 1}], department=["x"])

	def test_other_roles_cannot_collect(self):
		user = make_user("linen-r03@example.com", roles=("TC R03",))
		frappe.set_user(user)
		TOKENS[(user, LINEN_STATION)] = make_station_session(user, station=LINEN_STATION)["token"]
		with self.assertRaises(frappe.PermissionError):
			self.collect([{"linen_type": self.sheet, "qty": 1}])

	def test_session_is_required(self):
		TOKENS.clear()
		result = self.collect([{"linen_type": self.sheet, "qty": 1}])
		self.assert_rejection(result, "SESSION_INVALID", 401)
		self.assertEqual(frappe.db.count("Linen Collection", {"department": self.department}), 0)


class TestCatalog(LinenApiCase):
	def test_catalog_lists_active_types_with_the_department_quota(self):
		frappe.get_doc("Linen Type", self.sheet).update(
			{"quotas": [{"department": self.department, "min_qty": 5, "max_qty": 40}]}
		).save()
		frappe.db.set_value("Linen Type", self.gown, "is_active", 0)
		result = call(linen_api.catalog, department=self.department)
		self.assertIs(result["ok"], True, msg=result)
		by_name = {row["name"]: row for row in result["types"]}
		self.assertNotIn(self.gown, by_name)
		self.assertEqual((by_name[self.sheet]["min_qty"], by_name[self.sheet]["max_qty"]), (5, 40))
		self.assertEqual(by_name[self.sheet]["std_weight_kg"], 0.5)
		self.assertIn(self.department, {row["name"] for row in result["departments"]})

	def test_catalog_without_department_has_no_quota(self):
		by_name = {row["name"]: row for row in call(linen_api.catalog)["types"]}
		self.assertIsNone(by_name[self.sheet]["min_qty"])

	def test_catalog_at_a_wrong_station_is_rejected(self):
		TOKENS[("Administrator", "TR-001")] = make_station_session("Administrator", station="TR-001")["token"]
		self.assert_rejection(call(linen_api.catalog, station="TR-001"), "STATION_WRONG_STEP")
