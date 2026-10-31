"""Cột Tên cạnh cột mã (A-65): mọi Link `in_list_view` có cột tên hoặc nằm trong danh sách bỏ qua; patch điền dữ liệu cũ."""

import csv
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core.name_columns import (
	GRID_MAX_COLUMNS,
	NAME_FIELD,
	name_fieldname,
	skip_reason,
)
from tracecore.patches.v0_1 import backfill_name_columns
from tracecore.tests.factories import make_bom, make_department, make_instrument, make_set_type, make_set_unit

MODULES = (
	"TraceCore",
	"Instrument",
	"Reprocessing",
	"Linen",
	"Equipment",
	"Inventory",
	"Costing",
	"Par",
	"Admin Reports",
	"Waste",
	"UI",
)

# Dynamic Link `in_list_view`: đích đổi theo từng dòng nên không có cột tên cố định, xử lý tay
DYNAMIC_LINKS = {
	("Cost Allocation", "target"),
	("Cost Sheet", "source_name"),
	("Import Batch Row", "ref_name"),
	("Maintenance Affected Load", "load"),
	("Par Level", "target"),
}

VI_CSV = Path(frappe.get_app_path("tracecore", "translations", "vi.csv"))


def _tracecore_doctypes():
	return frappe.get_all("DocType", filters={"module": ["in", MODULES]}, pluck="name", order_by="name")


def _list_links():
	"""(doctype, link df) cho mọi Link `in_list_view` của DocType TraceCore, kể cả bảng con."""
	for name in _tracecore_doctypes():
		for df in frappe.get_meta(name).fields:
			if df.fieldtype == "Link" and df.in_list_view:
				yield name, df


class TestNameColumns(FrappeTestCase):
	def test_every_list_view_link_has_a_name_column_or_is_skipped(self):
		missing = []
		checked = 0
		for doctype, df in _list_links():
			if skip_reason(doctype, df.fieldname, df.options):
				continue
			checked += 1
			meta = frappe.get_meta(doctype)
			name_df = meta.get_field(name_fieldname(df.fieldname))
			expected = f"{df.fieldname}.{NAME_FIELD[df.options]}"
			ok = (
				name_df
				and name_df.fieldtype == "Data"
				and name_df.read_only
				and name_df.in_list_view
				and name_df.fetch_from == expected
				# ngay sau cột mã
				and meta.fields[meta.fields.index(meta.get_field(df.fieldname)) + 1].fieldname
				== name_df.fieldname
			)
			if not ok:
				missing.append(f"{doctype}.{df.fieldname}")
		self.assertGreater(checked, 50)
		self.assertFalse(missing, msg="Thiếu cột tên cho: " + ", ".join(missing))

	def test_skipped_links_have_a_known_reason(self):
		for doctype, df in _list_links():
			target = df.options
			if skip_reason(doctype, df.fieldname, target) == "no rule for target":
				self.fail(f"{doctype}.{df.fieldname} → {target}: chưa quyết định thêm cột tên hay bỏ qua")

	def test_dynamic_links_in_list_view_are_the_known_ones(self):
		found = {
			(name, df.fieldname)
			for name in _tracecore_doctypes()
			for df in frappe.get_meta(name).fields
			if df.fieldtype == "Dynamic Link" and df.in_list_view
		}
		self.assertEqual(found, DYNAMIC_LINKS)

	def test_set_unit_has_set_type_name(self):
		df = frappe.get_meta("Set Unit").get_field("set_type_name")
		self.assertEqual((df.fieldtype, df.fetch_from, df.read_only), ("Data", "set_type.set_type_name", 1))

	def test_existing_name_fields_are_not_duplicated(self):
		# trường đã có sẵn (employee_name của Certificate, instrument_name của Assembly Line, set_name…)
		for doctype, name_field in (
			("Certificate", "employee_name"),
			("Assembly Line", "instrument_name"),
			("Loaner BOM Item", "instrument_name"),
			("Dirty Receipt Item", "set_name"),
			("Issue Note Pack", "set_name"),
		):
			with self.subTest(doctype=doctype):
				fields = [f.fieldname for f in frappe.get_meta(doctype).fields]
				self.assertEqual(fields.count(name_field), 1)

	def test_child_grids_stay_within_the_column_limit(self):
		over = []
		for name in _tracecore_doctypes():
			meta = frappe.get_meta(name)
			if not meta.istable:
				continue
			shown = [f for f in meta.fields if f.in_list_view]
			if not any(f.fieldname.endswith("_name") and f.fetch_from for f in shown):
				continue
			total = sum(f.columns or 0 for f in shown)
			if any(not f.columns for f in shown) or total > GRID_MAX_COLUMNS:
				over.append(f"{name}: {[f.columns for f in shown]}")
		self.assertFalse(
			over, msg="Lưới bảng con vượt tổng cột " + str(GRID_MAX_COLUMNS) + ": " + "; ".join(over)
		)

	def test_patient_code_never_gets_a_name_column(self):
		for name in _tracecore_doctypes():
			for df in frappe.get_meta(name).fields:
				if "patient" in df.fieldname:
					self.assertFalse(df.fieldname.endswith("_name"), msg=f"{name}.{df.fieldname}")

	def test_new_name_labels_have_vi_translation_with_doctype_context(self):
		with VI_CSV.open(encoding="utf-8", newline="") as f:
			rows = {(r[0], r[2] if len(r) > 2 else "") for r in csv.reader(f) if r}
		missing = []
		for doctype in _tracecore_doctypes():
			for df in frappe.get_meta(doctype).fields:
				if df.fetch_from and df.fetch_from.split(".")[0] + "_name" == df.fieldname:
					if (df.label, doctype) not in rows:
						missing.append(f"{doctype}.{df.fieldname} ({df.label})")
		self.assertFalse(missing, msg="Thiếu dịch (cột context = tên DocType): " + ", ".join(missing))


