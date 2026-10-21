"""RPC tracecore.v1.instrument.get_image (FEAT-014 Task 3, FR-M1-01.6, A-06 I12): URL ảnh, thumbnail và etag."""

import inspect
import io
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from tracecore.instrument import catalog
from tracecore.tests.factories import (
	attach_instrument_file,
	make_bom,
	make_instrument,
	make_instrument_group,
	make_maintenance,
	make_set_type,
	make_set_unit,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import instrument as instrument_api

# Instrument liên kết Item (ERPNext) và User (owner): site CI chưa chạy Setup Wizard
test_ignore = ["Item", "User", "Batch", "Department", "Employee"]


def get_image(instrument):
	frappe.local.response.pop("http_status_code", None)
	with request_headers({}):
		return instrument_api.get_image(instrument=instrument)


def http_status():
	return frappe.local.response.get("http_status_code")


def _png(color=(20, 120, 20)):
	buffer = io.BytesIO()
	Image.new("RGB", (640, 480), color).save(buffer, format="PNG")
	return buffer.getvalue()


def _with_photo(code):
	make_instrument(code, name=f"Dụng cụ {code}")
	source = attach_instrument_file(code, "image", _png(), f"{code.lower()}.png")
	doc = frappe.get_doc("Instrument", code)
	doc.image = source.file_url
	doc.save()
	return doc


class TestInstrumentApi(FrappeTestCase):
	def test_get_image_returns_urls_and_etag(self):
		doc = _with_photo("API-IMG")
		result = get_image("API-IMG")
		thumb_hash = frappe.db.get_value(
			"File", {"file_url": doc.image_thumbnail, "attached_to_name": "API-IMG"}, "content_hash"
		)
		self.assertEqual(
			result,
			{
				"ok": True,
				"instrument": "API-IMG",
				"image_url": doc.image,
				"thumbnail_url": doc.image_thumbnail,
				"etag": thumb_hash,
				"has_image": True,
			},
		)
		self.assertTrue(result["etag"])
		self.assertIsNone(http_status())
		# R04 (trạm T4) đọc được
		frappe.set_user(make_user("api-img-r04@example.com", roles=("TC R04",)))
		try:
			self.assertTrue(get_image("API-IMG")["ok"])
		finally:
			frappe.set_user("Administrator")

	def test_get_image_without_photo(self):
		make_instrument("API-NOIMG")
		result = get_image("API-NOIMG")
		self.assertEqual(
			result,
			{
				"ok": True,
				"instrument": "API-NOIMG",
				"image_url": None,
				"thumbnail_url": None,
				"etag": None,
				"has_image": False,
			},
		)
		self.assertIsNone(http_status())

	def test_get_image_unknown_404_with_audit(self):
		result = get_image("API-NONE-404")
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INSTRUMENT_NOT_FOUND")
		self.assertIn("API-NONE-404", result["error"]["reason"])
		self.assertTrue(result["error"]["title"] and result["error"]["action"])
		self.assertEqual(http_status(), 404)
		log = frappe.get_all(
			"Audit Log",
			filters={"action": "Reject", "reason": "INSTRUMENT_NOT_FOUND", "ref_name": "API-NONE-404"},
			fields=["ref_doctype", "new_value"],
		)
		self.assertEqual(len(log), 1)
		self.assertEqual(log[0].ref_doctype, "Instrument")
		self.assertEqual(frappe.parse_json(log[0].new_value)["raw"], "API-NONE-404")
		# tham số không phải chuỗi: cũng 404, không 500
		self.assertEqual(get_image(None)["error"]["code"], "INSTRUMENT_NOT_FOUND")

	def test_get_image_requires_read_permission(self):
		make_instrument("API-PERM")
		before = frappe.db.count("Audit Log", {"action": "Reject"})
		frappe.set_user(make_user("api-img-nobody@example.com"))
		try:
			with self.assertRaises(frappe.PermissionError):
				get_image("API-PERM")
			with self.assertRaises(frappe.PermissionError):
				get_image("API-UNKNOWN")
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Reject"}), before)

	def test_get_image_is_get_only(self):
		self.assertEqual(frappe.get_attr("tracecore.v1.instrument.get_image"), instrument_api.get_image)
		self.assertIn(instrument_api.get_image, frappe.whitelisted)
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[instrument_api.get_image], ["GET"])
		# đọc thuần: không bọc @idempotent
		self.assertNotIn("core.idempotency", inspect.getsource(instrument_api))

	def test_get_rejection_audit_survives_request_end(self):
		# Frappe v15 app.sync_database: request GET (không thuộc UNSAFE_HTTP_METHODS) bị rollback khi kết thúc, trừ
		# khi frappe.local.flags.commit. Dòng Audit Log `Reject` của RPC GET phải được commit, không mất ở production.
		from frappe import app

		def end_of_request(fn, method="GET", **kwargs):
			frappe.local.response.pop("http_status_code", None)
			frappe.local.flags.pop("commit", None)
			previous = getattr(frappe.local, "request", None)
			frappe.local.request = SimpleNamespace(method=method, headers={})
			try:
				result = fn(**kwargs)
				with (
					patch.object(frappe.db, "commit") as commit,
					patch.object(frappe.db, "rollback") as rollback,
				):
					app.sync_database(True)
			finally:
				frappe.local.flags.pop("commit", None)
				if previous is None:
					del frappe.local.request
				else:
					frappe.local.request = previous
			return result, commit.called, rollback.called

		make_instrument("API-SYNC")
		for fn in (instrument_api.get_image, instrument_api.giai_preview, instrument_api.form_context):
			with self.subTest(fn=fn.__name__):
				result, committed, rolled_back = end_of_request(fn, instrument="API-SYNC-404")
				self.assertEqual(result["error"]["code"], "INSTRUMENT_NOT_FOUND")
				self.assertTrue(committed, msg="Reject row must be committed")
				self.assertFalse(rolled_back)
		# GET thành công không ghi gì: vẫn rollback như Frappe mặc định (không commit thừa)
		result, committed, rolled_back = end_of_request(instrument_api.get_image, instrument="API-SYNC")
		self.assertTrue(result["ok"])
		self.assertFalse(committed)
		self.assertTrue(rolled_back)
		# không có request (gọi từ console/job): không đụng tới cờ commit
		frappe.local.flags.pop("commit", None)
		get_image("API-SYNC-404")
		self.assertFalse(frappe.local.flags.get("commit"))


