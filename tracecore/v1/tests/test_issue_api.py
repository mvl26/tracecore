"""RPC tracecore.v1.issue.* (FEAT-026): phiếu cấp phát T7 qua phiên trạm thẻ nhân viên, mã HTTP, quyền, idempotent."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe

from tracecore.core import station_auth
from tracecore.tests import factories
from tracecore.tests.factories import (
	make_department,
	make_employee,
	make_par_level,
	make_sterile_location,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import issue as issue_api
from tracecore.v1 import station as station_api
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-007"
TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
SESSION_TOKENS = {}
SIGNATURE = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def as_administrator(fn, *args, **kwargs):
	"""Dựng dữ liệu bằng quyền Administrator: factory không chạy được với quyền R06 của người dùng kiosk."""
	user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		return fn(*args, **kwargs)
	finally:
		frappe.set_user(user)


def now_ts():
	return datetime.now(TIME_ZONE).isoformat(timespec="seconds")


def call(fn, key=None, station_header=STATION, **kwargs):
	"""Gọi RPC như kiosk T7: header khóa idempotent + trạm, `client_ts` hiện tại, token phiên của người dùng hiện tại."""
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	kwargs.setdefault("token", SESSION_TOKENS.get(frappe.session.user))
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": station_header}):
		return fn(**kwargs)


def http_status():
	return frappe.local.response.get("http_status_code")


def assert_block(case, result, code, status):
	case.assertIs(result["ok"], False)
	case.assertEqual(result["error"]["code"], code)
	case.assertEqual(result["error"]["http_status"], status)
	case.assertEqual(http_status(), status)


class IssueApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		SESSION_TOKENS.clear()
		self.addCleanup(SESSION_TOKENS.clear)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		self.dept = as_administrator(make_department, "Khoa API cấp phát")
		self.set_type = as_administrator(factories.make_set_type, "IAP").name
		self.shelf = as_administrator(make_sterile_location, "Kệ API T7")
		self.recipient = as_administrator(make_employee, first_name="Người nhận API", department=self.dept)
		self.as_user("capphat@example.com", ["TC R06"])

	def as_user(self, email, roles, station=STATION):
		"""Người dùng kiosk có thẻ nhân viên, năng lực trạm `station` và phiên trạm đang sống (FEAT-003)."""
		frappe.set_user("Administrator")
		user = make_user(email, roles=roles)
		SESSION_TOKENS[user] = make_station_session(user, station)["token"]
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		return user

	def stocked(self, **kwargs):
		return as_administrator(factories.make_stocked_pack, self.set_type, location=self.shelf, **kwargs)

	def open_draft(self):
		return call(issue_api.create, department=self.dept, station=STATION)["issue"]["issue_note"]


class TestFlow(IssueApiCase):
	@bru("BRU-FLOW-002", "BRU-FLOW-003", "BRU-PAR-005")
	def test_full_flow_issues_two_packs_to_department(self):
		# UC-12: chọn khoa → quét 2 gói → quét thẻ người nhận ký → xác nhận → in
		as_administrator(
			make_par_level,
			"Instrument Set Type",
			self.set_type,
			par_kind="Department Stock",
			department=self.dept,
			min_qty=0,
			max_qty=5,
			is_active=1,
		)
		listing = call(issue_api.departments, station=STATION)
		self.assertIn(self.dept, [row["name"] for row in listing["departments"]])
		context = call(issue_api.context, department=self.dept, station=STATION)
		self.assertTrue(context["ok"])
		note = self.open_draft()
		packs = [self.stocked(), self.stocked()]
		for pack in packs:
			result = call(issue_api.add_pack, issue_note=note, raw=pack.name, station=STATION)
			self.assertTrue(result["ok"])
		self.assertEqual(len(result["issue"]["packs"]), 2)
		signed = call(
			issue_api.sign,
			issue_note=note,
			card=self.recipient.tc_card_id,
			station=STATION,
			method="Touch",
			signature=SIGNATURE,
		)
		self.assertTrue(signed["issue"]["signed"])
		done = call(issue_api.submit, issue_note=note, station=STATION)
		self.assertTrue(done["ok"])
		self.assertIn("format=TC+Issue+Note", done["print_url"])
		self.assertEqual(frappe.db.get_value("Issue Note", note, "docstatus"), 1)
		for pack in packs:
			self.assertEqual(frappe.db.get_value("Pack", pack.name, "status"), "Issued")
			self.assertEqual(frappe.db.get_value("Set Unit", pack.set_unit, "status"), "At Department")

	def test_remove_pack(self):
		note = self.open_draft()
		pack = self.stocked()
		call(issue_api.add_pack, issue_note=note, raw=pack.name, station=STATION)
		result = call(issue_api.remove_pack, issue_note=note, cycle_id=pack.name, station=STATION)
		self.assertEqual(result["issue"]["packs"], [])

	def test_over_par_needs_r02_card_and_pin(self):
		as_administrator(
			make_par_level,
			"Instrument Set Type",
			self.set_type,
			par_kind="Department Stock",
			department=self.dept,
			min_qty=0,
			max_qty=1,
			is_active=1,
		)
		note = self.open_draft()
		for _ in range(2):
			call(issue_api.add_pack, issue_note=note, raw=self.stocked().name, station=STATION)
		listing = call(issue_api.sign, issue_note=note, card=self.recipient.tc_card_id, station=STATION)
		self.assertTrue(listing["issue"]["needs_approval"])
		assert_block(
			self, call(issue_api.submit, issue_note=note, station=STATION), "PAR_APPROVAL_REQUIRED", 409
		)

		# R02 quét thẻ + nhập PIN ngay trên kiosk của R06 (v1.station.verify_approver) → proof gắn với phiên R06
		frappe.set_user("Administrator")
		r02 = make_user("duyet-api-r02@example.com", ["TC R02"])
		approver = make_employee(first_name="Giám sát API", user_id=r02)
		station_auth.set_pin(approver.name, "246813")
		station_auth.clear_pin_rate_limit(approver.name)
		frappe.set_user("capphat@example.com")
		token = SESSION_TOKENS["capphat@example.com"]
		verified = station_api.verify_approver(
			token=token, card_id=approver.tc_card_id, pin="246813", role="TC R02", client_ts=now_ts()
		)
		self.assertTrue(verified["ok"])

		assert_block(
			self,
			call(issue_api.submit, issue_note=note, station=STATION, approver_proof="proof-sai"),
			"PAR_APPROVAL_REQUIRED",
			409,
		)
		done = call(issue_api.submit, issue_note=note, station=STATION, approver_proof=verified["proof"])
		self.assertTrue(done["ok"])
		self.assertEqual(frappe.db.get_value("Issue Note", note, "approved_by"), "duyet-api-r02@example.com")

	def test_over_par_rejects_proof_from_another_station_session(self):
		as_administrator(
			make_par_level,
			"Instrument Set Type",
			self.set_type,
			par_kind="Department Stock",
			department=self.dept,
			min_qty=0,
			max_qty=1,
			is_active=1,
		)
		note = self.open_draft()
		for _ in range(2):
			call(issue_api.add_pack, issue_note=note, raw=self.stocked().name, station=STATION)
		call(issue_api.sign, issue_note=note, card=self.recipient.tc_card_id, station=STATION)
		frappe.set_user("Administrator")
		r02 = make_user("duyet-api-r02b@example.com", ["TC R02"])
		approver = make_employee(first_name="Giám sát API B", user_id=r02)
		station_auth.set_pin(approver.name, "246813")
		station_auth.clear_pin_rate_limit(approver.name)
		# proof lấy trên phiên của một kiosk khác không dùng được cho phiếu của phiên này
		other = self.as_user("capphat-khac@example.com", ["TC R06"])
		proof = station_api.verify_approver(
			token=SESSION_TOKENS[other], card_id=approver.tc_card_id, pin="246813", client_ts=now_ts()
		)["proof"]
		frappe.set_user("capphat@example.com")
		assert_block(
			self,
			call(issue_api.submit, issue_note=note, station=STATION, approver_proof=proof),
			"PAR_APPROVAL_REQUIRED",
			409,
		)


class TestRejections(IssueApiCase):
	@bru("BRU-FLOW-002")
	def test_pack_not_in_stock_is_409_and_audited(self):
		note = self.open_draft()
		pack = as_administrator(factories.make_released_pack, set_type=self.set_type)
		result = call(issue_api.add_pack, issue_note=note, raw=pack.name, station=STATION)
		assert_block(self, result, "PACK_NOT_IN_STOCK", 409)
		self.assertTrue(frappe.db.exists("Audit Log", {"action": "Reject", "reason": "PACK_NOT_IN_STOCK"}))

	def test_unknown_pack_is_404(self):
		note = self.open_draft()
		result = call(issue_api.add_pack, issue_note=note, raw="CY-990101-9999", station=STATION)
		assert_block(self, result, "PACK_NOT_FOUND", 404)

	def test_not_a_pack_code_is_422(self):
		note = self.open_draft()
		result = call(issue_api.add_pack, issue_note=note, raw=self.shelf.name, station=STATION)
		assert_block(self, result, "SCAN_INVALID", 422)

	def test_unknown_department_is_404(self):
		assert_block(
			self,
			call(issue_api.create, department="Khoa không tồn tại", station=STATION),
			"DEPARTMENT_NOT_FOUND",
			404,
		)

	def test_unknown_recipient_card_is_422(self):
		note = self.open_draft()
		call(issue_api.add_pack, issue_note=note, raw=self.stocked().name, station=STATION)
		result = call(issue_api.sign, issue_note=note, card="KHONG-CO-THE", station=STATION)
		assert_block(self, result, "RECIPIENT_INVALID", 422)

	def test_submit_unsigned_is_409(self):
		note = self.open_draft()
		call(issue_api.add_pack, issue_note=note, raw=self.stocked().name, station=STATION)
		assert_block(self, call(issue_api.submit, issue_note=note, station=STATION), "ISSUE_NOT_SIGNED", 409)

	def test_missing_issue_note_is_404(self):
		result = call(issue_api.remove_pack, issue_note="IS-1999-00001", cycle_id="x", station=STATION)
		assert_block(self, result, "ISSUE_NOT_FOUND", 404)


class TestPackOfAnotherDepartment(IssueApiCase):
	"""A-102: gói của khoa khác: cảnh báo, phải xác nhận kèm lý do, ghi Audit Log; không chặn hẳn."""

	def other_pack(self):
		pack = self.stocked()
		other = as_administrator(make_department, "Khoa API khác")
		as_administrator(frappe.db.set_value, "Pack", pack.name, "department", other)
		return pack

	def test_first_scan_warns_and_nothing_is_added(self):
		note, pack = self.open_draft(), self.other_pack()
		result = call(issue_api.add_pack, issue_note=note, raw=pack.name, station=STATION)
		assert_block(self, result, "PACK_DEPT_MISMATCH", 409)
		self.assertEqual(frappe.db.count("Issue Note Pack", {"parent": note}), 0)

	def test_reason_adds_the_pack_and_is_audited(self):
		note, pack = self.open_draft(), self.other_pack()
		result = call(
			issue_api.add_pack,
			issue_note=note,
			raw=pack.name,
			station=STATION,
			department_reason="Khoa mượn gấp",
		)
		self.assertIs(result["ok"], True, msg=result)
		self.assertEqual([row["cycle_id"] for row in result["issue"]["packs"]], [pack.name])
		log = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Pack", "ref_name": pack.name, "reason": "PackOfOtherDepartment"},
			fields=["new_value"],
		)
		self.assertEqual(len(log), 1)
		self.assertEqual(frappe.parse_json(log[0].new_value)["note"], "Khoa mượn gấp")

	def test_blank_reason_is_not_a_confirmation(self):
		note, pack = self.open_draft(), self.other_pack()
		result = call(
			issue_api.add_pack, issue_note=note, raw=pack.name, station=STATION, department_reason="  "
		)
		assert_block(self, result, "PACK_DEPT_MISMATCH", 409)

	def test_pack_of_same_department_or_without_department_has_no_warning(self):
		note = self.open_draft()
		same, blank = self.stocked(), self.stocked()
		as_administrator(frappe.db.set_value, "Pack", same.name, "department", self.dept)
		as_administrator(frappe.db.set_value, "Pack", blank.name, "department", None)
		for pack in (same, blank):
			result = call(issue_api.add_pack, issue_note=note, raw=pack.name, station=STATION)
			self.assertEqual(result.get("error", {}).get("code") == "PACK_DEPT_MISMATCH", False, msg=result)


class TestSecurity(IssueApiCase):
	def test_all_rpcs_are_post_only(self):
		for fn in (
			issue_api.departments,
			issue_api.context,
			issue_api.create,
			issue_api.add_pack,
			issue_api.remove_pack,
			issue_api.sign,
			issue_api.submit,
		):
			self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[fn], ["POST"])

	def test_wrong_station_session_is_blocked(self):
		result = call(issue_api.departments, station="TR-006")
		assert_block(self, result, "SESSION_STATION_MISMATCH", 403)

	def test_t6_station_is_not_an_issuing_station(self):
		self.as_user("kho-t6@example.com", ["TC R06"], station="TR-006")
		result = call(issue_api.create, department=self.dept, station="TR-006")
		assert_block(self, result, "STATION_WRONG_STEP", 422)

	def test_requires_r06_role(self):
		self.as_user("sai-vai-tro@example.com", ["TC R03"])
		with self.assertRaises(frappe.PermissionError):
			call(issue_api.departments, station=STATION)

	def test_no_session_token_is_rejected(self):
		frappe.local.response.pop("http_status_code", None)
		with request_headers({"X-Idempotency-Key": str(uuid.uuid4()), "X-TC-Station": STATION}):
			result = issue_api.departments(station=STATION, token="khong-hop-le", client_ts=now_ts())
		self.assertIs(result["ok"], False)
		self.assertEqual(result["error"]["http_status"], 401)

	def test_create_is_idempotent(self):
		key, ts = str(uuid.uuid4()), now_ts()  # gửi lại y nguyên khóa và client_ts như kiosk Thử lại
		first = call(issue_api.create, key=key, department=self.dept, station=STATION, client_ts=ts)
		count = frappe.db.count("Issue Note")
		second = call(issue_api.create, key=key, department=self.dept, station=STATION, client_ts=ts)
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("Issue Note"), count)