class TestBackfillNameColumns(FrappeTestCase):
	def test_backfill_fills_old_rows_in_parent_and_child_and_is_rerunnable(self):
		department = make_department("Khoa backfill A-65")
		set_type = make_set_type("BF65", set_type_name="Bộ backfill A-65", department=department).name
		make_instrument("BF65-I", name="Kẹp backfill A-65")
		make_bom(set_type, [("BF65-I", 2)])
		unit = make_set_unit(set_type=set_type)

		set_type_name = frappe.db.get_value("Instrument Set Type", set_type, "set_type_name")
		# giả lập dữ liệu cũ: các cột tên còn trống
		frappe.db.sql("update `tabSet Unit` set set_type_name = null where name = %s", unit.name)
		frappe.db.sql("update `tabSet BOM Item` set instrument_name = '' where set_type = %s", set_type)
		frappe.db.sql("update `tabSet BOM Item` set set_type_name = null where set_type = %s", set_type)

		backfill_name_columns.execute()
		self.assertEqual(frappe.db.get_value("Set Unit", unit.name, "set_type_name"), set_type_name)
		rows = frappe.get_all(
			"Set BOM Item", filters={"set_type": set_type}, fields=["instrument_name", "set_type_name"]
		)
		self.assertTrue(rows)
		for row in rows:
			self.assertEqual(row.instrument_name, "Kẹp backfill A-65")
			self.assertEqual(row.set_type_name, set_type_name)

		# chạy lại: không đổi gì, không ghi đè giá trị đã có
		frappe.db.set_value("Set Unit", unit.name, "set_type_name", "Giữ nguyên", update_modified=False)
		backfill_name_columns.execute()
		self.assertEqual(frappe.db.get_value("Set Unit", unit.name, "set_type_name"), "Giữ nguyên")

	def test_backfill_does_not_touch_modified(self):
		set_type = make_set_type("BF66").name
		unit = make_set_unit(set_type=set_type)
		frappe.db.sql("update `tabSet Unit` set set_type_name = null where name = %s", unit.name)
		before = frappe.db.get_value("Set Unit", unit.name, "modified")
		backfill_name_columns.execute()
		self.assertEqual(frappe.db.get_value("Set Unit", unit.name, "modified"), before)

	def test_backfill_works_in_small_batches(self):
		set_type = make_set_type("BF67").name
		units = [make_set_unit(set_type=set_type).name for _ in range(3)]
		frappe.db.sql("update `tabSet Unit` set set_type_name = null where set_type = %s", set_type)
		backfill_name_columns.execute(batch_size=2)
		for name in units:
			self.assertTrue(frappe.db.get_value("Set Unit", name, "set_type_name"))
