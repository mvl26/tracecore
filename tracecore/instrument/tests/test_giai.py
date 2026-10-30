"""Mã GIAI khắc laser cho dụng cụ, bật/tắt trong TraceCore Settings (FEAT-014 Task 5).

FR-M1-02 (.1 tùy chọn + duy nhất, .3 bật/tắt không gián đoạn T1→T7), BRU-ID-001 (không cấp lại), A-06 I7/I8/I13/I15,
Review Focus 5: tắt cờ giữ nguyên mã, không cấp mới; quét mã dụng cụ ở T4 → SCAN_INVALID; tiền tố demo chỉ dev/test.
"""

import base64
import uuid
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.core import code_registry, gs1
from tracecore.core.errors import HTTP_STATUS
from tracecore.instrument import catalog
from tracecore.tests.factories import (
	deactivate_printers,
	make_bom,
	make_instrument,
	make_set_type,
	make_t4_ready_set,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import instrument as instrument_api
from tracecore.v1 import instrument_admin as admin_api
from tracecore.v1 import pack as pack_api
from tracecore.v1.tests.station_fixtures import make_station_session

# Instrument liên kết Item/User, Set Unit/Pack liên kết Department, Batch, Employee; CI chưa có Setup Wizard
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

SETTINGS = "TraceCore Settings"
T4_STATION = "TR-004"
PRODUCTION = {"developer_mode": 0, "allow_tests": 0}


def now_ts():
	return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(timespec="seconds")


def call(fn, key=None, station_header=None, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	if fn not in (instrument_api.giai_preview, instrument_api.form_context):
		kwargs.setdefault("client_ts", now_ts())
	headers = {"X-Idempotency-Key": key or str(uuid.uuid4())}
	if station_header:
		headers["X-TC-Station"] = station_header
	if fn.__module__ == pack_api.__name__ and "token" not in kwargs:
		# RPC trạm đóng gói cần phiên đăng nhập thẻ thật (FEAT-003)
		kwargs["token"] = make_station_session(frappe.session.user, kwargs.get("station") or "TR-004")[
			"token"
		]
	with request_headers(headers):
		return fn(**kwargs)


def http_status():
	return frappe.local.response.get("http_status_code")


def as_user(roles, fn, **kwargs):
	email = make_user(
		f"giai-{'-'.join(r.lower().replace(' ', '') for r in roles) or 'none'}@example.com", roles
	)
	frappe.set_user(email)
	try:
		return call(fn, **kwargs)
	finally:
		frappe.set_user("Administrator")


def set_flag(on):
	doc = frappe.get_single(SETTINGS)
	doc.enable_instrument_giai = 1 if on else 0
	doc.save()


def assign(instrument, roles=("TC R10",)):
	return as_user(list(roles), admin_api.assign_giai, instrument=instrument)


def giai_fields(instrument):
	return frappe.db.get_value(
		"Instrument", instrument, ["giai_code", "giai_etched_on", "giai_position"], as_dict=True
	)


def registry(code):
	return frappe.db.get_value(
		"Code Registry", code, ["prefix", "ref_doctype", "ref_name", "status"], as_dict=True
	)


def rejects(reason):
	return frappe.db.count("Audit Log", {"action": "Reject", "reason": reason})


class GiaiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.local.response.pop("http_status_code", None)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)

	def assertRejected(self, result, code, status):
		self.assertIs(result["ok"], False, msg=result)
		self.assertEqual(result["error"]["code"], code)
		self.assertEqual(result["error"]["http_status"], status)
		self.assertEqual(http_status(), status)
		for key in ("title", "reason", "action"):
			self.assertTrue(result["error"][key], msg=key)


class TestAssignGiai(GiaiCase):
	@bru("BRU-ID-001")
	def test_assign_giai_unique_registered_never_reissued(self):
		set_flag(True)
		for code in ("GI-A", "GI-B", "GI-C"):
			make_instrument(code)
		prefix = gs1.configured_company_prefix()

		first, second = assign("GI-A"), assign("GI-B")
		self.assertTrue(first["ok"] and second["ok"])
		self.assertNotEqual(first["giai"], second["giai"])
		for instrument, result in (("GI-A", first), ("GI-B", second)):
			self.assertRegex(result["giai"], rf"^{prefix}I-\d{{8}}$")
			self.assertEqual(result["hri"], f"(8004){result['giai']}")
			self.assertEqual(frappe.db.get_value("Instrument", instrument, "giai_code"), result["giai"])
			self.assertEqual(
				registry(result["giai"]),
				{"prefix": "GI", "ref_doctype": "Instrument", "ref_name": instrument, "status": "Active"},
			)
			self.assertEqual(gs1.parse_scan(result["giai"])["type"], "instrument")
		self.assertEqual(gs1.make_instrument_giai(prefix, 1), f"{prefix}I-00000001")

		# số kế tiếp đã có trong sổ và đã Disabled → không bao giờ cấp lại
		serial = int(second["giai"][-8:])
		disabled = gs1.make_instrument_giai(prefix, serial + 1)
		code_registry.register(disabled, "GI", "Instrument", make_instrument("GI-OLD").name)
		code_registry.disable(disabled, "test")
		third = assign("GI-C")
		self.assertEqual(third["giai"], gs1.make_instrument_giai(prefix, serial + 2))

		# gọi lần 2 → GIAI_ALREADY_ASSIGNED, không ghi sổ thêm
		count = frappe.db.count("Code Registry", {"prefix": "GI"})
		again = assign("GI-B")
		self.assertRejected(again, "GIAI_ALREADY_ASSIGNED", 409)
		self.assertEqual(frappe.db.count("Code Registry", {"prefix": "GI"}), count)
		self.assertEqual(frappe.db.get_value("Instrument", "GI-B", "giai_code"), second["giai"])

		# Audit Log Update ghi mã mới
		updates = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Instrument", "ref_name": "GI-A", "action": "Update"},
			pluck="new_value",
		)
		self.assertTrue(any(first["giai"] in (value or "") for value in updates))

	def test_assign_replay_returns_same_code(self):
		set_flag(True)
		make_instrument("GI-RP")
		key = str(uuid.uuid4())
		email = make_user("giai-replay@example.com", ["TC R10"])
		frappe.set_user(email)
		# cùng client_ts: lần gửi lại giống hệt (gọi now_ts() hai lần có thể lệch sang giây kế tiếp → khác request)
		ts = now_ts()
		try:
			first = call(admin_api.assign_giai, key=key, instrument="GI-RP", client_ts=ts)
			replay = call(admin_api.assign_giai, key=key, instrument="GI-RP", client_ts=ts)
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(first["ok"])
		self.assertEqual(replay, first)
		self.assertEqual(frappe.db.count("Code Registry", {"ref_name": "GI-RP", "prefix": "GI"}), 1)

	def test_assign_roles_and_unknown_instrument(self):
		set_flag(True)
		make_instrument("GI-ROLE")
		audit_rows = frappe.db.count("Audit Log", {"ref_doctype": ["!=", "User"]})
		for roles in (["TC R02"], ["TC R01"], ["TC R04"]):
			with self.assertRaises(frappe.PermissionError, msg=roles):
				assign("GI-ROLE", roles)
		self.assertEqual(frappe.db.count("Audit Log", {"ref_doctype": ["!=", "User"]}), audit_rows)
		self.assertTrue(assign("GI-ROLE", ["System Manager"])["ok"])
		self.assertRejected(assign("GI-NONE"), "INSTRUMENT_NOT_FOUND", 404)
		with self.assertRaises(frappe.ValidationError):
			assign(["GI-ROLE"])

	def test_assign_rejected_for_retired_instrument(self):
		set_flag(True)
		make_instrument("GI-RET")
		catalog.retire("GI-RET", "Hỏng", confirm=True)
		self.assertRejected(assign("GI-RET"), "INSTRUMENT_RETIRED", 409)
		self.assertFalse(frappe.db.get_value("Instrument", "GI-RET", "giai_code"))

	def test_assign_rejected_when_feature_off(self):
		make_instrument("GI-OFF")
		self.assertFalse(catalog.giai_enabled())
		before_registry, before_rejects = frappe.db.count("Code Registry"), rejects("FEATURE_DISABLED")
		result = assign("GI-OFF")
		self.assertRejected(result, "FEATURE_DISABLED", 409)
		self.assertEqual(rejects("FEATURE_DISABLED"), before_rejects + 1)
		row = frappe.get_all(
			"Audit Log",
			filters={"action": "Reject", "reason": "FEATURE_DISABLED"},
			fields=["ref_doctype", "ref_name"],
			order_by="name desc",
			limit=1,
		)[0]
		self.assertEqual((row.ref_doctype, row.ref_name), ("Instrument", "GI-OFF"))
		self.assertEqual(frappe.db.count("Code Registry"), before_registry)
		self.assertFalse(frappe.db.get_value("Instrument", "GI-OFF", "giai_code"))
		# dịch vụ cũng chặn khi gọi thẳng
		from tracecore.core.errors import BlockedError

		with self.assertRaises(BlockedError):
			catalog.assign_giai("GI-OFF")

	def test_legacy_instrument_without_clinical_data_gets_code(self):
		# dụng cụ cũ thiếu Spaulding/phương pháp vẫn được cấp mã (chỉ đổi trường GIAI)
		set_flag(True)
		make_instrument("GI-LEG")
		frappe.db.set_value("Instrument", "GI-LEG", "spaulding_class", None, update_modified=False)
		frappe.db.delete("Instrument Compatible Method", {"parent": "GI-LEG"})
		result = assign("GI-LEG")
		self.assertTrue(result["ok"], msg=result)


