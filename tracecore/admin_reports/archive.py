"""Gói hồ sơ tiệt khuẩn lưu trữ (M9, FEAT-012; FR-M9-12, OTH-RET-001, NFR-COMP-01, UC-39 bước 6, A3, E3; A-58).

`build` (job RQ ``long`` do `Archive Export.after_insert` xếp) gom bản ghi theo phạm vi (`related`: kỳ, một mẻ hoặc
một lệnh thu hồi → mẻ → gói → phiếu cấp phát → bản ghi sử dụng → Audit Log), sinh CSV UTF-8 có BOM và PDF (sổ tiệt
khuẩn, báo cáo KSNK của FEAT-007), `manifest.json` (SHA-256, số byte, số dòng từng file; giờ máy chủ có offset, người
xuất), nén ZIP, lưu File riêng tư đính vào phiếu và ghi SHA-256 của ZIP lên phiếu. `verify` tính lại SHA-256 của file
đang lưu. Chỉ đọc DocType theo tên (M9 không import M2). Mã bệnh nhân che, trừ phiếu R01 có lý do (A-58 Q2).
"""

import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, get_system_timezone, getdate, now_datetime
from frappe.utils.password import get_decrypted_password

from tracecore.admin_reports import sterilization_log

EXPORT = "Archive Export"
LOAD = "Sterilization Load"
SAVEPOINT = "tc_archive_build"
APP_NAME = "TraceCore"


# --- phạm vi (A-58 Q4, D1) ------------------------------------------------------------------------------------


def related(doc):
	"""Tên các bản ghi của gói: mẻ, dòng gói của mẻ, gói, phiếu cấp phát, bản ghi sử dụng, lệnh thu hồi."""
	if doc.scope_type == "Period":
		loads = frappe.get_all(
			LOAD,
			filters=[
				["status", "!=", "Running"],
				["started_at", ">=", getdate(doc.from_date)],
				["started_at", "<", add_days(getdate(doc.to_date), 1)],
			],
			pluck="name",
			order_by="started_at asc, name asc",
		)
	elif doc.scope_type == "Load":
		loads = [doc.sterilization_load]
	else:
		recall = frappe.get_doc("Recall Order", doc.recall_order)
		loads = [recall.sterilization_load] + [row.load for row in recall.packs]
		loads = [name for name in dict.fromkeys(loads) if name]
	load_packs = (
		frappe.get_all(
			"Load Pack",
			filters={"parent": ["in", loads], "parenttype": LOAD},
			fields=["parent", "pack", "set_unit"],
			order_by="parent asc, idx asc",
		)
		if loads
		else []
	)
	packs = [row.pack for row in load_packs]
	issue_rows = (
		frappe.db.sql(
			"""select p.parent as issue_note, p.pack, p.set_unit, n.issued_at, n.department, n.recipient_name,
				n.issued_by from `tabIssue Note Pack` p join `tabIssue Note` n on n.name = p.parent
			where p.parenttype = 'Issue Note' and n.docstatus = 1 and p.pack in %(packs)s
			order by n.issued_at asc, p.idx asc""",
			{"packs": packs},
			as_dict=True,
		)
		if packs
		else []
	)
	usage = (
		frappe.get_all(
			"Usage Record",
			filters={"pack": ["in", packs], "docstatus": ["<", 2]},
			pluck="name",
			order_by="used_at asc",
		)
		if packs
		else []
	)
	return frappe._dict(
		loads=loads,
		load_packs=load_packs,
		packs=packs,
		issue_rows=issue_rows,
		issue_notes=list(dict.fromkeys(row.issue_note for row in issue_rows)),
		usage=usage,
		recall=doc.recall_order,
	)


def _period(doc, rel):
	if doc.scope_type == "Period":
		return getdate(doc.from_date), getdate(doc.to_date)
	days = [
		getdate(day)
		for day in frappe.get_all(LOAD, filters={"name": ["in", rel.loads or [""]]}, pluck="started_at")
	]
	return (min(days), max(days)) if days else (getdate(), getdate())


# --- CSV ------------------------------------------------------------------------------------------------------


def _text(value):
	if value is None:
		return ""
	if isinstance(value, datetime):
		return value.isoformat(sep=" ")
	if isinstance(value, dict | list):
		return json.dumps(value, ensure_ascii=False, default=str)
	return str(value)


def _csv(columns, rows):
	out = io.StringIO()
	writer = csv.writer(out, lineterminator="\r\n")
	writer.writerow(columns)
	for row in rows:
		writer.writerow([_text(row.get(column)) for column in columns])
	return out.getvalue().encode("utf-8-sig")


