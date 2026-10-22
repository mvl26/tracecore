"""Thẻ kim loại và nhãn khay của Set Unit (FEAT-016 Task 3; FR-M1-05; BRU-ID-001; A-09 G3, G8).

- `KINDS`: loại bản in → `Label Template.label_object` (`core.print.SET_LABELS`); mỗi loại dùng mẫu active của nó.
- `tag_context`: `doc` của mẫu (Set ID, payload DataMatrix FNC1 + 8004 + GIAI, HRI ``(8004)…``, loại bộ, khoa, phương
  pháp, cấy ghép, ngày cấp ``dd/mm/yyyy`` theo giờ hệ thống, `is_test`). Mọi bản in, xem trước, xuất CSV đều dựng từ
  đây nên chặn tiền tố demo đặt ở đây: thẻ kim loại không sửa được, Set ID mang tiền tố demo ``952`` (DB dev chép sang
  site thật) không dựng được trên site không phải dev/test → ``BlockedError(GS1_PREFIX_NOT_CONFIGURED)`` (G3);
  trên dev/test thẻ in thêm dòng ``TEST``.
- `render` / `preview`: ZPL bằng `core.print.render_label`; ảnh PNG xem trước dựng từ chính ZPL (máy in không Unicode).

In qua hàng đợi server (Task 4; FR-M1-05.3, .4; EI-HW-008; G9-G12):

- `queue_prints`: **một Print Job cho mỗi (bộ, loại bản in)**, thứ tự thẻ rồi nhãn khay của từng bộ; kiểm cả lô
  (máy in có địa chỉ mạng, `check_printable`, `TAG_PRINT_PENDING`, lý do in lại, dựng ZPL) **trước** mọi ghi. Job
  ``Queued`` + một `print_server.enqueue_server_dispatch_many` cho cả lô. Máy in không gửi được từ server (chỉ qua
  agent, host bị chặn) → ``PRINTER_NOT_NETWORK`` (ruling Task 4/5): job ``Waiting`` của thẻ không ai giải phóng nên sẽ
  chặn bộ bằng ``TAG_PRINT_PENDING`` mãi mãi. Mỗi job một Audit ``Create`` trên Print Job (``new = {set_unit, kind,
  reprint, printer}``, ``reason`` = lý do in lại) vì Audit Log không có hành động "Print".
- `cancel_pending`: lối ra cho job đang chờ bị kẹt (``Waiting`` cũ, ``Queued`` của máy in đã tắt): đánh dấu ``Failed``
  qua `core.print.ack` kèm lý do, Audit ``Update`` trên Print Job; sau đó in bù không cần lý do.
- In lại (G10): bản in đầu tiên của (bộ, loại) và in bù khi mọi job trước của loại đó ``Failed`` không cần lý do; còn
  lại lý do bắt buộc 1-`REASON_MAX` ký tự (bỏ khoảng trắng). Từ lần in lại thứ `REPRINT_WARN_AT` trả cảnh báo.
  Thẻ và nhãn khay đếm/xét riêng theo cùng một luật.
- `print_counts` (G11): số lần in suy ra từ Print Job (index ``ref_doctype``, ``ref_name``), không có trường đếm.
- `verify` (G12): quét thẻ vừa in phải ra đúng Set ID của bộ.
"""

import base64

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime

from tracecore.core import audit, code_registry, gs1, print_server
from tracecore.core import print as core_print
from tracecore.core.errors import Block, BlockedError
from tracecore.core.print_preview import zpl_preview_png

KINDS = {"tag": "Set Tag", "tray": "Set Tray Label"}
# Xem trước như máy in không hỗ trợ Unicode: ZPL bỏ dấu, ảnh vẽ bằng phông mặc định của Pillow
PREVIEW_PRINTER = {"language": core_print.DEFAULT_LANGUAGE, "supports_unicode": 0}
UNIT_FIELDS = ["name", "set_type", "department", "creation"]
SET_TYPE_FIELDS = ["type_code", "set_type_name", "method", "is_implant"]
REASON_MAX = 500
REPRINT_WARN_AT = 3
MAX_UNITS = 100  # một lần in tối đa bằng một lô cấp (FR-M1-05.1)
REF_DOCTYPE = "Set Unit"
PENDING_STATUSES = ("Queued", "Waiting")
SAVEPOINT = "tc_queue_set_prints"
VERIFY_REASON = "verify_tag"  # cột reason của Audit Update khi quét kiểm tra thẻ