class TestGiaiFields(GiaiCase):
	def test_giai_field_optional_and_immutable(self):
		meta = frappe.get_meta("Instrument")
		field = meta.get_field("giai_code")
		self.assertEqual((field.fieldtype, field.unique, field.read_only, field.no_copy), ("Data", 1, 1, 1))
		self.assertEqual(meta.get_field("giai_etched_on").fieldtype, "Date")
		self.assertEqual(meta.get_field("giai_position").length, 140)

		# không có mã vẫn lưu (hai dụng cụ không mã không vi phạm unique)
		make_instrument("GI-OPT1")
		make_instrument("GI-OPT2")
		doc = frappe.get_doc("Instrument", "GI-OPT1")
		doc.manufacturer = "Aesculap"
		doc.save()

		# sửa tay giai_code (kể cả System Manager trên form) → lỗi
		doc.reload()
		doc.giai_code = gs1.make_instrument_giai(gs1.configured_company_prefix(), 99999990)
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Instrument",
					"instrument_code": "GI-OPT3",
					"instrument_name": "Kéo",
					"spaulding_class": "Critical",
					"compatible_methods": [{"method": "Steam 134"}],
					"giai_code": "9520000I-99999991",
				}
			).insert()

		set_flag(True)
		code = assign("GI-OPT2")["giai"]
		for field, value in (
			("giai_code", "9520000I-99999992"),
			("giai_code", None),
			("giai_etched_on", today()),
			("giai_position", "Cán"),
		):
			doc = frappe.get_doc("Instrument", "GI-OPT2")
			doc.set(field, value)
			with self.assertRaises(frappe.ValidationError, msg=field):
				doc.save()
		# mã đã có không đổi được, kể cả qua cờ dịch vụ
		doc = frappe.get_doc("Instrument", "GI-OPT2")
		doc.giai_code = "9520000I-99999993"
		doc.flags.tc_giai = True
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertEqual(frappe.db.get_value("Instrument", "GI-OPT2", "giai_code"), code)

	def test_toggle_off_keeps_existing_codes(self):
		set_flag(True)
		make_instrument("GI-TG")
		make_instrument("GI-TG2")
		code = assign("GI-TG")["giai"]
		etched = as_user(
			["TC R10"],
			admin_api.record_etching,
			instrument="GI-TG",
			etched_on=today(),
			position="Cán, mặt trong",
		)
		self.assertTrue(etched["ok"], msg=etched)
		kept = giai_fields("GI-TG")

		set_flag(False)
		self.assertFalse(catalog.giai_enabled())
		self.assertEqual(giai_fields("GI-TG"), kept)
		# vẫn lưu được dụng cụ có mã cũ khi cờ tắt
		doc = frappe.get_doc("Instrument", "GI-TG")
		doc.model = "BC-100"
		doc.save()
		self.assertEqual(giai_fields("GI-TG"), kept)
		self.assertEqual(registry(code)["status"], "Active")
		# không cấp mới được
		self.assertRejected(assign("GI-TG2"), "FEATURE_DISABLED", 409)
		self.assertRejected(
			as_user(
				["TC R10"], admin_api.record_etching, instrument="GI-TG", etched_on=today(), position="X"
			),
			"FEATURE_DISABLED",
			409,
		)
		# xem trước vẫn đọc được mã đã cấp
		self.assertTrue(call(instrument_api.giai_preview, instrument="GI-TG")["ok"])

		set_flag(True)
		self.assertEqual(giai_fields("GI-TG"), kept)
		self.assertRejected(assign("GI-TG"), "GIAI_ALREADY_ASSIGNED", 409)
		self.assertEqual(frappe.db.count("Code Registry", {"ref_name": "GI-TG", "prefix": "GI"}), 1)

	def test_giai_enabled_reads_fresh_each_call(self):
		# không dựa vào frappe.db.value_cache: giá trị đổi thẳng ở DB (process khác) thấy ngay ở lần gọi kế tiếp
		set_flag(False)
		self.assertFalse(catalog.giai_enabled())
		frappe.db.sql(
			"update `tabSingles` set value = 1 where doctype = %s and field = 'enable_instrument_giai'",
			SETTINGS,
		)
		self.assertTrue(catalog.giai_enabled())

	def test_form_onload_reports_flag(self):
		make_instrument("GI-ONL")
		doc = frappe.get_doc("Instrument", "GI-ONL")
		doc.run_method("onload")
		self.assertIs(doc.get_onload().get("giai_enabled"), False)
		set_flag(True)
		doc = frappe.get_doc("Instrument", "GI-ONL")
		doc.run_method("onload")
		self.assertIs(doc.get_onload().get("giai_enabled"), True)


