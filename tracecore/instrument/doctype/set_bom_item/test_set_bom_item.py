import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.instrument import bom
from tracecore.tests.factories import make_bom, make_instrument, make_set_type


def _bom_line(set_type, version, instrument, qty, position):
	return frappe.get_doc(
		{
			"doctype": "Set BOM Item",
			"set_type": set_type,
			"bom_version": version,
			"instrument": instrument,
			"qty": qty,
			"position": position,
		}
	).insert()


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
			set(rows[0]), {"instrument", "instrument_name", "image", "qty", "position"}, msg=rows[0]
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
