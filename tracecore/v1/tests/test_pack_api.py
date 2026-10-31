"""RPC tracecore.v1.pack.* và printer.set_roll (FEAT-018 Task 9): định tuyến ô quét, sinh Cycle ID, in lại, hủy.

Kiểm mã HTTP theo loại lỗi (D3), Audit Log `Reject`, replay idempotent giữ mã HTTP và quyền của trạm T4.
"""

import inspect
import json
import re
import time
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe

from tracecore.core import gs1
from tracecore.reprocessing import packing
from tracecore.tests.factories import (
	deactivate_printers,
	make_assembly_record,
	make_ci_batch,
	make_label_items,
	make_pack_type,
	make_printer,
	make_roll,
	make_t4_ready_set,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import pack as pack_api
from tracecore.v1 import printer as printer_api
from tracecore.v1 import set_unit as set_unit_api
from tracecore.v1._common import BadRequestError
from tracecore.v1.tests.station_fixtures import make_station_session

# Pack, Set Unit, Printer liên kết Item, Batch, Department, User, Employee của ERPNext/HRMS; site CI mới chưa chạy
# Setup Wizard nên bỏ phụ thuộc này (dữ liệu tạo qua tracecore/tests/factories.py).
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-004"
CYCLE_ID = re.compile(r"^CY-\d{6}-\d{4}$")
TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
AUDIT_FIELDS = ["name", "reason", "ref_doctype", "ref_name", "station", "user", "new_value", "client_ts"]
SESSION_TOKENS = {}


def now_ts():
	return datetime.now(TIME_ZONE).isoformat(timespec="seconds")


def call(fn, key=None, station_header=STATION, **kwargs):
	"""Gọi RPC như kiosk (header khóa idempotent + trạm, `client_ts` hiện tại).

	Xóa mã HTTP của lần gọi trước để `http_status()` chỉ phản ánh lần gọi này.
	"""
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	if fn in (
		pack_api.scan,
		pack_api.resolve_ci,
		pack_api.generate_cycle_id,
		pack_api.reprint_label,
		pack_api.void,
		printer_api.set_roll,
	):
		kwargs.setdefault("token", SESSION_TOKENS.get(frappe.session.user))
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": station_header}):
		return fn(**kwargs)


def http_status():
	return frappe.local.response.get("http_status_code")


def generate_args(ready, **overrides):
	return {
		"set_id": ready.set_id,
		"station": STATION,
		"confirmed_lines": list(ready.instruments),
		"ci_batch": ready.ci_batch,
		"pack_type": ready.pack_type,
		"maint_actions": [],
		**overrides,
	}


def roll_code_of(printer):
	return frappe.db.get_value("Printer", printer, "roll_code")


def reject_count():
	return frappe.db.count("Audit Log", {"action": "Reject"})


def rejects_since(count_before):
	"""Audit Log Reject ghi sau khi có `count_before` dòng, mới nhất trước (cùng thời điểm: tên tự tăng phân định)."""
	added = reject_count() - count_before
	if added <= 0:
		return []
	return frappe.get_all(
		"Audit Log",
		filters={"action": "Reject"},
		fields=AUDIT_FIELDS,
		order_by="creation desc, name desc",
		limit=added,
	)


def totals():
	"""Số dòng Audit Log, Pack, Idempotency Key, Print Job: để chứng minh một lệnh bị chặn không ghi gì."""
	return tuple(
		frappe.db.count(doctype) for doctype in ("Audit Log", "Pack", "Idempotency Key", "Print Job")
	)


def assert_rejection(case, result, code, status):
	case.assertIs(result["ok"], False)
	case.assertEqual(result["error"]["code"], code)
	case.assertEqual(result["error"]["http_status"], status)
	case.assertEqual(http_status(), status)
	for key in ("title", "reason", "action"):
		case.assertTrue(result["error"][key], msg=key)


class PackApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.get_doc("User", "Administrator").add_roles("TC R10")
		SESSION_TOKENS.clear()
		SESSION_TOKENS["Administrator"] = make_station_session("Administrator")["token"]
		self.addCleanup(SESSION_TOKENS.clear)
		frappe.local.response.pop("http_status_code", None)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		deactivate_printers(STATION)

	def as_user(self, email, roles=()):
		user = make_user(email, roles=roles)
		SESSION_TOKENS[user] = make_station_session(user)["token"]
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")


class TestScan(PackApiCase):
	def test_main_scan_never_resolves_indicator_lots_even_with_open_set(self):
		ready = make_t4_ready_set()
		with patch.object(packing, "resolve_ci_batch", wraps=packing.resolve_ci_batch) as resolver:
			result = call(pack_api.scan, raw=ready.ci_batch, station=STATION, open_set=ready.set_id)
			assert_rejection(self, result, "SCAN_INVALID", 422)
			resolver.assert_not_called()

	def test_dedicated_ci_endpoint_uses_existing_method_and_expiry_rules(self):
		endpoint = getattr(pack_api, "resolve_ci", None)
		self.assertTrue(callable(endpoint), "Dedicated indicator-lot RPC is missing")
		ready = make_t4_ready_set()
		args = dict(
			raw=ready.ci_batch, station=STATION, open_set=ready.set_id, token=SESSION_TOKENS["Administrator"]
		)
		result = call(endpoint, **args)
		self.assertTrue(result["ok"])
		self.assertEqual(result["ci"]["batch"], ready.ci_batch)
		self.assertEqual(result["kind"], "ci")
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		result = call(endpoint, **{**args, "token": "invalid"})
		assert_rejection(self, result, "SESSION_INVALID", 401)

	def test_scan_set_returns_context(self):
		ready = make_t4_ready_set()
		before = reject_count()
		result = call(pack_api.scan, raw="]d2\x1d8004" + ready.set_id + "\r\n", station=STATION)
		self.assertIs(result["ok"], True)
		self.assertEqual(result["kind"], "context")
		context = result["context"]
		self.assertEqual(context["set"]["set_id"], ready.set_id)
		self.assertEqual([line["instrument"] for line in context["bom"]], ready.instruments)
		self.assertEqual(context["printer"]["name"], ready.printer)
		self.assertIn(ready.pack_type, [row["item"] for row in context["pack_types"]])
		self.assertIsNone(http_status())
		self.assertEqual(reject_count(), before)

	def test_dedicated_ci_schema_and_replay_still_require_live_session(self):
		ready = make_t4_ready_set()
		for raw, open_set in (({}, ready.set_id), (ready.ci_batch, [])):
			with self.subTest(raw=raw, open_set=open_set), self.assertRaises(BadRequestError):
				call(pack_api.resolve_ci, raw=raw, station=STATION, open_set=open_set)
		key, ts = str(uuid.uuid4()), now_ts()
		args = dict(raw=ready.ci_batch, station=STATION, open_set=ready.set_id, client_ts=ts)
		first = call(pack_api.resolve_ci, key=key, **args)
		self.assertEqual(call(pack_api.resolve_ci, key=key, **args), first)
		token = SESSION_TOKENS["Administrator"]
		from tracecore.core import station_auth

		station_auth.logout(token)
		assert_rejection(self, call(pack_api.resolve_ci, key=key, **args), "SESSION_INVALID", 401)

	@bru("BRU-FLOW-004")
	def test_scan_gate_rejection_writes_audit_and_409(self):
		ready = make_t4_ready_set()
		make_assembly_record(ready.set_id, "Fail")
		before = reject_count()
		result = call(pack_api.scan, raw=ready.set_id, station=STATION)
		assert_rejection(self, result, "GATE_PREV_NOT_PASSED", 409)
		self.assertEqual(result["error"]["redo_step"], "T3")
		self.assertEqual(frappe.local.response.http_status_code, 409)

		[row] = rejects_since(before)
		self.assertEqual(
			(row.reason, row.ref_doctype, row.ref_name, row.station, row.user),
			("GATE_PREV_NOT_PASSED", "Set Unit", ready.set_id, STATION, "Administrator"),
		)
		self.assertEqual(frappe.parse_json(row.new_value)["raw"], ready.set_id)
		self.assertIsNotNone(row.client_ts)

	@bru("BRU-FLOW-001")
	def test_t4_scan_rejected_at_inactive_station(self):
		ready = make_t4_ready_set()
		frappe.db.set_value("Zone Station", STATION, "is_active", 0)
		before = reject_count()
		result = call(pack_api.scan, raw=ready.set_id, station=STATION)
		assert_rejection(self, result, "STATION_INACTIVE", 409)
		self.assertIn(STATION, result["error"]["reason"])
		[row] = rejects_since(before)
		self.assertEqual((row.reason, row.station), ("STATION_INACTIVE", STATION))

	def test_http_status_by_error_code(self):
		steam = make_t4_ready_set()
		plasma = make_t4_ready_set("Plasma", with_printer=False)
		missing_set = gs1.make_giai(gs1.configured_company_prefix(), "ZZZ999999")
		cases = [
			("set not found", pack_api.scan, {"raw": missing_set, "station": STATION}, "SET_NOT_FOUND", 404),
			(
				"lot of another method",
				pack_api.resolve_ci,
				{"raw": steam.ci_batch, "station": STATION, "open_set": plasma.set_id},
				"CI_LOT_INVALID",
				422,
			),
			(
				"station is not T4",
				pack_api.scan,
				{"raw": steam.set_id, "station": "TR-003"},
				"SESSION_STATION_MISMATCH",
				403,
			),
			*[
				(
					f"station {station!r}",
					pack_api.scan,
					{"raw": steam.set_id, "station": station},
					"SESSION_STATION_MISMATCH",
					403,
				)
				for station in ("TR-999", "ZONE-CLEAN", None, {"functions": [{"station_function": "PACK"}]})
			],
			("garbage", pack_api.scan, {"raw": "XYZ-123", "station": STATION}, "SCAN_INVALID", 422),
			(
				"pack not found",
				pack_api.scan,
				{"raw": "CY-991231-9999", "station": STATION},
				"PACK_NOT_FOUND",
				404,
			),
			(
				"roll not issued",
				pack_api.scan,
				{"raw": "CN-99999", "station": STATION},
				"ROLL_NOT_FOUND",
				404,
			),
			(
				"reprint without reason",
				pack_api.reprint_label,
				{"cycle_id": "CY-991231-9999", "reason": "", "station": STATION},
				"REASON_REQUIRED",
				422,
			),
			(
				"reprint unknown pack",
				pack_api.reprint_label,
				{"cycle_id": "CY-991231-9999", "reason": "Nhãn mờ", "station": STATION},
				"PACK_NOT_FOUND",
				404,
			),
			(
				"void unknown pack",
				pack_api.void,
				{"cycle_id": "CY-991231-9999", "reason": "Torn", "station": STATION},
				"PACK_NOT_FOUND",
				404,
			),
		]
		for label, fn, args, code, status in cases:
			with self.subTest(label):
				assert_rejection(self, call(fn, **args), code, status)

		self.assertTrue(call(pack_api.generate_cycle_id, **generate_args(steam))["ok"])
		with self.subTest("second cycle id for the set"):
			assert_rejection(
				self, call(pack_api.generate_cycle_id, **generate_args(steam)), "ACTIVE_CYCLE_EXISTS", 409
			)

	def test_scan_routes_pack_roll_and_dedicated_ci(self):
		ready = make_t4_ready_set()
		cycle_id = call(pack_api.generate_cycle_id, **generate_args(ready))["pack"]["cycle_id"]
		payload = frappe.db.get_value("Pack", cycle_id, "barcode_payload")
		for raw in (cycle_id, "]d2" + payload):
			with self.subTest(raw=raw):
				result = call(pack_api.scan, raw=raw, station=STATION)
				self.assertIs(result["ok"], True)
				self.assertEqual(result["kind"], "pack")
				self.assertEqual(result["pack"]["cycle_id"], cycle_id)
				self.assertEqual(result["pack"]["status"], "Packed")
				self.assertEqual(result["pack"]["set_id"], ready.set_id)
				self.assertIsNone(http_status())

		steam_label, _plasma_label = make_label_items()
		result = call(pack_api.scan, raw=make_roll(steam_label), station=STATION)
		self.assertEqual(result["kind"], "roll")
		self.assertEqual(result["roll"]["printer"], ready.printer)
		self.assertEqual(result["roll"]["label_type"], steam_label)

		other = make_t4_ready_set(with_printer=False)
		result = call(
			pack_api.resolve_ci, raw=" " + other.ci_batch + "\r\n", station=STATION, open_set=other.set_id
		)
		self.assertIs(result["ok"], True)
		self.assertEqual(result["kind"], "ci")
		self.assertEqual(result["ci"]["batch"], other.ci_batch)
		self.assertEqual(result["ci"]["ci_class"], "5")
		self.assertRegex(result["ci"]["expiry_date"], r"^\d{4}-\d{2}-\d{2}$")

	def test_scan_roll_needs_exactly_one_active_printer(self):
		steam_label, _plasma_label = make_label_items()
		roll = make_roll(steam_label)
		before = reject_count()

		result = call(pack_api.scan, raw=roll, station=STATION)
		assert_rejection(self, result, "ROLL_PRINTER_AMBIGUOUS", 409)
		none_reason = result["error"]["reason"]

		make_printer(STATION, steam_label, name="Máy 1")
		make_printer(STATION, steam_label, name="Máy 2")
		result = call(pack_api.scan, raw=roll, station=STATION)
		assert_rejection(self, result, "ROLL_PRINTER_AMBIGUOUS", 409)
		many_reason = result["error"]["reason"]

		self.assertNotEqual(none_reason, many_reason)
		self.assertIn("2", many_reason)
		rows = rejects_since(before)
		self.assertEqual([row.reason for row in rows], ["ROLL_PRINTER_AMBIGUOUS"] * 2)
		self.assertEqual(frappe.parse_json(rows[0].new_value)["raw"], roll)

	def test_scan_without_open_set_rejects_unknown_code(self):
		before = reject_count()
		result = call(pack_api.scan, raw="LOT-NO-SET-OPEN", station=STATION)
		assert_rejection(self, result, "SCAN_INVALID", 422)
		self.assertIn("LOT-NO-SET-OPEN", result["error"]["reason"])
		[row] = rejects_since(before)
		self.assertEqual((row.reason, row.ref_doctype, row.ref_name), ("SCAN_INVALID", None, None))
		self.assertEqual(frappe.parse_json(row.new_value)["raw"], "LOT-NO-SET-OPEN")

	def test_scan_other_recognised_code_types_are_invalid_even_with_open_set(self):
		ready = make_t4_ready_set()
		for raw in ("NV-00001", "TB-0001", "TR-003", "KE-0001"):
			for open_set in (None, ready.set_id):
				with self.subTest(raw=raw, open_set=open_set):
					result = call(pack_api.scan, raw=raw, station=STATION, open_set=open_set)
					assert_rejection(self, result, "SCAN_INVALID", 422)
					self.assertIn(raw, result["error"]["reason"])

	def test_scan_lot_for_unknown_open_set(self):
		ready = make_t4_ready_set()
		for open_set in ("not-a-set", gs1.make_giai(gs1.configured_company_prefix(), "ZZZ999998")):
			with self.subTest(open_set=open_set):
				result = call(pack_api.resolve_ci, raw=ready.ci_batch, station=STATION, open_set=open_set)
				assert_rejection(self, result, "SET_NOT_FOUND", 404)

	def test_scan_expired_lot_is_422(self):
		ready = make_t4_ready_set()
		expired = make_ci_batch("Steam", expiry_days=-3)
		result = call(pack_api.resolve_ci, raw=expired, station=STATION, open_set=ready.set_id)
		assert_rejection(self, result, "CI_LOT_EXPIRED", 422)

	def test_scan_replay_same_key_returns_same_result(self):
		ready = make_t4_ready_set()
		key, ts = str(uuid.uuid4()), now_ts()
		first = call(pack_api.scan, key=key, raw=ready.set_id, station=STATION, client_ts=ts)
		second = call(pack_api.scan, key=key, raw=ready.set_id, station=STATION, client_ts=ts)
		self.assertEqual(second, first)

	def test_scan_requires_the_station_role(self):
		ready = make_t4_ready_set()
		self.as_user("pack-api-norole@example.com")
		before = totals()
		with self.assertRaises(frappe.PermissionError):
			call(pack_api.scan, raw=ready.set_id, station=STATION)
		frappe.set_user("Administrator")
		self.assertEqual(totals(), before)


class TestGenerate(PackApiCase):
	def test_generate_returns_pack_label_and_print(self):
		ready = make_t4_ready_set()
		result = call(pack_api.generate_cycle_id, **generate_args(ready))
		self.assertIs(result["ok"], True)
		self.assertRegex(result["pack"]["cycle_id"], CYCLE_ID)
		self.assertEqual(result["pack"]["set_id"], ready.set_id)
		self.assertTrue(result["hri"].startswith("(01)" + ready.gtin))
		self.assertTrue(result["datamatrix_png_b64"])
		self.assertEqual(result["print"]["status"], "Queued")
		self.assertEqual(result["print"]["printer"], ready.printer)
		self.assertIsNone(result["print"]["warning"])
		self.assertIsNone(http_status())
		unit = frappe.db.get_value("Set Unit", ready.set_id, ["status", "active_cycle_id"], as_dict=True)
		self.assertEqual(unit.active_cycle_id, result["pack"]["cycle_id"])

	def test_generate_replay_same_key_returns_same_cycle(self):
		"""AC-13: gửi lại cùng khóa (mạng chập chờn) không sinh Cycle ID thứ hai."""
		ready = make_t4_ready_set()
		key, ts = str(uuid.uuid4()), now_ts()
		args = generate_args(ready, client_ts=ts)
		first = call(pack_api.generate_cycle_id, key=key, **args)
		second = call(pack_api.generate_cycle_id, key=key, **args)
		self.assertEqual(second["pack"]["cycle_id"], first["pack"]["cycle_id"])
		self.assertEqual(second["print"]["print_job"], first["print"]["print_job"])
		self.assertEqual(frappe.db.count("Pack", {"set_unit": ready.set_id}), 1)
		self.assertEqual(frappe.db.count("Print Job", {"ref_name": first["pack"]["cycle_id"]}), 1)

	def test_rejection_replay_keeps_status(self):
		missing = gs1.make_giai(gs1.configured_company_prefix(), "ZZZ999997")
		key, ts = str(uuid.uuid4()), now_ts()
		before = reject_count()
		first = call(pack_api.scan, key=key, raw=missing, station=STATION, client_ts=ts)
		assert_rejection(self, first, "SET_NOT_FOUND", 404)
		second = call(pack_api.scan, key=key, raw=missing, station=STATION, client_ts=ts)
		self.assertEqual(second, first)
		self.assertEqual(http_status(), 404)
		self.assertEqual(len(rejects_since(before)), 1)  # replay không ghi Audit Log lần nữa
		self.assertTrue(frappe.db.exists("Idempotency Key", key))

	def test_generate_rejection_keeps_audit_and_key_and_rolls_back_the_pack(self):
		ready = make_t4_ready_set()
		key, ts = str(uuid.uuid4()), now_ts()
		before = reject_count()
		result = call(
			pack_api.generate_cycle_id,
			key=key,
			**generate_args(ready, confirmed_lines=ready.instruments[:1], client_ts=ts),
		)
		assert_rejection(self, result, "BOM_INCOMPLETE", 422)
		self.assertEqual([item["instrument"] for item in result["error"]["items"]], ready.instruments[1:])
		self.assertEqual(frappe.db.count("Pack", {"set_unit": ready.set_id}), 0)
		self.assertIsNone(frappe.db.get_value("Set Unit", ready.set_id, "active_cycle_id"))
		self.assertTrue(frappe.db.exists("Idempotency Key", key))
		[row] = rejects_since(before)
		self.assertEqual(
			(row.reason, row.ref_doctype, row.ref_name), ("BOM_INCOMPLETE", "Set Unit", ready.set_id)
		)
		self.assertEqual(frappe.parse_json(row.new_value)["items"][0]["instrument"], ready.instruments[1])

		# nhập đủ rồi quét lại: bộ vẫn sinh được
		retry = call(pack_api.generate_cycle_id, **generate_args(ready))
		self.assertIs(retry["ok"], True)

	def test_print_warning_is_not_an_http_error(self):
		ready = make_t4_ready_set(with_printer=False)
		before = reject_count()
		result = call(pack_api.generate_cycle_id, **generate_args(ready))
		self.assertIs(result["ok"], True)
		self.assertEqual(result["print"]["status"], "Waiting")
		self.assertEqual(result["print"]["warning"]["code"], "NO_PRINTER_FOR_METHOD")
		self.assertIsNone(http_status())
		self.assertEqual(reject_count(), before)
		self.assertTrue(frappe.db.exists("Pack", result["pack"]["cycle_id"]))

	def test_generate_requires_create_permission(self):
		ready = make_t4_ready_set()
		self.as_user("pack-api-nobody@example.com")
		before = totals()
		with self.assertRaises(frappe.PermissionError):
			call(pack_api.generate_cycle_id, **generate_args(ready))
		frappe.set_user("Administrator")
		self.assertEqual(totals(), before)

		# role chỉ đọc Pack (TC R01) cũng không sinh được
		self.as_user("pack-api-reader@example.com", roles=["TC R01"])
		before = totals()
		with self.assertRaises(frappe.PermissionError):
			call(pack_api.generate_cycle_id, **generate_args(ready))
		frappe.set_user("Administrator")
		self.assertEqual(totals(), before)

	def test_generate_as_station_user(self):
		ready = make_t4_ready_set()
		self.as_user("pack-api-r04@example.com", roles=["TC R04"])
		result = call(pack_api.generate_cycle_id, **generate_args(ready))
		self.assertIs(result["ok"], True)
		self.assertEqual(
			frappe.db.get_value("Pack", result["pack"]["cycle_id"], "packed_by_user"),
			"pack-api-r04@example.com",
		)

	def test_generate_accepts_lists_and_json_strings(self):
		first = make_t4_ready_set(with_printer=False)
		action = {"instrument": first.instruments[0], "action": "Done", "oil_batch": None, "reason": None}
		result = call(
			pack_api.generate_cycle_id,
			**generate_args(
				first,
				confirmed_lines=json.dumps(first.instruments),
				maint_actions=json.dumps([{**action, "ignored": 1}]),
			),
		)
		self.assertIs(result["ok"], True)

		second = make_t4_ready_set(with_printer=False)
		result = call(
			pack_api.generate_cycle_id,
			**generate_args(second, maint_actions=[{**action, "instrument": second.instruments[0]}]),
		)
		self.assertIs(result["ok"], True)

		third = make_t4_ready_set(with_printer=False)
		result = call(pack_api.generate_cycle_id, **generate_args(third, maint_actions=None))
		self.assertIs(result["ok"], True)

	def test_generate_malformed_arguments_are_400(self):
		ready = make_t4_ready_set()
		good_action = {"instrument": ready.instruments[0], "action": "Done"}
		cases = {
			"confirmed_lines not json": {"confirmed_lines": "[KC-01"},
			"confirmed_lines not a list": {"confirmed_lines": {"KC-01": True}},
			"confirmed_lines numbers": {"confirmed_lines": [1, 2]},
			"confirmed_lines missing": {"confirmed_lines": None},
			"maint_actions not json": {"maint_actions": "{oops"},
			"maint_actions not a list": {"maint_actions": "done"},
			"maint_actions item not an object": {"maint_actions": ["KC-01"]},
			"maint_actions without instrument": {"maint_actions": [{"action": "Done"}]},
			"maint_actions bad action": {"maint_actions": [{**good_action, "action": "Skipped"}]},
			"maint_actions bad oil lot": {"maint_actions": [{**good_action, "oil_batch": ["x"]}]},
		}
		for label, overrides in cases.items():
			with self.subTest(label):
				before = totals()
				with self.assertRaises(BadRequestError) as raised:
					call(pack_api.generate_cycle_id, **generate_args(ready, **overrides))
				self.assertEqual(raised.exception.http_status_code, 400)
				self.assertEqual(totals(), before)

	def test_generate_malformed_client_ts_is_400_and_missing_key_is_400(self):
		from tracecore.core.client_time import ClientTimestampError
		from tracecore.core.idempotency import IdempotencyKeyError

		ready = make_t4_ready_set()
		with self.assertRaises(ClientTimestampError):
			call(pack_api.generate_cycle_id, **generate_args(ready, client_ts="2026-10-20T09:00:00"))
		with request_headers({}), self.assertRaises(IdempotencyKeyError):
			pack_api.generate_cycle_id(
				**generate_args(ready, client_ts=now_ts(), token=SESSION_TOKENS["Administrator"])
			)
		self.assertEqual(frappe.db.count("Pack", {"set_unit": ready.set_id}), 0)

	def test_generate_with_station_clock_skew_is_400_and_writes_nothing(self):
		# F1: giờ trạm lệch giờ server > 5 phút → 400 (ClientTimestampError), không Pack/Audit Log/Idempotency Key
		from tracecore.core.client_time import ClientTimestampError

		ready = make_t4_ready_set()
		before = totals()
		skewed = (datetime.now(TIME_ZONE) + timedelta(minutes=6)).isoformat(timespec="seconds")
		with self.assertRaises(ClientTimestampError) as raised:
			call(pack_api.generate_cycle_id, **generate_args(ready, client_ts=skewed))
		self.assertEqual(raised.exception.http_status_code, 400)
		self.assertEqual(totals(), before)

	def test_wrong_station_rejects_before_writing(self):
		ready = make_t4_ready_set()
		token = make_station_session("Administrator", "TR-003")["token"]
		result = call(pack_api.generate_cycle_id, **generate_args(ready, station="TR-003", token=token))
		assert_rejection(self, result, "STATION_WRONG_STEP", 422)
		self.assertEqual(frappe.db.count("Pack", {"set_unit": ready.set_id}), 0)

	def test_no_request_context_leaves_http_status_unset(self):
		"""Gọi từ bench execute/test (không có request) vẫn ra body lỗi, không đặt mã HTTP."""
		frappe.local.response.pop("http_status_code", None)
		missing = gs1.make_giai(gs1.configured_company_prefix(), "ZZZ999996")
		result = inspect.unwrap(pack_api.scan)(raw=missing, station=STATION, client_ts=now_ts())
		self.assertEqual(result["error"]["code"], "SET_NOT_FOUND")
		self.assertIsNone(http_status())


class TestReprintAndVoid(PackApiCase):
	def packed(self, **kwargs):
		ready = make_t4_ready_set(**kwargs)
		return ready, call(pack_api.generate_cycle_id, **generate_args(ready))["pack"]["cycle_id"]

	@bru("BRU-ID-005")
	def test_reprint_then_void_then_reprint_is_rejected(self):
		ready, cycle_id = self.packed()
		result = call(pack_api.reprint_label, cycle_id=cycle_id, reason="Nhãn bị nhòe", station=STATION)
		self.assertIs(result["ok"], True)
		self.assertEqual(result["pack"]["cycle_id"], cycle_id)
		self.assertEqual(result["print"]["status"], "Queued")
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "label_print_count"), 2)
		self.assertIsNone(http_status())

		voided = call(pack_api.void, cycle_id=cycle_id, reason="Label Damaged", station=STATION, note="Rách")
		self.assertEqual(
			voided,
			{
				"ok": True,
				"cycle_id": cycle_id,
				"set_id": ready.set_id,
				"status": "Void",
				"void_reason": "Label Damaged",
			},
		)
		self.assertEqual(frappe.db.get_value("Set Unit", ready.set_id, "status"), "Reprocess")

		before = reject_count()
		again = call(pack_api.reprint_label, cycle_id=cycle_id, reason="Nhãn bị nhòe", station=STATION)
		assert_rejection(self, again, "STATUS_INVALID_FOR_STATION", 409)
		again = call(pack_api.void, cycle_id=cycle_id, reason="Torn", station=STATION)
		assert_rejection(self, again, "PACK_NOT_VOIDABLE", 409)
		rows = rejects_since(before)
		# so như tập hợp: hai lần từ chối có thể cùng thời điểm, thứ tự không phải điều cần kiểm
		self.assertEqual(
			sorted((row.reason, row.ref_doctype, row.ref_name) for row in rows),
			[
				("PACK_NOT_VOIDABLE", "Pack", cycle_id),
				("STATUS_INVALID_FOR_STATION", "Pack", cycle_id),
			],
		)

	def test_reprint_while_label_waiting_keeps_one_job(self):
		# F3: cảnh báo LABEL_ALREADY_WAITING (200, ok), không tạo Print Job mới, không tăng số lần in
		_ready, cycle_id = self.packed(method="Plasma", with_printer=False)
		jobs = frappe.get_all(
			"Print Job", filters={"ref_doctype": "Pack", "ref_name": cycle_id}, pluck="name"
		)
		result = call(pack_api.reprint_label, cycle_id=cycle_id, reason="Kẹt giấy", station=STATION)
		self.assertIs(result["ok"], True)
		self.assertIsNone(http_status())
		self.assertEqual(result["print"]["print_job"], str(jobs[0]))
		self.assertEqual(result["print"]["warning"]["code"], "LABEL_ALREADY_WAITING")
		self.assertEqual(
			frappe.get_all("Print Job", filters={"ref_doctype": "Pack", "ref_name": cycle_id}, pluck="name"),
			jobs,
		)
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "label_print_count"), 1)

	def test_reprint_window_expired_is_409(self):
		_ready, cycle_id = self.packed()
		created = frappe.utils.get_datetime(frappe.db.get_value("Pack", cycle_id, "creation"))
		with patch.object(packing, "now_datetime", return_value=created + timedelta(seconds=601)):
			result = call(pack_api.reprint_label, cycle_id=cycle_id, reason="Nhãn bị nhòe", station=STATION)
		assert_rejection(self, result, "REPRINT_WINDOW_EXPIRED", 409)
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "label_print_count"), 1)

	def test_void_reason_must_be_a_listed_option(self):
		_ready, cycle_id = self.packed()
		result = call(pack_api.void, cycle_id=cycle_id, reason="Dropped", station=STATION)
		assert_rejection(self, result, "REASON_REQUIRED", 422)
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "status"), "Packed")

	def test_reprint_and_void_replay_same_key(self):
		_ready, cycle_id = self.packed()
		key, ts = str(uuid.uuid4()), now_ts()
		args = {"cycle_id": cycle_id, "reason": "Nhãn bị nhòe", "station": STATION, "client_ts": ts}
		first = call(pack_api.reprint_label, key=key, **args)
		second = call(pack_api.reprint_label, key=key, **args)
		self.assertEqual(second, first)
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "label_print_count"), 2)

	def test_reprint_and_void_require_the_station_role(self):
		_ready, cycle_id = self.packed()
		self.as_user("pack-api-norole2@example.com")
		before = totals()
		for fn, args in (
			(pack_api.reprint_label, {"cycle_id": cycle_id, "reason": "x"}),
			(pack_api.void, {"cycle_id": cycle_id, "reason": "Torn"}),
		):
			with self.subTest(fn.__name__), self.assertRaises(frappe.PermissionError):
				call(fn, station=STATION, **args)
		frappe.set_user("Administrator")
		self.assertEqual(totals(), before)
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "status"), "Packed")