class TestMainFlow(GiaiCase):
	def setUp(self):
		super().setUp()
		deactivate_printers(T4_STATION)

	def test_main_flow_unaffected_by_flag(self):
		ready = make_t4_ready_set()
		results = []
		for on in (False, True, False):
			set_flag(on)
			result = call(pack_api.scan, station_header=T4_STATION, station=T4_STATION, raw=ready.set_id)
			self.assertTrue(result["ok"], msg=result)
			self.assertEqual(result["kind"], "context")
			self.assertIsNone(http_status())
			results.append(result)
		self.assertEqual(results[0], results[1])
		self.assertEqual(results[1], results[2])

		set_flag(True)
		code = assign(ready.instruments[0])["giai"]
		for raw in (code, "]d2\x1d8004" + code, "(8004)" + code):
			for open_set in (None, ready.set_id):
				result = call(
					pack_api.scan, station_header=T4_STATION, station=T4_STATION, raw=raw, open_set=open_set
				)
				self.assertRejected(result, "SCAN_INVALID", 422)
		# sau khi có mã dụng cụ, quét Set ID vẫn như cũ
		after = call(pack_api.scan, station_header=T4_STATION, station=T4_STATION, raw=ready.set_id)
		self.assertEqual(after["kind"], "context")
		self.assertEqual(after["context"]["set"], results[0]["context"]["set"])


