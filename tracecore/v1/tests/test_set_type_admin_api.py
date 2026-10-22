"""RPC tracecore.v1.set_type_admin.* (FEAT-015 Task 2): tạo loại bộ cùng BOM v1, lưu phiên bản BOM mới, sao chép.

Quyền TC R02 / TC R10 / System Manager kiểm trước mọi ghi (S12); từ chối nghiệp vụ trả body chuẩn + mã HTTP + Audit Log
`Reject` (ADR-003, S14); gửi lại cùng `X-Idempotency-Key` trả cùng response (Review Focus 3).
"""

import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_days, getdate, nowdate

from tracecore.core.errors import HTTP_STATUS
from tracecore.tests.factories import (
	AUTO_PACK_TYPE,
	make_department,
	make_instrument,
	make_pack_type,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import set_type_admin as api
from tracecore.v1._common import BadRequestError

# Instrument Set Type liên kết Department, Item; Set BOM Item/Instrument liên kết Item; CI chưa có Setup Wizard
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

SET_TYPE = "Instrument Set Type"


def now_ts():
	return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(timespec="seconds")


def call(fn, key=None, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4())}):
		return fn(**kwargs)


def http_status():
	return frappe.local.response.get("http_status_code")


def as_user(roles, fn, **kwargs):
	email = make_user(f"st-admin-{'-'.join(r.lower().replace(' ', '') for r in roles)}@example.com", roles)
	frappe.set_user(email)
	try:
		return call(fn, **kwargs)
	finally:
		frappe.set_user("Administrator")


def header(type_code, method="Steam"):
	return {
		"type_code": type_code,
		"set_type_name": f"Set {type_code}",
		"method": method,
		"department": make_department(),
		"default_pack_type": make_pack_type(*AUTO_PACK_TYPE),
	}


def rejects(set_type, code):
	return frappe.get_all(
		"Audit Log",
		filters={"ref_doctype": SET_TYPE, "ref_name": set_type, "action": "Reject", "reason": code},
		fields=["new_value", "client_ts"],
	)


