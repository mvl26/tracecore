"""Loại import Vật tư (Item ERPNext có nhóm CSSD) cho khung `core.importer` (FEAT-011 Task 7, FR-M9-11; A-41).

Ghi qua controller Item để luật vật tư FEAT-041 (`inventory.items.validate_item`: nhóm CSSD, phương pháp của nhãn/chỉ
thị, loại chỉ thị, tự bật lô/hạn dùng) chạy như nhập tay; vi phạm luật thành lỗi dòng.
"""

import frappe
from frappe import _

from tracecore.core.importer import Column, ImportKind, Issue
from tracecore.inventory.items import CSSD_GROUPS

ITEM_GROUP_ROOT = "All Item Groups"
METHODS = ("Steam", "Plasma")
CI_CLASSES = ("1", "2", "3", "4", "5", "6")


def _item_exists(code):
	return bool(frappe.db.exists("Item", code))


def _validate_item(unit):
	row = unit[0]
	values = row.values
	issues = []
	if not frappe.db.exists("UOM", values.get("stock_uom") or ""):
		issues.append(
			Issue(
				row.row,
				"UOM_NOT_FOUND",
				"stock_uom",
				_("Unit {0} does not exist.").format(values.get("stock_uom")),
			)
		)
	group = values.get("item_group") or ITEM_GROUP_ROOT
	if not frappe.db.exists("Item Group", group):
		issues.append(
			Issue(
				row.row,
				"ITEM_GROUP_NOT_FOUND",
				"item_group",
				_("Item group {0} does not exist.").format(group),
			)
		)
	return issues


def _write_item(unit):
	values = unit[0].values
	doc = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": values["item_code"],
			"item_name": values["item_name"],
			"item_group": values.get("item_group") or ITEM_GROUP_ROOT,
			"stock_uom": values["stock_uom"],
			"is_stock_item": 1,
			"tc_item_group_cssd": values["item_group_cssd"],
			"tc_compatible_method": values.get("compatible_method"),
			"tc_ci_class": values.get("ci_class"),
			"tc_shelf_life_days": values.get("shelf_life_days"),
			"tc_specification": values.get("specification"),
		}
	)
	return doc.insert().name


def import_kinds():
	"""Hook ``tracecore_import_kinds``."""
	return [
		ImportKind(
			key="item",
			label="Consumable items",
			doctype="Item",
			columns=[
				Column("item_code", "Item Code", required=True),
				Column("item_name", "Item Name", required=True),
				Column("item_group_cssd", "CSSD Group", required=True, kind="select", options=CSSD_GROUPS),
				Column(
					"stock_uom", "Unit", required=True, help="Unit of measure, for example Nos, Box, Litre."
				),
				Column("item_group", "Item Group", help="ERPNext item group; empty uses All Item Groups."),
				Column("compatible_method", "Compatible Method", kind="select", options=METHODS),
				Column("ci_class", "Indicator Class", kind="select", options=CI_CLASSES),
				Column("shelf_life_days", "Shelf Life (days)", kind="int"),
				Column("specification", "Specification"),
			],
			code_field="item_code",
			exists=_item_exists,
			validate=_validate_item,
			write=_write_item,
		)
	]