class TestPrefixGuard(GiaiCase):
	def test_demo_prefix_blocked_outside_dev_or_test(self):
		set_flag(True)
		make_instrument("GI-DEMO")
		make_instrument("GI-DEMO2")
		demo_code = assign("GI-DEMO2")["giai"]  # cấp trên site test (cho phép)
		self.assertTrue(gs1.is_demo_prefix(demo_code))
		before = frappe.db.count("Code Registry")
		with patch.dict(frappe.conf, {**PRODUCTION, "tc_gs1_company_prefix": "9520000"}):
			with patch.dict(frappe.flags, {"in_test": False}):
				result = assign("GI-DEMO")
				preview = call(instrument_api.giai_preview, instrument="GI-DEMO2")
		self.assertRejected(result, "GS1_PREFIX_NOT_CONFIGURED", 409)
		self.assertEqual(frappe.db.count("Code Registry"), before)
		self.assertFalse(frappe.db.get_value("Instrument", "GI-DEMO", "giai_code"))
		# mã demo cấp trên dev/test không được đưa ra khắc, cũng không được ghi nhận đã khắc trên site thật
		self.assertRejected(preview, "GS1_PREFIX_NOT_CONFIGURED", 409)
		with patch.dict(frappe.conf, {**PRODUCTION, "tc_gs1_company_prefix": "8930001"}):
			with patch.dict(frappe.flags, {"in_test": False}):
				etched = as_user(
					["TC R10"],
					admin_api.record_etching,
					instrument="GI-DEMO2",
					etched_on=today(),
					position="Cán",
				)
		self.assertRejected(etched, "GS1_PREFIX_NOT_CONFIGURED", 409)
		self.assertIsNone(giai_fields("GI-DEMO2").giai_etched_on)
		# trở lại site test: ghi nhận được
		ok = as_user(
			["TC R10"], admin_api.record_etching, instrument="GI-DEMO2", etched_on=today(), position="Cán"
		)
		self.assertTrue(ok["ok"], msg=ok)