def label_object(kind) -> str:
	"""`Label Template.label_object` của loại bản in `kind` (``tag`` | ``tray``); loại khác → ValidationError."""
	if not isinstance(kind, str) or kind not in KINDS:
		frappe.throw(_("Unknown set label kind: {0}").format(repr(kind)))
	return KINDS[kind]


def tag_context(set_unit: str, kind: str) -> dict:
	"""`doc` của mẫu thẻ kim loại / nhãn khay cho Set Unit `set_unit` (cùng khóa với `sample_set_context`).

	Set Unit không có → DoesNotExistError; Set ID mang tiền tố demo trên site không phải dev/test → BlockedError.
	"""
	label_object(kind)
	unit = frappe.db.get_value("Set Unit", set_unit, UNIT_FIELDS, as_dict=True) if set_unit else None
	if not unit:
		frappe.throw(_("Set Unit {0} not found.").format(set_unit), frappe.DoesNotExistError)
	set_type = frappe.db.get_value("Instrument Set Type", unit.set_type, SET_TYPE_FIELDS, as_dict=True) or {}
	block = code_registry.set_id_block(unit.name, set_type.get("type_code"))
	if block:
		raise BlockedError(block)
	department = (
		frappe.db.get_value("Department", unit.department, "department_name") if unit.department else ""
	)
	method = set_type.get("method")
	return {
		"set_id": unit.name,
		"payload": gs1.giai_payload(unit.name),
		"hri": gs1.giai_hri(unit.name),
		"type_code": set_type.get("type_code") or "",
		"set_type_name": set_type.get("set_type_name") or "",
		"department": department or "",
		"method": _(method) if method else "",
		"is_implant": bool(cint(set_type.get("is_implant"))),
		# `creation` do Frappe ghi theo giờ hệ thống (Asia/Ho_Chi_Minh), không đổi múi giờ thêm
		"issued_on": get_datetime(unit.creation).strftime("%d/%m/%Y"),
		"is_test": gs1.is_demo_prefix(unit.name),
	}


def render(set_unit: str, kind: str, printer: dict | None = None, with_template: bool = False):
	"""ZPL thẻ kim loại (``tag``) hoặc nhãn khay (``tray``) của `set_unit` bằng mẫu active theo ngôn ngữ máy in.

	`printer`, `with_template` như `core.print.render_label` (``(zpl, dòng mẫu)`` khi `with_template`).
	"""
	return core_print.render_label(label_object(kind), tag_context(set_unit, kind), printer, with_template)


def preview(set_unit: str, kind: str) -> dict:
	"""``{png_b64, zpl, hri}``: ZPL như máy in không Unicode và ảnh PNG đúng kích thước mẫu (dot) dựng từ ZPL đó."""
	context = tag_context(set_unit, kind)
	zpl, template = core_print.render_label(label_object(kind), context, PREVIEW_PRINTER, with_template=True)
	size = (
		core_print.mm_to_dots(template.width_mm, template.dpi),
		core_print.mm_to_dots(template.height_mm, template.dpi),
	)
	png = zpl_preview_png(zpl, context["payload"], size)
	return {"png_b64": base64.b64encode(png).decode("ascii"), "zpl": zpl, "hri": context["hri"]}


# --- In qua hàng đợi (Task 4) -------------------------------------------------------------------------------------


def _kind_of(label):
	return next((kind for kind, value in KINDS.items() if value == label), None)


def _empty_counts():
	return {
		kind: {
			"requested": 0,
			"printed": 0,
			"failed": 0,
			"reprints": 0,
			"pending": 0,
			"last_printed_at": None,
		}
		for kind in KINDS
	}