class TestSetTypeAdminRpc(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		for code in ("SA-1", "SA-2", "SA-3"):
			make_instrument(code, methods=("Steam 134",))
		make_instrument("SA-PL", methods=("Plasma",))

	def test_create_save_copy_happy_path(self):
		lines = [{"instrument": "SA-1", "qty": 2}, {"instrument": "SA-2", "qty": 1}]
		created = as_user(["TC R02"], api.create, header=json.dumps(header("SAC")), lines=json.dumps(lines))
		self.assertEqual(
			created,
			{
				"ok": True,
				"set_type": "SAC",
				"bom_version": 1,
				"effective_from": nowdate(),
				"status": "Effective",
			},
		)
		self.assertEqual(frappe.db.get_value(SET_TYPE, "SAC", "owner"), "st-admin-tcr02@example.com")

		tomorrow = str(add_days(getdate(nowdate()), 1))
		saved = as_user(
			["TC R10"],
			api.save_bom,
			set_type="SAC",
			lines=[{"instrument": "SA-3", "qty": 1}],
			effective_from=tomorrow,
			reason="New layout",
			base_version="1",
		)
		self.assertEqual(
			saved,
			{
				"ok": True,
				"set_type": "SAC",
				"bom_version": 2,
				"effective_from": tomorrow,
				"status": "Scheduled",
			},
		)
		copied = call(api.copy, source="SAC", type_code="SAC2", set_type_name="Copy")
		self.assertEqual((copied["ok"], copied["set_type"], copied["bom_version"]), (True, "SAC2", 1))

	def test_rpc_roles_before_any_write(self):
		lines = [{"instrument": "SA-1", "qty": 1}]
		keys, audit_rows = frappe.db.count("Idempotency Key"), frappe.db.count("Audit Log")
		for fn, kwargs in (
			(api.create, {"header": header("SAR"), "lines": lines}),
			(
				api.save_bom,
				{
					"set_type": "SAR",
					"lines": lines,
					"effective_from": nowdate(),
					"reason": "x",
					"base_version": 1,
				},
			),
			(api.copy, {"source": "SAR", "type_code": "SAR2", "set_type_name": "x"}),
		):
			with self.assertRaises(frappe.PermissionError, msg=fn.__name__):
				as_user(["TC R04"], fn, **kwargs)
		self.assertEqual(
			(frappe.db.count("Idempotency Key"), frappe.db.count("Audit Log")), (keys, audit_rows)
		)
		self.assertFalse(frappe.db.exists(SET_TYPE, "SAR"))
		self.assertEqual(api.ADMIN_ROLES, ("TC R02", "TC R10", "System Manager"))

	def test_save_bom_and_copy_check_document_permission(self):
		# review cuối Minor 2: ngoài role, kiểm quyền mức bản ghi (User Permission giới hạn loại bộ được truy cập)
		lines = [{"instrument": "SA-1", "qty": 1}]
		for code in ("SAUA", "SAUB"):
			call(api.create, header=header(code), lines=lines)
		email = make_user("st-admin-userperm@example.com", ["TC R02"])
		frappe.get_doc(
			{"doctype": "User Permission", "user": email, "allow": SET_TYPE, "for_value": "SAUA"}
		).insert(ignore_permissions=True)
		frappe.clear_cache(user=email)
		changed = [{"instrument": "SA-2", "qty": 1}]
		frappe.set_user(email)
		try:
			for fn, kwargs in (
				(
					api.save_bom,
					{
						"set_type": "SAUB",
						"lines": changed,
						"effective_from": nowdate(),
						"reason": "x",
						"base_version": 1,
					},
				),
				(api.copy, {"source": "SAUB", "type_code": "SAUC", "set_type_name": "x"}),
			):
				with self.assertRaises(frappe.PermissionError, msg=fn.__name__):
					call(fn, **kwargs)
			allowed = call(
				api.save_bom,
				set_type="SAUA",
				lines=changed,
				effective_from=nowdate(),
				reason="x",
				base_version=1,
			)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual((allowed["ok"], allowed["bom_version"]), (True, 2))
		self.assertEqual(frappe.db.get_value(SET_TYPE, "SAUB", "current_bom_version"), 1)
		self.assertFalse(frappe.db.count("Set BOM Item", {"set_type": "SAUB", "bom_version": 2}))
		self.assertFalse(frappe.db.exists(SET_TYPE, "SAUC"))

	def test_rpc_reject_bodies_and_http_status(self):
		bad = call(
			api.create,
			header=header("SAX"),
			lines=[{"instrument": "SA-1", "qty": 1}, {"instrument": "SA-PL", "qty": 1}],
		)
		self.assertEqual((bad["ok"], bad["error"]["code"], http_status()), (False, "BOM_LINE_INVALID", 422))
		self.assertEqual([(i["row"], i["code"]) for i in bad["error"]["items"]], [(2, "INCOMPATIBLE")])
		self.assertTrue(bad["error"]["title"] and bad["error"]["reason"] and bad["error"]["action"])
		self.assertFalse(frappe.db.exists(SET_TYPE, "SAX"))
		self.assertEqual(len(rejects("SAX", "BOM_LINE_INVALID")), 1)

		empty = call(api.create, header=header("SAE"), lines=[])
		self.assertEqual((empty["error"]["code"], http_status()), ("BOM_EMPTY", 422))

		call(api.create, header=header("SAV"), lines=[{"instrument": "SA-1", "qty": 1}])
		args = {"set_type": "SAV", "effective_from": nowdate(), "reason": "Edit", "base_version": 1}
		first = call(api.save_bom, lines=[{"instrument": "SA-2", "qty": 1}], **args)
		self.assertEqual(first["bom_version"], 2)
		conflict = call(api.save_bom, lines=[{"instrument": "SA-3", "qty": 1}], **args)
		self.assertEqual((conflict["error"]["code"], http_status()), ("BOM_VERSION_CONFLICT", 409))
		self.assertEqual(conflict["error"]["items"], [{"latest": 2}])
		self.assertEqual(len(rejects("SAV", "BOM_VERSION_CONFLICT")), 1)

		missing = call(
			api.save_bom,
			set_type="NOPE97",
			lines=[{"instrument": "SA-2", "qty": 1}],
			**{k: v for k, v in args.items() if k != "set_type"},
		)
		self.assertEqual((missing["error"]["code"], http_status()), ("SET_TYPE_NOT_FOUND", 404))
		exists = call(api.copy, source="SAV", type_code="SAV", set_type_name="Dup")
		self.assertEqual((exists["error"]["code"], http_status()), ("SET_TYPE_CODE_EXISTS", 409))

	def test_rpc_bad_arguments_are_400(self):
		for kwargs in (
			{"header": "{not json", "lines": []},
			{"header": "[]", "lines": []},
			{"header": header("SAB"), "lines": "{}"},
			{"header": header("SAB"), "lines": ["SA-1"]},
			{"header": {**header("SAB"), "current_bom_version": 3}, "lines": []},
		):
			with self.assertRaises(BadRequestError, msg=kwargs):
				call(api.create, **kwargs)
		for base in ("x", -1, 1.5, None):
			with self.assertRaises(BadRequestError, msg=base):
				call(
					api.save_bom,
					set_type="SAB",
					lines=[{"instrument": "SA-1", "qty": 1}],
					effective_from=nowdate(),
					reason="x",
					base_version=base,
				)
		with self.assertRaises(BadRequestError):
			call(api.copy, source=["SAB"], type_code="X1", set_type_name="x")
		self.assertEqual(BadRequestError.http_status_code, 400)

	def test_rpc_replay_same_key_same_response(self):
		call(api.create, header=header("SAP"), lines=[{"instrument": "SA-1", "qty": 1}])
		key = str(uuid.uuid4())
		args = {
			"set_type": "SAP",
			"lines": [{"instrument": "SA-2", "qty": 1}],
			"effective_from": nowdate(),
			"reason": "Replay",
			"base_version": 1,
			"client_ts": now_ts(),
		}
		first = call(api.save_bom, key=key, **args)
		again = call(api.save_bom, key=key, **args)
		self.assertEqual(again, first)
		self.assertEqual(frappe.db.count("Set BOM Item", {"set_type": "SAP", "bom_version": 3}), 0)

		# từ chối cũng được phát lại với cùng mã HTTP
		conflict_key = str(uuid.uuid4())
		bad = call(api.save_bom, key=conflict_key, **{**args, "reason": "Late"})
		self.assertEqual(http_status(), 409)
		replay = call(api.save_bom, key=conflict_key, **{**args, "reason": "Late"})
		self.assertEqual((replay, http_status()), (bad, 409))
		self.assertEqual(len(rejects("SAP", "BOM_VERSION_CONFLICT")), 1)

	def test_http_status_new_codes(self):
		expected = {
			"SET_TYPE_NOT_FOUND": 404,
			"BOM_VERSION_NOT_FOUND": 404,
			"BOM_EMPTY": 422,
			"BOM_LINE_INVALID": 422,
			"BOM_TOO_LARGE": 422,
			"BOM_EFFECTIVE_DATE_INVALID": 422,
			"SHELF_LIFE_INVALID": 422,
			"BOM_VERSION_CONFLICT": 409,
			"SET_TYPE_CODE_EXISTS": 409,
		}
		self.assertEqual({code: HTTP_STATUS.get(code) for code in expected}, expected)

	def test_set_pack_shelf_life_rpc_roles(self):
		pack = make_pack_type("Giấy crepe", 30)
		ok = as_user(["TC R02"], api.set_pack_shelf_life, item=pack, days="25", reason="R02 edit")
		self.assertEqual(
			ok,
			{"ok": True, "item": pack, "old_days": 30, "new_days": 25, "affected_set_types": []},
		)
		ok = as_user(["TC R10"], api.set_pack_shelf_life, item=pack, days=28, reason="R10 edit")
		self.assertEqual((ok["old_days"], ok["new_days"]), (25, 28))

		keys, audit_rows = frappe.db.count("Idempotency Key"), frappe.db.count("Audit Log")
		with self.assertRaises(frappe.PermissionError):
			as_user(["TC R04"], api.set_pack_shelf_life, item=pack, days=10, reason="No")
		self.assertEqual(
			(frappe.db.count("Idempotency Key"), frappe.db.count("Audit Log")), (keys, audit_rows)
		)
		self.assertEqual(frappe.db.get_value("Item", pack, "tc_shelf_life_days"), 28)

		# gửi lại cùng khóa → cùng response, không ghi lần hai
		key = str(uuid.uuid4())
		args = {"item": pack, "days": 21, "reason": "Replay", "client_ts": now_ts()}
		first = call(api.set_pack_shelf_life, key=key, **args)
		again = call(api.set_pack_shelf_life, key=key, **args)
		self.assertEqual(again, first)
		updates = {"ref_doctype": "Item", "ref_name": pack, "action": "Update"}
		self.assertEqual(frappe.db.count("Audit Log", updates), 3)

	def test_set_pack_shelf_life_rpc_rejections(self):
		pack = make_pack_type("Giấy crepe", 30)
		for kwargs, code in (
			({"item": pack, "days": 0, "reason": "x"}, "SHELF_LIFE_INVALID"),
			({"item": "VT-GOI-NOPE", "days": 10, "reason": "x"}, "PACK_TYPE_INVALID"),
			({"item": pack, "days": 10, "reason": " "}, "REASON_REQUIRED"),
		):
			result = call(api.set_pack_shelf_life, **kwargs)
			self.assertEqual((result["ok"], result["error"]["code"], http_status()), (False, code, 422))
			self.assertTrue(
				result["error"]["title"] and result["error"]["reason"] and result["error"]["action"]
			)
			rejected = {"ref_doctype": "Item", "ref_name": kwargs["item"], "action": "Reject", "reason": code}
			self.assertEqual(frappe.db.count("Audit Log", rejected), 1, msg=code)
		self.assertEqual(frappe.db.get_value("Item", pack, "tc_shelf_life_days"), 30)
		for kwargs in ({"item": [pack], "days": 10, "reason": "x"}, {"item": pack, "days": 10, "reason": 5}):
			with self.assertRaises(BadRequestError, msg=kwargs):
				call(api.set_pack_shelf_life, **kwargs)

	def test_http_status_shelf_life_invalid(self):
		codes = ("SHELF_LIFE_INVALID", "PACK_TYPE_INVALID", "REASON_REQUIRED")
		self.assertEqual({code: HTTP_STATUS.get(code) for code in codes}, dict.fromkeys(codes, 422))
