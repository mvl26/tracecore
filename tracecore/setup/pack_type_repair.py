"""Thống nhất danh sách loại gói của chương trình máy tiệt khuẩn (A-83, A-97; ticket #1839 T5-06, #1843 T4-03). Chạy tay.

Nhóm `Packaging` là danh mục duy nhất. Mỗi chương trình thường còn dùng của máy hấp/plasma nhận đúng các Item `Packaging`
còn dùng có `tc_compatible_method` trùng phương pháp của máy; mã khác bị bỏ. Item để trống phương pháp không được thêm mà
liệt kê để R10 rà. Chương trình test và chương trình đã ngừng dùng không đụng tới. Phụ kiện truyền qua `accessories` chuyển
sang nhóm `Packaging Accessory`. Không xóa Item, không đổi Pack hay mẻ.

Không có `@frappe.whitelist`: chỉ gọi được bằng `bench execute`, và chỉ với Administrator.
"""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core import audit
from tracecore.equipment.doctype.process_program.process_program import KIND_REGULAR, PACKAGING_GROUP
from tracecore.reprocessing import sterilizing

ACCESSORY_GROUP = "Packaging Accessory"
EVENT = "PackTypeListsRepaired"
PROGRAM = "Process Program"
SAVEPOINT = "tc_pack_type_repair"
OPEN_PACK_STATUSES = (sterilizing.LOADABLE, sterilizing.IN_LOAD)


def _codes(accessories):
	"""Danh sách mã từ list hoặc chuỗi cách nhau bằng dấu phẩy; bỏ trùng, giữ thứ tự."""
	if isinstance(accessories, str):
		accessories = accessories.split(",")
	return list(dict.fromkeys(code.strip() for code in accessories or [] if code and code.strip()))


def _classify_accessories(codes):
	"""``(move, already, refused)``: phụ kiện cần chuyển, đã chuyển từ lần trước, và mã không chuyển được."""
	move, already, refused = [], [], []
	for code in codes:
		exists = frappe.db.exists("Item", code)
		group = frappe.db.get_value("Item", code, "tc_item_group_cssd") if exists else None
		if group == PACKAGING_GROUP:
			move.append(code)
		elif group == ACCESSORY_GROUP:
			already.append(code)
		else:
			refused.append({"item": code, "reason": "not_packaging" if exists else "not_found"})
	return move, already, refused


def _targets(excluded):
	"""``({method: set(mã)}, [mã để trống phương pháp])`` của Item `Packaging` còn dùng, trừ phụ kiện sắp chuyển."""
	targets = {method: set() for method in sterilizing.STERILIZER_TYPES.values()}
	blank = []
	for item in frappe.get_all(
		"Item",
		filters={"tc_item_group_cssd": PACKAGING_GROUP, "disabled": 0},
		fields=["name", "tc_compatible_method"],
		order_by="name asc",
	):
		if item.name in excluded:
			continue
		if not item.tc_compatible_method:
			blank.append(item.name)
		elif item.tc_compatible_method in targets:
			targets[item.tc_compatible_method].add(item.name)
	return targets, blank


def _programs():
	"""``[(tên chương trình, phương pháp)]`` của chương trình thường còn dùng trên máy hấp/plasma."""
	machines = dict(
		frappe.get_all(
			"Equipment",
			filters={"equipment_type": ["in", list(sterilizing.STERILIZER_TYPES)]},
			fields=["name", "equipment_type"],
			as_list=True,
		)
	)
	if not machines:
		return []
	rows = frappe.get_all(
		PROGRAM,
		filters={"equipment": ["in", list(machines)], "is_active": 1},
		fields=["name", "equipment", "program_kind"],
		order_by="name asc",
	)
	return [
		(row.name, sterilizing.STERILIZER_TYPES[machines[row.equipment]])
		for row in rows
		if (row.program_kind or KIND_REGULAR) == KIND_REGULAR
	]


