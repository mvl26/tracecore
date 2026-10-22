"""Phiên bản BOM của loại bộ (FEAT-015 Task 2; FR-M1-03, .1, .3, .6, FR-M1-04, .4; OTH-RET-002; S1, S2, S4, S5, S13, S14).

Review Focus 1 (ngày hiệu lực, biên múi giờ), 2 (phiên bản đã lưu bất biến), 3 (tạo đồng thời), 4 (dữ liệu dòng xấu).
"""

import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from tracecore.core.errors import BlockedError
from tracecore.instrument import bom, bom_versions, catalog
from tracecore.instrument import set_type as set_type_rules
from tracecore.tests.factories import (
	AUTO_PACK_TYPE,
	make_bom,
	make_department,
	make_instrument,
	make_pack_type,
	make_set_type,
	make_user,
	next_free_test_gtin,
)
from tracecore.tests.utils import IsolatedTestCase

# Instrument Set Type liên kết Department, Item; Set BOM Item/Instrument liên kết Item; CI chưa có Setup Wizard
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

SET_TYPE = "Instrument Set Type"
ITEM = "Set BOM Item"


@contextmanager
def utc_clock(instant):
	"""Đồng hồ tiến trình đứng ở thời điểm UTC `instant`: Frappe vẫn tự đổi sang múi giờ hệ thống (Asia/Ho_Chi_Minh)
	như khi server chạy giờ UTC (``now_datetime`` = ``convert_utc_to_system_timezone(datetime.now(UTC))``)."""
	from frappe.utils import data

	convert = data.convert_utc_to_system_timezone
	with patch.object(data, "convert_utc_to_system_timezone", side_effect=lambda _now: convert(instant)):
		yield


def _today():
	return getdate(nowdate())


def _header(type_code, method="Steam", **values):
	return {
		"type_code": type_code,
		"set_type_name": f"Set {type_code}",
		"method": method,
		"department": make_department(),
		"default_pack_type": make_pack_type(*AUTO_PACK_TYPE),
		**values,
	}


def _lines(*pairs):
	return [{"instrument": code, "qty": qty} for code, qty in pairs]


def _instruments(*codes, methods=("Steam 134",)):
	for code in codes:
		make_instrument(code, methods=methods)


def _blocked(testcase, fn, *args, **kwargs):
	with testcase.assertRaises(BlockedError) as raised:
		fn(*args, **kwargs)
	return raised.exception.block


def _rows(set_type, version):
	return [
		(row.instrument, row.qty, row.position)
		for row in frappe.get_all(
			ITEM,
			filters={"set_type": set_type, "bom_version": version},
			fields=["instrument", "qty", "position"],
			order_by="position asc",
		)
	]


def _audit(doctype, name, action):
	return frappe.get_all(
		"Audit Log",
		filters={"ref_doctype": doctype, "ref_name": name, "action": action},
		fields=["old_value", "new_value", "reason", "user"],
		order_by="creation asc",
	)


def _new_version(set_type, pairs, day=None, reason="Change tray", base=None):
	if base is None:
		base = max(row["bom_version"] for row in bom_versions.versions(set_type))
	return bom_versions.create_version(set_type, _lines(*pairs), day or _today(), reason, base)