def _loads_csv(rel):
	columns = [
		"load",
		"equipment",
		"program",
		"operator",
		"status",
		"cycle_result",
		"bi_result",
		"started_at",
		"ended_at",
		"data_source",
		"manual_reason",
		"unloaded_by",
		"released_by",
		"released_at",
		"release_reason",
		"out_of_range_accepted",
		"out_of_range_accepted_by",
		"out_of_range_approved_by",
		"out_of_range_reason",
	]
	rows = frappe.get_all(
		LOAD,
		filters={"name": ["in", rel.loads or [""]]},
		fields=["name", *columns[1:]],
		order_by="started_at asc",
	)
	for row in rows:
		row["load"] = row.pop("name")  # `load` là từ khóa SQL: không đặt alias trong câu truy vấn
	return columns, rows


def _indicators_csv(rel):
	columns = ["name", "load", "indicator", "pack", "result", "lot", "test_date", "read_at", "read_by"]
	return columns, frappe.get_all(
		"Load Indicator Result",
		filters={"load": ["in", rel.loads or [""]]},
		fields=columns,
		order_by="creation asc",  # không sắp theo `load`: từ khóa SQL, order_by không được bọc dấu `
	)


def _machine_csv(rel):
	columns = ["load", "parameter_name", "unit", "value", "min_value", "max_value", "outside_range"]
	rows = []
	for load in frappe.get_all(
		LOAD,
		filters={"name": ["in", rel.loads or [""]]},
		fields=["name", "params"],
		order_by="started_at asc",
	):
		try:
			params = frappe.parse_json(load.params) if load.params else []
		except Exception:
			params = []
		for param in params if isinstance(params, list) else []:
			if isinstance(param, dict):
				rows.append({"load": load.name, **{key: param.get(key) for key in columns[1:]}})
	return columns, rows


def _load_packs_csv(rel):
	columns = ["load", "pack", "set_unit", "set_id", "set_type", "department", "cycle_no", "expiry", "status"]
	packs = {
		row.name: row
		for row in frappe.get_all(
			"Pack",
			filters={"name": ["in", rel.packs or [""]]},
			fields=["name", "set_type", "department", "cycle_no", "expiry", "status"],
		)
	}
	set_ids = dict(
		frappe.get_all(
			"Set Unit",
			filters={"name": ["in", [row.set_unit for row in rel.load_packs] or [""]]},
			fields=["name", "set_id"],
			as_list=True,
		)
	)
	rows = []
	for row in rel.load_packs:
		pack = packs.get(row.pack) or frappe._dict()
		rows.append(
			{
				"load": row.parent,
				"pack": row.pack,
				"set_unit": row.set_unit,
				"set_id": set_ids.get(row.set_unit),
				**{key: pack.get(key) for key in ("set_type", "department", "cycle_no", "expiry", "status")},
			}
		)
	return columns, rows


def _issues_csv(rel):
	columns = ["issue_note", "issued_at", "department", "recipient_name", "issued_by", "pack", "set_unit"]
	return columns, rel.issue_rows


def _usage_csv(doc, rel):
	columns = [
		"usage_record",
		"pack",
		"set_unit",
		"department",
		"used_at",
		"patient_code",
		"emergency",
		"surgery_code",
		"surgeon",
		"room",
		"scanned_by",
	]
	rows = []
	for name in rel.usage:
		record = frappe.get_doc("Usage Record", name)
		code = (
			get_decrypted_password("Usage Record", name, "patient_code", raise_exception=False)
			if doc.full_patient_code
			else record.patient_code_masked
		)
		rows.append(
			{
				"usage_record": name,
				"patient_code": code,
				**{key: record.get(key) for key in columns if key not in ("usage_record", "patient_code")},
			}
		)
	return columns, rows


def _audit_csv(rel):
	columns = [
		"timestamp",
		"user",
		"action",
		"ref_doctype",
		"ref_name",
		"station",
		"reason",
		"old_value",
		"new_value",
	]
	indicators = frappe.get_all(
		"Load Indicator Result", filters={"load": ["in", rel.loads or [""]]}, pluck="name"
	)
	refs = {
		LOAD: rel.loads,
		"Load Indicator Result": indicators,
		"Pack": rel.packs,
		"Issue Note": rel.issue_notes,
		"Usage Record": rel.usage,
		"Recall Order": [rel.recall] if rel.recall else [],
	}
	rows = []
	for doctype, names in refs.items():
		if names:
			rows += frappe.get_all(
				"Audit Log",
				filters={"ref_doctype": doctype, "ref_name": ["in", names]},
				fields=columns,
				order_by="timestamp asc",
			)
	return columns, sorted(rows, key=lambda row: (row.timestamp or datetime.min, row.ref_name or ""))


