import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from tracecore.instrument import bom, catalog
from tracecore.tests.factories import make_bom, make_instrument, make_set_type

# Set BOM Item liên kết Instrument Set Type (→ Department, Item) và Instrument (→ Item); CI chưa có Setup Wizard
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def _bom_line(set_type, version, instrument, qty, position):
	"""Dòng BOM ghi như dịch vụ BOM (cờ ``flags.tc_bom``) nhưng bỏ luật dòng của ``bom_versions``: giả lập dữ liệu có
	trước FEAT-015 (vd hai dòng cùng thứ tự xếp) để kiểm phần đọc và chốt chặn của chính DocType."""
	doc = frappe.get_doc(
		{
			"doctype": "Set BOM Item",
			"set_type": set_type,
			"bom_version": version,
			"instrument": instrument,
			"qty": qty,
			"position": position,
			"effective_from": nowdate(),
			"change_reason": "Legacy line",
			"based_on_version": max(version - 1, 0),
		}
	)
	doc.flags.tc_bom = True
	return doc.insert()


class TestSetBOMItem(FrappeTestCase):
	def test_bom_lines_for_version(self):
		st = make_set_type("BMT")
		make_instrument("BM-KEL", name="Kelly forceps", image="/files/bm-kel.png")
		make_bom(st.name, [("BM-SCI", 1), ("BM-KEL", 4)], version=1)
		make_bom(st.name, [("BM-KEL", 6), ("BM-SCI", 2), ("BM-NEE", 1)], version=2)

		rows = bom.lines(st.name, 2)
		self.assertEqual(
			[(r["instrument"], r["qty"], r["position"]) for r in rows],
			[("BM-KEL", 6, 1), ("BM-SCI", 2, 2), ("BM-NEE", 1, 3)],
		)
		self.assertEqual(
			set(rows[0]),
			{"instrument", "instrument_name", "image", "thumbnail", "qty", "position"},
			msg=rows[0],
		)
		self.assertEqual(rows[0]["instrument_name"], "Kelly forceps")
		self.assertEqual(rows[0]["image"], "/files/bm-kel.png")
		self.assertFalse(rows[1]["image"])

		self.assertEqual([r["instrument"] for r in bom.lines(st.name, 1)], ["BM-SCI", "BM-KEL"])
		self.assertEqual(bom.lines(st.name, 3), [])

	def test_bom_lines_only_for_requested_set_type(self):
		first, second = make_set_type("BMA"), make_set_type("BMB")
		make_bom(first.name, [("BM-ONE", 1)])
		make_bom(second.name, [("BM-TWO", 2)])
		self.assertEqual([r["instrument"] for r in bom.lines(first.name, 1)], ["BM-ONE"])
		self.assertEqual([r["instrument"] for r in bom.lines(second.name, 1)], ["BM-TWO"])

	def test_bom_lines_ordered_by_position_then_name(self):
		st = make_set_type("BMO")
		for code in ("BM-O1", "BM-O2", "BM-O3", "BM-O4"):
			make_instrument(code)
		# thứ tự chèn khác thứ tự xếp; hai dòng cùng position 2 phải theo name
		inserted = [
			_bom_line(st.name, 1, "BM-O3", 1, 3),
			_bom_line(st.name, 1, "BM-O1", 1, 1),
			_bom_line(st.name, 1, "BM-O2", 1, 2),
			_bom_line(st.name, 1, "BM-O4", 1, 2),
		]
		by_name = {doc.name: doc.instrument for doc in inserted}
		tied_names = sorted((n for n, i in by_name.items() if i in ("BM-O2", "BM-O4")), key=str.lower)
		expected = ["BM-O1", *(by_name[n] for n in tied_names), "BM-O3"]
		self.assertEqual([r["instrument"] for r in bom.lines(st.name, 1)], expected)

	def test_pack_context_gives_current_bom_and_tray_image(self):
		st = make_set_type("BMP", tray_image="/files/bmp-tray.png")
		make_bom(st.name, [("BM-P1", 2)], version=1)
		make_bom(st.name, [("BM-P2", 1), ("BM-P1", 3)], version=2)
		set_type = {"name": st.name, "current_bom_version": 2, "tray_image": "/files/bmp-tray.png"}

		result = bom.pack_context({"set_type": set_type, "station": "T4"})

		self.assertEqual(set(result), {"bom", "bom_version", "tray_image"})
		self.assertEqual(result["bom_version"], 2)
		self.assertEqual(result["tray_image"], "/files/bmp-tray.png")
		self.assertEqual([(r["instrument"], r["qty"]) for r in result["bom"]], [("BM-P2", 1), ("BM-P1", 3)])
		self.assertEqual(result["bom"], bom.lines(st.name, 2))

		# phiên bản cũ vẫn dựng được; loại bộ chưa có phiên bản BOM thì BOM rỗng
		older = bom.pack_context({"set_type": {**set_type, "current_bom_version": 1}})
		self.assertEqual((older["bom_version"], [r["instrument"] for r in older["bom"]]), (1, ["BM-P1"]))
		empty = bom.pack_context({"set_type": {"name": st.name, "current_bom_version": None}})
		self.assertEqual((empty["bom"], empty["bom_version"], empty["tray_image"]), ([], 0, None))

	def test_quantity_at_least_one(self):
		st = make_set_type("BMQ")
		make_instrument("BM-Q")
		for qty in (0, -2):
			with self.assertRaises(frappe.ValidationError, msg=qty):
				_bom_line(st.name, 1, "BM-Q", qty, 1)
		self.assertEqual(_bom_line(st.name, 1, "BM-Q", 1, 1).qty, 1)

	def test_set_bom_item_has_set_type_version_index(self):
		indexes = frappe.db.sql("SHOW INDEX FROM `tabSet BOM Item`", as_dict=True)
		columns = {}
		for row in indexes:
			columns.setdefault(row["Key_name"], []).append((row["Seq_in_index"], row["Column_name"]))
		composite = [[c for _, c in sorted(cols)] for cols in columns.values()]
		self.assertIn(["set_type", "bom_version"], composite)

	def test_create_writes_audit_log_and_delete_blocked(self):
		st = make_set_type("BMD")
		line = make_bom(st.name, [("BM-AUD", 3)])[0]
		self.assertEqual(
			frappe.db.count(
				"Audit Log", {"ref_doctype": "Set BOM Item", "ref_name": line.name, "action": "Create"}
			),
			1,
		)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Set BOM Item", line.name)
		self.assertTrue(frappe.db.exists("Set BOM Item", line.name))

	def test_new_bom_line_rejects_retired_instrument(self):
		# FR-M1-01 "danh sách chọn khi lập BOM", A-06 I13: dòng cũ giữ nguyên, dòng mới không nhận dụng cụ đã ngừng
		# (chốt chặn của DocType, kể cả khi dịch vụ BOM ghi); FEAT-015: dòng đã lưu không sửa được nữa
		st = make_set_type("BMR")
		old_line = make_bom(st.name, [("BM-RET", 2)], version=1)[0]
		make_instrument("BM-ACT")
		catalog.retire("BM-RET", "Broken", confirm=True)

		self.assertTrue(frappe.db.exists("Set BOM Item", old_line.name))
		old_line.reload()
		old_line.qty = 3
		with self.assertRaises(frappe.ValidationError):
			old_line.save()
		self.assertEqual(frappe.db.get_value("Set BOM Item", old_line.name, "qty"), 2)

		frappe.local.lang = "vi"
		try:
			with self.assertRaises(frappe.ValidationError) as raised:
				_bom_line(st.name, 2, "BM-RET", 1, 1)
			self.assertIn("BM-RET", str(raised.exception))
			self.assertIn("ngừng sử dụng", str(raised.exception))
		finally:
			frappe.local.lang = "en"
		self.assertEqual(_bom_line(st.name, 2, "BM-ACT", 1, 1).instrument, "BM-ACT")
