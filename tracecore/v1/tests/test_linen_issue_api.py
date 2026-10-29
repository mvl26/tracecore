"""RPC tracecore.v1.linen.balance / issue (FEAT-035 Task 4): phiên thẻ, bước LIN, thẻ người nhận, chữ ký, cảnh báo định mức."""

import uuid

import frappe

from tracecore.tests.factories import (
	LINEN_STATION,
	linen_line,
	make_department,
	make_employee,
	make_linen_collection,
	make_linen_station,
	make_linen_type,
)
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1 import linen as linen_api
from tracecore.v1.tests.station_fixtures import make_station_session
from tracecore.v1.tests.test_linen_api import TOKENS, call, http_status, now_ts

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

PNG = "data:image/png;base64,iVBORw0KGgo="
CARD = "LINEN-RCP-0001"


class LinenIssueApiCase(IsolatedTestCase):
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
		self.department = make_department("Test linen issue ward")
		self.sheet = make_linen_type(
			std_weight_kg=0.5, quotas=[{"department": self.department, "min_qty": 2, "max_qty": 12}]
		).name
		self.recipient = make_employee(card=CARD, department=self.department)

	def issue(self, lines=None, **kwargs):
		kwargs.setdefault("department", self.department)
		kwargs.setdefault("kind", "Return")
		kwargs.setdefault("recipient_card", CARD)
		kwargs.setdefault("sign_method", "Card")
		lines = lines if lines is not None else [{"linen_type": self.sheet, "qty": 10, "weight_kg": 5}]
		return call(linen_api.issue, lines=lines, **kwargs)

	def assert_rejection(self, result, code, status=422):
		self.assertIs(result["ok"], False, msg=result)
		self.assertEqual(result["error"]["code"], code)
		self.assertEqual(http_status(), status)
		for key in ("title", "reason", "action"):
			self.assertTrue(result["error"][key], msg=key)


class TestIssue(LinenIssueApiCase):
	@bru("BRU-LIN-001")
	def test_issue_records_and_submits_with_card_signature(self):  # FR-M3-05, .1
		result = self.issue()
		self.assertIs(result["ok"], True, msg=result)
		view = result["issue"]
		self.assertRegex(view["issue"], r"^LNI-\d{4}-\d{5}$")
		doc = frappe.get_doc("Linen Issue", view["issue"])
		self.assertEqual(
			(doc.docstatus, doc.kind, doc.recipient, doc.sign_method),
			(1, "Return", self.recipient.name, "Card"),
		)
		self.assertEqual((doc.department, doc.station), (self.department, LINEN_STATION))
		self.assertTrue(doc.issued_by)

	def test_response_carries_the_new_balance(self):  # FR-M3-05: hiển thị ngay đối chiếu
		make_linen_collection([linen_line(self.sheet, 10, 5)], department=self.department, submit=True)
		view = self.issue([{"linen_type": self.sheet, "qty": 4, "weight_kg": 2}])["issue"]
		line = next(row for row in view["balance"] if row["linen_type"] == self.sheet)
		self.assertEqual((line["unreturned"], line["stock"]), (6, -6))

	def test_touch_signature_is_stored(self):
		result = self.issue(sign_method="Touch", signature=PNG)
		doc = frappe.get_doc("Linen Issue", result["issue"]["issue"])
		self.assertEqual((doc.sign_method, doc.signature), ("Touch", PNG))

	def test_over_max_quota_still_records_with_a_warning(self):  # FR-M3-05.2
		result = self.issue([{"linen_type": self.sheet, "qty": 20, "weight_kg": 10}])
		self.assertIs(result["ok"], True, msg=result)
		self.assertIn(self.sheet, result["issue"]["quota_warning"])

	def test_new_kind_is_accepted(self):  # UC-18 A1
		self.assertIs(self.issue(kind="New")["ok"], True)

	def test_replay_with_the_same_key_does_not_record_twice(self):
		key, stamp = str(uuid.uuid4()), now_ts()
		lines = [{"linen_type": self.sheet, "qty": 2, "weight_kg": 1}]
		args = {
			"department": self.department,
			"kind": "Return",
			"recipient_card": CARD,
			"sign_method": "Card",
			"lines": lines,
			"client_ts": stamp,
		}
		one = call(linen_api.issue, key=key, **args)
		two = call(linen_api.issue, key=key, **args)
		self.assertEqual(one["issue"]["issue"], two["issue"]["issue"])
		self.assertEqual(frappe.db.count("Linen Issue", {"department": self.department}), 1)


