"""RPC tracecore.v1.set_type.* (FEAT-015 Task 6, S10, S11; FR-M1-03, FR-M1-04.3, F-17, AC-11).

``bom`` đọc BOM theo phiên bản cho trạm (cache Redis ``tc_bom:<set_type>:<version>`` TTL 600 s, ``etag``,
``if_none_match``), ``versions``, ``compare``, ``form_context``: GET, quyền đọc Instrument Set Type kiểm trước mọi ghi
Audit, không có → 404 qua ``reject_block`` (Audit ``Reject`` được commit cả với request GET).
"""

import io
import time
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, nowdate
from PIL import Image

from tracecore.core.errors import HTTP_STATUS
from tracecore.instrument import bom
from tracecore.instrument.tests.test_bom_compare import bulk_set_type, count_queries
from tracecore.tests.factories import (
	attach_instrument_file,
	attach_set_type_photo,
	make_bom,
	make_set_type,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import set_type as api
from tracecore.v1._common import BadRequestError

# Instrument Set Type liên kết Department, Item; Set BOM Item/Instrument liên kết Item; CI chưa có Setup Wizard
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

SET_TYPE = "Instrument Set Type"
RPCS = ("bom", "versions", "compare", "form_context")


def call(fn, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	with request_headers({}):
		return fn(**kwargs)


def http_status():
	return frappe.local.response.get("http_status_code")


def as_user(roles, fn, **kwargs):
	email = make_user(
		f"st-read-{'-'.join(r.lower().replace(' ', '') for r in roles) or 'none'}@example.com", roles
	)
	frappe.set_user(email)
	try:
		return call(fn, **kwargs)
	finally:
		frappe.set_user("Administrator")


def png(color=(20, 120, 20), size=(64, 48)):
	buffer = io.BytesIO()
	Image.new("RGB", size, color).save(buffer, format="PNG")
	return buffer.getvalue()


def cache_key(set_type, version):
	return f"tc_bom:{set_type}:{version}"


def cached(set_type, version):
	return frappe.cache.get_value(cache_key(set_type, version), expires=True)


class TestSetTypeBomRpc(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		make_set_type("STB", bom=[("STB-A", 2), ("STB-B", 1)], set_type_name="Bộ khám")
		self.tomorrow = add_days(getdate(nowdate()), 1)
		make_bom("STB", [("STB-B", 1), ("STB-A", 3), ("STB-C", 4)], version=2, effective_from=self.tomorrow)
		bom.invalidate(set_type="STB")

	def test_bom_rpc_effective_version_by_default(self):
		result = call(api.bom, set_type="STB")
		self.assertTrue(result["ok"])
		self.assertIsNone(http_status())
		self.assertEqual(
			(result["set_type"], result["bom_version"], result["status"]), ("STB", 1, "Effective")
		)
		self.assertEqual(result["set_type_name"], "Bộ khám")
		self.assertEqual(result["method"], "Steam")
		self.assertEqual(result["effective_from"], nowdate())
		self.assertEqual([line["instrument"] for line in result["lines"]], ["STB-A", "STB-B"])
		self.assertEqual(
			set(result),
			{
				"ok",
				"set_type",
				"set_type_name",
				"method",
				"bom_version",
				"effective_from",
				"status",
				"lines",
				"tray_images",
				"total_lines",
				"total_qty",
				"etag",
			},
		)
		self.assertEqual(
			set(result["lines"][0]),
			{"instrument", "instrument_name", "image", "thumbnail", "image_etag", "qty", "position"},
		)
		# mã loại bộ chữ thường / có khoảng trắng như khi gõ tay
		self.assertEqual(call(api.bom, set_type=" stb ")["bom_version"], 1)

	def test_bom_rpc_specific_version_and_totals(self):
		result = call(api.bom, set_type="STB", version="2")
		self.assertEqual((result["bom_version"], result["status"]), (2, "Scheduled"))
		self.assertEqual(result["effective_from"], str(self.tomorrow))
		self.assertEqual(
			[(line["instrument"], line["qty"], line["position"]) for line in result["lines"]],
			[("STB-B", 1, 1), ("STB-A", 3, 2), ("STB-C", 4, 3)],
		)
		self.assertEqual((result["total_lines"], result["total_qty"]), (3, 8))
		first = call(api.bom, set_type="STB", version=1)
		self.assertEqual((first["total_lines"], first["total_qty"]), (2, 3))
		# hai phiên bản khác nhau không dùng chung cache / etag
		self.assertNotEqual(first["etag"], result["etag"])
		self.assertEqual(cached("STB", 1)["bom_version"], 1)
		self.assertEqual(cached("STB", 2)["bom_version"], 2)
		# khóa cache theo site (frappe.cache thêm tiền tố db_name)
		self.assertTrue(
			frappe.cache.make_key(cache_key("STB", 1)).startswith(f"{frappe.conf.db_name}|".encode())
		)
		# status không nằm trong cache (tính lại mỗi lần theo ngày)
		self.assertNotIn("status", cached("STB", 2))

	def test_bom_rpc_etag_and_not_modified(self):
		first = call(api.bom, set_type="STB")
		self.assertEqual(len(first["etag"]), 16)
		int(first["etag"], 16)
		again = call(api.bom, set_type="STB")
		self.assertEqual(again["etag"], first["etag"])
		same = call(api.bom, set_type="STB", if_none_match=first["etag"])
		self.assertEqual(
			same,
			{
				"ok": True,
				"not_modified": True,
				"etag": first["etag"],
				"set_type": "STB",
				"bom_version": 1,
				"status": "Effective",
			},
		)
		self.assertIsNone(http_status())
		self.assertIn("lines", call(api.bom, set_type="STB", if_none_match="0000000000000000"))

		# đổi tên dụng cụ → cache của mọi phiên bản chứa dụng cụ bị xóa, etag mới
		call(api.bom, set_type="STB", version=2)
		doc = frappe.get_doc("Instrument", "STB-A")
		doc.instrument_name = "Kéo Mayo cong"
		doc.save()
		self.assertIsNone(cached("STB", 1))
		self.assertIsNone(cached("STB", 2))
		renamed = call(api.bom, set_type="STB")
		self.assertNotEqual(renamed["etag"], first["etag"])
		self.assertEqual(renamed["lines"][0]["instrument_name"], "Kéo Mayo cong")
		self.assertIn("lines", call(api.bom, set_type="STB", if_none_match=first["etag"]))

		# lưu dụng cụ không đổi tên/ảnh: cache giữ nguyên
		doc.reload()
		doc.manufacturer = "Aesculap"
		doc.save()
		self.assertIsNotNone(cached("STB", 1))

		# thay ảnh dụng cụ → etag mới (thumbnail + etag ảnh của dòng)
		source = attach_instrument_file("STB-A", "image", png(), "stb-a.png")
		doc.reload()
		doc.image = source.file_url
		doc.save()
		self.assertIsNone(cached("STB", 1))
		photo = call(api.bom, set_type="STB")
		self.assertNotEqual(photo["etag"], renamed["etag"])
		line = photo["lines"][0]
		self.assertEqual(line["image"], source.file_url)
		self.assertTrue(line["thumbnail"])
		self.assertEqual(
			line["image_etag"],
			frappe.db.get_value(
				"File", {"file_url": line["thumbnail"], "attached_to_name": "STB-A"}, "content_hash"
			),
		)
		# ảnh khác (cùng tên trường) → etag khác
		other = attach_instrument_file("STB-A", "image", png((200, 10, 10)), "stb-a2.png")
		doc.reload()
		doc.image = other.file_url
		doc.save()
		self.assertNotEqual(call(api.bom, set_type="STB")["etag"], photo["etag"])

		# thay ảnh khay → cache của loại bộ bị xóa, etag mới, tray_images có etag ảnh
		before = call(api.bom, set_type="STB")
		tray = attach_set_type_photo("STB", "tray_image_2", png((10, 10, 200)), "stb-tray.png")
		set_type = frappe.get_doc(SET_TYPE, "STB")
		set_type.tray_image_2 = tray.file_url
		set_type.save()
		self.assertIsNone(cached("STB", 1))
		with_tray = call(api.bom, set_type="STB")
		self.assertNotEqual(with_tray["etag"], before["etag"])
		self.assertEqual(len(with_tray["tray_images"]), 1)
		self.assertEqual(with_tray["tray_images"][0]["position"], 2)
		self.assertEqual(with_tray["tray_images"][0]["image_url"], tray.file_url)
		self.assertTrue(with_tray["tray_images"][0]["thumbnail_url"])
		self.assertTrue(with_tray["tray_images"][0]["etag"])

		# đổi tên loại bộ → etag mới
		set_type.reload()
		set_type.set_type_name = "Bộ khám tổng quát"
		set_type.save()
		self.assertIsNone(cached("STB", 1))
		self.assertNotEqual(call(api.bom, set_type="STB")["etag"], with_tray["etag"])

	def test_new_version_and_status_change_keep_etag_stable(self):
		first = call(api.bom, set_type="STB")
		# phiên bản mới (đã lên lịch) không đổi nội dung v1: etag v1 giữ nguyên, danh sách phiên bản cập nhật ngay
		make_bom("STB", [("STB-C", 1)], version=3, effective_from=add_days(self.tomorrow, 1))
		self.assertEqual(call(api.bom, set_type="STB", version=3)["bom_version"], 3)
		self.assertEqual(call(api.bom, set_type="STB")["etag"], first["etag"])
		# hôm sau: v2 hiệu lực, cùng etag của v2 nhưng status mới (status ngoài etag)
		scheduled = call(api.bom, set_type="STB", version=2)
		with patch("tracecore.instrument.bom_versions.today", return_value=self.tomorrow):
			effective = call(api.bom, set_type="STB")
			self.assertEqual((effective["bom_version"], effective["status"]), (2, "Effective"))
			self.assertEqual(effective["etag"], scheduled["etag"])
			not_modified = call(api.bom, set_type="STB", if_none_match=scheduled["etag"])
			self.assertEqual((not_modified["not_modified"], not_modified["status"]), (True, "Effective"))
			self.assertEqual(call(api.bom, set_type="STB", version=1)["status"], "Superseded")

	def test_bom_rpc_cache_hit_no_db(self):
		call(api.bom, set_type="STB")
		call(api.bom, set_type="STB", version=2)
		for kwargs in ({}, {"version": 2}):
			with self.subTest(**kwargs):
				result, _count, queries = count_queries(call, api.bom, set_type="STB", **kwargs)
				self.assertTrue(result["ok"])
				self.assertFalse([sql for sql in queries if "Set BOM Item" in sql], msg=queries)
				self.assertFalse(
					[sql for sql in queries if "tabFile" in sql or "`tabInstrument`" in sql], msg=queries
				)
		# lần đầu (chưa cache) dựng bằng số truy vấn cố định
		bom.invalidate(set_type="STB")
		_result, _count, queries = count_queries(bom.payload, "STB", 2)
		self.assertLessEqual(len(queries), 4, msg=queries)

	def test_bom_rpc_unknown_404_with_audit_commit(self):
		from frappe import app

		def end_of_request(fn, **kwargs):
			frappe.local.response.pop("http_status_code", None)
			frappe.local.flags.pop("commit", None)
			previous = getattr(frappe.local, "request", None)
			frappe.local.request = SimpleNamespace(method="GET", headers={})
			try:
				result = fn(**kwargs)
				status = http_status()
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
			return result, status, commit.called, rollback.called

		cases = (
			(api.bom, {"set_type": "STB-NONE"}, "SET_TYPE_NOT_FOUND", "STB-NONE"),
			(api.versions, {"set_type": "STB-NONE"}, "SET_TYPE_NOT_FOUND", "STB-NONE"),
			(api.form_context, {"set_type": "STB-NONE"}, "SET_TYPE_NOT_FOUND", "STB-NONE"),
			(
				api.compare,
				{"set_type": "STB-NONE", "from_version": 1, "to_version": 2},
				"SET_TYPE_NOT_FOUND",
				"STB-NONE",
			),
			(api.bom, {"set_type": "STB", "version": 9}, "BOM_VERSION_NOT_FOUND", "STB"),
			(
				api.compare,
				{"set_type": "STB", "from_version": 1, "to_version": 9},
				"BOM_VERSION_NOT_FOUND",
				"STB",
			),
		)
		for fn, kwargs, code, ref in cases:
			with self.subTest(fn=fn.__name__, code=code):
				before = frappe.db.count("Audit Log", {"action": "Reject", "reason": code, "ref_name": ref})
				result, status, committed, rolled_back = end_of_request(fn, **kwargs)
				self.assertFalse(result["ok"])
				self.assertEqual(result["error"]["code"], code)
				self.assertTrue(
					result["error"]["title"] and result["error"]["reason"] and result["error"]["action"]
				)
				self.assertEqual(status, 404)
				self.assertTrue(committed, msg="Reject row must be committed")
				self.assertFalse(rolled_back)
				log = frappe.get_all(
					"Audit Log",
					filters={"action": "Reject", "reason": code, "ref_name": ref},
					fields=["ref_doctype"],
				)
				self.assertEqual(len(log), before + 1)
				self.assertEqual(log[0].ref_doctype, SET_TYPE)
		# set type không phải chuỗi / trống: vẫn 404, không 500
		self.assertEqual(call(api.bom, set_type=None)["error"]["code"], "SET_TYPE_NOT_FOUND")
		self.assertEqual(call(api.bom, set_type="")["error"]["code"], "SET_TYPE_NOT_FOUND")
		# GET thành công: không commit thừa
		result, _status, committed, rolled_back = end_of_request(api.bom, set_type="STB")
		self.assertTrue(result["ok"])
		self.assertFalse(committed)
		self.assertTrue(rolled_back)

	def test_bom_rpc_version_format_and_empty_set_type(self):
		for bad in ("abc", "2.5", True, -1, 0):
			with self.subTest(version=bad):
				if bad in (-1, 0):
					self.assertEqual(
						call(api.bom, set_type="STB", version=bad)["error"]["code"], "BOM_VERSION_NOT_FOUND"
					)
				else:
					with self.assertRaises(BadRequestError):
						call(api.bom, set_type="STB", version=bad)
		with self.assertRaises(BadRequestError):
			call(api.compare, set_type="STB", from_version="x", to_version=1)
		# loại bộ cũ chưa có phiên bản BOM nào
		make_set_type("STBE")
		bom.invalidate(set_type="STBE")
		empty = call(api.bom, set_type="STBE")
		self.assertEqual(empty["error"]["code"], "BOM_VERSION_NOT_FOUND")
		self.assertEqual(http_status(), 404)
		self.assertEqual(call(api.versions, set_type="STBE")["versions"], [])

	def test_set_type_rpcs_require_read_permission_and_get_only(self):
		before = frappe.db.count("Audit Log", {"action": "Reject"})
		kwargs = {
			"bom": {"set_type": "STB"},
			"versions": {"set_type": "STB"},
			"compare": {"set_type": "STB", "from_version": 1, "to_version": 2},
			"form_context": {"set_type": "STB"},
		}
		for name in RPCS:
			fn = getattr(api, name)
			with self.subTest(rpc=name):
				self.assertEqual(frappe.get_attr(f"tracecore.v1.set_type.{name}"), fn)
				self.assertIn(fn, frappe.whitelisted)
				self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[fn], ["GET"])
				# thiếu quyền đọc: PermissionError trước khi lộ loại bộ có tồn tại hay không, không ghi Audit
				with self.assertRaises(frappe.PermissionError):
					as_user([], fn, **kwargs[name])
				with self.assertRaises(frappe.PermissionError):
					as_user([], fn, **{**kwargs[name], "set_type": "STB-NONE"})
				# mọi TC role đọc được loại bộ (S12), vd R04 ở T3/T4
				self.assertTrue(as_user(["TC R04"], fn, **kwargs[name])["ok"])
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Reject"}), before)

	def test_versions_and_compare_rpc(self):
		result = call(api.versions, set_type="STB")
		self.assertEqual((result["ok"], result["set_type"], result["effective_version"]), (True, "STB", 1))
		self.assertEqual([row["bom_version"] for row in result["versions"]], [2, 1])
		self.assertEqual([row["status"] for row in result["versions"]], ["Scheduled", "Effective"])
		compared = call(api.compare, set_type="stb", from_version="1", to_version="2")
		self.assertTrue(compared["ok"])
		self.assertEqual([row["instrument"] for row in compared["added"]], ["STB-C"])
		self.assertEqual(compared["unchanged"], 1)
		same = call(api.compare, set_type="STB", from_version=1, to_version=1)
		self.assertEqual(same["error"]["code"], "BOM_LINE_INVALID")
		self.assertEqual(http_status(), 422)

	def test_form_context_shape_and_permissions(self):
		r04 = as_user(["TC R04"], api.form_context, set_type="STB")
		self.assertTrue(r04["ok"])
		self.assertEqual(
			set(r04),
			{
				"ok",
				"set_type",
				"effective_version",
				"versions",
				"shelf_life",
				"usable_pack_types",
				"derived_max_cycles",
				"photos",
				"missing",
				"permissions",
			},
		)
		self.assertEqual(r04["permissions"], {"can_edit": False, "can_set_shelf_life": False})
		self.assertEqual((r04["set_type"], r04["effective_version"]), ("STB", 1))
		self.assertEqual([row["bom_version"] for row in r04["versions"]], [2, 1])
		self.assertEqual(set(r04["shelf_life"]), {"days", "source", "pack_type_days", "override"})
		self.assertEqual(r04["shelf_life"]["source"], "Pack Type")
		self.assertIn(
			frappe.db.get_value(SET_TYPE, "STB", "default_pack_type"),
			[row["item"] for row in r04["usable_pack_types"]],
		)
		self.assertEqual(set(r04["derived_max_cycles"]), {"value", "undefined", "limiting"})
		self.assertEqual(r04["photos"], [])
		# chưa có ảnh bộ, chưa nhập thời gian lắp ráp chuẩn → hai cảnh báo có chữ
		self.assertEqual([row["code"] for row in r04["missing"]], ["PHOTOS", "ASSEMBLY_MINUTES"])
		self.assertTrue(all(row["message"] for row in r04["missing"]))

		r02 = as_user(["TC R02"], api.form_context, set_type="STB")
		self.assertEqual(r02["permissions"], {"can_edit": True, "can_set_shelf_life": True})
		r10 = as_user(["TC R10"], api.form_context, set_type="STB")
		self.assertEqual(r10["permissions"], {"can_edit": True, "can_set_shelf_life": True})

		# có ảnh và thời gian lắp ráp → không còn cảnh báo
		tray = attach_set_type_photo("STB", "tray_image", png(), "stb-tray1.png")
		doc = frappe.get_doc(SET_TYPE, "STB")
		doc.tray_image = tray.file_url
		doc.assembly_minutes = 15
		doc.save()
		full = call(api.form_context, set_type="STB")
		self.assertEqual(full["missing"], [])
		self.assertEqual([photo["position"] for photo in full["photos"]], [1])

	def test_http_status_new_codes(self):
		# mã của RPC đọc loại bộ / phiên bản (A-07, ADR-003)
		self.assertEqual(HTTP_STATUS["SET_TYPE_NOT_FOUND"], 404)
		self.assertEqual(HTTP_STATUS["BOM_VERSION_NOT_FOUND"], 404)
		self.assertEqual(HTTP_STATUS["BOM_LINE_INVALID"], 422)
		call(api.versions, set_type="STB-NONE")
		self.assertEqual(http_status(), 404)
		call(api.bom, set_type="STB", version=7)
		self.assertEqual(http_status(), 404)

	def test_count_sheet_rpc_returns_pdf_and_404(self):
		# FR-M1-03, EI-HW-007: GET trả file PDF của phiên bản bất kỳ, sinh khi yêu cầu, không ghi Audit/File
		fn = api.count_sheet
		self.assertEqual(frappe.get_attr("tracecore.v1.set_type.count_sheet"), fn)
		self.assertIn(fn, frappe.whitelisted)
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[fn], ["GET"])

		def download(**kwargs):
			for key in ("type", "filename", "filecontent", "http_status_code"):
				frappe.local.response.pop(key, None)
			# request GET như trình duyệt (render Jinja và get_pdf đọc path/host của request)
			previous = getattr(frappe.local, "request", None)
			frappe.local.request = SimpleNamespace(
				method="GET",
				headers={},
				path="/api/method/tracecore.v1.set_type.count_sheet",
				host="localhost",
			)
			try:
				result = fn(**kwargs)
			finally:
				if previous is None:
					del frappe.local.request
				else:
					frappe.local.request = previous
			response = {
				key: frappe.local.response.pop(key, None) for key in ("type", "filename", "filecontent")
			}
			return result, response

		before = (frappe.db.count("Audit Log"), frappe.db.count("File"))
		result, response = download(set_type=" stb ")
		self.assertIsNone(result)
		self.assertIsNone(http_status())
		self.assertEqual((response["type"], response["filename"]), ("pdf", "STB-BOM-V1.pdf"))
		self.assertTrue(response["filecontent"].startswith(b"%PDF"))
		_result, scheduled = download(set_type="STB", version="2")
		self.assertEqual(scheduled["filename"], "STB-BOM-V2.pdf")
		self.assertEqual((frappe.db.count("Audit Log"), frappe.db.count("File")), before)

		for kwargs, code in (
			({"set_type": "STB-NONE"}, "SET_TYPE_NOT_FOUND"),
			({"set_type": None}, "SET_TYPE_NOT_FOUND"),
			({"set_type": "STB", "version": 9}, "BOM_VERSION_NOT_FOUND"),
			({"set_type": "STB", "version": 0}, "BOM_VERSION_NOT_FOUND"),
		):
			with self.subTest(**kwargs):
				count = frappe.db.count("Audit Log", {"action": "Reject", "reason": code})
				result, response = download(**kwargs)
				self.assertFalse(result["ok"])
				self.assertEqual(result["error"]["code"], code)
				self.assertEqual(http_status(), 404)
				self.assertIsNone(response["filecontent"])
				self.assertEqual(
					frappe.db.count("Audit Log", {"action": "Reject", "reason": code}), count + 1
				)
		with self.assertRaises(BadRequestError):
			download(set_type="STB", version="abc")
		# R04 (T3/T4) tải được; người không có quyền đọc → PermissionError, không lộ loại bộ, không Audit
		email = make_user("st-read-tcr04@example.com", ["TC R04"])
		frappe.set_user(email)
		try:
			_result, response = download(set_type="STB")
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(response["filename"], "STB-BOM-V1.pdf")
		rejects = frappe.db.count("Audit Log", {"action": "Reject"})
		for set_type in ("STB", "STB-NONE"):
			with self.assertRaises(frappe.PermissionError):
				as_user([], fn, set_type=set_type)
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Reject"}), rejects)


class TestSetTypeBomRpcLarge(IsolatedTestCase):
	def test_bom_rpc_under_one_second_for_500_lines(self):
		# Review Focus 5: BOM 500 dòng, chưa cache, ≤ 1 s (bench dev)
		bulk_set_type("STBL", 500, [(list(range(500)), lambda index: 1 + index % 3)])
		bom.invalidate(set_type="STBL")
		started = time.perf_counter()
		result = call(api.bom, set_type="STBL")
		elapsed = time.perf_counter() - started
		print(f"\nv1.set_type.bom 500 lines, uncached: {elapsed * 1000:.0f} ms")
		self.assertTrue(result["ok"])
		self.assertEqual(result["total_lines"], 500)
		self.assertEqual(result["total_qty"], sum(1 + index % 3 for index in range(500)))
		self.assertEqual([line["position"] for line in result["lines"]], list(range(1, 501)))
		self.assertLess(elapsed, 1.0)
		started = time.perf_counter()
		self.assertEqual(call(api.bom, set_type="STBL")["etag"], result["etag"])
		print(f"v1.set_type.bom 500 lines, cached: {(time.perf_counter() - started) * 1000:.0f} ms")