class TestSetRoll(PackApiCase):
	@bru("BRU-REP-011")
	def test_set_roll_releases_the_waiting_label(self):
		"""AC-9: sinh Cycle ID khi máy in đang lắp nhãn sai, đổi cuộn thì nhãn chờ được in."""
		ready = make_t4_ready_set("Plasma", with_printer=False)
		steam_label, plasma_label = make_label_items()
		printer = make_printer(STATION, steam_label)
		generated = call(pack_api.generate_cycle_id, **generate_args(ready))
		self.assertEqual(generated["print"]["warning"]["code"], "NO_PRINTER_FOR_METHOD")

		result = call(printer_api.set_roll, roll_code=make_roll(plasma_label), station=STATION)
		self.assertIs(result["ok"], True)
		roll = result["roll"]
		self.assertEqual(
			(roll["printer"], roll["label_type"], roll["method"]), (printer, plasma_label, "Plasma")
		)
		[released] = roll["released_jobs"]
		self.assertEqual(released["print_job"], generated["print"]["print_job"])
		self.assertEqual(roll["jobs_waiting"], 0)
		self.assertEqual(released["printer"], printer)
		self.assertTrue(released["zpl"].startswith("^XA"))
		self.assertIsNone(http_status())

	def test_set_roll_with_explicit_printer(self):
		steam_label, plasma_label = make_label_items()
		first = make_printer(STATION, steam_label, name="Máy A")
		second = make_printer(STATION, steam_label, name="Máy B")
		roll = make_roll(plasma_label)
		result = call(printer_api.set_roll, roll_code=roll, station=STATION, printer=second)
		self.assertEqual(result["roll"]["printer"], second)
		self.assertEqual(frappe.db.get_value("Printer", second, "label_type_loaded"), plasma_label)
		self.assertEqual(frappe.db.get_value("Printer", first, "label_type_loaded"), steam_label)

	def test_set_roll_rejects_printer_of_another_station(self):
		steam_label, plasma_label = make_label_items()
		elsewhere = make_printer("TR-005", steam_label, name="Máy trạm khác")
		before = reject_count()
		result = call(
			printer_api.set_roll, roll_code=make_roll(plasma_label), station=STATION, printer=elsewhere
		)
		assert_rejection(self, result, "ROLL_PRINTER_AMBIGUOUS", 409)
		self.assertIn(elsewhere, result["error"]["reason"])
		self.assertEqual(frappe.db.get_value("Printer", elsewhere, "label_type_loaded"), steam_label)
		self.assertEqual(len(rejects_since(before)), 1)

	def test_set_roll_rejections(self):
		steam_label, _plasma_label = make_label_items()
		make_printer(STATION, steam_label)
		cases = (
			("not issued", {"roll_code": "CN-99999"}, "ROLL_NOT_FOUND", 404),
			("not a label", {"roll_code": make_roll(make_pack_type())}, "ROLL_NOT_LABEL", 422),
		)
		for label, args, code, status in cases:
			with self.subTest(label):
				assert_rejection(self, call(printer_api.set_roll, station=STATION, **args), code, status)
		with self.subTest("station is not T4"):
			token = make_station_session("Administrator", "TR-003")["token"]
			result = call(printer_api.set_roll, roll_code="CN-99999", station="TR-003", token=token)
			assert_rejection(self, result, "STATION_WRONG_STEP", 422)

	def test_set_roll_printer_must_be_a_name(self):
		steam_label, _plasma_label = make_label_items()
		make_printer(STATION, steam_label)
		with self.assertRaises(BadRequestError) as raised:
			call(printer_api.set_roll, roll_code=make_roll(steam_label), station=STATION, printer=["PRN-1"])
		self.assertEqual(raised.exception.http_status_code, 400)

	def test_set_roll_requires_the_station_role(self):
		steam_label, _plasma_label = make_label_items()
		make_printer(STATION, steam_label)
		roll = make_roll(steam_label)
		self.as_user("pack-api-norole3@example.com")
		before = totals()
		with self.assertRaises(frappe.PermissionError):
			call(printer_api.set_roll, roll_code=roll, station=STATION)
		frappe.set_user("Administrator")
		self.assertEqual(totals(), before)


