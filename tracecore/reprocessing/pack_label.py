"""Nhãn gói và lệnh in của trạm T4 (M2, FEAT-018, D7, BRU-REP-011, FR-M2-08.8).

Tách khỏi `packing` (dịch vụ sinh/in lại/hủy/tra cứu gọi các hàm ở đây):

- `label_context(pack)`: `doc` của mẫu nhãn gói (đúng bộ khóa `sample_pack_context`), dùng lúc sinh và in lại.
- `queue_label(pack, station, printer, reprint_reason=None)`: tạo Print Job ``Queued`` hoặc ``Waiting`` + cảnh báo.
- `waiting_label(pack)`: nhãn còn chờ in của gói (cảnh báo ``LABEL_ALREADY_WAITING``), để in lại không tạo job thứ hai.
- `pack_summary(pack)`, `pack_result(pack, printed)`: dữ liệu gói trả về cho trạm.
- `label_items(method)`: Item nhãn của phương pháp.
- `cancel_waiting_jobs(pack, reason)`: hủy nhãn còn chờ in của gói vừa hủy hiệu lực.

Chỉ import `tracecore.core` (lint R1); in không bao giờ làm mất Cycle ID.
"""

import base64

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, get_fullname, getdate

from tracecore.core import error_codes, gs1
from tracecore.core import print as core_print


def label_items(method):
	"""Item nhãn (nhóm Label) còn dùng của phương pháp `method`, theo mã."""
	return frappe.get_all(
		"Item",
		filters={"tc_item_group_cssd": "Label", "tc_compatible_method": method, "disabled": 0},
		fields=["name", "item_name"],
		order_by="name asc",
	)


def packer_name(pack):
	"""Họ tên người đóng gói: nhân viên của phiên trạm (A-81); gói cũ chưa có `packed_by` lấy theo user."""
	name = pack.packed_by and frappe.db.get_value("Employee", pack.packed_by, "employee_name")
	return name or get_fullname(pack.packed_by_user)


def label_context(pack):
	"""`doc` của mẫu nhãn gói, đúng bộ khóa của `sample_pack_context`; dùng cho Print Job và khi in lại.

	Ngày ``dd/mm/yyyy``, giờ ``dd/mm/yyyy HH:mm``; chữ giữ tiếng Việt có dấu (chỉ `core.print.render` bỏ dấu cho
	máy in không hỗ trợ Unicode). `dept` = tên khoa (trống nếu không có), `packer` = họ tên người đóng gói.
	"""
	packed_at, expiry = get_datetime(pack.packed_at), getdate(pack.expiry)
	department = pack.department and frappe.db.get_value("Department", pack.department, "department_name")
	return {
		"set_id": pack.set_unit,
		"cycle_id": pack.name,
		"set_name": pack.set_name or "",
		"dept": department or pack.department or "",
		"packer": packer_name(pack),
		"packed_at": f"{packed_at:%d/%m/%Y %H:%M}",
		"expiry": f"{expiry:%d/%m/%Y}",
		"method_label": _(pack.method),
		"pack_type": frappe.db.get_value("Item", pack.pack_type, "item_name") or pack.pack_type,
		"ci_lot": pack.ci_batch or "",
		"bom_version": cint(pack.bom_version),
		"is_loaner": _is_loaner(pack),
		"is_test": gs1.is_test_gtin(pack.gtin),
		"warning": _shortage_warning(pack),
		"payload": pack.barcode_payload,
		"hri": _hri(pack),
	}