class TestBomVersions(IsolatedTestCase):
	def test_create_set_type_with_v1(self):
		# FR-M1-03, AC-1
		_instruments("BV-A1", "BV-A2", "BV-A3")
		name = bom_versions.create_set_type(_header("BVC"), _lines(("BV-A1", 2), ("BV-A2", 1), ("BV-A3", 4)))
		self.assertEqual(name, "BVC")
		self.assertEqual(frappe.db.get_value(SET_TYPE, name, "current_bom_version"), 1)
		self.assertEqual(_rows(name, 1), [("BV-A1", 2, 1), ("BV-A2", 1, 2), ("BV-A3", 4, 3)])
		meta = frappe.get_all(
			ITEM,
			filters={"set_type": name},
			fields=["effective_from", "change_reason", "based_on_version"],
			distinct=True,
		)
		self.assertEqual(len(meta), 1)
		self.assertEqual(
			(getdate(meta[0].effective_from), meta[0].change_reason, meta[0].based_on_version),
			(_today(), "Initial version", 0),
		)
		self.assertEqual(len(_audit(SET_TYPE, name, "Create")), 1)
		lines = frappe.get_all(ITEM, filters={"set_type": name}, pluck="name")
		self.assertEqual(sum(len(_audit(ITEM, line, "Create")) for line in lines), 3)
		self.assertEqual(bom_versions.effective_version(name), 1)

	def test_empty_bom_rejected(self):
		# FR-M1-03.1, AC-2
		for empty in ([], None):
			block = _blocked(self, bom_versions.create_set_type, _header("BVE"), empty)
			self.assertEqual((block.code, block.http_status), ("BOM_EMPTY", 422))
		self.assertFalse(frappe.db.exists(SET_TYPE, "BVE"))

		# loại bộ không tạo trực tiếp được (Desk, frappe.client.insert), chỉ cùng BOM v1
		doc = frappe.get_doc({"doctype": SET_TYPE, **_header("BVD")})
		with self.assertRaises(frappe.ValidationError):
			doc.insert()
		self.assertFalse(frappe.db.exists(SET_TYPE, "BVD"))

	def test_incompatible_lines_reported_per_line(self):
		# FR-M1-03.3, AC-4
		_instruments("BV-S1", "BV-S2", methods=("Steam 134",))
		_instruments("BV-P1", "BV-P2", methods=("Plasma",))
		make_instrument("BV-121", methods=("Steam 121",))
		lines = _lines(("BV-S1", 1), ("BV-P1", 1), ("BV-121", 1), ("BV-P2", 2), ("BV-S2", 1))
		block = _blocked(self, bom_versions.create_set_type, _header("BVI"), lines)
		self.assertEqual((block.code, block.http_status), ("BOM_LINE_INVALID", 422))
		self.assertEqual(
			[(item["row"], item["instrument"], item["code"]) for item in block.items],
			[(2, "BV-P1", "INCOMPATIBLE"), (4, "BV-P2", "INCOMPATIBLE")],
		)
		self.assertTrue(all(item["message"] for item in block.items))
		self.assertFalse(frappe.db.exists(SET_TYPE, "BVI"))
		self.assertFalse(frappe.db.exists(ITEM, {"set_type": "BVI"}))

	def test_retired_instrument_rejected_in_new_version_even_when_copied(self):
		# FR-M1-03.6, AC-7, Review Focus 4
		_instruments("BV-R1", "BV-R2")
		name = bom_versions.create_set_type(_header("BVR"), _lines(("BV-R1", 1), ("BV-R2", 2)))
		catalog.retire("BV-R1", "Broken", confirm=True)
		block = _blocked(self, _new_version, name, [("BV-R1", 1), ("BV-R2", 3)])
		self.assertEqual(block.code, "BOM_LINE_INVALID")
		self.assertEqual(
			[(i["row"], i["instrument"], i["code"]) for i in block.items], [(1, "BV-R1", "RETIRED")]
		)
		self.assertEqual(bom_versions.versions(name)[0]["bom_version"], 1)

		result = _new_version(name, [("BV-R2", 3)])
		self.assertEqual(result["bom_version"], 2)
		self.assertEqual(_rows(name, 1), [("BV-R1", 1, 1), ("BV-R2", 2, 2)])
		self.assertEqual(_rows(name, 2), [("BV-R2", 3, 1)])

	def test_line_rules_duplicates_qty_positions(self):
		# Review Focus 4: mọi lỗi trả cùng lúc, theo từng dòng
		_instruments("BV-L1", "BV-L2", "BV-L3", "BV-L4", "BV-L5")
		lines = [
			{"instrument": "BV-L1", "qty": 1, "position": 1},
			{"instrument": "bv-l1 ", "qty": 2, "position": 2},
			{"instrument": "BV-L2", "qty": 0, "position": 3},
			{"instrument": "BV-L3", "qty": 1000, "position": 3},
			{"instrument": "BV-L4", "qty": "2.5", "position": 4},
			{"instrument": "BV-NONE", "qty": 1, "position": 5},
			{"instrument": "bad code!", "qty": 1, "position": 6},
			{"instrument": "BV-L5", "qty": 1, "position": "x"},
		]
		block = _blocked(self, bom_versions.create_set_type, _header("BVL"), lines)
		self.assertEqual(
			[(i["row"], i["code"]) for i in block.items],
			[
				(2, "DUPLICATE_INSTRUMENT"),
				(3, "QTY_RANGE"),
				(4, "DUPLICATE_POSITION"),
				(4, "QTY_RANGE"),
				(5, "QTY_RANGE"),
				(6, "NOT_FOUND"),
				(7, "NOT_FOUND"),
				(8, "POSITION_INVALID"),
			],
		)
		self.assertEqual(block.items[0]["instrument"], "BV-L1")
		self.assertFalse(frappe.db.exists(SET_TYPE, "BVL"))

		# số thứ tự xếp gửi lên chỉ để sắp; server đánh lại 1..n
		name = bom_versions.create_set_type(
			_header("BVP"),
			[
				{"instrument": "BV-L1", "qty": 1, "position": 5},
				{"instrument": "BV-L2", "qty": "2", "position": 9},
				{"instrument": "BV-L3", "qty": 3.0, "position": 2},
			],
		)
		self.assertEqual(_rows(name, 1), [("BV-L3", 3, 1), ("BV-L1", 1, 2), ("BV-L2", 2, 3)])

	def test_normalize_lines(self):
		rows = bom_versions.normalize_lines(
			[
				{"instrument": " bv-n2", "qty": 1},
				{"instrument": "BV-N1", "qty": 2, "position": 1},
				{"instrument": "BV-N3", "qty": True},
			]
		)
		self.assertEqual(
			[(r["row"], r["instrument"], r["qty"], r["position"]) for r in rows],
			[(2, "BV-N1", 2, 1), (1, "BV-N2", 1, 2), (3, "BV-N3", None, 3)],
		)
		with self.assertRaises(frappe.ValidationError):
			bom_versions.normalize_lines(["BV-N1"])

	def test_bom_too_large(self):
		codes = [f"BV-BIG-{n:03d}" for n in range(1, bom_versions.MAX_LINES + 2)]
		_instruments(*codes)
		block = _blocked(self, bom_versions.create_set_type, _header("BVX"), _lines(*((c, 1) for c in codes)))
		self.assertEqual((block.code, block.http_status), ("BOM_TOO_LARGE", 422))
		self.assertFalse(frappe.db.exists(SET_TYPE, "BVX"))

		name = bom_versions.create_set_type(_header("BVB"), _lines(*((c, 1) for c in codes[:-1])))
		self.assertEqual(frappe.db.count(ITEM, {"set_type": name, "bom_version": 1}), bom_versions.MAX_LINES)
		block = _blocked(self, _new_version, name, [(c, 2) for c in codes])
		self.assertEqual(block.code, "BOM_TOO_LARGE")

	def test_new_version_increments_and_keeps_old(self):
		# FR-M1-04, AC-8, OTH-RET-002
		_instruments("BV-N1", "BV-N2", "BV-N3")
		name = bom_versions.create_set_type(_header("BVN"), _lines(("BV-N1", 2), ("BV-N2", 1)))
		before = frappe.get_all(
			ITEM, filters={"set_type": name, "bom_version": 1}, fields=["*"], order_by="name"
		)

		result = bom_versions.create_version(
			name, _lines(("BV-N3", 1), ("BV-N1", 3)), _today(), "  Add retractor  ", 1
		)
		self.assertEqual(
			result,
			{"set_type": name, "bom_version": 2, "effective_from": str(_today()), "status": "Effective"},
		)
		self.assertEqual(_rows(name, 2), [("BV-N3", 1, 1), ("BV-N1", 3, 2)])
		self.assertEqual(
			frappe.get_all(ITEM, filters={"set_type": name, "bom_version": 1}, fields=["*"], order_by="name"),
			before,
		)
		meta = frappe.get_all(
			ITEM,
			filters={"set_type": name, "bom_version": 2},
			fields=["change_reason", "based_on_version", "effective_from"],
			distinct=True,
		)
		self.assertEqual(
			[(m.change_reason, m.based_on_version, getdate(m.effective_from)) for m in meta],
			[("Add retractor", 1, _today())],
		)
		self.assertEqual(frappe.db.get_value(SET_TYPE, name, "current_bom_version"), 2)

		updates = _audit(SET_TYPE, name, "Update")
		self.assertEqual(len(updates), 1)
		self.assertEqual(updates[0].reason, "Add retractor")
		self.assertEqual(
			frappe.parse_json(updates[0].new_value),
			{
				"bom_version": 2,
				"effective_from": str(_today()),
				"based_on_version": 1,
				"line_count": 2,
				"total_qty": 4,
				"current_bom_version": 2,
			},
		)
		self.assertEqual(frappe.parse_json(updates[0].old_value), {"current_bom_version": 1})
		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": SET_TYPE, "reference_name": name, "comment_type": "Info"},
			pluck="content",
		)
		self.assertEqual(len(comments), 1)
		self.assertIn("Add retractor", comments[0])

		listed = bom_versions.versions(name)
		self.assertEqual(
			[(v["bom_version"], v["status"]) for v in listed], [(2, "Effective"), (1, "Skipped")]
		)
		self.assertEqual(
			{
				key: listed[0][key]
				for key in ("reason", "based_on_version", "line_count", "total_qty", "created_by")
			},
			{
				"reason": "Add retractor",
				"based_on_version": 1,
				"line_count": 2,
				"total_qty": 4,
				"created_by": "Administrator",
			},
		)
		self.assertEqual(listed[1]["reason"], "Initial version")

	def test_saved_version_is_immutable(self):
		# Review Focus 2: không sửa, không xóa, không chèn thêm dòng vào phiên bản đã lưu — kể cả System Manager
		_instruments("BV-I1", "BV-I2")
		name = bom_versions.create_set_type(_header("BVM"), _lines(("BV-I1", 2)))
		line = frappe.get_doc(ITEM, {"set_type": name, "bom_version": 1})
		line.qty = 5
		with self.assertRaises(frappe.ValidationError):
			line.save()
		line.reload()
		line.flags.tc_bom = True  # cờ dịch vụ cũng không mở được phiên bản đã lưu
		line.change_reason = "Edited"
		with self.assertRaises(frappe.ValidationError):
			line.save()
		with self.assertRaises(frappe.ValidationError):
			frappe.client.set_value(ITEM, line.name, "qty", 7)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(ITEM, line.name)
		self.assertEqual(_rows(name, 1), [("BV-I1", 2, 1)])
		# lưu lại không đổi gì thì được (không phải sửa)
		line.reload()
		line.save()

		extra = frappe.get_doc(
			{
				"doctype": ITEM,
				"set_type": name,
				"bom_version": 1,
				"instrument": "BV-I2",
				"qty": 1,
				"position": 2,
			}
		)
		with self.assertRaises(frappe.ValidationError):
			extra.insert()
		self.assertEqual(_rows(name, 1), [("BV-I1", 2, 1)])

		for right in ("create", "write", "delete"):
			self.assertFalse(
				frappe.has_permission(ITEM, right, user=make_user("bv-sm@example.com", ["System Manager"])),
				right,
			)

	def test_set_bom_item_unique_index(self):
		indexes = frappe.db.sql("SHOW INDEX FROM `tabSet BOM Item` WHERE Non_unique = 0", as_dict=True)
		columns = {}
		for row in indexes:
			columns.setdefault(row["Key_name"], []).append((row["Seq_in_index"], row["Column_name"]))
		self.assertIn(
			["set_type", "bom_version", "instrument"],
			[[c for _s, c in sorted(cols)] for cols in columns.values()],
		)
		meta = frappe.get_meta(ITEM)
		for field in ("change_reason", "effective_from"):
			self.assertTrue(meta.get_field(field).reqd, msg=field)
		self.assertEqual(meta.get_field("based_on_version").fieldtype, "Int")

	def test_effective_date_rules(self):
		# FR-M1-04.4, AC-12, Review Focus 1
		_instruments("BV-D1", "BV-D2", "BV-D3")
		name = bom_versions.create_set_type(_header("BVT"), _lines(("BV-D1", 1)))
		today, tomorrow = _today(), add_days(_today(), 1)

		block = _blocked(self, _new_version, name, [("BV-D2", 1)], day=add_days(today, -1))
		self.assertEqual((block.code, block.http_status), ("BOM_EFFECTIVE_DATE_INVALID", 422))
		for bad in ("31/12/2026", "2026-02-30", "", None, 5):
			block = _blocked(self, bom_versions.create_version, name, _lines(("BV-D2", 1)), bad, "Change", 1)
			self.assertEqual(block.code, "BOM_EFFECTIVE_DATE_INVALID", msg=repr(bad))

		scheduled = _new_version(name, [("BV-D2", 1)], day=str(tomorrow))
		self.assertEqual((scheduled["bom_version"], scheduled["status"]), (2, "Scheduled"))
		self.assertEqual(scheduled["effective_from"], str(tomorrow))
		self.assertEqual(frappe.db.get_value(SET_TYPE, name, "current_bom_version"), 1)
		self.assertEqual(bom_versions.effective_version(name), 1)
		self.assertEqual(bom_versions.effective_version(name, tomorrow), 2)

		# ngày sớm hơn phiên bản mới nhất (đã lên lịch) bị chặn, kể cả hôm nay
		block = _blocked(self, _new_version, name, [("BV-D3", 1)], day=today)
		self.assertEqual(block.code, "BOM_EFFECTIVE_DATE_INVALID")
		self.assertIn(frappe.utils.formatdate(tomorrow), block.reason)

		later = _new_version(name, [("BV-D3", 1)], day=add_days(today, 5))
		self.assertEqual(later["status"], "Scheduled")
		self.assertEqual(
			[(v["bom_version"], v["status"]) for v in bom_versions.versions(name)],
			[(3, "Scheduled"), (2, "Scheduled"), (1, "Effective")],
		)
		self.assertEqual(bom_versions.live_versions(name), [1, 2, 3])

	def test_today_effective_applies_immediately_on_legacy_set_type(self):
		# carry-over review Task 1: loại bộ cũ thiếu khoa/loại gói vẫn nhận phiên bản mới (không lưu qua validate)
		_instruments("BV-G1", "BV-G2")
		name = bom_versions.create_set_type(_header("BVG"), _lines(("BV-G1", 1)))
		frappe.db.set_value(
			SET_TYPE, name, {"department": None, "default_pack_type": None}, update_modified=False
		)
		result = _new_version(name, [("BV-G2", 1)])
		self.assertEqual((result["bom_version"], result["status"]), (2, "Effective"))
		self.assertEqual(frappe.db.get_value(SET_TYPE, name, "current_bom_version"), 2)

		# loại bộ cũ chưa có dòng BOM nào: phiên bản đầu tiên qua Sửa BOM với base_version 0
		legacy = make_set_type("BVG0")
		frappe.db.set_value(SET_TYPE, legacy.name, {"department": None, "default_pack_type": None})
		first = bom_versions.create_version(legacy.name, _lines(("BV-G1", 2)), _today(), "First BOM", 0)
		self.assertEqual((first["bom_version"], first["status"]), (1, "Effective"))
		self.assertEqual(frappe.db.get_value(ITEM, {"set_type": legacy.name}, "based_on_version"), 0)

	def test_same_day_versions_higher_wins(self):
		# S2: cùng ngày hiệu lực → phiên bản số lớn thắng; phiên bản thua không bao giờ áp dụng
		_instruments("BV-W1", "BV-W2", "BV-W3")
		name = bom_versions.create_set_type(_header("BVW"), _lines(("BV-W1", 1)))
		tomorrow = add_days(_today(), 1)
		_new_version(name, [("BV-W2", 1)], day=tomorrow)
		_new_version(name, [("BV-W3", 1)], day=tomorrow)
		self.assertEqual(bom_versions.effective_version(name, tomorrow), 3)
		self.assertEqual(bom_versions.effective_version(name, add_days(tomorrow, 30)), 3)
		self.assertEqual(
			[(v["bom_version"], v["status"]) for v in bom_versions.versions(name)],
			[(3, "Scheduled"), (2, "Skipped"), (1, "Effective")],
		)
		self.assertEqual(bom_versions.live_versions(name), [1, 3])

	def test_live_versions_ignore_version_overtaken_on_earlier_date(self):
		# carry-over review Task 1 (b): v2 lên lịch ngày +5, v3 (số lớn hơn) ngày +3 → v2 không bao giờ áp dụng
		make_instrument("BV-OS", methods=("Steam 134",))
		make_instrument("BV-OB", methods=("Steam 134", "Plasma"))
		name = bom_versions.create_set_type(_header("BVO"), _lines(("BV-OB", 1)))
		_new_version(name, [("BV-OS", 1)], day=add_days(_today(), 3))
		_new_version(name, [("BV-OB", 2)], day=add_days(_today(), 3))
		# dữ liệu cũ vi phạm ràng buộc đơn điệu: dời v2 ra sau v3
		frappe.db.set_value(
			ITEM, {"set_type": name, "bom_version": 2}, "effective_from", add_days(_today(), 5)
		)
		self.assertEqual(bom_versions.live_versions(name), [1, 3])
		self.assertEqual(set_type_rules.live_versions(name), [1, 3])
		statuses = {v["bom_version"]: v["status"] for v in bom_versions.versions(name)}
		self.assertEqual(statuses, {1: "Effective", 2: "Skipped", 3: "Scheduled"})
		# đổi phương pháp chỉ kiểm phiên bản còn áp dụng: dòng Steam-only của v2 không chặn
		doc = frappe.get_doc(SET_TYPE, name)
		doc.method = "Plasma"
		doc.save()

	def test_effective_version_timezone_boundary(self):
		# Review Focus 1: tiến trình chạy giờ UTC; ngày theo Asia/Ho_Chi_Minh (UTC+7)
		_instruments("BV-Z1", "BV-Z2")
		day = _today()
		name = bom_versions.create_set_type(_header("BVZ"), _lines(("BV-Z1", 1)))
		_new_version(name, [("BV-Z2", 1)], day=add_days(day, 1))
		next_day = add_days(day, 1)
		before = datetime(day.year, day.month, day.day, 16, 59, tzinfo=timezone.utc)  # 23:59 ngày D giờ VN
		after = datetime(day.year, day.month, day.day, 17, 1, tzinfo=timezone.utc)  # 00:01 ngày D+1 giờ VN
		with utc_clock(before):
			self.assertEqual(bom_versions.today(), day)
			self.assertEqual(bom_versions.effective_version(name), 1)
		with utc_clock(after):
			self.assertEqual(bom_versions.today(), next_day)
			self.assertEqual(bom_versions.effective_version(name), 2)
			self.assertEqual(bom_versions.versions(name)[0]["status"], "Effective")

	def test_roll_effective_versions_scheduled(self):
		_instruments("BV-K1", "BV-K2")
		name = bom_versions.create_set_type(_header("BVK"), _lines(("BV-K1", 1)))
		tomorrow = add_days(_today(), 1)
		_new_version(name, [("BV-K2", 1)], day=tomorrow)
		self.assertNotIn(name, bom_versions.roll_effective_versions())
		self.assertEqual(frappe.db.get_value(SET_TYPE, name, "current_bom_version"), 1)

		# scheduler trễ 3 ngày: phiên bản áp dụng vẫn tính đúng trực tiếp từ dòng
		late = add_days(_today(), 3)
		with utc_clock(datetime(late.year, late.month, late.day, 3, 0, tzinfo=timezone.utc)):
			self.assertEqual(bom_versions.effective_version(name), 2)
			self.assertEqual(frappe.db.get_value(SET_TYPE, name, "current_bom_version"), 1)
			self.assertIn(name, bom_versions.roll_effective_versions())
			self.assertEqual(frappe.db.get_value(SET_TYPE, name, "current_bom_version"), 2)
			self.assertNotIn(name, bom_versions.roll_effective_versions())  # chạy lại không đổi gì
		updates = [
			frappe.parse_json(u.new_value)
			for u in _audit(SET_TYPE, name, "Update")
			if u.reason == "scheduled"
		]
		self.assertEqual(updates, [{"current_bom_version": 2}])

	def test_scheduler_registered(self):
		from tracecore import hooks

		self.assertIn(
			"tracecore.instrument.bom_versions.roll_effective_versions",
			hooks.scheduler_events["cron"]["0 0 * * *"],
		)

	def test_concurrent_versions_conflict(self):
		# Review Focus 3: hai người cùng sửa từ v1 → người sau BOM_VERSION_CONFLICT kèm phiên bản mới nhất
		_instruments("BV-C1", "BV-C2", "BV-C3")
		name = bom_versions.create_set_type(_header("BVY"), _lines(("BV-C1", 1)))
		_new_version(name, [("BV-C2", 1)], base=1)
		block = _blocked(self, _new_version, name, [("BV-C3", 1)], base=1)
		self.assertEqual((block.code, block.http_status), ("BOM_VERSION_CONFLICT", 409))
		self.assertEqual(block.items, [{"latest": 2}])
		self.assertFalse(frappe.db.exists(ITEM, {"set_type": name, "bom_version": 3}))
		block = _blocked(self, _new_version, name, [("BV-C3", 1)], base=5)
		self.assertEqual(block.code, "BOM_VERSION_CONFLICT")

	def test_no_change_rejected(self):
		_instruments("BV-U1", "BV-U2")
		name = bom_versions.create_set_type(_header("BVU"), _lines(("BV-U1", 1), ("BV-U2", 2)))
		block = _blocked(self, _new_version, name, [("bv-u1", 1), ("BV-U2", "2")])
		self.assertEqual(block.code, "BOM_LINE_INVALID")
		self.assertFalse(block.items)
		# chỉ đổi thứ tự xếp là một thay đổi
		self.assertEqual(_new_version(name, [("BV-U2", 2), ("BV-U1", 1)])["bom_version"], 2)

	def test_reason_required(self):
		_instruments("BV-Q1", "BV-Q2")
		name = bom_versions.create_set_type(_header("BVQ"), _lines(("BV-Q1", 1)))
		for blank in ("", "   ", None, "x" * (bom_versions.REASON_MAX + 1)):
			block = _blocked(self, _new_version, name, [("BV-Q2", 1)], reason=blank)
			self.assertEqual((block.code, block.http_status), ("REASON_REQUIRED", 422), msg=repr(blank)[:20])
		self.assertEqual(_new_version(name, [("BV-Q2", 1)], reason="y" * 500)["bom_version"], 2)

	def test_unknown_set_type(self):
		block = _blocked(self, bom_versions.create_version, "NOPE99", _lines(("BV-Q1", 1)), _today(), "x", 1)
		self.assertEqual((block.code, block.http_status), ("SET_TYPE_NOT_FOUND", 404))

	def test_copy_set_type(self):
		# UC-02 A2, S13: phần đầu trừ mã/GTIN/ảnh; v1 = phiên bản hiệu lực của nguồn
		_instruments("BV-Y1", "BV-Y2", "BV-Y3")
		source = bom_versions.create_set_type(
			_header("BVS", is_implant=1, assembly_minutes=25, shelf_life_days=10, gtin=next_free_test_gtin()),
			_lines(("BV-Y1", 1)),
		)
		frappe.db.set_value(SET_TYPE, source, "tray_image", "/files/bvs.png")
		_new_version(source, [("BV-Y2", 2), ("BV-Y1", 1)])
		_new_version(source, [("BV-Y3", 1)], day=add_days(_today(), 2))

		copy = bom_versions.copy_set_type(source, " bvs2 ", "Copied tray")
		self.assertEqual(copy, "BVS2")
		row = frappe.db.get_value(SET_TYPE, copy, ["*"], as_dict=True)
		src = frappe.db.get_value(SET_TYPE, source, ["*"], as_dict=True)
		for field in (
			"method",
			"department",
			"default_pack_type",
			"shelf_life_days",
			"is_implant",
			"assembly_minutes",
		):
			self.assertEqual(row[field], src[field], msg=field)
		self.assertEqual(row.set_type_name, "Copied tray")
		self.assertEqual((row.gtin, row.tray_image, row.current_bom_version), (None, None, 1))
		self.assertEqual(_rows(copy, 1), [("BV-Y2", 2, 1), ("BV-Y1", 1, 2)])

		block = _blocked(self, bom_versions.copy_set_type, source, "BVS2", "Again")
		self.assertEqual((block.code, block.http_status), ("SET_TYPE_CODE_EXISTS", 409))
		block = _blocked(self, bom_versions.create_set_type, _header("BVS"), _lines(("BV-Y1", 1)))
		self.assertEqual(block.code, "SET_TYPE_CODE_EXISTS")
		block = _blocked(self, bom_versions.copy_set_type, "NOPE98", "BVS3", "x")
		self.assertEqual(block.code, "SET_TYPE_NOT_FOUND")

		# dụng cụ đã ngừng sử dụng trong BOM nguồn → lỗi từng dòng, không tạo gì
		catalog.retire("BV-Y2", "Broken", confirm=True)
		block = _blocked(self, bom_versions.copy_set_type, source, "BVS4", "Retired copy")
		self.assertEqual([(i["instrument"], i["code"]) for i in block.items], [("BV-Y2", "RETIRED")])
		self.assertFalse(frappe.db.exists(SET_TYPE, "BVS4"))

	def test_bom_usage_includes_scheduled_versions(self):
		# FEAT-014 I3/I13: dụng cụ chỉ có ở phiên bản đã lên lịch vẫn được liệt kê khi đổi phương pháp/ngừng sử dụng
		_instruments("BV-H1", "BV-H2")
		name = bom_versions.create_set_type(_header("BVH"), _lines(("BV-H1", 1)))
		_new_version(name, [("BV-H1", 1), ("BV-H2", 1)], day=add_days(_today(), 4))
		usage = catalog.bom_usage("BV-H2")
		self.assertEqual(
			[(u["set_type"], u["bom_version"], u["scheduled"]) for u in usage], [(name, 2, True)]
		)
		self.assertEqual(
			[(u["set_type"], u["bom_version"], u["scheduled"]) for u in catalog.bom_usage("BV-H1")],
			[(name, 1, False)],
		)
		self.assertFalse(catalog.retire("BV-H2", "Broken")["retired"])

	def test_pack_context_unchanged_for_single_version(self):
		# T4 (FEAT-018) với loại bộ một phiên bản: BOM như cũ
		_instruments("BV-T1", "BV-T2")
		name = bom_versions.create_set_type(_header("BVJ"), _lines(("BV-T1", 2), ("BV-T2", 1)))
		row = frappe.db.get_value(SET_TYPE, name, ["name", "current_bom_version", "tray_image"], as_dict=True)
		context = bom.pack_context({"set_type": row, "station": "T4"})
		self.assertEqual(context["bom_version"], 1)
		self.assertEqual([(r["instrument"], r["qty"]) for r in context["bom"]], [("BV-T1", 2), ("BV-T2", 1)])

	def test_factory_make_bom_goes_through_service(self):
		st = make_set_type("BVF")
		make_bom(st, [("BV-F1", 1)])
		make_bom(st, [("BV-F1", 2)], version=2, reason="Factory v2")
		self.assertEqual(
			[(v["bom_version"], v["reason"]) for v in bom_versions.versions(st.name)],
			[(2, "Factory v2"), (1, "Test BOM version 1")],
		)
		with self.assertRaises(frappe.ValidationError):
			make_bom(st, [("BV-F1", 3)], version=5)

	def test_patch_backfills_version_meta(self):
		from tracecore.patches.v0_1 import set_bom_item_version_meta

		_instruments("BV-M1", "BV-M2")
		st = make_set_type("BVPT")
		make_bom(st, [("BV-M1", 1)])
		make_bom(st, [("BV-M2", 1)], version=2)
		# dữ liệu có trước FEAT-015: không ngày hiệu lực, không lý do, không phiên bản cơ sở; current còn 1
		frappe.db.sql(
			"update `tabSet BOM Item` set effective_from = null, change_reason = null, based_on_version = 0 "
			"where set_type = %s",
			st.name,
		)
		frappe.db.set_value(SET_TYPE, st.name, "current_bom_version", 1)
		set_bom_item_version_meta.execute()
		rows = frappe.get_all(
			ITEM,
			filters={"set_type": st.name},
			fields=["bom_version", "effective_from", "change_reason", "based_on_version"],
			order_by="bom_version",
		)
		self.assertEqual(
			[(r.bom_version, getdate(r.effective_from), r.change_reason, r.based_on_version) for r in rows],
			[(1, _today(), "Initial version", 0), (2, _today(), "Recorded before BOM versioning", 1)],
		)
		self.assertEqual(frappe.db.get_value(SET_TYPE, st.name, "current_bom_version"), 2)
		count = frappe.db.count("Audit Log")
		set_bom_item_version_meta.execute()  # idempotent
		self.assertEqual(frappe.db.count("Audit Log"), count)

		with open(frappe.get_app_path("tracecore", "patches.txt"), encoding="utf-8") as handle:
			post = handle.read().split("[post_model_sync]", 1)[1]
		self.assertIn("tracecore.patches.v0_1.set_bom_item_version_meta", post)