class TestSetRollFromDesk(PackApiCase):
	"""Ruling P1/F2: có `printer` là đường Desk (R10, System Manager; không cần trạm T4, không phát hành nhãn chờ);
	không có là đường kiosk."""

	DESK_STATION = "TR-003"  # trạm bước T3, không phải T4

	def desk_printer(self):
		steam_label, plasma_label = make_label_items()
		return make_printer(self.DESK_STATION, steam_label), plasma_label

	@bru("BRU-REP-011")
	def test_r10_desk_path_works_at_a_non_t4_station(self):
		printer, plasma_label = self.desk_printer()
		self.as_user("pack-api-r10@example.com", roles=("TC R10",))
		result = call(
			printer_api.set_roll,
			roll_code=make_roll(plasma_label),
			station=self.DESK_STATION,
			printer=printer,
			station_header=self.DESK_STATION,
		)
		self.assertIs(result["ok"], True)
		self.assertEqual(result["roll"]["printer"], printer)
		self.assertEqual(frappe.db.get_value("Printer", printer, "label_type_loaded"), plasma_label)
		self.assertIsNone(http_status())

	def test_desk_path_records_roll_but_leaves_waiting_labels(self):
		"""Ruling F2: Desk không gửi được job tới Station Agent nên không phát hành; nhãn chờ in khi quét cuộn ở T4."""
		ready = make_t4_ready_set("Plasma", with_printer=False)
		steam_label, plasma_label = make_label_items()
		printer = make_printer(STATION, steam_label)
		generated = call(pack_api.generate_cycle_id, **generate_args(ready))
		job = generated["print"]["print_job"]
		self.as_user("pack-api-r10c@example.com", roles=("TC R10",))
		result = call(
			printer_api.set_roll, roll_code=make_roll(plasma_label), station=STATION, printer=printer
		)
		roll = result["roll"]
		self.assertEqual((roll["printer"], roll["label_type"]), (printer, plasma_label))
		self.assertEqual((roll["released_jobs"], roll["jobs_waiting"]), ([], 1))
		self.assertEqual(frappe.db.get_value("Print Job", job, "status"), "Waiting")
		# quét cùng cuộn ở màn T4 (đường kiosk) thì nhãn chờ được phát hành
		frappe.set_user("Administrator")
		kiosk = call(printer_api.set_roll, roll_code=roll_code_of(printer), station=STATION)
		self.assertEqual([row["print_job"] for row in kiosk["roll"]["released_jobs"]], [job])

	def test_r04_cannot_use_the_desk_path(self):
		"""Ruling F2: đường Desk (có `printer`) chỉ cho TC R10 và System Manager; R04 dùng đường kiosk."""
		printer, plasma_label = self.desk_printer()
		roll = make_roll(plasma_label)
		self.as_user("pack-api-r04d@example.com", roles=("TC R04",))
		with self.assertRaises(frappe.PermissionError):
			call(
				printer_api.set_roll,
				roll_code=roll,
				station=self.DESK_STATION,
				printer=printer,
				station_header=self.DESK_STATION,
			)
		frappe.set_user("Administrator")
		self.assertNotEqual(frappe.db.get_value("Printer", printer, "label_type_loaded"), plasma_label)

	def test_r10_without_printer_is_rejected_by_role(self):
		printer, plasma_label = self.desk_printer()
		roll = make_roll(plasma_label)
		self.as_user("pack-api-r10b@example.com", roles=("TC R10",))
		before = totals()
		with self.assertRaises(frappe.PermissionError):
			call(printer_api.set_roll, roll_code=roll, station="TR-004")
		frappe.set_user("Administrator")
		self.assertEqual(totals(), before)
		self.assertNotEqual(frappe.db.get_value("Printer", printer, "label_type_loaded"), plasma_label)

	def test_desk_path_rejects_user_without_desk_role(self):
		printer, plasma_label = self.desk_printer()
		self.as_user("pack-api-norole4@example.com")
		with self.assertRaises(frappe.PermissionError):
			call(
				printer_api.set_roll,
				roll_code=make_roll(plasma_label),
				station=self.DESK_STATION,
				printer=printer,
			)

	def test_desk_path_rejects_printer_of_another_station(self):
		steam_label, plasma_label = make_label_items()
		elsewhere = make_printer("TR-005", steam_label, name="Máy trạm khác")
		before = reject_count()
		result = call(
			printer_api.set_roll,
			roll_code=make_roll(plasma_label),
			station=self.DESK_STATION,
			printer=elsewhere,
		)
		assert_rejection(self, result, "ROLL_PRINTER_AMBIGUOUS", 409)
		self.assertEqual(frappe.db.get_value("Printer", elsewhere, "label_type_loaded"), steam_label)
		self.assertEqual(len(rejects_since(before)), 1)

	def test_desk_path_rejects_unknown_printer(self):
		_printer, plasma_label = self.desk_printer()
		result = call(
			printer_api.set_roll,
			roll_code=make_roll(plasma_label),
			station=self.DESK_STATION,
			printer="PRN-999999",
		)
		assert_rejection(self, result, "ROLL_PRINTER_AMBIGUOUS", 409)

	def test_desk_path_rejects_inactive_station(self):
		printer, plasma_label = self.desk_printer()
		frappe.db.set_value("Zone Station", self.DESK_STATION, "is_active", 0)
		before = reject_count()
		result = call(
			printer_api.set_roll,
			roll_code=make_roll(plasma_label),
			station=self.DESK_STATION,
			printer=printer,
		)
		assert_rejection(self, result, "STATION_INACTIVE", 409)
		self.assertNotEqual(frappe.db.get_value("Printer", printer, "label_type_loaded"), plasma_label)
		self.assertEqual(len(rejects_since(before)), 1)

	def test_kiosk_path_still_needs_t4_for_system_manager(self):
		"""Không truyền `printer` thì giữ luật FEAT-018: trạm phải là T4, kể cả khi người gọi là Administrator."""
		_printer, plasma_label = self.desk_printer()
		token = make_station_session("Administrator", self.DESK_STATION)["token"]
		result = call(
			printer_api.set_roll, roll_code=make_roll(plasma_label), station=self.DESK_STATION, token=token
		)
		assert_rejection(self, result, "STATION_WRONG_STEP", 422)