class TestRetireDisablesGiai(GiaiCase):
	@bru("BRU-ID-001")
	def test_retire_disables_giai_code(self):
		set_flag(True)
		make_instrument("GI-RT")
		set_type = make_set_type("GRT")
		make_bom(set_type, [("GI-RT", 1)])
		code = assign("GI-RT")["giai"]

		pending = catalog.retire("GI-RT", "Gãy mỏ")
		self.assertFalse(pending["retired"])
		self.assertEqual(registry(code)["status"], "Active")

		catalog.retire("GI-RT", "Gãy mỏ", confirm=True)
		row = frappe.db.get_value("Code Registry", code, ["status", "disabled_reason"], as_dict=True)
		self.assertEqual(row.status, "Disabled")
		self.assertIn("Gãy mỏ", row.disabled_reason)
		self.assertEqual(frappe.db.get_value("Instrument", "GI-RT", "giai_code"), code)
		with self.assertRaises(code_registry.CodeAlreadyIssuedError):
			code_registry.register(code, "GI", "Instrument", "OTHER")

		# dụng cụ cũ thiếu trường bắt buộc vẫn ngừng sử dụng được và mã bị vô hiệu (Task 4 fix giữ nguyên)
		make_instrument("GI-RT-LEG")
		legacy = assign("GI-RT-LEG")["giai"]
		frappe.db.set_value("Instrument", "GI-RT-LEG", "spaulding_class", None, update_modified=False)
		frappe.db.delete("Instrument Compatible Method", {"parent": "GI-RT-LEG"})
		self.assertTrue(catalog.retire("GI-RT-LEG", "Cũ", confirm=True)["retired"])
		self.assertEqual(registry(legacy)["status"], "Disabled")

		# dụng cụ không có mã: ngừng sử dụng như cũ
		make_instrument("GI-RT-NO")
		self.assertTrue(catalog.retire("GI-RT-NO", "Cũ", confirm=True)["retired"])