# --- SCR-01 Desk (FEAT-014 Task 6): check_code, form_context -------------------------------------------------

SETTINGS = "TraceCore Settings"


def check_code(code):
	frappe.local.response.pop("http_status_code", None)
	with request_headers({}):
		return instrument_api.check_code(code=code)


def form_context(instrument):
	frappe.local.response.pop("http_status_code", None)
	with request_headers({}):
		return instrument_api.form_context(instrument=instrument)


def as_user(email, roles, fn, *args):
	frappe.set_user(make_user(email, roles))
	try:
		return fn(*args)
	finally:
		frappe.set_user("Administrator")


def set_flag(on):
	doc = frappe.get_single(SETTINGS)
	doc.enable_instrument_giai = 1 if on else 0
	doc.save()


class TestInstrumentFormApi(IsolatedTestCase):
	def test_check_code_available_and_suggestion(self):
		make_instrument("CC-KC-013")
		make_instrument("CC-KC-014")
		taken = check_code("  cc-kc-013\t")
		self.assertEqual(
			taken,
			{"ok": True, "code": "CC-KC-013", "valid": True, "available": False, "suggestion": "CC-KC-015"},
		)
		# full-width (NFKC) và chữ thường: cùng mã
		self.assertEqual(check_code("\uff23\uff23-\uff2b\uff23-014")["suggestion"], "CC-KC-015")
		free = check_code("cc-kc-099")
		self.assertEqual(
			free, {"ok": True, "code": "CC-KC-099", "valid": True, "available": True, "suggestion": None}
		)
		# dụng cụ Ngừng sử dụng vẫn giữ mã
		make_instrument("CC-RET")
		catalog.retire("CC-RET", "Hỏng")
		self.assertFalse(check_code("CC-RET")["available"])
		self.assertEqual(check_code("CC-RET")["suggestion"], "CC-RET-01")

		# mã sai định dạng: không lỗi 500, không để lại thông báo của frappe.throw
		frappe.clear_messages()
		for bad in ("KC 01!", "", None, "A" * 41, ["KC-01"]):
			with self.subTest(bad=bad):
				result = check_code(bad)
				self.assertEqual(result["ok"], True)
				self.assertIs(result["valid"], False)
				self.assertIs(result["available"], False)
				self.assertIsNone(result["code"])
				self.assertIsNone(result["suggestion"])
				self.assertTrue(result["message"])
		self.assertFalse(frappe.get_message_log())

		# R04 đọc được; user không có quyền đọc Instrument → PermissionError
		self.assertTrue(as_user("cc-r04@example.com", ("TC R04",), check_code, "CC-KC-013")["ok"])
		with self.assertRaises(frappe.PermissionError):
			as_user("cc-nobody@example.com", (), check_code, "CC-KC-013")
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[instrument_api.check_code], ["GET"])

	def _bom_fixture(self):
		group = make_instrument_group("FC Kéo", interval=40, maint_type="Blade Check")
		make_instrument("FC-KEO", group=group, methods=("Steam 134",))
		set_type = make_set_type("FCS", set_type_name="Bộ FC")
		make_bom(set_type, [("FC-KEO", 1)])
		units = [make_set_unit(set_type.name).name for _i in range(4)]
		make_maintenance(units[0], "FC-KEO", cycles_since=45)  # 45 ≥ 40, ≤ 120 % → Đến hạn
		make_maintenance(units[1], "FC-KEO", cycles_since=49)  # > 120 % → Quá hạn
		make_maintenance(units[2], "FC-KEO", cycles_since=3, deferred_count=1)  # đã hoãn ở T4
		return set_type, units

	def test_form_context_shape_and_permissions(self):
		set_type, units = self._bom_fixture()
		doc = frappe.get_doc("Instrument", "FC-KEO")
		doc.compatible_methods = []
		doc.append("compatible_methods", {"method": "Plasma"})
		doc.save()

		result = form_context("FC-KEO")
		self.assertTrue(result["ok"])
		self.assertEqual(
			set(result),
			{
				"ok",
				"instrument",
				"status",
				"version_no",
				"giai_enabled",
				"giai",
				"effective_rule",
				"bom_usage",
				"history",
				"image",
				"counters",
				"permissions",
			},
		)
		self.assertEqual(result["instrument"], "FC-KEO")
		self.assertEqual(result["status"], "Active")
		self.assertEqual(result["version_no"], 2)
		self.assertEqual(
			result["effective_rule"], {"interval": 40, "maint_type": "Blade Check", "source": "Group"}
		)
		self.assertEqual([row["set_type"] for row in result["bom_usage"]], [set_type.name])
		self.assertEqual([row["version_no"] for row in result["history"]], [1, 2])
		self.assertEqual(result["history"][0]["methods"], ["Steam 134"])
		self.assertEqual(result["history"][1]["methods"], ["Plasma"])
		for row in result["history"]:
			self.assertEqual(
				set(row), {"version_no", "methods", "changed_on", "changed_by", "changed_by_name"}
			)
			self.assertIsInstance(row["changed_on"], str)
			self.assertRegex(row["changed_on"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
		self.assertEqual(
			set(result["image"]), {"instrument", "image_url", "thumbnail_url", "etag", "has_image"}
		)

		counters = {row["set_unit"]: row for row in result["counters"]}
		self.assertEqual(sorted(counters), sorted(units))
		self.assertEqual(
			set(counters[units[0]]),
			{"set_unit", "set_type", "cycles_since", "deferred_count", "state", "has_counter", "can_init"},
		)
		self.assertEqual(
			[(counters[u]["state"], counters[u]["cycles_since"], counters[u]["can_init"]) for u in units],
			[("due", 45, True), ("overdue", 49, True), ("not_due", 3, False), ("not_due", 0, True)],
		)
		self.assertFalse(counters[units[3]]["has_counter"])
		self.assertEqual(counters[units[2]]["deferred_count"], 1)

		admin = {
			"can_write": True,
			"can_retire": True,
			"can_init_counters": True,
			"can_assign_giai": False,
			"can_record_etching": False,
		}
		self.assertEqual(result["permissions"], admin)
		r02 = as_user("fc-r02@example.com", ("TC R02",), form_context, "FC-KEO")
		self.assertEqual(r02["permissions"], admin)
		# R04 (trạm) đọc được nhưng không có quyền ghi nào
		r04 = as_user("fc-r04@example.com", ("TC R04",), form_context, "FC-KEO")
		self.assertTrue(r04["ok"])
		self.assertEqual(r04["counters"], result["counters"])
		self.assertFalse(any(r04["permissions"].values()), msg=r04["permissions"])
		with self.assertRaises(frappe.PermissionError):
			as_user("fc-nobody@example.com", (), form_context, "FC-KEO")

		# không có ngưỡng hiệu lực → trạng thái "no_rule"
		make_instrument("FC-NORULE")
		make_bom(set_type, [("FC-NORULE", 1)], version=2)
		frappe.db.set_value("Instrument Set Type", set_type.name, "current_bom_version", 2)
		bare = form_context("FC-NORULE")
		self.assertIsNone(bare["effective_rule"])
		self.assertEqual({row["state"] for row in bare["counters"]}, {"no_rule"})
		# BOM hiện hành không còn FC-KEO: dòng bộ đếm cũ vẫn hiện nhưng không khởi tạo được, bộ chưa có dòng biến mất
		moved = {row["set_unit"]: row for row in form_context("FC-KEO")["counters"]}
		self.assertEqual(sorted(moved), sorted(units[:3]))
		self.assertFalse(any(row["can_init"] for row in moved.values()))
		self.assertEqual(moved[units[0]]["set_type"], set_type.name)

		# dụng cụ đã ngừng sử dụng: không ngừng được nữa
		catalog.retire("FC-NORULE", "Hỏng", confirm=1)
		self.assertFalse(form_context("FC-NORULE")["permissions"]["can_retire"])

		missing = form_context("FC-NONE-404")
		self.assertEqual(missing["error"]["code"], "INSTRUMENT_NOT_FOUND")
		self.assertEqual(frappe.local.response.get("http_status_code"), 404)
		self.assertEqual(
			frappe.allowed_http_methods_for_whitelisted_func[instrument_api.form_context], ["GET"]
		)

	def test_form_context_hides_giai_when_flag_off(self):
		make_instrument("FC-GIAI")
		set_flag(False)
		off = as_user("fc-giai-r10@example.com", ("TC R10",), form_context, "FC-GIAI")
		self.assertIs(off["giai_enabled"], False)
		self.assertIsNone(off["giai"])
		self.assertFalse(off["permissions"]["can_assign_giai"])

		set_flag(True)
		on = as_user("fc-giai-r10@example.com", ("TC R10",), form_context, "FC-GIAI")
		self.assertIs(on["giai_enabled"], True)
		self.assertIsNone(on["giai"])
		self.assertTrue(on["permissions"]["can_assign_giai"])
		self.assertFalse(on["permissions"]["can_record_etching"])
		# R02 không cấp mã GIAI (R10/SM)
		r02 = as_user("fc-giai-r02@example.com", ("TC R02",), form_context, "FC-GIAI")
		self.assertFalse(r02["permissions"]["can_assign_giai"])

		code = catalog.assign_giai("FC-GIAI")
		on = as_user("fc-giai-r10@example.com", ("TC R10",), form_context, "FC-GIAI")
		self.assertEqual(
			on["giai"],
			{
				"code": code,
				"hri": f"(8004){code}",
				"etched_on": None,
				"position": None,
				"read_only": False,
			},
		)
		self.assertFalse(on["permissions"]["can_assign_giai"])
		self.assertTrue(on["permissions"]["can_record_etching"])

		# cờ tắt mà đã có mã: hiện chỉ đọc, không nút ghi
		set_flag(False)
		off = as_user("fc-giai-r10@example.com", ("TC R10",), form_context, "FC-GIAI")
		self.assertIs(off["giai_enabled"], False)
		self.assertEqual(off["giai"]["code"], code)
		self.assertIs(off["giai"]["read_only"], True)
		self.assertFalse(off["permissions"]["can_assign_giai"])
		self.assertFalse(off["permissions"]["can_record_etching"])