def _counts_for(set_units: list[str]) -> dict[str, dict]:
	"""`print_counts` của nhiều bộ bằng một truy vấn: ``{set_unit: {kind: {...}}}``."""
	result = {name: _empty_counts() for name in set_units}
	if not set_units:
		return result
	rows = frappe.get_all(
		"Print Job",
		filters={"ref_doctype": REF_DOCTYPE, "ref_name": ["in", list(set_units)]},
		fields=["ref_name", "status", "data", "printed_at"],
		order_by="name asc",
	)
	for row in rows:
		data = frappe.parse_json(row.data) if row.data else {}
		data = data if isinstance(data, dict) else {}
		kind = _kind_of(data.get("label_object"))
		if kind is None or row.ref_name not in result:
			continue  # job không phải thẻ/nhãn khay không tính
		counts = result[row.ref_name][kind]
		counts["requested"] += 1
		if row.status == "Printed":
			counts["printed"] += 1
			last = counts["last_printed_at"]
			if row.printed_at and (last is None or row.printed_at > last):
				counts["last_printed_at"] = row.printed_at
		elif row.status == "Failed":
			counts["failed"] += 1
		elif row.status in PENDING_STATUSES:
			counts["pending"] += 1
		if data.get("reprint"):
			counts["reprints"] += 1
	return result


def print_counts(set_unit: str) -> dict[str, dict]:
	"""Số lần in theo loại: ``{"tag"|"tray": {requested, printed, failed, reprints, pending, last_printed_at}}``.

	Suy ra từ Print Job (``ref_doctype = Set Unit``, ``data.label_object``) bằng một truy vấn (G11).
	"""
	if not isinstance(set_unit, str) or not set_unit:
		return _empty_counts()
	return _counts_for([set_unit])[set_unit]


def _not_found_block(set_unit) -> Block:
	return Block(
		"SET_NOT_FOUND",
		_("Set not found"),
		_("Set ID {0} does not exist in TraceCore.").format(set_unit if isinstance(set_unit, str) else "-"),
		_("Check the set tag or call R02."),
	)


def check_printable(set_unit: str) -> Block | None:
	"""Block nếu thẻ/nhãn của bộ không được in, ngược lại None.

	Không có bộ (hoặc tham số không phải chuỗi) → ``SET_NOT_FOUND``; bộ ``Disposed`` → ``SET_DISPOSED``; mã Set ID
	``Disabled`` trong Code Registry → ``CODE_DISABLED``; tiền tố trong Set ID không dùng được trên site này →
	``GS1_PREFIX_NOT_CONFIGURED`` (G3). ``End of Life`` vẫn in được: thẻ cần tới khi thanh lý (G10).
	"""
	unit = (
		frappe.db.get_value(REF_DOCTYPE, set_unit, ["name", "status", "set_type"], as_dict=True)
		if isinstance(set_unit, str) and set_unit
		else None
	)
	if not unit:
		return _not_found_block(set_unit)
	if unit.status == "Disposed":
		return Block(
			"SET_DISPOSED",
			_("Set disposed"),
			_("Set {0} has been disposed; its tag and tray label can no longer be printed.").format(
				unit.name
			),
			_("Do not print a tag for a disposed set. Issue a new Set ID for a replacement set."),
		)
	if frappe.db.get_value("Code Registry", unit.name, "status") == "Disabled":
		return Block(
			"CODE_DISABLED",
			_("Code disabled"),
			_("Set ID {0} is disabled in the code registry.").format(unit.name),
			_("Do not print this code. Call R10 to check the set record."),
		)
	type_code = frappe.db.get_value("Instrument Set Type", unit.set_type, "type_code")
	return code_registry.set_id_block(unit.name, type_code)


def needs_reason(set_unit: str, kind: str) -> bool:
	"""True khi (bộ, loại) đã có bản in ``Printed``: bản in mới là in lại, cần lý do. Chưa có job hoặc chỉ ``Failed``
	(chưa ra giấy) → False (bản in đầu tiên / in bù)."""
	label_object(kind)
	return print_counts(set_unit)[kind]["printed"] > 0


def _pending_block(items: list[dict]) -> Block:
	return Block(
		"TAG_PRINT_PENDING",
		_("Print already pending"),
		_("A tag or tray label of this set is still waiting to be printed."),
		_("Wait for the pending print to finish or fail before printing again."),
		items=items,
	)


def pending_block(set_unit: str, kind: str) -> Block | None:
	"""``TAG_PRINT_PENDING`` khi (bộ, loại) còn job ``Queued``/``Waiting`` (tránh hai thẻ cùng Set ID), ngược lại None."""
	label_object(kind)
	if print_counts(set_unit)[kind]["pending"]:
		return _pending_block([{"set_unit": set_unit, "kind": kind}])
	return None