def _shortage_warning(pack):
	"""Dòng THIẾU trên nhãn (FR-M2-06.1): tên các dụng cụ thiếu mà R02 đã xác nhận ở T3; không có thì rỗng.

	Nhãn luôn in tiếng Việt (mẫu nhãn cố định), nên dịch sang ``vi`` bất kể ngôn ngữ của người dùng đang thao tác.
	"""
	flags = (
		frappe.db.get_value("Assembly Record", pack.assembly, ["shortage_confirmed", "shortage_accepted"])
		if pack.assembly
		else None
	)
	if not flags or not any(flags):  # FEAT-052 A-71: nhận thiếu theo DC-001 Cảnh báo được lưu lúc ghi T3
		return ""
	names = frappe.get_all(
		"Assembly Line",
		filters={"parent": pack.assembly, "parenttype": "Assembly Record", "line_status": "Short"},
		fields=["instrument", "instrument_name"],
		order_by="idx asc",
	)
	if not names:
		return ""
	listed = ", ".join(row.instrument_name or row.instrument for row in names)
	return _("MISSING: {0}", "vi").format(listed)


def _hri(pack):
	return gs1.cycle_hri(pack.gtin, get_datetime(pack.packed_at).date(), getdate(pack.expiry), pack.name)


def _is_loaner(pack):
	return bool(cint(frappe.db.get_value("Set Unit", pack.set_unit, "is_loaner")))


def _warning(code, title, reason, action):
	return {"code": code, "title": title, "reason": reason, "action": action}


def queue_label(pack, station, printer, reprint_reason=None):
	"""Tạo Print Job cho nhãn gói tại `station`; trả ``{"print_job", "status", "printer", "zpl", "warning"}``.

	Có máy in đúng loại nhãn (`printer`, từ `select_printer`) và mẫu active theo phương pháp + ngôn ngữ máy in →
	render với cờ Unicode của máy in, job ``Queued``. Không có máy in (``NO_PRINTER_FOR_METHOD``), không có mẫu
	(``LABEL_TEMPLATE_MISSING``) hay mẫu lỗi (``LABEL_RENDER_FAILED``) → job ``Waiting`` giữ ``label_context`` trong
	``data`` để `core.print.set_roll` dựng lại, kèm cảnh báo; Cycle ID vẫn giữ.
	"""
	context = label_context(pack)
	job = {
		"station": station,
		"data": {"method": pack.method, "label_object": "Pack", "label_context": context},
		"ref_doctype": "Pack",
		"ref_name": pack.name,
		"reprint_reason": reprint_reason,
	}
	template = core_print.active_template("Pack", pack.method, printer["language"]) if printer else None
	zpl, warning = None, None
	if not printer:
		labels = ", ".join(row.item_name or row.name for row in label_items(pack.method))
		warning = _warning(
			"NO_PRINTER_FOR_METHOD",
			_("No printer has the right labels"),
			_(
				"No active printer at station {0} has {1} labels loaded. Cycle ID {2} is kept; its label is waiting."
			).format(station, _(pack.method), pack.name),
			_(
				"Load a roll of {0} into a printer at this station, then scan the roll code (CN-#####) to print the waiting label."
			).format(labels or _(pack.method)),
		)
	elif not template:
		warning = _warning(
			"LABEL_TEMPLATE_MISSING",
			_("No label template"),
			_(
				"There is no active {0} label template for {1} packs. Cycle ID {2} is kept; its label is waiting."
			).format(printer["language"], _(pack.method), pack.name),
			_(
				"Ask R10 to activate a label template, then scan the roll code on the printer to print the waiting label."
			),
		)
	else:
		logged = len(frappe.local.message_log)
		try:
			zpl = core_print.render(
				template.body,
				context,
				bool(printer["supports_unicode"]),
				dpi=template.dpi,
				width_mm=template.width_mm,
				height_mm=template.height_mm,
				language=template.language,
				name=template.name,
			)
		except frappe.ValidationError as error:
			del frappe.local.message_log[logged:]  # lỗi đã thành cảnh báo, không để msgprint lên kiosk
			warning = _warning(
				"LABEL_RENDER_FAILED",
				_("Label could not be prepared"),
				_("{0} Cycle ID {1} is kept; its label is waiting.").format(error, pack.name),
				_(
					"Ask R10 to fix the label template, then scan the roll code on the printer to print the waiting label."
				),
			)
	if zpl is None:
		name = core_print.create_job(zpl=None, template=None, status="Waiting", **job)
		return {"print_job": name, "status": "Waiting", "printer": None, "zpl": None, "warning": warning}
	name = core_print.create_job(
		zpl=zpl, template=template.name, printer=printer["name"], status="Queued", **job
	)
	return {"print_job": name, "status": "Queued", "printer": printer["name"], "zpl": zpl, "warning": None}


