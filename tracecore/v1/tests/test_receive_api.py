"""RPC tracecore.v1.receive.* (FEAT-019 Task 7): phiên trạm thẻ, quyền, mã HTTP theo loại lỗi, replay idempotent."""

import base64
import io
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe
from PIL import Image

from tracecore.core import gs1, step_gate
from tracecore.tests.factories import (
	make_department,
	make_employee,
	make_set_type,
	make_set_unit,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import receive as receive_api
from tracecore.v1._common import BadRequestError
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-001"
TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
TOKENS = {}


def now_ts():
	return datetime.now(TIME_ZONE).isoformat(timespec="seconds")


def call(fn, key=None, station_header=STATION, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	kwargs.setdefault("station", STATION)
	kwargs.setdefault("token", TOKENS.get((frappe.session.user, kwargs["station"])))
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": station_header}):
		return fn(**kwargs)


def http_status():
	return frappe.local.response.get("http_status_code")


def png_b64():
	buffer = io.BytesIO()
	Image.new("RGB", (6, 6), (10, 10, 10)).save(buffer, format="PNG")
	return base64.b64encode(buffer.getvalue()).decode()


class ReceiveApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		TOKENS.clear()
		self.addCleanup(TOKENS.clear)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		TOKENS[("Administrator", STATION)] = make_station_session("Administrator", station=STATION)["token"]
		self.department = make_department("Test API ward")
		self.card = "DLV-" + uuid.uuid4().hex[:10].upper()
		self.deliverer = make_employee(card=self.card, department=self.department, first_name="API deliverer")
		self.set_type = make_set_type("RCVA", bom=[("RA-KC-01", 2), ("RA-KC-02", 1)]).name

	def new_set(self, status="At Department"):
		unit = make_set_unit(self.set_type).name
		frappe.db.set_value("Set Unit", unit, "status", status, update_modified=False)
		return unit

	def opened(self):
		return call(receive_api.open, raw=self.card)["receipt"]

	def assert_rejection(self, result, code, status):
		self.assertIs(result["ok"], False, msg=result)
		self.assertEqual(result["error"]["code"], code)
		self.assertEqual(http_status(), status)
		for key in ("title", "reason", "action"):
			self.assertTrue(result["error"][key], msg=key)


class TestReceiveFlowApi(ReceiveApiCase):
	@bru("BRU-REP-012")
	def test_full_flow_open_scan_confirm_submit(self):
		opened = call(receive_api.open, raw=self.card)
		self.assertTrue(opened["ok"])
		self.assertEqual((opened["department"], opened["items"]), (self.department, []))
		receipt = opened["receipt"]
		units = [self.new_set(), self.new_set("New")]
		for unit in units:
			scanned = call(receive_api.scan_set, receipt=receipt, raw=unit)
			self.assertEqual((scanned["ok"], scanned["duplicate"]), (True, False))
			self.assertEqual(len(scanned["item"]["lines"]), 2)
			confirmed = call(
				receive_api.confirm_line, receipt=receipt, set_id=unit, confirm_all=1, finalize=1, note=None
			)
			self.assertEqual(confirmed["item"]["confirmed"], 1)
		self.assertEqual(scanned["summary"]["set_count"], 2)
		done = call(receive_api.submit, receipt=receipt)
		self.assertEqual((done["ok"], sorted(done["sets"]), done["rejected"]), (True, sorted(units), []))
		for unit in units:
			self.assertEqual(frappe.db.get_value("Set Unit", unit, "status"), "Processing")
			self.assertIsNone(step_gate.check(unit, "T2"))

	def test_open_without_arguments_resumes_or_lists_departments(self):
		empty = call(receive_api.open)
		self.assertTrue(empty["ok"] and empty["receipt"] is None)
		self.assertIn(self.department, {row["name"] for row in empty["departments"]})
		receipt = self.opened()
		self.assertEqual(call(receive_api.open)["receipt"], receipt)

	def test_manual_deliverer_without_card(self):
		result = call(receive_api.open, department=self.department, deliverer_name="Tran B")
		self.assertTrue(result["needs_card"])

	def test_discard_then_open_lists_departments(self):
		receipt = self.opened()
		result = call(receive_api.discard, receipt=receipt)
		self.assertTrue(result["ok"] and result["receipt"] is None)

	def test_photo_attaches_to_the_set(self):
		receipt = self.opened()
		unit = self.new_set()
		call(receive_api.scan_set, receipt=receipt, raw=unit)
		result = call(
			receive_api.attach_photo, receipt=receipt, set_id=unit, file_name="a.png", content=png_b64()
		)
		self.assertTrue(result["item"]["photo"].startswith("/private/files/"))
		bad = call(receive_api.attach_photo, receipt=receipt, set_id=unit, file_name="a.png", content="AAAA")
		self.assert_rejection(bad, "PHOTO_INVALID", 422)


class TestReceiveAsStationUser(ReceiveApiCase):
	"""Kiosk chạy bằng user trạm TC R03 thật (không phải Administrator): mọi bước ghi qua quyền của dịch vụ."""

	@bru("BRU-FLOW-004")
	def test_r03_station_user_completes_a_receipt_end_to_end(self):
		user = make_user("t1-api-r03@test.local", roles=("TC R03",))
		TOKENS[(user, STATION)] = make_station_session(user, station=STATION)["token"]
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		receipt = call(receive_api.open, raw=self.card)["receipt"]
		units = [self.new_set(), self.new_set("Awaiting Receipt")]
		for index, unit in enumerate(units):
			call(receive_api.scan_set, receipt=receipt, raw=unit)
			if index == 0:  # ảnh gắn trước khi Xác nhận bộ (gắn sau thì phải xác nhận lại)
				call(
					receive_api.attach_photo,
					receipt=receipt,
					set_id=unit,
					file_name="a.png",
					content=png_b64(),
				)
			call(receive_api.confirm_line, receipt=receipt, set_id=unit, confirm_all=1, finalize=1)
		done = call(receive_api.submit, receipt=receipt)
		self.assertTrue(done["ok"], done)
		self.assertEqual(sorted(done["sets"]), sorted(units))
		self.assertEqual(frappe.db.get_value("Dirty Receipt", receipt, "docstatus"), 1)
		for unit in units:
			self.assertEqual(frappe.db.get_value("Set Unit", unit, "status"), "Processing")


class TestReceiveRejections(ReceiveApiCase):
	@bru("BRU-ID-006")
	def test_unknown_code_is_rejected_with_audit_log(self):
		before = frappe.db.count("Audit Log", {"action": "Reject"})
		result = call(receive_api.open, raw="NOT-A-CARD")
		self.assert_rejection(result, "SCAN_INVALID", 422)
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Reject"}), before + 1)
		receipt = self.opened()
		result = call(receive_api.scan_set, receipt=receipt, raw="NOT-A-SET")
		self.assert_rejection(result, "SCAN_INVALID", 422)

	@bru("BRU-FLOW-002")
	def test_wrong_status_returns_409_with_reason_and_audit_reject(self):
		receipt = self.opened()
		unit = self.new_set("Sterile")
		before = frappe.db.count("Audit Log", {"action": "Reject", "ref_name": unit})
		result = call(receive_api.scan_set, receipt=receipt, raw=unit)
		self.assert_rejection(result, "STATUS_INVALID_FOR_STATION", 409)
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Reject", "ref_name": unit}), before + 1)

	def test_error_codes_map_to_http_statuses(self):
		self.assert_rejection(call(receive_api.open, raw="NV-99999"), "DELIVERER_NOT_FOUND", 404)
		self.assert_rejection(
			call(receive_api.confirm_line, receipt="RC-0000-00000", set_id="x"), "RECEIPT_NOT_FOUND", 404
		)
		receipt = self.opened()
		self.assert_rejection(call(receive_api.submit, receipt=receipt), "RECEIPT_EMPTY", 422)

	def test_wrong_step_station_is_rejected(self):
		TOKENS[("Administrator", "TR-002")] = make_station_session("Administrator", station="TR-002")["token"]
		result = call(receive_api.open, raw=self.card, station="TR-002", station_header="TR-002")
		self.assert_rejection(result, "STATION_WRONG_STEP", 422)
		self.assertFalse(frappe.db.exists("Dirty Receipt", {"station": "TR-002"}))

	def test_session_of_other_station_is_rejected(self):
		result = call(
			receive_api.open, raw=self.card, station="TR-002", token=TOKENS[("Administrator", STATION)]
		)
		self.assert_rejection(result, "SESSION_STATION_MISMATCH", 403)

	def test_bad_parameters_are_400(self):
		receipt = self.opened()
		for fn, kwargs in (
			(receive_api.open, {"raw": ["x"]}),
			(receive_api.scan_set, {"receipt": receipt, "raw": 7}),
			(receive_api.confirm_line, {"receipt": receipt, "set_id": "x", "lines": "not json"}),
			(receive_api.confirm_line, {"receipt": receipt, "set_id": "x", "lines": [{"confirmed": 1}]}),
			(receive_api.submit, {"receipt": None}),
		):
			with self.assertRaises(BadRequestError, msg=kwargs):
				call(fn, **kwargs)

	def test_user_without_receive_role_is_forbidden_and_leaves_no_trace(self):
		user = make_user("t1-api-r06@test.local", roles=("TC R06",))
		TOKENS[(user, STATION)] = make_station_session(user, station=STATION)["token"]
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		counts = tuple(frappe.db.count(d) for d in ("Audit Log", "Idempotency Key", "Dirty Receipt"))
		with self.assertRaises(frappe.PermissionError):
			call(receive_api.open, raw=self.card)
		self.assertEqual(
			tuple(frappe.db.count(d) for d in ("Audit Log", "Idempotency Key", "Dirty Receipt")), counts
		)


class TestReceiveIdempotency(ReceiveApiCase):
	@bru("BRU-REP-012")
	def test_replay_with_the_same_key_does_not_write_twice(self):
		key, ts = "11111111-1111-4111-8111-111111111111", now_ts()
		first = call(receive_api.open, key=key, raw=self.card, client_ts=ts)
		again = call(receive_api.open, key=key, raw=self.card, client_ts=ts)
		self.assertEqual(first["receipt"], again["receipt"])
		self.assertEqual(frappe.db.count("Dirty Receipt", {"name": first["receipt"]}), 1)
		self.assertEqual(
			frappe.db.count("Dirty Receipt", {"abandoned": 0, "docstatus": 0, "station": STATION}), 1
		)

	@bru("BRU-FLOW-004")
	def test_submit_replay_returns_the_stored_answer_and_opens_one_cycle(self):
		receipt = self.opened()
		unit = self.new_set()
		call(receive_api.scan_set, receipt=receipt, raw=unit)
		call(receive_api.confirm_line, receipt=receipt, set_id=unit, confirm_all=1, finalize=1)
		key = "22222222-2222-4222-8222-222222222222"
		ts = now_ts()
		first = call(receive_api.submit, key=key, receipt=receipt, client_ts=ts)
		again = call(receive_api.submit, key=key, receipt=receipt, client_ts=ts)
		# bản lưu là JSON: thời điểm thành chuỗi, còn lại giống hệt
		self.assertEqual(frappe.parse_json(frappe.as_json(first)), frappe.parse_json(frappe.as_json(again)))
		self.assertEqual(frappe.db.get_value("Set Unit", unit, "current_cycle_no"), 1)

	def test_stored_rejection_replays_with_the_same_http_status(self):
		key = "33333333-3333-4333-8333-333333333333"
		ts = now_ts()
		first = call(receive_api.open, key=key, raw="NOT-A-CARD", client_ts=ts)
		self.assert_rejection(first, "SCAN_INVALID", 422)
		frappe.local.response.pop("http_status_code", None)
		again = call(receive_api.open, key=key, raw="NOT-A-CARD", client_ts=ts)
		self.assertEqual(again, first)
		self.assertEqual(http_status(), 422)

	def test_gs1_scan_of_set_is_logged_with_the_id(self):
		receipt = self.opened()
		unit = self.new_set("Sterile")
		call(receive_api.scan_set, receipt=receipt, raw=unit)
		self.assertTrue(gs1.parse_scan(unit)["type"] == "set")
		self.assertTrue(
			frappe.db.exists("Audit Log", {"action": "Reject", "ref_doctype": "Set Unit", "ref_name": unit})
		)


class TestSubmitOfflineApi(ReceiveApiCase):
	"""FEAT-009 (A-40 D3): phiếu T1 offline phát lại thành một lệnh; bộ bị từ chối → Sync Conflict."""

	def replay(self, receipt, key=None):
		frappe.local.response.pop("http_status_code", None)
		headers = {"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": STATION, "X-TC-Replay": "1"}
		with request_headers(headers):
			return receive_api.submit_offline(
				station=STATION,
				receipt=receipt,
				client_ts=now_ts(),
				token=TOKENS[("Administrator", STATION)],
			)

	def test_submit_offline_replay_receives_sets(self):
		unit = self.new_set()
		result = self.replay({"deliverer_raw": self.card, "items": [{"set_id": unit, "confirm_all": 1}]})
		self.assertIs(result["ok"], True, msg=result)
		self.assertEqual(result["sets"], [unit])
		self.assertEqual(frappe.db.get_value("Set Unit", unit, "status"), "Processing")

	def test_submit_offline_rejected_set_becomes_conflict(self):
		unit = self.new_set("Sterile")
		key = str(uuid.uuid4())
		result = self.replay({"deliverer_raw": self.card, "items": [{"set_id": unit, "confirm_all": 1}]}, key)
		self.assertIs(result["ok"], False)
		self.assertEqual(result["error"]["code"], "STATUS_INVALID_FOR_STATION")
		self.assertTrue(frappe.db.exists("Sync Conflict", {"idempotency_key": key}))

	def test_submit_offline_payload_must_be_object(self):
		with self.assertRaises(BadRequestError):
			call(receive_api.submit_offline, receipt="[1, 2]")
