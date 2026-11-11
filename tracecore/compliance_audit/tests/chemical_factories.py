"""Dữ liệu test hóa chất KSNK và đơn vị thuê ngoài (FEAT-066; A-142)."""

import frappe
from frappe.utils import today

from tracecore.compliance_audit import chemicals
from tracecore.tests import factories

LITRE = "Litre"
BOTTLE = "TC Chai 500ml"


def ensure_uoms():
	factories.ensure_item_masters()
	for uom in (LITRE, BOTTLE):
		if not frappe.db.exists("UOM", uom):
			frappe.get_doc({"doctype": "UOM", "uom_name": uom, "enabled": 1}).insert(ignore_permissions=True)


def make_chemical(code, chemical_type="Hand Rub", stock_uom=LITRE, litre_factor=None):
	"""Item hóa chất KSNK; ``litre_factor``: số đơn vị kho trong 1 lít (UOM Conversion "Litre" của Item)."""
	ensure_uoms()
	if frappe.db.exists("Item", code):
		return code
	doc = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": code,
			"item_name": code,
			"item_group": factories.ITEM_GROUP_ROOT,
			"stock_uom": stock_uom,
			"is_stock_item": 1,
			"tc_ic_chemical_type": chemical_type,
		}
	)
	if litre_factor:
		doc.append("uoms", {"uom": LITRE, "conversion_factor": litre_factor})
	doc.flags.tc_legacy_data = True
	return doc.insert(ignore_permissions=True).name


def ward_warehouse(name, department):
	warehouse = factories.make_warehouse(name)
	frappe.db.set_value("Warehouse", warehouse, "tc_department", department)
	return warehouse


def make_transfer(item, qty, target, source=None, submit=True, posting_date=None):
	"""Stock Entry Material Receipt vào kho nguồn rồi Material Transfer sang ``target`` (kho khoa)."""
	masters = factories.ensure_stock_masters()
	source = source or masters["warehouse"]
	stock_uom = frappe.db.get_value("Item", item, "stock_uom")
	if not frappe.db.exists("Stock Entry Type", "Material Transfer"):
		frappe.get_doc(
			{"doctype": "Stock Entry Type", "name": "Material Transfer", "purpose": "Material Transfer"}
		).insert(ignore_permissions=True)
	line = {"item_code": item, "qty": qty, "uom": stock_uom, "stock_uom": stock_uom, "conversion_factor": 1}
	receipt = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Receipt",
			"purpose": "Material Receipt",
			"company": masters["company"],
			"posting_date": posting_date or today(),
			"set_posting_time": 1,
			"items": [{**line, "t_warehouse": source, "basic_rate": 1000}],
		}
	).insert(ignore_permissions=True)
	receipt.submit()
	doc = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": masters["company"],
			"posting_date": posting_date or today(),
			"set_posting_time": 1,
			"items": [{**line, "s_warehouse": source, "t_warehouse": target}],
		}
	).insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


def record(item, department, qty=1.0, period=None, source=chemicals.MANUAL, **values):
	"""Một bản ghi đã ghi sổ qua dịch vụ (bỏ kiểm quyền: dữ liệu test)."""
	return chemicals.record(
		{
			"period": period or today()[:7],
			"department": department,
			"item": item,
			"qty": qty,
			"source_note": values.pop("source_note", "Test note") if source == chemicals.MANUAL else None,
			**values,
		},
		source=source,
	)


def make_vendor(name, service="Industrial Cleaning", license_expiry=None, contract=(None, None)):
	supplier = factories.make_supplier(name)
	frappe.db.set_value(
		"Supplier",
		supplier,
		{
			"tc_ic_service_type": service,
			"tc_license_no": f"GP-{name[:6]}",
			"tc_license_expiry": license_expiry,
			"tc_contract_from": contract[0],
			"tc_contract_to": contract[1],
		},
	)
	return supplier
