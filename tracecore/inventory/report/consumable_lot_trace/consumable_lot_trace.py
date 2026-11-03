"""Consumable Lot Trace: từ một lô vật tư ra mọi lô rửa, mẻ tiệt khuẩn, test đầu ngày và phiếu xuất đã dùng lô đó
(A-112 D14; FR-M6-08), để thu hồi khi lô lỗi.

Nguồn: phiếu xuất đã ghi sổ có lô (dòng phiếu hoặc Serial and Batch Bundle), dòng `Run Consumable.batch`,
`Wash Batch Chemical.lot`, `Load Indicator Result.batch`, `Daily Test.batch`. Mỗi dòng báo cáo là một chứng từ nguồn;
phiếu xuất của lô/mẻ/test gộp vào dòng của nguồn đó (`tc_source_doctype`, `tc_source_name`), phiếu xuất tay đứng riêng.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

PRECISION = 6
WASH, LOAD, DAILY, ENTRY = "Wash Batch", "Sterilization Load", "Daily Test", "Stock Entry"
DATE_FIELDS = {WASH: "started_at", LOAD: "started_at", DAILY: "started_at"}
STATUS_FIELDS = {WASH: "status", LOAD: "status", DAILY: "result"}


def _columns():
	return [
		{"fieldname": "source_type", "label": _("Source Type"), "fieldtype": "Data", "width": 140},
		{
			"fieldname": "source",
			"label": _("Source"),
			"fieldtype": "Dynamic Link",
			"options": "source_type",
			"width": 170,
		},
		{"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{
			"fieldname": "equipment",
			"label": _("Machine"),
			"fieldtype": "Link",
			"options": "Equipment",
			"width": 110,
		},
		{"fieldname": "equipment_name", "label": _("Equipment Name"), "fieldtype": "Data", "width": 160},
		{"fieldname": "item", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 130},
		{"fieldname": "recorded_qty", "label": _("Recorded Quantity"), "fieldtype": "Float", "width": 110},
		{"fieldname": "issued_qty", "label": _("Issued Quantity"), "fieldtype": "Float", "width": 110},
		{
			"fieldname": "stock_entry",
			"label": _("Stock Entry"),
			"fieldtype": "Link",
			"options": "Stock Entry",
			"width": 150,
		},
		{"fieldname": "packs", "label": _("Packs"), "fieldtype": "Int", "width": 70},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 110},
	]


def _issued(batch):
	"""``{phiếu xuất đã ghi sổ: số lượng xuất của lô}`` từ dòng phiếu, hoặc từ Serial and Batch Bundle khi dòng không ghi lô."""
	issued = {}
	for row in frappe.db.sql(
		"""
		select sed.parent, sum(sed.transfer_qty) as qty
		from `tabStock Entry Detail` sed join `tabStock Entry` se on se.name = sed.parent
		where sed.batch_no = %s and se.docstatus = 1 and ifnull(sed.s_warehouse, '') != ''
		group by sed.parent
		""",
		batch,
		as_dict=True,
	):
		issued[row.parent] = flt(row.qty, PRECISION)
	for row in frappe.db.sql(
		"""
		select sbb.voucher_no as parent, sum(abs(sbe.qty)) as qty
		from `tabSerial and Batch Entry` sbe join `tabSerial and Batch Bundle` sbb on sbb.name = sbe.parent
		where sbe.batch_no = %s and sbb.voucher_type = 'Stock Entry' and sbb.docstatus = 1
			and sbb.is_cancelled = 0 and sbb.type_of_transaction = 'Outward'
		group by sbb.voucher_no
		""",
		batch,
		as_dict=True,
	):
		issued.setdefault(row.parent, flt(row.qty, PRECISION))
	return issued


def _recorded(batch):
	"""``{(DocType nguồn, tên): số đã ghi trên chứng từ}`` từ các trường lô của lô/mẻ/test và kết quả chỉ thị."""
	recorded = {}

	def add(key, qty):
		recorded[key] = flt(recorded.get(key, 0) + flt(qty), PRECISION)

	for row in frappe.get_all(
		"Run Consumable",
		filters={"batch": batch, "parenttype": ["in", (WASH, LOAD, DAILY)]},
		fields=["parenttype", "parent", "actual_qty"],
	):
		add((row.parenttype, row.parent), row.actual_qty)
	for row in frappe.get_all(
		"Wash Batch Chemical", filters={"lot": batch, "parenttype": WASH}, fields=["parent", "qty"]
	):
		add((WASH, row.parent), row.qty)
	for row in frappe.get_all(
		"Load Indicator Result", filters={"batch": batch}, fields=["load", "wash_batch"]
	):
		if row.load or row.wash_batch:
			add((LOAD, row.load) if row.load else (WASH, row.wash_batch), 1)
	for name in frappe.get_all(DAILY, filters={"batch": batch}, pluck="name"):
		recorded.setdefault((DAILY, name), 0)
	return recorded


def _source_row(doctype, name):
	if doctype == ENTRY:
		entry = (
			frappe.db.get_value(ENTRY, name, ["posting_date", "docstatus"], as_dict=True) or frappe._dict()
		)
		return {
			"date": entry.posting_date,
			"status": _("Cancelled") if entry.docstatus == 2 else _("Submitted"),
		}
	doc = frappe.db.get_value(
		doctype,
		name,
		["equipment", DATE_FIELDS[doctype], STATUS_FIELDS[doctype], "docstatus"],
		as_dict=True,
	)
	if not doc:
		return {}
	started = doc.get(DATE_FIELDS[doctype])
	status = doc.get(STATUS_FIELDS[doctype])
	return {
		"date": getdate(started) if started else None,
		"equipment": doc.equipment,
		"equipment_name": doc.equipment and frappe.db.get_value("Equipment", doc.equipment, "equipment_name"),
		"status": _("Cancelled") if doc.docstatus == 2 else (_(status) if status else ""),
		"packs": frappe.db.count("Load Pack", {"parent": name, "parenttype": LOAD})
		if doctype == LOAD
		else None,
	}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	batch = filters.get("batch")
	if not batch:
		return _columns(), []
	item = frappe.db.get_value("Batch", batch, "item")
	recorded = _recorded(batch)
	issued = {}
	entries = {}
	for entry, qty in _issued(batch).items():
		source = frappe.db.get_value(ENTRY, entry, ["tc_source_doctype", "tc_source_name"], as_dict=True)
		key = (
			(source.tc_source_doctype, source.tc_source_name)
			if source and source.tc_source_doctype in (WASH, LOAD, DAILY) and source.tc_source_name
			else (ENTRY, entry)
		)
		issued[key] = flt(issued.get(key, 0) + qty, PRECISION)
		entries.setdefault(key, entry)
	data = []
	for key in {**recorded, **issued}:
		doctype, name = key
		data.append(
			{
				"source_type": doctype,
				"source": name,
				"item": item,
				"recorded_qty": recorded.get(key),
				"issued_qty": issued.get(key, 0),
				"stock_entry": entries.get(key),
				**_source_row(doctype, name),
			}
		)
	data.sort(key=lambda row: (row.get("date") or getdate("1900-01-01"), row["source_type"], row["source"]))
	return _columns(), data
