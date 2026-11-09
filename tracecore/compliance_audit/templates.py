"""Mẫu phiếu giám sát có phiên bản (FEAT-060; ADR-015, FR-M12-01, BRU-AUD-001, A-132).

Ghi sổ `Audit Template` = R01 duyệt và khóa nội dung phiên bản `MP-<mã>-V<n>`. Sửa mẫu = `new_version` chép phiên bản
đang dùng thành Nháp V(n+1) (không dùng Amend vì Amend đòi hủy bản đang dùng). Phiếu dùng phiên bản đã duyệt mới nhất
có `effective_from` ≤ ngày phiếu (`active_version`). Mỗi mã chỉ có một bản Nháp tại một thời điểm.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from tracecore.core import audit, versioning

DOCTYPE = "Audit Template"
ITEM_DOCTYPE = "Audit Template Item"
PREFIX = "MP"
BINARY_ITEM = "Pass/Fail"
BY_OPPORTUNITY, ALL_OR_NONE, WEIGHTED = "By Opportunity", "All or None", "Weighted Score"
SCORED = (ALL_OR_NONE, WEIGHTED)
BUNDLE = "Prevention Bundle"
NO_CRITICAL_REASON = "[NO_CRITICAL_ITEM]"
ITEM_FIELDS = (
	"item_code",
	"section",
	"question",
	"answer_type",
	"options",
	"weight",
	"is_critical",
	"guidance",
)
# trường hệ thống ghi sau khi duyệt; mọi trường khác của phiên bản đã duyệt bị khóa
AFTER_APPROVAL = frozenset({"superseded_by", "modified", "modified_by", "_comments", "_assign", "_liked_by"})


def normalize_code(raw):
	try:
		return versioning.normalize_code(raw)
	except ValueError:
		frappe.throw(
			_("Template code {0} is invalid. Use Latin letters without accents, digits and dashes.").format(
				frappe.bold(raw or "")
			)
		)


def _versions(code):
	return frappe.get_all(
		DOCTYPE,
		filters={"template_code": code},
		fields=["name", "version_no", "docstatus"],
		order_by="version_no desc",
	)


def _draft(code):
	return next((row for row in _versions(code) if row.docstatus == 0), None)


def next_version(code):
	"""Số phiên bản kế của mã; đã có bản Nháp thì chặn (mỗi mã một bản Nháp)."""
	versions = _versions(code)
	draft = next((row for row in versions if row.docstatus == 0), None)
	if draft:
		frappe.throw(
			_("Template {0} already has a draft version {1}. Open and edit that draft instead.").format(
				code, draft.name
			)
		)
	return (versions[0].version_no if versions else 0) + 1


def autoname(doc):
	doc.template_code = normalize_code(doc.template_code)
	doc.version_no = next_version(doc.template_code)
	doc.name = versioning.make_versioned_code(PREFIX, doc.template_code, doc.version_no)


def validate(doc):
	"""Luật của mẫu (gọi từ ``AuditTemplate.validate``)."""
	if cint(doc.min_sample) < 0:
		frappe.throw(_("Minimum sample cannot be negative."))
	if doc.pass_threshold not in (None, "") and not 0 <= flt(doc.pass_threshold) <= 100:
		frappe.throw(_("Pass threshold must be between 0 and 100 %."))
	if doc.audit_type != BUNDLE:
		doc.bundle_type = None
	if not doc.items:
		frappe.throw(_("Add at least one item to the template."))
	seen = set()
	for row in doc.items:
		row.item_code = (row.item_code or "").strip().upper()
		if row.item_code in seen:
			frappe.throw(_("Item code {0} is used twice in the template.").format(row.item_code))
		seen.add(row.item_code)
		if flt(row.weight) < 0:
			frappe.throw(_("Row {0}: weight cannot be negative.").format(row.idx))
		if row.answer_type != BINARY_ITEM:
			row.is_critical = 0  # chỉ mục Đạt/Không đạt mới chấm được, nên chỉ chúng là trọng yếu
	if doc.scoring_method in SCORED and not any(row.answer_type == BINARY_ITEM for row in doc.items):
		frappe.throw(_("Scoring method {0} needs at least one Pass/Fail item.").format(_(doc.scoring_method)))


def _row_values(row):
	return tuple(row.get(field) for field in ITEM_FIELDS)


def guard_locked(doc):
	"""Phiên bản đã duyệt bất biến (FR-M12-01.1): chặn và gợi ý tạo V(n+1)."""
	before = doc.get_doc_before_save()
	if not before:
		return
	changed = [
		field.fieldname
		for field in doc.meta.fields
		if field.fieldtype not in ("Table", "Section Break", "Column Break")
		and field.fieldname not in AFTER_APPROVAL
		and doc.get(field.fieldname) != before.get(field.fieldname)
	]
	if [_row_values(row) for row in doc.items] != [_row_values(row) for row in before.items]:
		changed.append("items")
	if changed:
		frappe.throw(
			_(
				"Version {0} is approved and locked. Create version V{1} to change it; audits already filled keep version {0}."
			).format(doc.name, cint(doc.version_no) + 1),
			title=_("Approved template is locked"),
		)


def on_approve(doc):
	"""Ghi sổ = duyệt: phiên bản cũ hơn trỏ sang bản mới (hết hiệu lực); mẫu gói không có mục trọng yếu thì cảnh báo."""
	for row in _versions(doc.template_code):
		if row.docstatus == 1 and row.version_no < doc.version_no:
			if not frappe.db.get_value(DOCTYPE, row.name, "superseded_by"):
				frappe.db.set_value(DOCTYPE, row.name, "superseded_by", doc.name, update_modified=False)
	if doc.audit_type == BUNDLE and not any(cint(row.is_critical) for row in doc.items):
		message = _("Bundle template {0} has no critical item.").format(doc.name)
		# UC-43 E3: chỉ cảnh báo, không chặn; Audit Log giữ dấu người duyệt đã được báo
		audit.log("Submit", DOCTYPE, doc.name, reason=NO_CRITICAL_REASON + " " + message)
		frappe.msgprint(message, indicator="orange", alert=True)


def active_version(code, on=None):
	"""Phiên bản đã duyệt mới nhất có hiệu lực tại ngày ``on`` (mặc định hôm nay); không có → None."""
	names = frappe.get_all(
		DOCTYPE,
		filters={
			"template_code": normalize_code(code),
			"docstatus": 1,
			"effective_from": ["<=", getdate(on or today())],
		},
		order_by="version_no desc",
		limit=1,
		pluck="name",
	)
	return names[0] if names else None


def new_version(name):
	"""Chép phiên bản đã duyệt mới nhất thành Nháp V(n+1); đã có Nháp thì trả bản Nháp đó."""
	source = frappe.get_doc(DOCTYPE, name)
	if source.docstatus != 1:
		frappe.throw(_("Only an approved version can be revised. Edit draft {0} directly.").format(name))
	draft = _draft(source.template_code)
	if draft:
		return frappe.get_doc(DOCTYPE, draft.name)
	latest = next(row for row in _versions(source.template_code) if row.docstatus == 1)
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
	for row in doc.items:
		row.docstatus = 0
	return doc.insert()


def install_templates(rows):
	"""Nạp mẫu khởi tạo ở trạng thái Nháp; mã đã có (đã sửa/duyệt tại bệnh viện) thì bỏ qua (NFR-MAINT-04).

	``rows``: dict trường của Audit Template kèm ``items``. Trả tên các mẫu vừa tạo."""
	created = []
	for row in rows:
		code = normalize_code(row.get("template_code"))
		if frappe.db.exists(DOCTYPE, {"template_code": code}):
			continue
		doc = frappe.get_doc({**row, "doctype": DOCTYPE, "template_code": code})
		created.append(doc.insert(ignore_permissions=True).name)
	return created