class TestIssueRejections(LinenIssueApiCase):
	def test_dispose_is_not_a_station_action(self):  # G10: hủy làm trên Desk vì cần ảnh
		self.assert_rejection(self.issue(kind="Dispose"), "LINEN_ISSUE_KIND_INVALID")

	def test_unknown_kind_is_rejected(self):
		self.assert_rejection(self.issue(kind="Gift"), "LINEN_ISSUE_KIND_INVALID")

	def test_unknown_card_is_rejected(self):
		self.assert_rejection(self.issue(recipient_card="NOPE-1234"), "LINEN_RECIPIENT_INVALID")

	def test_inactive_employee_card_is_rejected(self):
		frappe.db.set_value("Employee", self.recipient.name, "tc_card_enabled", 0)
		self.assert_rejection(self.issue(), "LINEN_RECIPIENT_INVALID")

	def test_touch_without_drawing_is_rejected(self):
		self.assert_rejection(self.issue(sign_method="Touch"), "LINEN_SIGNATURE_INVALID")
		self.assert_rejection(
			self.issue(sign_method="Touch", signature="not-an-image"), "LINEN_SIGNATURE_INVALID"
		)

	def test_unknown_sign_method_is_rejected(self):
		self.assert_rejection(self.issue(sign_method="Fax"), "LINEN_SIGNATURE_INVALID")

	def test_bad_department_is_rejected(self):
		self.assert_rejection(self.issue(department="Nowhere"), "DEPARTMENT_INVALID")

	def test_empty_and_bad_lines_are_rejected(self):  # BRU-LIN-001
		self.assert_rejection(self.issue(lines=[]), "LINEN_EMPTY")
		self.assert_rejection(self.issue(lines=[{"linen_type": "nope", "qty": 1}]), "LINEN_TYPE_INVALID")
		self.assert_rejection(self.issue(lines=[{"linen_type": self.sheet}]), "LINEN_QTY_INVALID")

	def test_variance_over_tolerance_needs_a_note(self):
		self.assert_rejection(
			self.issue(lines=[{"linen_type": self.sheet, "qty": 10, "weight_kg": 8}]),
			"LINEN_VARIANCE_NOTE_REQUIRED",
		)

	def test_nothing_is_saved_when_rejected(self):
		self.issue(recipient_card="NOPE-1234")
		self.assertEqual(frappe.db.count("Linen Issue", {"department": self.department}), 0)

	def test_wrong_station_step_is_rejected(self):
		result = call(
			linen_api.issue,
			department=self.department,
			kind="Return",
			recipient_card=CARD,
			sign_method="Card",
			lines=[{"linen_type": self.sheet, "qty": 1, "weight_kg": 0.5}],
			station="TR-T1",
		)
		self.assertIs(result.get("ok"), False, msg=result)


class TestBalance(LinenIssueApiCase):
	def test_balance_lists_unreturned_stock_and_quota(self):  # UC-18 bước 2
		make_linen_collection([linen_line(self.sheet, 8, 4)], department=self.department, submit=True)
		result = call(linen_api.balance, department=self.department)
		self.assertIs(result["ok"], True, msg=result)
		line = next(row for row in result["balance"] if row["linen_type"] == self.sheet)
		self.assertEqual(
			(line["unreturned"], line["stock"], line["min_qty"], line["max_qty"]), (8, -8, 2, 12)
		)

	def test_balance_rejects_a_bad_department(self):
		self.assert_rejection(call(linen_api.balance, department="Nowhere"), "DEPARTMENT_INVALID")

	def test_balance_writes_nothing(self):
		before = frappe.db.count("Idempotency Key")
		call(linen_api.balance, department=self.department)
		self.assertEqual(frappe.db.count("Idempotency Key"), before)