def _reason_block(reason: str, items: list[dict] | None = None) -> Block:
	return Block(
		"REASON_REQUIRED",
		_("Reason is required"),
		reason,
		_("Enter why the tag is printed again, at most {0} characters.").format(REASON_MAX),
		items=items,
	)


def _unit_list(set_units) -> list[str]:
	if (
		not isinstance(set_units, list | tuple)
		or not set_units
		or not all(isinstance(name, str) and name for name in set_units)
	):
		frappe.throw(_("set_units must be a non-empty list of Set IDs."))
	units = list(dict.fromkeys(set_units))
	if len(units) > MAX_UNITS:
		frappe.throw(_("At most {0} sets can be printed at once.").format(MAX_UNITS))
	return units


def _kind_list(kinds) -> list[str]:
	if not isinstance(kinds, list | tuple) or not kinds:
		frappe.throw(_("Choose at least one label kind to print."))
	for kind in kinds:
		label_object(kind)
	return [kind for kind in KINDS if kind in kinds]  # thứ tự cố định: thẻ rồi nhãn khay


def _printer_rows(kinds: list[str], printers) -> dict:
	if not isinstance(printers, dict):
		frappe.throw(_("printers must map each label kind to a printer."))
	rows = {}
	for kind in kinds:
		name = printers.get(kind)
		if not isinstance(name, str) or not name:
			frappe.throw(_("Choose a printer for {0}.").format(_(KINDS[kind], context="Label Template")))
		row = frappe.db.get_value(
			"Printer", name, ["name", "station", "language", "supports_unicode", "is_active"], as_dict=True
		)
		if not row or not cint(row.is_active):
			frappe.throw(_("Printer {0} does not exist or is not active.").format(name))
		rows[kind] = row
	return rows


def _render_or_block(set_unit, kind, printer):
	"""``(zpl, mẫu)``; mẫu thiếu/lỗi → ``BlockedError(LABEL_RENDER_FAILED)`` (không để lại msgprint)."""
	logged = len(frappe.local.message_log)
	try:
		return render(set_unit, kind, printer, with_template=True)
	except BlockedError:
		raise
	except frappe.ValidationError as error:
		del frappe.local.message_log[logged:]
		raise BlockedError(
			Block(
				"LABEL_RENDER_FAILED",
				_("Label could not be rendered"),
				str(error),
				_("Ask R10 to check the active label template for this object."),
				items=[{"set_unit": set_unit, "kind": kind}],
			)
		) from None


def printer_block(printers: list[str]) -> Block | None:
	"""``PRINTER_NOT_NETWORK`` khi một máy in trong `printers` không gửi được từ server (không có host, host bị chặn,
	port sai, không hoạt động), ngược lại None. Thẻ/nhãn khay Set ID chỉ in qua đường server (A-09 G9, ruling Task 4/5).
	"""
	refused = [name for name in dict.fromkeys(printers) if print_server.printer_address(name) is None]
	if not refused:
		return None
	return Block(
		"PRINTER_NOT_NETWORK",
		_("Printer not reachable from the server"),
		_(
			"Printer {0} has no network address the server can send to; set tags and tray labels are printed only from the server."
		).format(", ".join(refused)),
		_("Choose a printer with a network address, or ask R10 to set the printer host and port."),
		items=refused,
	)


def _reprint_warning(items: list[dict]) -> dict:
	return {
		"code": "TAG_REPRINTED",
		"title": _("Tag reprinted many times"),
		"reason": _("A tag of this batch has been reprinted {0} times.").format(
			max(item["reprints"] for item in items)
		),
		"action": _("Check for lost tags: a set must carry only one tag with its Set ID."),
		"items": items,
	}


