"""Chuyển đổi site đang chạy sang A-64 (FEAT-051): kiểm tra trước, sơ đồ yhct, năng lực theo CSV R02 duyệt.

Chạy thủ công qua ``bench --site <SITE> execute tracecore.setup.migrate_a64.<hàm>``. Mọi hàm ghi mặc định ``dry_run=True``:
chỉ trả kế hoạch, hoàn tác toàn bộ. Không hàm nào tự chạy khi migrate.
"""

import csv
import json
from pathlib import Path

import frappe
from frappe.utils import cint, now_datetime

from tracecore.core import audit, zones

# Link tới Zone Station không phải chứng từ phát sinh tại trạm
NOT_DOCUMENTS = {
	"Zone Station",
	"Station Competency",
	"Station Session",
	"Printer",
	"Code Range",
	"Code Registry",
}

PLAN_FILE = Path(__file__).with_name("yhct_plan.json")
COUNTED = ("Station Competency", "Equipment", "Sterile Location", "Step Gate Result", "Zone Station")
IN_PROGRESS = (
	("Wash Batch", {"status": "Running"}),
	("Assembly Record", {"docstatus": 0}),
	("Dirty Receipt", {"docstatus": 0}),
	("Sterilization Load", {"docstatus": 0}),
)
CSV_FIELDS = (
	"competency",
	"employee",
	"old_station",
	"old_function",
	"valid_until",
	"suggested_stations",
	"new_stations",
	"approved",
)
REVOKE_REASON = "A-64"


def _document_links():
	"""``{doctype: [fieldname]}`` các chứng từ có Link tới Zone Station."""
	links = {}
	for row in frappe.get_all(
		"DocField", filters={"fieldtype": "Link", "options": "Zone Station"}, fields=["parent", "fieldname"]
	):
		meta = frappe.get_meta(row.parent)
		if row.parent not in NOT_DOCUMENTS and not meta.issingle and not meta.istable:
			links.setdefault(row.parent, []).append(row.fieldname)
	return links


def station_documents(station, links=None):
	"""Số chứng từ theo DocType đã phát sinh tại trạm; rỗng = đổi nghĩa trạm không làm sai lịch sử."""
	counts = {}
	for doctype, fieldnames in (links or _document_links()).items():
		for fieldname in fieldnames:
			count = frappe.db.count(doctype, {fieldname: station})
			if count:
				counts[doctype] = counts.get(doctype, 0) + count
	return counts


def preflight():
	"""Báo cáo chỉ đọc trước khi chuyển đổi (A-64 bước 0). Backup và đồng bộ hàng đợi kiosk/PDA là việc của người vận hành."""
	links = _document_links()
	stations = frappe.get_all(
		"Zone Station",
		filters={"is_zone": 0},
		fields=["name", "zone_station_name", "parent_zone", "is_active", "station_no"],
		order_by="name asc",
	)
	report = {
		"counts": {doctype: frappe.db.count(doctype) for doctype in COUNTED},
		"stations": [
			{
				**row,
				"documents": station_documents(row.name, links),
				"functions": zones.station_functions(row.name),
			}
			for row in stations
		],
		"in_progress": {
			doctype: frappe.get_all(doctype, filters=filters, pluck="name")
			for doctype, filters in IN_PROGRESS
		},
		"active_competencies": frappe.db.count("Station Competency", {"is_active": 1}),
		"open_sync_conflicts": frappe.db.count("Sync Conflict", {"status": "Open"}),
		"temp_property_setter": bool(
			frappe.db.exists("Property Setter", "Zone Station-station_step-options")
		),
	}
	print(json.dumps(report, indent=1, ensure_ascii=False, default=str))
	return report


def _zone_of_type(zone_type):
	rows = frappe.get_all(
		"Zone Station", filters={"is_zone": 1, "zone_type": zone_type}, pluck="name", order_by="name asc"
	)
	if not rows:
		frappe.throw(f"No zone of type {zone_type}.")
	return rows[0]