def _files(doc, rel):
	"""``[(tên file, nội dung bytes, số dòng)]`` theo phạm vi chọn; PDF dùng lại bản in của FEAT-007."""
	start, end = _period(doc, rel)
	filters = {"from_date": str(start), "to_date": str(end)}
	if doc.scope_type != "Period":
		filters["loads"] = rel.loads
	files = [
		("sterilization_log.pdf", sterilization_log.render_pdf("sterilization_log", filters), len(rel.loads))
	]
	if doc.scope_type == "Period":
		files.append(("ksnk_summary.pdf", sterilization_log.render_pdf("ksnk_summary", filters), None))
	builders = (
		("inc_loads", "loads.csv", lambda: _loads_csv(rel)),
		("inc_indicators", "indicators.csv", lambda: _indicators_csv(rel)),
		("inc_machine_data", "machine_data.csv", lambda: _machine_csv(rel)),
		("inc_loads", "load_packs.csv", lambda: _load_packs_csv(rel)),
		("inc_issues", "issues.csv", lambda: _issues_csv(rel)),
		("inc_usage", "usage.csv", lambda: _usage_csv(doc, rel)),
		("inc_audit", "audit.csv", lambda: _audit_csv(rel)),
	)
	for flag, name, build_rows in builders:
		if doc.get(flag):
			columns, rows = build_rows()
			files.append((name, _csv(columns, rows), len(rows)))
	return files


# --- job ------------------------------------------------------------------------------------------------------


def _iso_with_offset(value):
	return get_datetime(value).replace(tzinfo=ZoneInfo(get_system_timezone())).isoformat(timespec="seconds")


def _set(doc, **values):
	doc.flags.tc_archive = True
	doc.update(values)
	doc.save(ignore_permissions=True)


def _notify(doc, subject):
	frappe.get_doc(
		{
			"doctype": "Notification Log",
			"for_user": doc.requested_by,
			"type": "Alert",
			"subject": subject,
			"document_type": EXPORT,
			"document_name": doc.name,
		}
	).insert(ignore_permissions=True)
	frappe.publish_realtime("tc_archive_ready", {"name": doc.name}, user=doc.requested_by, after_commit=True)


def build(name, lang=None):
	"""Sinh gói ZIP của phiếu `name`; lỗi → trạng thái Failed + thông báo (A-58 D3)."""
	doc = frappe.get_doc(EXPORT, name)
	sterilization_log.use_language(lang, doc.requested_by)
	_set(doc, status="Running")
	frappe.db.savepoint(SAVEPOINT)
	try:
		rel = related(doc)
		files = _files(doc, rel)
		generated_at = now_datetime()
		provisional = int(not sterilization_log.is_locked(_period(doc, rel)[1]))
		manifest = {
			"export": doc.name,
			"application": APP_NAME,
			"scope": {
				"type": doc.scope_type,
				"from_date": str(doc.from_date) if doc.from_date else None,
				"to_date": str(doc.to_date) if doc.to_date else None,
				"sterilization_load": doc.sterilization_load,
				"recall_order": doc.recall_order,
			},
			"generated_at": _iso_with_offset(generated_at),
			"generated_by": doc.requested_by,
			"provisional": bool(provisional),
			"full_patient_codes": bool(doc.full_patient_code),
			"files": [
				{
					"name": file_name,
					"sha256": hashlib.sha256(content).hexdigest(),
					"bytes": len(content),
					"rows": rows,
				}
				for file_name, content, rows in files
			],
		}
		manifest_text = json.dumps(manifest, ensure_ascii=False, indent=1)
		buffer = io.BytesIO()
		with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
			for file_name, content, _rows in files:
				archive.writestr(file_name, content)
			archive.writestr("manifest.json", manifest_text.encode("utf-8"))
		content = buffer.getvalue()
		file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{doc.name}.zip",
				"content": content,
				"is_private": 1,
				"attached_to_doctype": EXPORT,
				"attached_to_name": doc.name,
				"attached_to_field": "archive_file",
			}
		).insert(ignore_permissions=True)
		_set(
			doc,
			status="Completed",
			archive_file=file.file_url,
			sha256=hashlib.sha256(content).hexdigest(),
			file_size=len(content),
			provisional=provisional,
			generated_at=generated_at,
			manifest=manifest_text,
			error=None,
		)
		_notify(doc, _("Archive export {0} is ready").format(doc.name))
	except Exception as error:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.log_error(title=_("Archive export failed"), message=frappe.get_traceback())
		doc.reload()
		_set(doc, status="Failed", error=str(error)[:500])
		_notify(doc, _("Archive export {0} failed").format(doc.name))
	return doc.name


def verify(name):
	"""So SHA-256 của file ZIP đang lưu với giá trị ghi trên phiếu."""
	doc = frappe.get_doc(EXPORT, name)
	if doc.status != "Completed" or not doc.archive_file:
		return {"ok": False, "sha256": None, "expected": doc.sha256}
	content = frappe.get_doc("File", {"file_url": doc.archive_file}).get_content()
	actual = hashlib.sha256(content).hexdigest()
	return {"ok": actual == doc.sha256, "sha256": actual, "expected": doc.sha256}
