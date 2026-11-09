"""Quy tắc đa kháng có phiên bản (FEAT-067; FR-M14-03, BRU-MDR-001, D10, NFR-MAINT-04; A-136 Q1, Q3).

Ghi sổ `MDRO Rule` = R01 duyệt và khóa phiên bản ``MDR-<mã>-V<n>`` (`core.versioning`). Sửa quy tắc = nhân bản phiên
bản đang dùng (Desk "Duplicate") thành Nháp V(n+1); mỗi mã chỉ có một bản Nháp. Chủng mới dùng phiên bản đã duyệt mới
nhất của mỗi mã có ``effective_from`` ≤ ngày lấy mẫu (`active_rules`); chủng đã ghi không bao giờ bị gắn lại nhãn.

Tiêu chí chuyên môn (loài, kháng sinh, nhóm kháng sinh, điều kiện) là dữ liệu của quy tắc, không nằm trong code.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate

from tracecore.core import versioning

DOCTYPE = "MDRO Rule"
PREFIX = "MDR"
ANY, ALL, CLASSES = "Resistant to any", "Resistant to all", "Resistant in at least N classes"
RESISTANT, INTERMEDIATE = "R", "I"
AFTER_APPROVAL = frozenset({"superseded_by", "modified", "modified_by", "_comments", "_assign", "_liked_by"})
ROW_FIELDS = {
	"organisms": ("organism", "organism_group"),
	"criteria": ("antibiotic", "antibiotic_name", "antibiotic_class"),
}


def normalize_code(raw):
	try:
		return versioning.normalize_code(raw)
	except ValueError:
		frappe.throw(
			_("Rule code {0} is invalid. Use Latin letters without accents, digits and dashes.").format(
				frappe.bold(raw or "")
			)
		)


def _versions(code):
	return frappe.get_all(
		DOCTYPE,
		filters={"rule_code": code},
		fields=["name", "version_no", "docstatus"],
		order_by="version_no desc",
	)


def next_version(code):
	versions = _versions(code)
	draft = next((row for row in versions if row.docstatus == 0), None)
	if draft:
		frappe.throw(
			_("Rule {0} already has a draft version {1}. Open and edit that draft instead.").format(
				code, draft.name
			)
		)
	return (versions[0].version_no if versions else 0) + 1


def autoname(doc):
	doc.rule_code = normalize_code(doc.rule_code)
	doc.version_no = next_version(doc.rule_code)
	doc.name = versioning.make_versioned_code(PREFIX, doc.rule_code, doc.version_no)


def antibiotic_code(raw) -> str:
	return " ".join(str(raw or "").split()).upper()


def validate(doc):
	if not doc.organisms:
		frappe.throw(_("Add at least one organism or organism group to the rule."))
	for row in doc.organisms:
		row.organism_group = " ".join((row.organism_group or "").split()) or None
		if not row.organism and not row.organism_group:
			frappe.throw(
				_("Organisms row {0}: choose an organism or enter an organism group.").format(row.idx)
			)
	if not doc.criteria:
		frappe.throw(_("Add at least one antibiotic to the rule."))
	seen = set()
	for row in doc.criteria:
		row.antibiotic = antibiotic_code(row.antibiotic)
		row.antibiotic_class = " ".join((row.antibiotic_class or "").split()) or None
		if row.antibiotic in seen:
			frappe.throw(_("Antibiotic {0} is listed twice in the rule.").format(row.antibiotic))
		seen.add(row.antibiotic)
	if doc.condition == CLASSES:
		if any(not row.antibiotic_class for row in doc.criteria):
			frappe.throw(_("Every antibiotic needs a class when the rule counts resistant classes."))
		classes = {row.antibiotic_class.casefold() for row in doc.criteria}
		if not 1 <= cint(doc.min_classes) <= len(classes):
			frappe.throw(
				_(
					"Minimum resistant classes must be between 1 and {0}, the number of classes in the rule."
				).format(len(classes))
			)
	else:
		doc.min_classes = 0
	roles = [line.strip() for line in (doc.alert_roles or "").splitlines() if line.strip()]
	for role in roles:
		if not frappe.db.exists("Role", role):
			frappe.throw(_("Role {0} does not exist.").format(role))
	doc.alert_roles = "\n".join(dict.fromkeys(roles)) or None


def _rows(doc, table):
	return [tuple(row.get(field) for field in ROW_FIELDS[table]) for row in doc.get(table) or []]


def guard_locked(doc):
	"""Phiên bản đã duyệt bất biến: chỉ ``superseded_by`` đổi được sau ghi sổ."""
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
	changed += [table for table in ROW_FIELDS if _rows(doc, table) != _rows(before, table)]
	if changed:
		frappe.throw(
			_(
				"Version {0} is approved and locked. Duplicate it to create version V{1}; isolates already labelled keep their labels."
			).format(doc.name, cint(doc.version_no) + 1),
			title=_("Approved rule is locked"),
		)


def on_approve(doc):
	for row in _versions(doc.rule_code):
		if row.docstatus == 1 and row.version_no < doc.version_no:
			if not frappe.db.get_value(DOCTYPE, row.name, "superseded_by"):
				frappe.db.set_value(DOCTYPE, row.name, "superseded_by", doc.name, update_modified=False)


def active_rules(on):
	"""Phiên bản đã duyệt mới nhất của mỗi mã quy tắc có hiệu lực tại ngày ``on`` (Document)."""
	chosen = {}
	for row in frappe.get_all(
		DOCTYPE,
		filters={"docstatus": 1, "effective_from": ["<=", getdate(on)]},
		fields=["name", "rule_code", "version_no"],
		order_by="version_no desc",
	):
		chosen.setdefault(row.rule_code, row.name)
	return [frappe.get_cached_doc(DOCTYPE, name) for name in sorted(chosen.values())]


def applies_to(rule, organism, organism_group) -> bool:
	group = (organism_group or "").casefold()
	for row in rule.organisms:
		if row.organism and row.organism == organism:
			return True
		if not row.organism and row.organism_group and group and row.organism_group.casefold() == group:
			return True
	return False


def matches(rule, organism, organism_group, results: dict) -> bool:
	"""Chủng (loài, nhóm loài, {mã kháng sinh: S/I/R}) thỏa quy tắc."""
	if not applies_to(rule, organism, organism_group):
		return False
	bad = {RESISTANT, INTERMEDIATE} if cint(rule.count_intermediate) else {RESISTANT}
	resistant = [row for row in rule.criteria if results.get(row.antibiotic) in bad]
	if rule.condition == ALL:
		return len(resistant) == len(rule.criteria)
	if rule.condition == CLASSES:
		classes = {row.antibiotic_class.casefold() for row in resistant if row.antibiotic_class}
		return len(classes) >= cint(rule.min_classes)
	return bool(resistant)


def install_rules(rows):
	"""Nạp quy tắc khởi tạo ở trạng thái Nháp; mã đã có (đã sửa/duyệt tại bệnh viện) thì bỏ qua (NFR-MAINT-04)."""
	created = []
	for row in rows:
		code = normalize_code(row.get("rule_code"))
		if frappe.db.exists(DOCTYPE, {"rule_code": code}):
			continue
		doc = frappe.get_doc({**row, "doctype": DOCTYPE, "rule_code": code})
		created.append(doc.insert(ignore_permissions=True).name)
	return created