def _current_codes(program):
	return frappe.get_all(
		"Program Compatible Pack Type",
		filters={"parent": program, "parenttype": PROGRAM},
		pluck="pack_type",
		order_by="idx asc",
	)


def _incompatible_open_packs(method, target):
	return [
		{"pack": pack.name, "status": pack.status, "pack_type": pack.pack_type}
		for pack in frappe.get_all(
			"Pack",
			filters={"docstatus": 1, "status": ["in", OPEN_PACK_STATUSES], "method": method},
			fields=["name", "status", "pack_type"],
			order_by="name asc",
		)
		if pack.pack_type not in target
	]


def _move_accessory(code):
	item = frappe.get_doc("Item", code, for_update=True)
	item.tc_item_group_cssd = ACCESSORY_GROUP
	item.save()
	audit.log(
		"Update",
		"Item",
		code,
		old={"tc_item_group_cssd": PACKAGING_GROUP},
		new={"event": EVENT, "tc_item_group_cssd": ACCESSORY_GROUP},
		reason=EVENT,
	)


def _save_program(name, added, removed):
	doc = frappe.get_doc(PROGRAM, name, for_update=True)
	doc.compatible_pack_types = [row for row in doc.compatible_pack_types if row.pack_type not in removed]
	for code in added:
		doc.append("compatible_pack_types", {"pack_type": code})
	doc.save()
	audit.log(
		"Update",
		PROGRAM,
		name,
		old={"removed": removed},
		new={"event": EVENT, "added": added},
		reason=EVENT,
	)


def _apply(move, changes):
	frappe.db.savepoint(SAVEPOINT)
	try:
		for code in move:
			_move_accessory(code)
		for name, added, removed in changes:
			_save_program(name, added, removed)
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		raise


def run(dry_run=1, accessories=None):
	"""Xem trước (mặc định) hoặc sửa với ``dry_run=0``; chạy lại an toàn. Trả bản tóm tắt theo phương pháp của máy.

	``{"dry_run", "applied", "accessories_moved", "accessories_already_moved", "accessories_refused",
	"blank_method_items", "methods": {method: {"programs", "programs_changed", "packaging_items", "codes_added",
	"codes_removed", "open_packs_incompatible"}}}``. Việc ghi nằm trong một savepoint: lỗi bất kỳ hoàn tác hết rồi ném lại.
	"""
	if frappe.session.user != "Administrator":
		frappe.throw(_("Only Administrator can run this repair."), frappe.PermissionError)
	dry_run = bool(cint(dry_run))
	move, already, refused = _classify_accessories(_codes(accessories))
	if refused and not dry_run:
		frappe.throw(
			_("These accessories cannot be moved: {0}").format(", ".join(row["item"] for row in refused))
		)

	targets, blank = _targets(set(move))
	methods = {
		method: {
			"programs": 0,
			"programs_changed": 0,
			"packaging_items": len(target),
			"codes_added": set(),
			"codes_removed": set(),
			"open_packs_incompatible": _incompatible_open_packs(method, target),
		}
		for method, target in targets.items()
	}
	changes = []
	for name, method in _programs():
		current = _current_codes(name)
		added = sorted(targets[method] - set(current))
		removed = sorted(set(current) - targets[method])
		summary = methods[method]
		summary["programs"] += 1
		if added or removed:
			summary["programs_changed"] += 1
			summary["codes_added"].update(added)
			summary["codes_removed"].update(removed)
			changes.append((name, added, removed))
	for summary in methods.values():
		summary["codes_added"] = sorted(summary["codes_added"])
		summary["codes_removed"] = sorted(summary["codes_removed"])

	if not dry_run:
		_apply(move, changes)
	return {
		"dry_run": dry_run,
		"applied": not dry_run,
		"accessories_moved": move,
		"accessories_already_moved": already,
		"accessories_refused": refused,
		"blank_method_items": blank,
		"methods": methods,
	}
