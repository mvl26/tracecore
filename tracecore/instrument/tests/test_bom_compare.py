"""So sánh hai phiên bản BOM của loại bộ (FEAT-015 Task 6, S10; FR-M1-04.3, AC-11; Review Focus 5).

``bom_versions.compare(set_type, from_version, to_version)`` so theo mã dụng cụ: ``added``, ``removed``,
``qty_changed`` (``from_qty → to_qty``), ``moved`` (đổi thứ tự xếp tương đối giữa các dụng cụ có ở cả hai phiên bản),
``unchanged`` (số dụng cụ có ở cả hai phiên bản với cùng số lượng), số truy vấn cố định bất kể số dòng.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, nowdate

from tracecore.core.errors import BlockedError
from tracecore.instrument import bom, bom_versions
from tracecore.tests.factories import make_bom, make_set_type
from tracecore.tests.utils import IsolatedTestCase

# Instrument Set Type liên kết Department, Item; Set BOM Item/Instrument liên kết Item; CI chưa có Setup Wizard
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def _codes(rows):
	return [row["instrument"] for row in rows]


def count_queries(fn, *args, **kwargs):
	"""Gọi `fn` và đếm số lệnh SQL đi qua ``frappe.db.sql`` (get_value/get_all/exists đều đi qua đây)."""
	with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as sql:
		result = fn(*args, **kwargs)
	return result, sql.call_count, [str(call.args[0]) if call.args else "" for call in sql.call_args_list]


def bulk_set_type(type_code, size, versions):
	"""Loại bộ cũ có `versions` phiên bản (mỗi phiên bản: list mã dụng cụ theo thứ tự, qty theo hàm), ghi thẳng bằng
	bulk insert để dựng nhanh BOM 500 dòng (dữ liệu test; luật dòng đã có test riêng ở test_bom_versions).
	"""
	make_set_type(type_code)
	bom.invalidate(set_type=type_code)
	codes = [f"{type_code}-{index:03d}" for index in range(size + 1)]
	now = frappe.utils.now()
	frappe.db.bulk_insert(
		"Instrument",
		[
			"name",
			"instrument_code",
			"instrument_name",
			"status",
			"spaulding_class",
			"version_no",
			"creation",
			"modified",
			"owner",
			"modified_by",
		],
		[
			(
				code,
				code,
				f"Instrument {code}",
				"Active",
				"Critical",
				1,
				now,
				now,
				"Administrator",
				"Administrator",
			)
			for code in codes
		],
	)
	rows = []
	for version, (members, qty_of) in enumerate(versions, 1):
		for position, index in enumerate(members, 1):
			rows.append(
				(
					frappe.generate_hash(length=12),
					type_code,
					version,
					codes[index],
					qty_of(index),
					position,
					getdate(nowdate()),
					f"Bulk version {version}",
					version - 1,
					now,
					now,
					"Administrator",
					"Administrator",
				)
			)
	frappe.db.bulk_insert(
		"Set BOM Item",
		[
			"name",
			"set_type",
			"bom_version",
			"instrument",
			"qty",
			"position",
			"effective_from",
			"change_reason",
			"based_on_version",
			"creation",
			"modified",
			"owner",
			"modified_by",
		],
		rows,
	)
	return codes


class TestBomCompare(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		make_set_type("CMP", bom=[("CMP-A", 2), ("CMP-B", 1), ("CMP-C", 1)])
		tomorrow = add_days(getdate(nowdate()), 1)
		make_bom(
			"CMP",
			[("CMP-C", 1), ("CMP-A", 3), ("CMP-D", 1)],
			version=2,
			effective_from=tomorrow,
			reason="New tray",
		)

	def test_compare_added_removed_qty_moved(self):
		result = bom_versions.compare("CMP", 1, 2)
		self.assertEqual(result["set_type"], "CMP")
		self.assertEqual(_codes(result["added"]), ["CMP-D"])
		self.assertEqual(result["added"][0]["qty"], 1)
		self.assertEqual(result["added"][0]["position"], 3)
		self.assertTrue(result["added"][0]["instrument_name"])
		self.assertEqual(_codes(result["removed"]), ["CMP-B"])
		self.assertEqual(result["removed"][0]["position"], 2)
		self.assertEqual(
			[(row["instrument"], row["from_qty"], row["to_qty"]) for row in result["qty_changed"]],
			[("CMP-A", 2, 3)],
		)
		self.assertEqual(sorted(_codes(result["moved"])), ["CMP-A", "CMP-C"])
		moved = {row["instrument"]: (row["from_position"], row["to_position"]) for row in result["moved"]}
		self.assertEqual(moved, {"CMP-A": (1, 2), "CMP-C": (3, 1)})
		self.assertEqual(result["unchanged"], 1)
		# thông tin hai phiên bản: ngày hiệu lực, lý do, người tạo, tổng dòng / tổng dụng cụ, trạng thái
		self.assertEqual(result["from_version"]["bom_version"], 1)
		self.assertEqual(result["from_version"]["status"], "Effective")
		self.assertEqual((result["from_version"]["line_count"], result["from_version"]["total_qty"]), (3, 4))
		self.assertEqual(result["to_version"]["bom_version"], 2)
		self.assertEqual(result["to_version"]["status"], "Scheduled")
		self.assertEqual(result["to_version"]["reason"], "New tray")
		self.assertEqual((result["to_version"]["line_count"], result["to_version"]["total_qty"]), (3, 5))
		self.assertEqual(result["to_version"]["created_by"], "Administrator")
		# nhãn chữ cho bảng khác biệt (trạng thái không chỉ bằng màu)
		self.assertEqual(set(result["labels"]), {"added", "removed", "qty_changed", "moved"})
		self.assertTrue(all(result["labels"].values()))

		# đảo chiều: kết quả đối xứng
		reverse = bom_versions.compare("CMP", 2, 1)
		self.assertEqual(_codes(reverse["added"]), ["CMP-B"])
		self.assertEqual(_codes(reverse["removed"]), ["CMP-D"])
		self.assertEqual(
			[(row["instrument"], row["from_qty"], row["to_qty"]) for row in reverse["qty_changed"]],
			[("CMP-A", 3, 2)],
		)
		moved = {row["instrument"]: (row["from_position"], row["to_position"]) for row in reverse["moved"]}
		self.assertEqual(moved, {"CMP-A": (2, 1), "CMP-C": (1, 3)})
		self.assertEqual(reverse["unchanged"], 1)
		self.assertEqual(reverse["from_version"]["bom_version"], 2)

	def test_compare_removal_alone_is_not_a_move(self):
		# bỏ một dòng ở giữa làm số thứ tự xếp phía sau dồn lên: không tính là đổi thứ tự
		make_bom(
			"CMP", [("CMP-C", 1), ("CMP-A", 3)], version=3, effective_from=add_days(getdate(nowdate()), 2)
		)
		result = bom_versions.compare("CMP", 2, 3)
		self.assertEqual(_codes(result["removed"]), ["CMP-D"])
		self.assertEqual(result["moved"], [])
		self.assertEqual(result["unchanged"], 2)

	def test_compare_same_or_missing_version(self):
		with self.assertRaises(BlockedError) as same:
			bom_versions.compare("CMP", 2, 2)
		self.assertEqual(same.exception.block.code, "BOM_LINE_INVALID")
		for args in ((1, 9), (9, 1), (0, 1), (1, None), ("x", 1)):
			with self.subTest(args=args), self.assertRaises(BlockedError) as missing:
				bom_versions.compare("CMP", *args)
			self.assertEqual(missing.exception.block.code, "BOM_VERSION_NOT_FOUND")
			self.assertEqual(missing.exception.block.http_status, 404)
		with self.assertRaises(BlockedError) as no_type:
			bom_versions.compare("CMP-NONE", 1, 2)
		self.assertEqual(no_type.exception.block.code, "SET_TYPE_NOT_FOUND")
		# chuỗi số từ query string được nhận
		self.assertEqual(_codes(bom_versions.compare("CMP", "1", "2")["added"]), ["CMP-D"])


class TestBomCompareLarge(IsolatedTestCase):
	def test_compare_500_lines_constant_queries(self):
		# Review Focus 5: không N+1 — cùng số truy vấn cho BOM 3 dòng và BOM 500 dòng, và ≤ 6
		bulk_set_type(
			"CMPL",
			500,
			[
				(list(range(500)), lambda index: 1),
				# bỏ dòng 0, thêm dòng 500, đổi số lượng các dòng chẵn, đảo hai dòng cuối
				([*range(1, 498), 499, 498, 500], lambda index: 2 if index % 2 == 0 else 1),
			],
		)
		large, large_count, _sql = count_queries(bom_versions.compare, "CMPL", 1, 2)
		self.assertEqual(_codes(large["added"]), ["CMPL-500"])
		self.assertEqual(_codes(large["removed"]), ["CMPL-000"])
		self.assertEqual(len(large["qty_changed"]), 249)
		self.assertEqual(sorted(_codes(large["moved"])), ["CMPL-498", "CMPL-499"])
		self.assertEqual(large["unchanged"], 499 - 249)
		self.assertEqual(large["to_version"]["line_count"], 500)

		make_set_type("CMPS", bom=[("CMPS-A", 1), ("CMPS-B", 1)])
		make_bom(
			"CMPS", [("CMPS-B", 2), ("CMPS-C", 1)], version=2, effective_from=add_days(getdate(nowdate()), 1)
		)
		_small, small_count, _sql = count_queries(bom_versions.compare, "CMPS", 1, 2)
		self.assertLessEqual(large_count, 6)
		self.assertEqual(large_count, small_count)