class TestContractUnchanged(PackApiCase):
	def test_set_unit_get_contract_unchanged(self):
		"""FEAT-001 vẫn trả 200 + ok:false (D3: chưa amendment thì không đổi contract)."""
		result = call(set_unit_api.get, set_id="XYZ-123")
		self.assertIs(result["ok"], False)
		self.assertEqual(result["error"]["code"], "SCAN_INVALID")
		self.assertNotIn("http_status", result["error"])
		self.assertNotIn("http_status_code", frappe.local.response)


class TestGeneratePerformance(PackApiCase):
	SETS = 50
	CALLS = 20

	def test_generate_p95_under_1s_with_50_sets(self):
		"""AC-15: sinh Cycle ID ≤ 1 s ở P95 với 50 bộ đã seed (BOM 10 dòng mỗi bộ)."""
		bom = tuple((f"KC-{n:02d}", 1 + n % 3) for n in range(1, 11))
		sets = [make_t4_ready_set(bom=bom, with_printer=index == 0) for index in range(self.SETS)]
		durations = []
		for ready in sets[: self.CALLS]:
			args = generate_args(ready)
			started = time.perf_counter()
			result = call(pack_api.generate_cycle_id, **args)
			durations.append(time.perf_counter() - started)
			self.assertIs(result["ok"], True)
		p95 = sorted(durations)[18]  # 20 lần đo: phần tử thứ 19 là P95
		print(f"\nAC-15 generate_cycle_id: P95 = {p95 * 1000:.0f} ms, max = {max(durations) * 1000:.0f} ms")
		self.assertLess(p95, 1.0)
