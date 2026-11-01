"""Rà và sửa mẻ tiệt khuẩn mang chương trình test còn chứa gói dụng cụ (A-83, ticket #1821). Chạy tay, không tự chạy.

`test_loads_with_packs` chỉ đọc. `detach_packs` mặc định chỉ xem trước; với ``dry_run=0`` đưa gói về `Packed` (nạp lại được,
cổng T5 chưa ghi vì mẻ chưa giải phóng) và đóng mẻ `Failed`, có Audit Log. Mẻ đã đóng không đụng tới: gói có thể đã qua
kho hoặc cấp phát, phải xử lý theo quy trình thu hồi.
"""

import frappe
from frappe.utils import cint

from tracecore.core import audit
from tracecore.reprocessing import sterilizing

LOAD = "Sterilization Load"
EVENT = "TestLoadPacksDetached"


def test_loads_with_packs():
	"""``[{"load", "status", "docstatus", "equipment", "program", "packs"}]`` của mẻ mang chương trình test và có gói."""
	programs = frappe.get_all(
		"Process Program", filters={"program_kind": sterilizing.TEST_PROGRAM}, pluck="name"
	)
	if not programs:
		return []
	rows = []
	for load in frappe.get_all(
		LOAD,
		filters={"program": ["in", programs]},
		fields=["name", "status", "docstatus", "equipment", "program"],
		order_by="name asc",
	):
		packs = frappe.get_all("Load Pack", filters={"parent": load.name, "parenttype": LOAD}, pluck="pack")
		if packs:
			rows.append(
				{
					"load": load.name,
					"status": load.status,
					"docstatus": load.docstatus,
					"equipment": load.equipment,
					"program": load.program,
					"packs": packs,
				}
			)
	return rows


def detach_packs(load, dry_run=1):
	"""Tách gói khỏi mẻ test còn mở; trả ``{"load", "packs", "applied", "refused"}``. Chạy lại an toàn."""
	doc = frappe.get_doc(LOAD, load)
	packs = [row.pack for row in doc.packs]
	result = {"load": doc.name, "packs": packs, "applied": False, "refused": None}
	if frappe.db.get_value("Process Program", doc.program, "program_kind") != sterilizing.TEST_PROGRAM:
		result["refused"] = "not_a_test_program"
	elif doc.status not in sterilizing.OPEN_STATUSES or doc.docstatus != 0:
		result["refused"] = "load_closed"
	elif not packs:
		result["refused"] = "no_packs"
	if result["refused"] or cint(dry_run):
		return result
	for name in packs:
		pack = frappe.get_doc("Pack", name, for_update=True)
		if pack.status == sterilizing.IN_LOAD and pack.load == doc.name:
			pack.update({"status": sterilizing.LOADABLE, "load": None})
			pack.flags.tc_packing = True
			pack.save(ignore_permissions=True)
	doc.packs = []
	doc.status = "Failed"
	doc.release_reason = "Test program load: packs returned to loading"
	doc.flags.update(tc_sterilizing=True, tc_load_repair=True, ignore_mandatory=True)
	doc.save(ignore_permissions=True)
	audit.log("Update", LOAD, doc.name, new={"event": EVENT, "packs": packs}, reason=EVENT)
	result["applied"] = True
	return result
