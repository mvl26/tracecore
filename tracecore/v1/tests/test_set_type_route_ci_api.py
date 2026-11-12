"""A-157 (FR-M1-06.6): sửa Quy trình xử lý / Loại chỉ thị hóa học của loại bộ từ form Set Unit.

RPC ``tracecore.v1.set_type_admin.set_route_ci`` ghi trên Loại bộ (áp cho mọi bộ cùng loại) qua ``save()`` nên chạy đủ
kiểm FR-M1-03.3/.9/.10; Audit Log ``Update`` qua hook; chỉ thị mặc định không còn hợp lệ thì bỏ trống và báo lại.
``tracecore.v1.set_unit_lifecycle.form_context`` trả ``set_type_edit`` (quyền, lựa chọn, số bộ, số bộ trong chu trình).
"""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe

from tracecore.tests.factories import make_item, make_set_type, make_set_unit, make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import set_type_admin as api
from tracecore.v1 import set_unit_lifecycle
from tracecore.v1._common import BadRequestError

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

SET_TYPE = "Instrument Set Type"


def now_ts():
	return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(timespec="seconds")


def call(key=None, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4())}):
		return api.set_route_ci(**kwargs)


def as_user(roles, fn, *args, **kwargs):
	email = make_user(f"route-ci-{'-'.join(r.lower().replace(' ', '') for r in roles)}@example.com", roles)
	frappe.set_user(email)
	try:
		return fn(*args, **kwargs)
	finally:
		frappe.set_user("Administrator")


def updates(set_type):
	return frappe.get_all(
		"Audit Log",
		filters={"ref_doctype": SET_TYPE, "ref_name": set_type, "action": "Update"},
		fields=["old_value", "new_value"],
	)


class TestSetRouteCi(IsolatedTestCase):
	def test_admin_roles_change_route_and_class_on_the_set_type(self):
		st = make_set_type("RCA").name
		out = as_user(["TC R02"], call, set_type=st, method="Plasma", ci_class="6")
		self.assertTrue(out["ok"])
		self.assertTrue(out["changed"])
		self.assertEqual(frappe.db.get_value(SET_TYPE, st, ["method", "ci_class"]), ("Plasma", "6"))
		out = as_user(["TC R10"], call, set_type=st, method="Steam", ci_class="")
		self.assertEqual(frappe.db.get_value(SET_TYPE, st, "method"), "Steam")
		self.assertFalse(frappe.db.get_value(SET_TYPE, st, "ci_class"))
		self.assertEqual((out["method"], out["ci_class"]), ("Steam", ""))

	def test_change_is_audited_with_old_and_new_values(self):
		st = make_set_type("RCB").name
		before = len(updates(st))
		call(set_type=st, method="Steam", ci_class="4")
		rows = updates(st)
		self.assertEqual(len(rows), before + 1)
		self.assertIn("ci_class", frappe.parse_json(rows[0].new_value) or {})

	def test_no_change_writes_nothing(self):
		st = make_set_type("RCC").name
		before = len(updates(st))
		out = call(set_type=st, method="Steam", ci_class="")
		self.assertEqual((out["ok"], out["changed"]), (True, False))
		self.assertEqual(len(updates(st)), before)

	def test_other_roles_are_refused(self):
		st = make_set_type("RCD").name
		with self.assertRaises(frappe.PermissionError):
			as_user(["TC R04"], call, set_type=st, method="Plasma", ci_class="")
		self.assertEqual(frappe.db.get_value(SET_TYPE, st, "method"), "Steam")

	def test_values_outside_the_choices_are_bad_requests(self):
		st = make_set_type("RCE").name
		for kwargs in (
			{"method": "Boil", "ci_class": ""},
			{"method": "Steam", "ci_class": "3"},
			{"method": None, "ci_class": ""},
			{"method": "Steam", "ci_class": 5},
		):
			with self.subTest(kwargs=kwargs), self.assertRaises(BadRequestError):
				call(set_type=st, **kwargs)

	def test_set_type_rules_still_apply(self):
		st = make_set_type("RCF").name
		with self.assertRaises(frappe.ValidationError):  # FR-M1-03.10: Khử khuẩn không nhận chỉ thị 4/5/6
			call(set_type=st, method="Disinfection", ci_class="5")
		self.assertEqual(frappe.db.get_value(SET_TYPE, st, "method"), "Steam")
		self.assertFalse(frappe.db.get_value(SET_TYPE, st, "ci_class"))

	def test_default_indicator_that_no_longer_fits_is_cleared(self):
		ci5 = make_item("CI5-RC-STEAM", "Chemical Indicator", method="Steam", ci_class="5").name
		st = make_set_type("RCG")
		st.default_ci_item = ci5
		st.save()
		out = call(set_type=st.name, method="Steam", ci_class="4")
		self.assertEqual(out["cleared_default_ci"], ci5)
		self.assertFalse(frappe.db.get_value(SET_TYPE, st.name, "default_ci_item"))
		out = call(set_type=st.name, method="Steam", ci_class="")
		self.assertIsNone(out["cleared_default_ci"])

	def test_same_key_returns_same_response(self):
		st = make_set_type("RCH").name
		key = str(uuid.uuid4())
		first = call(key=key, set_type=st, method="Plasma", ci_class="")
		again = call(key=key, set_type=st, method="Plasma", ci_class="")
		self.assertEqual(first, again)

	def test_unknown_set_type_is_not_found(self):
		out = call(set_type="NOPE-RC", method="Steam", ci_class="")
		self.assertFalse(out["ok"])
		self.assertEqual(out["error"]["code"], "SET_TYPE_NOT_FOUND")


class TestSetUnitFormContextRouteCi(IsolatedTestCase):
	def test_context_reports_choices_counts_and_permission(self):
		st = make_set_type("RCK").name
		unit = make_set_unit(st).name
		other = make_set_unit(st).name
		frappe.db.set_value("Set Unit", other, "active_cycle_id", "TEST-CYCLE-RCK")
		edit = set_unit_lifecycle.form_context(set_unit=unit)["set_type_edit"]
		self.assertTrue(edit["can_edit"])
		self.assertEqual(edit["set_type"], st)
		self.assertEqual(edit["methods"], ["Steam", "Plasma", "Disinfection"])
		self.assertEqual(edit["ci_classes"], ["", "Not Needed", "4", "5", "6"])
		self.assertEqual((edit["units"], edit["units_in_cycle"]), (2, 1))
		edit = as_user(["TC R04"], set_unit_lifecycle.form_context, set_unit=unit)["set_type_edit"]
		self.assertFalse(edit["can_edit"])