def waiting_label(pack):
	"""Print Job ``Waiting`` mới nhất của gói, cùng dạng `queue_label` kèm cảnh báo ``LABEL_ALREADY_WAITING``; không có → None.

	In lại khi nhãn còn chờ máy in thì trả lại job đó thay vì tạo job mới: nếu không, đổi cuộn sẽ in hai nhãn hợp lệ
	cùng một Cycle ID trong khi `label_print_count` đã tăng mà chưa có nhãn nào được in.
	"""
	names = frappe.get_all(
		"Print Job",
		filters={"ref_doctype": "Pack", "ref_name": pack.name, "status": "Waiting"},
		pluck="name",
		order_by="creation desc, name desc",
		limit=1,
	)
	if not names:
		return None
	job = str(names[0])
	warning = _warning(
		"LABEL_ALREADY_WAITING",
		_("Label not printed yet"),
		_(
			"The label of Cycle ID {0} has not been printed yet: print job {1} is still waiting for a printer. No new label was created."
		).format(pack.name, job),
		_(
			"Load the right label roll into the printer, then scan the roll code (CN-#####) to print the waiting label."
		),
	)
	return {"print_job": job, "status": "Waiting", "printer": None, "zpl": None, "warning": warning}


def pack_summary(pack):
	return {
		"cycle_id": pack.name,
		"set_id": pack.set_unit,
		"set_name": pack.set_name,
		"method": pack.method,
		"pack_type": pack.pack_type,
		"pack_type_name": frappe.db.get_value("Item", pack.pack_type, "item_name"),
		"expiry": str(getdate(pack.expiry)),
		"shelf_life_days_applied": cint(pack.shelf_life_days_applied),
		"packed_at": f"{get_datetime(pack.packed_at):%Y-%m-%d %H:%M:%S}",
		"packer": packer_name(pack),
		"ci_batch": pack.ci_batch,
		"bom_version": cint(pack.bom_version),
		"label_type": pack.label_type,
		"is_loaner": _is_loaner(pack),
		"is_test": gs1.is_test_gtin(pack.gtin),
	}


def pack_result(pack, printed):
	png = gs1.encode_datamatrix_png(pack.barcode_payload)
	return {
		"pack": pack_summary(pack),
		"hri": _hri(pack),
		"datamatrix_png_b64": base64.b64encode(png).decode("ascii"),
		"print": printed,
	}


def cancel_waiting_jobs(pack, reason):
	"""Nhãn còn chờ in (Print Job ``Waiting``) của gói vừa hủy chuyển ``Failed`` kèm ghi chú (D12).

	Không có bước này, `core.print.set_roll` sẽ phát hành job chờ khi lắp đúng cuộn và in nhãn của Cycle ID đã hủy
	cạnh nhãn của Cycle ID mới. Job đã ``Queued``/``Printed`` giữ nguyên (agent có thể đang in). Mỗi job được khóa
	rồi kiểm lại trạng thái, như `set_roll`, nên hai bên không chồng nhau.
	"""
	note = _("Not printed: Cycle ID {0} was voided ({1}).").format(pack.name, _(reason, context="Pack"))
	names = frappe.get_all(
		"Print Job", filters={"ref_doctype": "Pack", "ref_name": pack.name, "status": "Waiting"}, pluck="name"
	)
	for name in names:
		job = frappe.get_doc("Print Job", name, for_update=True)
		if job.status == "Waiting":
			job.update({"status": "Failed", "error": note})
			job.save(ignore_permissions=True)