class TestBomVersionConcurrency(FrappeTestCase):
	"""Hai kết nối DB thật (REPEATABLE READ của MariaDB): người sau thấy phiên bản người trước vừa commit."""

	CODE = "BVCC"
	INSTRUMENTS = ("BV-CC1", "BV-CC2", "BV-CC3")

	def _cleanup(self):
		frappe.db.rollback()
		frappe.db.delete(ITEM, {"set_type": self.CODE})
		frappe.db.delete("Comment", {"reference_doctype": SET_TYPE, "reference_name": self.CODE})
		frappe.db.delete(SET_TYPE, {"name": self.CODE})
		frappe.db.commit()

	def test_parallel_create_version_one_wins(self):
		self._cleanup()
		_instruments(*self.INSTRUMENTS)
		bom_versions.create_set_type(_header(self.CODE), _lines(("BV-CC1", 1)))
		frappe.db.commit()
		self.addCleanup(self._cleanup)
		site, sites_path = frappe.local.site, frappe.local.sites_path
		errors = []

		def other_request():
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			frappe.set_user("Administrator")
			try:
				bom_versions.create_version(self.CODE, _lines(("BV-CC2", 1)), _today(), "First editor", 1)
				time.sleep(1.0)  # giữ khóa loại bộ, chưa commit
				frappe.db.commit()
			except Exception as error:  # pragma: no cover - chỉ để báo lỗi của luồng phụ
				errors.append(error)
			finally:
				frappe.destroy()

		# snapshot của transaction chính mở trước khi người kia commit
		frappe.db.sql("select count(*) from `tabSet BOM Item` where set_type = %s", self.CODE)
		thread = threading.Thread(target=other_request)
		thread.start()
		time.sleep(0.4)
		try:
			with self.assertRaises(BlockedError) as raised:
				bom_versions.create_version(self.CODE, _lines(("BV-CC3", 1)), _today(), "Second editor", 1)
		finally:
			thread.join()
		self.assertFalse(errors)
		self.assertEqual(raised.exception.block.code, "BOM_VERSION_CONFLICT")
		self.assertEqual(raised.exception.block.items, [{"latest": 2}])
		frappe.db.rollback()
		self.assertEqual(
			frappe.db.sql(
				"select bom_version, count(*) from `tabSet BOM Item` where set_type = %s group by bom_version",
				self.CODE,
			),
			((1, 1), (2, 1)),
		)
