"""FEAT-099 (A-158, FR-M9-31): RPC đọc của cổng khoa trên Page tc-flow."""

import uuid
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.linen import received as linen_received_service
from tracecore.reprocessing import department_recall, dirty_return, issue_request
from tracecore.tests.utils import request_headers
from tracecore.v1 import flow


def make_department(name, ward=1):
	existing = frappe.db.get_value("Department", {"department_name": name}, "name")
	if existing:
		frappe.db.set_value("Department", existing, {"tc_is_ward": ward, "disabled": 0})
		return existing
	company = frappe.db.get_value("Company", {}, "name")
	doc = frappe.get_doc(
		{"doctype": "Department", "department_name": name, "company": company, "tc_is_ward": ward}
	).insert(ignore_permissions=True)
	return doc.name


class TestFlowApi(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.ward = make_department("TCF Ward A")
		self.other = make_department("TCF Ward B")
		self.office = make_department("TCF Office", ward=0)

	def test_departments_lists_only_wards(self):
		names = [row["name"] for row in flow.departments()["departments"]]
		self.assertIn(self.ward, names)
		self.assertIn(self.other, names)
		self.assertNotIn(self.office, names)
		row = next(row for row in flow.departments()["departments"] if row["name"] == self.ward)
		self.assertEqual(row["label"], "TCF Ward A")

	def test_ward_staff_only_get_their_own_department(self):
		with patch.object(flow, "_scope", return_value=self.ward):
			self.assertEqual([row["name"] for row in flow.departments()["departments"]], [self.ward])
			self.assertTrue(flow.department_stock(self.ward)["ok"])
			with self.assertRaises(frappe.PermissionError):
				flow.department_stock(self.other)

	def test_department_stock_reuses_the_usage_overview(self):
		out = flow.department_stock(self.ward)
		self.assertEqual(out["department"], self.ward)
		self.assertEqual(out["department_name"], "TCF Ward A")
		self.assertEqual(out["at_department"], [])
		self.assertEqual(out["waiting_return"], [])
		# 4 số liệu của màn Bộ tại khoa và cơ số; khoa mới chưa đặt cơ số
		self.assertEqual(
			out["counts"], {"held": 0, "reprocessing": 0, "recall_pending": 0, "waiting_return": 0}
		)
		self.assertIsNone(out["par"])
		# không có trường mã người bệnh
		self.assertNotIn("patient", " ".join(out.keys()))

	def test_waiting_return_counts_the_sets_in_pickup_requests(self):
		# ô "Yêu cầu trả đồ bẩn chờ KSNK lấy" khớp với bảng yêu cầu đã gửi: đếm bộ đã gửi mà T1 chưa tiếp nhận
		with patch.object(dirty_return, "pending_sets", return_value={"SET-1", "SET-2", "SET-3"}) as pending:
			out = flow.department_stock(self.ward)
		pending.assert_called_once_with(self.ward)
		self.assertEqual(out["counts"]["waiting_return"], 3)

	def test_unknown_or_non_ward_department_is_rejected(self):
		for value in (None, "", "TCF-NOPE", self.office):
			with self.assertRaises(frappe.DoesNotExistError):
				flow.department_stock(value)

	def test_scope_by_role(self):
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.session.user = "someone@example.com"
		with patch.object(frappe, "get_roles", return_value=["TC R02"]):
			self.assertIsNone(flow._scope())
		with patch.object(frappe, "get_roles", return_value=["TC R08"]):
			with patch.object(flow, "_own_department", return_value=self.ward):
				self.assertEqual(flow._scope(), self.ward)
			with patch.object(flow, "_own_department", return_value=None):
				self.assertEqual(flow._scope(), "-")  # R08 chưa gắn khoa: không thấy khoa nào
		with patch.object(frappe, "get_roles", return_value=["TC R03"]):
			with self.assertRaises(frappe.PermissionError):
				flow._scope()

	def post(self, **kwargs):
		kwargs.setdefault("client_ts", "2026-11-13T15:20:00+07:00")
		with request_headers({"X-Idempotency-Key": kwargs.pop("key", None) or str(uuid.uuid4())}):
			return flow.request_return(**kwargs)

	def test_return_overview_lists_candidates_and_todays_requests(self):
		rows = [{"set_id": "SET-1", "set_name": "A", "cycle_id": "CY-1", "used": True}]
		sent = [{"request": "YC-1", "status": "Waiting", "set_count": 1, "received_count": 0}]
		with (
			patch.object(dirty_return, "candidates", return_value=rows) as candidates,
			patch.object(dirty_return, "requests_on", return_value=sent),
			patch.object(dirty_return, "sets_on", return_value=[{"set_id": "SET-9", "received": False}]),
		):
			out = flow.return_overview(self.ward)
		self.assertEqual(out["sent_sets"], [{"set_id": "SET-9", "received": False}])
		candidates.assert_called_once_with(self.ward)
		self.assertEqual((out["candidates"], out["requests"]), (rows, sent))
		self.assertEqual(out["conditions"][0], "Complete")
		self.assertNotIn("patient", frappe.as_json(out))

	def test_return_rpcs_keep_the_department_scope(self):
		with patch.object(flow, "_scope", return_value=self.ward):
			with self.assertRaises(frappe.PermissionError):
				flow.return_overview(self.other)
			with self.assertRaises(frappe.PermissionError):
				self.post(department=self.other, items="[]")
		with self.assertRaises(frappe.DoesNotExistError):
			flow.return_overview(self.office)

	def test_request_return_answers_a_rejection_inline(self):
		out = self.post(department=self.ward, items="[]")
		self.assertFalse(out["ok"])
		self.assertEqual(out["error"]["code"], "NO_SETS")
		for part in ("title", "reason", "action"):
			self.assertTrue(out["error"][part])

	def test_request_return_is_idempotent_and_needs_client_ts(self):
		created = {"request": "YC-TEST", "set_count": 1}
		key = str(uuid.uuid4())
		items = '[{"set_id": "SET-1", "condition": "Complete"}]'
		with (
			patch.object(dirty_return, "create", return_value=created) as create,
			patch.object(dirty_return, "candidates", return_value=[]),
			patch.object(dirty_return, "requests_on", return_value=[]),
			patch.object(dirty_return, "sets_on", return_value=[]),
		):
			first = self.post(department=self.ward, items=items, key=key)
			again = self.post(department=self.ward, items=items, key=key)
			self.assertEqual(create.call_count, 1)
			self.assertEqual(create.call_args.args[:2], (self.ward, items))
			with self.assertRaises(frappe.ValidationError):
				self.post(department=self.ward, items=items, client_ts="2026-11-13 15:20:00")
		self.assertTrue(first["ok"])
		self.assertEqual((first["request"], again["request"]), ("YC-TEST", "YC-TEST"))

	def post_issue(self, **kwargs):
		kwargs.setdefault("client_ts", "2026-11-13T15:20:00+07:00")
		with request_headers({"X-Idempotency-Key": kwargs.pop("key", None) or str(uuid.uuid4())}):
			return flow.request_issue(**kwargs)

	def test_recall_overview_and_stock_count_use_the_open_orders(self):
		orders = [{"recall": "TH-1", "lines": [{"cycle_id": "CY-1", "confirmed": False}]}]
		with (
			patch.object(department_recall, "open_orders", return_value=orders) as opened,
			patch.object(department_recall, "pending_count", return_value=2),
		):
			out = flow.recall_overview(self.ward)
			stock = flow.department_stock(self.ward)
		opened.assert_called_once_with(self.ward)
		self.assertEqual((out["orders"], out["pending"]), (orders, 2))
		self.assertEqual(stock["counts"]["recall_pending"], 2)

	def test_issue_overview_lists_options_and_todays_requests(self):
		options = [{"set_type": "BO-A", "set_name": "A", "stock": 1, "min": 6, "max": 10, "available": 3}]
		sent = [{"request": "DN-1", "status": "Waiting", "qty": 2, "issued_count": 0}]
		with (
			patch.object(issue_request, "options", return_value=options),
			patch.object(issue_request, "requests_on", return_value=sent),
		):
			out = flow.issue_overview(self.ward)
		self.assertEqual((out["options"], out["requests"], out["max_qty"]), (options, sent, 99))

	def test_request_issue_is_idempotent_and_answers_rejections_inline(self):
		key = str(uuid.uuid4())
		args = {"department": self.ward, "set_type": "BO-A", "qty": "2", "needed_by": "2026-11-14 14:00:00"}
		with (
			patch.object(issue_request, "create", return_value={"request": "DN-TEST", "qty": 2}) as create,
			patch.object(issue_request, "options", return_value=[]),
			patch.object(issue_request, "requests_on", return_value=[]),
		):
			first = self.post_issue(key=key, **args)
			again = self.post_issue(key=key, **args)
			self.assertEqual(create.call_count, 1)
			self.assertEqual(create.call_args.args[:4], (self.ward, "BO-A", "2", "2026-11-14 14:00:00"))
		self.assertTrue(first["ok"])
		self.assertEqual((first["request"], again["request"]), ("DN-TEST", "DN-TEST"))
		rejected = issue_request.RequestRejected("QTY_INVALID", "reason", "action")
		with patch.object(issue_request, "create", side_effect=rejected):
			out = self.post_issue(**args)
		self.assertFalse(out["ok"])
		self.assertEqual(out["error"]["code"], "QTY_INVALID")
		for part in ("title", "reason", "action"):
			self.assertTrue(out["error"][part])

	def test_linen_received_passes_the_month(self):
		data = {"month": "2026-11", "rows": [], "quotas": [], "variance_pct": 0.0}
		with patch.object(linen_received_service, "overview", return_value=data) as overview:
			out = flow.linen_received(self.ward, "2026-11")
		overview.assert_called_once_with(self.ward, "2026-11")
		self.assertEqual((out["month"], out["department"]), ("2026-11", self.ward))

	def test_new_department_rpcs_keep_the_department_scope(self):
		with patch.object(flow, "_scope", return_value=self.ward):
			for call in (flow.recall_overview, flow.issue_overview, flow.linen_received):
				with self.assertRaises(frappe.PermissionError):
					call(self.other)
			with self.assertRaises(frappe.PermissionError):
				self.post_issue(
					department=self.other, set_type="BO-A", qty=1, needed_by="2026-11-14 14:00:00"
				)

	def test_par_range_sums_the_department_stock_levels(self):
		rows = [frappe._dict(min_qty=2, max_qty=4), frappe._dict(min_qty=4, max_qty=6)]
		with patch.object(frappe, "get_all", return_value=rows):
			self.assertEqual(flow._par_range(self.ward), {"min": 6, "max": 10})
		with patch.object(frappe, "get_all", return_value=[]):
			self.assertIsNone(flow._par_range(self.ward))

	def test_held_packs_carry_set_id_and_set_type(self):
		overview = {"at_department": [{"cycle_id": "CY-1", "set_name": "A", "expiry": "2026-12-01"}]}
		packs = [frappe._dict(name="CY-1", set_unit="SET-1", set_type="BO-A")]
		with patch.object(frappe, "get_all", return_value=packs):
			rows = flow._held_packs(overview)
		self.assertEqual(rows[0]["set_id"], "SET-1")
		self.assertEqual(rows[0]["set_type"], "BO-A")
		self.assertEqual(flow._held_packs({"at_department": []}), [])