def _functions_changed(station, functions):
	return set(zones.station_functions(station)) != set(functions)


def _clear_numbers(plan):
	"""Bỏ số các trạm trong kế hoạch trước khi đánh lại, để không vướng ràng buộc trùng số giữa chừng."""
	for _no, station, *_rest in plan:
		if frappe.db.exists("Zone Station", station):
			frappe.db.set_value("Zone Station", station, "station_no", 0, update_modified=False)


def _retire(station):
	doc = frappe.get_doc("Zone Station", station)
	doc.is_active = 0
	doc.save(ignore_permissions=True)


def _apply_row(number, station, zone, label, functions):
	values = {
		"zone_station_name": label,
		"parent_zone": zone,
		"station_no": number,
		"is_active": 1,
		"functions": [{"station_function": function} for function in functions],
	}
	if station and frappe.db.exists("Zone Station", station):
		doc = frappe.get_doc("Zone Station", station)
		doc.update(values)
		return doc.save(ignore_permissions=True).name
	doc = frappe.get_doc({"doctype": "Zone Station", "is_zone": 0, **values})
	# tên trống: chứng từ cũ vẫn gắn TR cũ, trạm thay thế lấy mã kế tiếp và phải in lại nhãn QR
	return (
		doc.insert(ignore_permissions=True, set_name=station).name
		if station
		else doc.insert(ignore_permissions=True).name
	)


def load_plan(path=PLAN_FILE):
	"""Sơ đồ trạm của site: ``[số trạm, trạm, loại vùng, tên trạm, [chức năng]]``; số 0 = không đánh số (A-64 Q4)."""
	return json.loads(Path(path).read_text(encoding="utf-8"))


def apply_yhct(dry_run=True, plan=None):
	"""Áp sơ đồ yhct; trả ``[{"no", "station", "action", ...}]``.

	Trạm đã có chứng từ mà chức năng đổi thì KHÔNG đổi nghĩa: tắt trạm cũ, tạo trạm mới cùng số T (truy vết lịch sử giữ
	đúng). Trạm cũ không xóa. ``dry_run`` hoàn tác mọi thứ sau khi chạy thử, nên lỗi validate cũng lộ ra ở bước này.
	"""
	dry_run = cint(dry_run) if not isinstance(dry_run, str) else dry_run.lower() not in ("0", "false", "no")
	plan = plan or load_plan()
	frappe.db.savepoint("a64_yhct")
	links = _document_links()
	result = []
	try:
		_clear_numbers(plan)
		replaced = []
		for row in plan:
			number, station, zone_type, label, functions = row
			documents = station_documents(station, links) if frappe.db.exists("Zone Station", station) else {}
			if documents and _functions_changed(station, functions):
				_retire(station)
				replaced.append((row, documents))
				continue
			action = "updated" if frappe.db.exists("Zone Station", station) else "created"
			name = _apply_row(number, station, _zone_of_type(zone_type), label, functions)
			result.append({"no": number, "station": name, "action": action})
		# trạm thay thế lấy mã tự sinh: tạo sau cùng để không chiếm mã TR đã có trong kế hoạch
		for (number, station, zone_type, label, functions), documents in replaced:
			name = _apply_row(number, None, _zone_of_type(zone_type), label, functions)
			result.append(
				{
					"no": number,
					"station": name,
					"action": "replaced",
					"retired": station,
					"documents": documents,
				}
			)
		audit.log("Update", "Zone Station", "A-64", old=None, new={"yhct_plan": result})
	except Exception:
		frappe.db.rollback(save_point="a64_yhct")
		raise
	if dry_run:
		frappe.db.rollback(save_point="a64_yhct")
	print(json.dumps({"dry_run": bool(dry_run), "plan": result}, indent=1, ensure_ascii=False))
	return result


