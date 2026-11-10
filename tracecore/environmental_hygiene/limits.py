"""Ngưỡng môi trường có phiên bản (FEAT-070; FR-M15-03, .1; BRU-ENV-002; NFR-MAINT-04; D10; A-148 b).

Ghi sổ `Environmental Limit` = R01 duyệt và khóa phiên bản `NG-<mã>-V<n>` (cùng cách `Audit Template`, mã ghép qua
``core.versioning``). Sửa = ``new_version`` chép bản đang dùng thành Nháp V(n+1). Mẫu dùng phiên bản đã duyệt mới nhất
có ``effective_from`` ≤ ngày lấy mẫu (``active_limit``) và lưu bản chụp, nên đổi ngưỡng không đổi kết quả mẫu cũ.
Giá trị ngưỡng là cấu hình có ``legal_ref``, không viết trong code.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from tracecore.core import versioning

DOCTYPE = "Environmental Limit"
PREFIX = "NG"
PASS, FAIL = "Pass", "Fail"
AFTER_APPROVAL = frozenset({"superseded_by", "modified", "modified_by", "_comments", "_assign", "_liked_by"})


def normalize_code(raw):
	try:
		return versioning.normalize_code(raw)
	except ValueError:
		frappe.throw(
			_("Limit code {0} is invalid. Use Latin letters without accents, digits and dashes.").format(
				frappe.bold(raw or "")
			)
		)


def _versions(code):
	return frappe.get_all(
		DOCTYPE,
		filters={"limit_code": code},
		fields=["name", "version_no", "docstatus"],
		order_by="version_no desc",
	)


def autoname(doc):
	doc.limit_code = normalize_code(doc.limit_code)
	versions = _versions(doc.limit_code)
	draft = next((row for row in versions if row.docstatus == 0), None)
	if draft:
		frappe.throw(
			_("Limit {0} already has a draft version {1}. Open and edit that draft instead.").format(
				doc.limit_code, draft.name
			)
		)
	doc.version_no = (versions[0].version_no if versions else 0) + 1
	doc.name = versioning.make_versioned_code(PREFIX, doc.limit_code, doc.version_no)


def validate(doc):
	if doc.min_value not in (None, "") and flt(doc.min_value) > flt(doc.limit_value):
		frappe.throw(_("The lower limit cannot be above the upper limit."))


def guard_locked(doc):
	"""Phiên bản đã duyệt bất biến: chặn và gợi ý tạo V(n+1)."""
	before = doc.get_doc_before_save()
	if not before:
		return
	changed = [
		field.fieldname
		for field in doc.meta.fields
		if field.fieldtype not in ("Section Break", "Column Break")
		and field.fieldname not in AFTER_APPROVAL
		and doc.get(field.fieldname) != before.get(field.fieldname)
	]
	if changed:
		frappe.throw(
			_(
				"Version {0} is approved and locked. Create version V{1} to change it; samples already recorded keep version {0}."
			).format(doc.name, cint(doc.version_no) + 1),
			title=_("Approved limit is locked"),
		)


def on_approve(doc):
	"""Ghi sổ = duyệt: phiên bản cũ hơn trỏ sang bản mới."""
	for row in _versions(doc.limit_code):
		if row.docstatus == 1 and row.version_no < doc.version_no:
			if not frappe.db.get_value(DOCTYPE, row.name, "superseded_by"):
				frappe.db.set_value(DOCTYPE, row.name, "superseded_by", doc.name, update_modified=False)


def new_version(name):
	"""Chép phiên bản đã duyệt mới nhất thành Nháp V(n+1); đã có Nháp thì trả bản Nháp đó."""
	source = frappe.get_doc(DOCTYPE, name)
	if source.docstatus != 1:
		frappe.throw(_("Only an approved version can be revised. Edit draft {0} directly.").format(name))
	versions = _versions(source.limit_code)
	draft = next((row for row in versions if row.docstatus == 0), None)
	if draft:
		return frappe.get_doc(DOCTYPE, draft.name)
	latest = next(row for row in versions if row.docstatus == 1)
	if latest.name != source.name:
		frappe.throw(_("Version {0} is no longer current. Revise version {1}.").format(name, latest.name))
	doc = frappe.copy_doc(source)
	doc.update(
		{
			"docstatus": 0,
			"version_no": None,
			"effective_from": today(),
			"superseded_by": None,
			"amended_from": None,
		}
	)
	return doc.insert()


def active_limit(code, on=None):
	"""Phiên bản đã duyệt mới nhất có hiệu lực tại ngày ``on`` (BRU-ENV-002); không có → None."""
	names = frappe.get_all(
		DOCTYPE,
		filters={
			"limit_code": normalize_code(code),
			"docstatus": 1,
			"effective_from": ["<=", getdate(on or today())],
		},
		order_by="version_no desc",
		limit=1,
		pluck="name",
	)
	return names[0] if names else None


def candidates(sample_type, method, risk_level, on=None):
	"""Mã ngưỡng có phiên bản hiệu lực tại ``on`` khớp loại mẫu, phương pháp, mức nguy cơ (trống = mọi mức)."""
	rows = frappe.get_all(
		DOCTYPE,
		filters={
			"docstatus": 1,
			"sample_type": sample_type,
			"method": method,
			"effective_from": ["<=", getdate(on or today())],
		},
		fields=["limit_code", "applies_to_risk_level"],
	)
	return sorted(
		{
			row.limit_code
			for row in rows
			if not row.applies_to_risk_level or row.applies_to_risk_level == risk_level
		}
	)


def matches(limit, sample_type, method, risk_level):
	return (
		limit.sample_type == sample_type
		and limit.method == method
		and (not limit.applies_to_risk_level or limit.applies_to_risk_level == risk_level)
	)


def evaluate(limit, value):
	"""Đạt khi kết quả ≤ ngưỡng trên và (nếu có) ≥ ngưỡng dưới."""
	value = flt(value)
	if value > flt(limit.limit_value):
		return FAIL
	if limit.min_value not in (None, "") and flt(limit.min_value) and value < flt(limit.min_value):
		return FAIL
	return PASS


def _number(value):
	"""Số gọn, dấu phẩy thập phân (10 → "10", 0,5 → "0,5")."""
	return f"{flt(value):g}".replace(".", ",")


def snapshot(limit):
	"""Bản chụp ngưỡng lưu trên mẫu: phiên bản, thông số, khoảng, đơn vị, căn cứ."""
	band = f"≤ {_number(limit.limit_value)}"
	if limit.min_value not in (None, "") and flt(limit.min_value):
		band = f"{_number(limit.min_value)} - {_number(limit.limit_value)}"
	return f"{limit.name} · {limit.parameter} {band} {limit.unit} · {limit.legal_ref}"


def install(rows):
	"""Nạp ngưỡng khởi tạo ở Nháp; mã đã có (bệnh viện đã sửa/duyệt) thì bỏ qua (NFR-MAINT-04)."""
	created = []
	for row in rows:
		code = normalize_code(row.get("limit_code"))
		if frappe.db.exists(DOCTYPE, {"limit_code": code}):
			continue
		doc = frappe.get_doc({**row, "doctype": DOCTYPE, "limit_code": code})
		created.append(doc.insert(ignore_permissions=True).name)
	return created