def _check_batch(units, kinds, reason) -> dict:
	"""Kiểm cả lô trước mọi ghi; trả ``_counts_for(units)``. Lỗi nghiệp vụ → ``BlockedError``."""
	for unit in units:
		block = check_printable(unit)
		if block:
			raise BlockedError(block)
	counts = _counts_for(units)
	pending = [{"set_unit": u, "kind": k} for u in units for k in kinds if counts[u][k]["pending"]]
	if pending:
		raise BlockedError(_pending_block(pending))
	reprints = [{"set_unit": u, "kind": k} for u in units for k in kinds if counts[u][k]["printed"]]
	if len(reason) > REASON_MAX:
		too_long = _("The reason has {0} characters; at most {1} are allowed.").format(
			len(reason), REASON_MAX
		)
		raise BlockedError(_reason_block(too_long, reprints or None))
	if reprints and not reason:
		raise BlockedError(
			_reason_block(
				_("These tags have already been printed; a reason is required to reprint."), reprints
			)
		)
	return counts


def queue_prints(
	set_units: list[str], kinds: list[str], printers: dict[str, str], reason: str | None = None
) -> dict:
	"""Xếp hàng in thẻ kim loại / nhãn khay cho `set_units` (FR-M1-05, .3, .4; G9, G10).

	`kinds` ⊂ ``KINDS``; `printers` = ``{kind: tên Printer đang hoạt động}``; tham số sai → ``ValidationError``.
	Kiểm cả lô trước mọi ghi: ``PRINTER_NOT_NETWORK``, ``check_printable``, ``TAG_PRINT_PENDING``, ``REASON_REQUIRED``
	(``items`` = các (bộ, loại) là in lại), ``LABEL_RENDER_FAILED`` → ``BlockedError``. Trả
	``{"jobs": [{set_unit, kind, print_job, status}], "warnings": [...]}``; gửi thật do worker sau commit.
	"""
	units = _unit_list(set_units)
	kinds = _kind_list(kinds)
	rows = _printer_rows(kinds, printers)
	block = printer_block([rows[k].name for k in kinds])
	if block:
		raise BlockedError(block)
	reason = reason.strip() if isinstance(reason, str) else ""
	counts = _check_batch(units, kinds, reason)
	rendered = {(u, k): _render_or_block(u, k, rows[k]) for u in units for k in kinds}

	jobs, queued, warned = [], [], []
	frappe.db.savepoint(SAVEPOINT)
	try:
		for unit in units:
			for kind in kinds:
				zpl, template = rendered[(unit, kind)]
				printer = rows[kind]
				reprint = bool(counts[unit][kind]["printed"])
				name = core_print.create_job(
					printer.station,
					zpl,
					{"label_object": KINDS[kind], "set_unit": unit, "kind": kind, "reprint": reprint},
					template.name,
					printer=printer.name,
					status="Queued",
					ref_doctype=REF_DOCTYPE,
					ref_name=unit,
					reprint_reason=reason if reprint else None,
				)
				audit.log(
					"Create",
					"Print Job",
					name,
					new={"set_unit": unit, "kind": kind, "reprint": reprint, "printer": printer.name},
					reason=reason if reprint else None,
				)
				jobs.append({"set_unit": unit, "kind": kind, "print_job": name, "status": "Queued"})
				queued.append(name)
				total = counts[unit][kind]["reprints"] + 1
				if reprint and total >= REPRINT_WARN_AT:
					warned.append({"set_unit": unit, "kind": kind, "reprints": total})
		print_server.enqueue_server_dispatch_many(queued)
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		raise

	return {"jobs": jobs, "warnings": [_reprint_warning(warned)] if warned else []}