class TestRecordEtching(GiaiCase):
	def etch(self, instrument, etched_on, position, roles=("TC R10",), **kwargs):
		return as_user(
			list(roles),
			admin_api.record_etching,
			instrument=instrument,
			etched_on=etched_on,
			position=position,
			**kwargs,
		)

	def test_record_etching_rules(self):
		set_flag(True)
		make_instrument("GI-ET")
		# cần mã
		self.assertRejected(self.etch("GI-ET", today(), "Cán"), "GIAI_NOT_ASSIGNED", 409)
		assign("GI-ET")
		with self.assertRaises(frappe.PermissionError):
			self.etch("GI-ET", today(), "Cán", roles=("TC R02",))
		# ngày tương lai, ngày sai định dạng, vị trí trống hoặc > 140 → lỗi
		for etched_on, position in (
			(add_days(today(), 1), "Cán"),
			("21/10/2026", "Cán"),
			("2026-02-30", "Cán"),
			("", "Cán"),
			(today(), ""),
			(today(), "   "),
			(today(), "x" * 141),
		):
			result = self.etch("GI-ET", etched_on, position)
			self.assertRejected(result, "ETCHING_INVALID", 422)
		self.assertIsNone(giai_fields("GI-ET").giai_etched_on)
		with self.assertRaises(frappe.ValidationError):
			self.etch("GI-ET", today(), ["Cán"])
		self.assertRejected(self.etch("GI-NONE", today(), "Cán"), "INSTRUMENT_NOT_FOUND", 404)

		day = add_days(today(), -2)
		result = self.etch("GI-ET", day, " " + "y" * 140 + " ")
		self.assertTrue(result["ok"], msg=result)
		fields = giai_fields("GI-ET")
		self.assertEqual((getdate(fields.giai_etched_on), fields.giai_position), (getdate(day), "y" * 140))
		self.assertEqual(result["instrument"]["giai_etched_on"], str(getdate(day)))

		# ghi một lần: sửa lại cần lý do, có Audit Log
		self.assertRejected(self.etch("GI-ET", today(), "Mặt trong"), "REASON_REQUIRED", 422)
		self.assertEqual(giai_fields("GI-ET").giai_position, "y" * 140)
		fixed = self.etch("GI-ET", today(), "Mặt trong", reason="Ghi nhầm vị trí")
		self.assertTrue(fixed["ok"], msg=fixed)
		self.assertEqual(giai_fields("GI-ET").giai_position, "Mặt trong")
		row = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Instrument", "ref_name": "GI-ET", "action": "Update"},
			fields=["reason", "old_value", "new_value"],
			order_by="name desc",
			limit=1,
		)[0]
		self.assertEqual(row.reason, "Ghi nhầm vị trí")
		self.assertEqual(frappe.parse_json(row.new_value)["giai_position"], "Mặt trong")
		# dịch vụ nhận cả datetime.date; kiểu khác → ETCHING_INVALID
		from tracecore.core.errors import BlockedError

		catalog.record_etching("GI-ET", getdate(day), "Mặt ngoài", reason="Sửa lần hai")
		self.assertEqual(getdate(giai_fields("GI-ET").giai_etched_on), getdate(day))
		with self.assertRaises(BlockedError) as raised:
			catalog.record_etching("GI-ET", 20261021, "Cán", reason="x")
		self.assertEqual(raised.exception.block.code, "ETCHING_INVALID")

	def test_record_etching_rejected_for_retired(self):
		set_flag(True)
		make_instrument("GI-ETR")
		assign("GI-ETR")
		catalog.retire("GI-ETR", "Hỏng", confirm=True)
		self.assertRejected(self.etch("GI-ETR", today(), "Cán"), "INSTRUMENT_RETIRED", 409)