def _old_function(station):
	"""Chức năng cũ của trạm theo mã trước migration; đây là công việc mà năng lực đã được đánh giá."""
	from tracecore.patches.v0_1.a64_configurable_stations import FUNCTIONS_BY_STEP

	return FUNCTIONS_BY_STEP.get(frappe.db.get_value("Zone Station", station, "legacy_step"), ())


def competency_csv(path):
	"""Xuất năng lực còn hiệu lực ra CSV để R02 duyệt: điền ``new_stations`` (cách nhau ``;``) và ``approved`` (1 hoặc 0)."""
	rows = frappe.get_all(
		"Station Competency",
		filters={"is_active": 1, "valid_until": [">=", now_datetime()]},
		fields=["name", "employee", "station", "valid_until"],
		order_by="employee asc, station asc",
	)
	with open(path, "w", newline="", encoding="utf-8-sig") as handle:
		writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
		writer.writeheader()
		for row in rows:
			functions = _old_function(row.station)
			suggested = []
			for function in functions:
				suggested += [s for s in zones.stations_with_function(function) if s not in suggested]
			writer.writerow(
				{
					"competency": row.name,
					"employee": row.employee,
					"old_station": row.station,
					"old_function": ";".join(functions),
					"valid_until": row.valid_until,
					"suggested_stations": ";".join(suggested),
					"new_stations": "",
					"approved": "",
				}
			)
	print(f"{len(rows)} competencies written to {path}")
	return len(rows)


def _copy_competency(source, station):
	doc = frappe.get_doc("Station Competency", source)
	return (
		frappe.get_doc(
			{
				"doctype": "Station Competency",
				"employee": doc.employee,
				"station": station,
				"valid_from": doc.valid_from,
				"valid_until": doc.valid_until,
				"evaluator": doc.evaluator,
				"evaluated_on": doc.evaluated_on,
				"is_temporary": doc.is_temporary,
				"temporary_reason": doc.temporary_reason,
				"approved_by": doc.approved_by,
				"required_certificates": [
					{"certificate_type": row.certificate_type} for row in doc.required_certificates
				],
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _revoke(name):
	doc = frappe.get_doc("Station Competency", name)
	doc.is_active = 0
	doc.revoke_reason = REVOKE_REASON
	doc.save(ignore_permissions=True)


def apply_competency_csv(path, dry_run=True):
	"""Áp CSV R02 đã duyệt. Mọi dòng phải có ``approved`` 1 hoặc 0, thiếu là từ chối cả file: không có năng lực nào giữ nghĩa
	trạm cũ một cách âm thầm. Bản cũ chỉ ``is_active = 0``, không xóa; ``approved = 1`` tạo bản mới ở từng trạm ``new_stations``.
	"""
	dry_run = cint(dry_run) if not isinstance(dry_run, str) else dry_run.lower() not in ("0", "false", "no")
	with open(path, newline="", encoding="utf-8-sig") as handle:
		rows = list(csv.DictReader(handle))
	undecided = [row["competency"] for row in rows if row["approved"].strip() not in ("0", "1")]
	if undecided:
		frappe.throw(f"Rows without a decision: {', '.join(undecided)}")
	frappe.db.savepoint("a64_competency")
	created, revoked = [], []
	try:
		for row in rows:
			stations = [s.strip() for s in row["new_stations"].split(";") if s.strip()]
			if row["approved"].strip() == "1":
				if not stations:
					frappe.throw(f"Competency {row['competency']} is approved without a new station.")
				created += [_copy_competency(row["competency"], station) for station in stations]
			_revoke(row["competency"])
			revoked.append(row["competency"])
	except Exception:
		frappe.db.rollback(save_point="a64_competency")
		raise
	if dry_run:
		frappe.db.rollback(save_point="a64_competency")
	summary = {"dry_run": bool(dry_run), "created": len(created), "revoked": len(revoked)}
	print(json.dumps(summary))
	return summary