def cancel_pending(set_unit: str, kind: str | None, reason: str) -> list[str]:
	"""Hủy các lệnh in đang chờ (``Queued``/``Waiting``) thẻ/nhãn khay của `set_unit` (chỉ loại `kind` nếu có).

	Lối ra cho job kẹt (ruling Task 4/5): ``Waiting`` của máy in agent tạo trước ruling, ``Queued`` của máy in đã tắt
	(cron bỏ qua mãi) — không có thì ``TAG_PRINT_PENDING`` chặn bộ mãi mãi. Mỗi job đọc lại có khóa (worker có thể vừa
	in xong: job đã ``Printed`` thì bỏ qua), đánh dấu ``Failed`` qua `core.print.ack` (cùng đường lỗi in, đếm lần thử),
	``error`` = lý do hủy, Audit ``Update`` trên Print Job (``old/new status``, ``reason``). Bộ không có →
	``BlockedError(SET_NOT_FOUND)``; lý do rỗng hoặc quá `REASON_MAX` → ``BlockedError(REASON_REQUIRED)``. Trả tên các
	job đã hủy theo thứ tự tạo (rỗng nếu không có job chờ). Sau đó bản in kế tiếp là in bù (không cần lý do) nếu chưa
	có bản ``Printed``.
	"""
	if kind is not None:
		label_object(kind)
	if not isinstance(set_unit, str) or not set_unit or not frappe.db.exists(REF_DOCTYPE, set_unit):
		raise BlockedError(_not_found_block(set_unit))
	reason = reason.strip() if isinstance(reason, str) else ""
	if not reason or len(reason) > REASON_MAX:
		raise BlockedError(
			_reason_block(
				_("Enter why the pending print is cancelled, at most {0} characters.").format(REASON_MAX)
			)
		)
	rows = frappe.get_all(
		"Print Job",
		filters={"ref_doctype": REF_DOCTYPE, "ref_name": set_unit, "status": ["in", PENDING_STATUSES]},
		fields=["name", "data"],
		order_by="name asc",
	)
	cancelled = []
	frappe.db.savepoint(SAVEPOINT)
	try:
		for row in rows:
			data = frappe.parse_json(row.data) if row.data else {}
			job_kind = _kind_of(data.get("label_object")) if isinstance(data, dict) else None
			if job_kind is None or (kind is not None and job_kind != kind):
				continue
			name = str(row.name)
			old = frappe.db.get_value("Print Job", name, "status", for_update=True)
			if old not in PENDING_STATUSES:
				continue  # worker vừa in xong / báo lỗi
			error = _("Cancelled by {0}: {1}").format(frappe.session.user, reason)
			core_print.ack(name, "Failed", "Printer", error=error)
			audit.log(
				"Update",
				"Print Job",
				name,
				old={"status": old},
				new={"status": "Failed", "set_unit": set_unit, "kind": job_kind, "cancelled": True},
				reason=reason,
			)
			cancelled.append(name)
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		raise
	return cancelled


# --- Quét kiểm tra thẻ (G12) ----------------------------------------------------------------------------------------


def verify(set_unit: str, raw: str) -> dict:
	"""Quét thẻ vừa in (UC-03 bước 4, E2): mã phải là Set ID của chính bộ `set_unit`.

	Đúng → ghi ``tag_verified_on/by`` (cờ ``flags.tc_tag_verify``; Audit ``Update`` của Set Unit, lý do
	``verify_tag``), trả ``{set_unit, verified_on}``. Bộ không có → ``SET_NOT_FOUND``; chuỗi không phải Set ID →
	``SCAN_INVALID``; Set ID khác → ``TAG_MISMATCH`` (``items = [{expected, scanned}]``).
	"""
	if not isinstance(set_unit, str) or not set_unit or not frappe.db.exists(REF_DOCTYPE, set_unit):
		raise BlockedError(_not_found_block(set_unit))
	scanned = gs1.parse_scan(raw) if isinstance(raw, str) else {"type": "unknown", "id": None, "raw": ""}
	if scanned["type"] != "set":
		raise BlockedError(
			Block(
				"SCAN_INVALID",
				_("Invalid code"),
				_("Code {0} is not a Set ID tag.").format(scanned.get("raw") or "-"),
				_("Scan the DataMatrix on the printed tag of set {0}.").format(set_unit),
			)
		)
	if scanned["id"] != set_unit:
		raise BlockedError(
			Block(
				"TAG_MISMATCH",
				_("Tag does not match"),
				_("The scanned tag is {0}, but this set is {1}.").format(scanned["id"], set_unit),
				_("Take the tag off this set, find the right tag, or reprint the tag with a reason."),
				items=[{"expected": set_unit, "scanned": scanned["id"]}],
			)
		)
	doc = frappe.get_doc(REF_DOCTYPE, set_unit, for_update=True)
	doc.update({"tag_verified_on": now_datetime(), "tag_verified_by": frappe.session.user})
	doc.flags.tc_tag_verify = True
	doc.flags.tc_audit_reason = VERIFY_REASON
	doc.save(ignore_permissions=True)
	return {"set_unit": set_unit, "verified_on": doc.tag_verified_on}