class TestGiaiPreview(GiaiCase):
	def test_giai_preview_decodes_to_payload(self):
		set_flag(True)
		make_instrument("GI-PV")
		code = assign("GI-PV")["giai"]
		result = as_user(["TC R10"], instrument_api.giai_preview, instrument="GI-PV")
		self.assertTrue(result["ok"], msg=result)
		self.assertEqual(result["giai"], code)
		self.assertEqual(result["payload"], gs1.giai_payload(code))
		self.assertEqual(result["hri"], gs1.giai_hri(code))
		png = base64.b64decode(result["png_b64"])
		self.assertEqual(gs1.decode_datamatrix_png(png), result["payload"])

	def test_giai_preview_roles_and_flag_off(self):
		# Quyết định (final fix wave, Minor 5): xem trước DataMatrix chỉ TC R10/System Manager (như nút trên form),
		# kể cả khi cờ tắt: mã đã cấp vẫn xem được để đối chiếu; cờ tắt chỉ chặn cấp mới/ghi khắc (FEATURE_DISABLED).
		set_flag(True)
		make_instrument("GI-PVROLE")
		code = assign("GI-PVROLE")["giai"]
		before = frappe.db.count("Audit Log", {"action": "Reject"})
		for roles in (["TC R02"], ["TC R04"], ["TC R01"]):
			with self.subTest(roles=roles), self.assertRaises(frappe.PermissionError):
				as_user(roles, instrument_api.giai_preview, instrument="GI-PVROLE")
		# thiếu role: từ chối trước mọi ghi, kể cả với dụng cụ không có
		with self.assertRaises(frappe.PermissionError):
			as_user(["TC R02"], instrument_api.giai_preview, instrument="GI-PV-NONE")
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Reject"}), before)
		set_flag(False)
		off = as_user(["TC R10"], instrument_api.giai_preview, instrument="GI-PVROLE")
		self.assertTrue(off["ok"], msg=off)
		self.assertEqual(off["giai"], code)
		# form_context: nút xem trước theo cùng quy tắc
		context = as_user(["TC R10"], instrument_api.form_context, instrument="GI-PVROLE")
		self.assertTrue(context["permissions"]["can_preview_giai"])
		self.assertFalse(context["permissions"]["can_record_etching"])
		context = as_user(["TC R02"], instrument_api.form_context, instrument="GI-PVROLE")
		self.assertFalse(context["permissions"]["can_preview_giai"])

	def test_giai_preview_registry_row_missing_is_not_found(self):
		make_instrument("GI-PVREG")
		frappe.db.set_value("Instrument", "GI-PVREG", "giai_code", "9520000I-99999999")
		self.assertFalse(frappe.db.exists("Code Registry", "9520000I-99999999"))
		result = call(instrument_api.giai_preview, instrument="GI-PVREG")
		self.assertRejected(result, "CODE_NOT_FOUND", 404)
		self.assertIn("9520000I-99999999", result["error"]["reason"])

	def test_giai_preview_rejections_and_get_only(self):
		make_instrument("GI-PV0")
		self.assertRejected(call(instrument_api.giai_preview, instrument="GI-PV0"), "GIAI_NOT_ASSIGNED", 409)
		self.assertRejected(
			call(instrument_api.giai_preview, instrument="GI-NONE"), "INSTRUMENT_NOT_FOUND", 404
		)
		self.assertRejected(call(instrument_api.giai_preview, instrument=None), "INSTRUMENT_NOT_FOUND", 404)
		set_flag(True)
		make_instrument("GI-PVR")
		assign("GI-PVR")
		catalog.retire("GI-PVR", "Hỏng", confirm=True)
		self.assertRejected(call(instrument_api.giai_preview, instrument="GI-PVR"), "CODE_DISABLED", 409)
		with self.assertRaises(frappe.PermissionError):
			as_user([], instrument_api.giai_preview, instrument="GI-PVR")
		self.assertEqual(
			frappe.allowed_http_methods_for_whitelisted_func[instrument_api.giai_preview], ["GET"]
		)
		for fn in (admin_api.assign_giai, admin_api.record_etching):
			self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[fn], ["POST"])


class TestHttpStatus(IsolatedTestCase):
	def test_http_status_new_codes(self):
		for code, status in (
			("FEATURE_DISABLED", 409),
			("GIAI_ALREADY_ASSIGNED", 409),
			("GS1_PREFIX_NOT_CONFIGURED", 409),
			("GIAI_NOT_ASSIGNED", 409),
			("ETCHING_INVALID", 422),
		):
			self.assertEqual(HTTP_STATUS[code], status, msg=code)
