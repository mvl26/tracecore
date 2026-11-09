"""Chủng phân lập: ghi, gắn nhãn đa kháng, chủng đầu tiên, thông báo, tiền sử (FEAT-067; FR-M14-01..05; UC-51; A-136).

- `create` là đường duy nhất tạo `Microbiology Isolate` (import file và nhập tay có xác nhận); Desk không tạo/sửa trực
  tiếp (cờ ``flags.tc_micro``). Khóa (`lab_sample_id`, `organism`) không trùng ở mọi nguồn.
- Gắn nhãn **một lần khi ghi** theo các bản `MDRO Rule` đã duyệt có hiệu lực tại ngày lấy mẫu; lưu bản chụp tên phiên
  bản đã khớp; duyệt quy tắc mới không gắn lại nhãn chủng cũ (BRU-MDR-001, A-136 Q3).
- Chủng đầu tiên của mỗi (hash mã BN, loài, quý dương lịch theo ``collected_on``): chủng lấy mẫu sớm nhất, hòa thì
  ``lab_sample_id`` nhỏ nhất; tính lại cả nhóm khi có chủng mới (nhập trễ) — mọi chủng vẫn được lưu (BRU-MDR-002).
- Chủng đa kháng mới → thông báo khẩn ``MDRO_DETECTED`` cho R11 (theo Notification Rule), mạng lưới viên đang hiệu lực
  và R08 của khoa, vai trò ``alert_roles`` của quy tắc; phát hook ``tracecore_mdro_detected(isolate)`` (M13 đăng ký).
  Đọc mạng lưới viên (M11) qua ``frappe.get_all``, không import module khác.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, getdate, now_datetime

from tracecore.core import extension, notification, patient_code
from tracecore.microbiology import rules

DOCTYPE = "Microbiology Isolate"
SOURCE_IMPORT, SOURCE_MANUAL = "Import", "Manual"
MDRO_EVENT = "MDRO_DETECTED"
MDRO_HOOK = "tracecore_mdro_detected"
SCREEN_LINK = "/app/tc-ksnk/vi-sinh"
RESULTS = ("S", "I", "R")
DEPARTMENT_ROLE = "TC R08"
NETWORK_DOCTYPE = "IC Network Member"
VALUE_FIELDS = (
	"lab_sample_id",
	"organism",
	"patient_code",
	"birth_year",
	"sex",
	"department",
	"specimen_type",
	"collected_on",
)


def period_key(day) -> str:
	day = getdate(day)
	return f"{day.year}-Q{(day.month - 1) // 3 + 1}"


def sample_id(raw) -> str:
	return " ".join(cstr(raw).split())


def organism_ref(raw) -> str | None:
	"""Tên Organism theo mã WHONET (không phân biệt hoa thường); không có hoặc đã tắt → None."""
	code = "".join(cstr(raw).split()).lower()
	if not code:
		return None
	row = frappe.db.get_value("Organism", {"organism_code": code}, ["name", "disabled"], as_dict=True)
	return row.name if row and not row.disabled else None


def exists(lab_sample_id, organism) -> bool:
	return bool(frappe.db.exists(DOCTYPE, {"lab_sample_id": sample_id(lab_sample_id), "organism": organism}))


def susceptibility_rows(rows) -> list[dict]:
	"""Dòng kháng sinh đồ đã chuẩn hóa: mã viết hoa, kết quả S/I/R; mã trùng giữ dòng đầu."""
	out, seen = [], set()
	for row in rows or ():
		code = rules.antibiotic_code(row.get("antibiotic"))
		if not code or code in seen:
			continue
		seen.add(code)
		out.append(
			{
				"antibiotic": code,
				"antibiotic_name": cstr(row.get("antibiotic_name")).strip() or None,
				"result": cstr(row.get("result")).strip().upper(),
				"mic": cstr(row.get("mic")).strip() or None,
			}
		)
	return out


def create(values: dict, susceptibility, source=SOURCE_IMPORT, import_batch=None, confirmed=False):
	"""Ghi một chủng (quyền tạo kiểm như nhập tay trên Desk). Trả Document đã ghi."""
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			**{field: values.get(field) for field in VALUE_FIELDS},
			"lab_sample_id": sample_id(values.get("lab_sample_id")),
			"susceptibility": susceptibility_rows(susceptibility),
			"source": source,
			"import_batch": import_batch,
		}
	)
	if confirmed:
		doc.confirmed_by = frappe.session.user
		doc.confirmed_on = now_datetime()
	doc.flags.tc_micro = True
	doc.insert()
	return doc


def problems(values: dict, susceptibility) -> list[str]:
	"""Lý do không ghi được một kết quả nhập tay (rỗng = hợp lệ); cùng luật với import file."""
	reasons = []
	labels = {
		"lab_sample_id": _("Lab Sample ID"),
		"organism": _("Organism Code"),
		"patient_code": _("Patient Code"),
		"department": _("Department"),
		"collected_on": _("Collection Date"),
	}
	for field, label in labels.items():
		if not cstr(values.get(field)).strip():
			reasons.append(_("{0} is required.").format(label))
	if reasons:
		return reasons
	organism = organism_ref(values.get("organism"))
	if not organism:
		reasons.append(_("Organism code {0} is not in the Organism catalog.").format(values.get("organism")))
	if not frappe.db.exists("Department", values.get("department")):
		reasons.append(_("Department {0} does not exist.").format(values.get("department")))
	try:
		if getdate(values.get("collected_on")) > getdate(now_datetime()):
			reasons.append(_("Collection date cannot be in the future."))
	except Exception:
		reasons.append(_("Collection date is not valid."))
	year = values.get("birth_year")
	if year not in (None, "") and not 1900 <= cint(year) <= now_datetime().year:
		reasons.append(_("Birth year {0} is not valid.").format(year))
	if values.get("sex") not in (None, "", "Male", "Female", "Other"):
		reasons.append(_("Sex must be Male, Female or Other."))
	rows = susceptibility_rows(susceptibility)
	if not rows:
		reasons.append(_("Enter at least one antibiotic result."))
	for row in rows:
		if row["result"] not in RESULTS:
			reasons.append(_("Antibiotic {0}: result must be S, I or R.").format(row["antibiotic"]))
	if organism and exists(values.get("lab_sample_id"), organism):
		reasons.append(
			_("Isolate {0} with organism {1} already exists.").format(
				sample_id(values.get("lab_sample_id")), organism
			)
		)
	return reasons


# --- controller ---------------------------------------------------------------------------------------------------


def validate(doc):
	if not doc.flags.tc_micro:
		frappe.throw(
			_(
				"Microbiology isolates are recorded by file import or confirmed manual entry and cannot be changed."
			)
		)
	if not doc.is_new():
		return
	patient_code.apply(doc)
	doc.lab_sample_id = sample_id(doc.lab_sample_id)
	if exists(doc.lab_sample_id, doc.organism):
		frappe.throw(
			_("Isolate {0} with organism {1} already exists.").format(doc.lab_sample_id, doc.organism)
		)
	if getdate(doc.collected_on) > getdate(now_datetime()):
		frappe.throw(_("Collection date cannot be in the future."))
	for row in doc.susceptibility:
		if row.result not in RESULTS:
			frappe.throw(_("Antibiogram row {0}: result must be S, I or R.").format(row.idx))
	if doc.source == SOURCE_MANUAL and not doc.confirmed_by:
		frappe.throw(_("A manually entered result needs the confirmation of the person entering it."))
	doc.period_key = period_key(doc.collected_on)
	_label(doc)


def _label(doc):
	results = {row.antibiotic: row.result for row in doc.susceptibility}
	matched = [
		rule
		for rule in rules.active_rules(doc.collected_on)
		if rules.matches(rule, doc.organism, doc.organism_group, results)
	]
	doc.is_mdro = int(bool(matched))
	doc.mdro_flags = ", ".join(dict.fromkeys(rule.label for rule in matched)) or None
	doc.mdro_rule_versions = "\n".join(rule.name for rule in matched) or None
	doc.flags.tc_mdro_rules = matched


def after_insert(doc):
	doc.flags.tc_micro = False  # cờ chỉ cho lần ghi này: lưu lại cùng object sau đó cũng bị chặn
	refresh_first_isolate(doc.patient_code_hash, doc.organism, doc.period_key)
	doc.is_first_isolate = frappe.db.get_value(DOCTYPE, doc.name, "is_first_isolate")
	if doc.is_mdro:
		_alert(doc, doc.flags.tc_mdro_rules or [])
		extension.run(MDRO_HOOK, doc)


def refresh_first_isolate(hash_value, organism, period):
	"""Đánh dấu lại chủng đầu tiên của một (người bệnh, loài, quý)."""
	if not hash_value:
		return
	rows = frappe.get_all(
		DOCTYPE,
		filters={"patient_code_hash": hash_value, "organism": organism, "period_key": period},
		fields=["name", "is_first_isolate"],
		order_by="collected_on asc, lab_sample_id asc, name asc",
	)
	for index, row in enumerate(rows):
		wanted = int(index == 0)
		if row.is_first_isolate != wanted:
			frappe.db.set_value(DOCTYPE, row.name, "is_first_isolate", wanted, update_modified=False)


# --- thông báo ----------------------------------------------------------------------------------------------------


def _network_users(department):
	employees = frappe.get_all(
		NETWORK_DOCTYPE, filters={"department": department, "is_active": 1}, pluck="employee"
	)
	if not employees:
		return []
	return frappe.get_all(
		"Employee", filters={"name": ["in", employees], "status": "Active"}, pluck="user_id"
	)


def _department_role_users(department):
	allowed = frappe.get_all(
		"User Permission", filters={"allow": "Department", "for_value": department}, pluck="user"
	)
	if not allowed:
		return []
	return frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": DEPARTMENT_ROLE, "parent": ["in", allowed]},
		pluck="parent",
	)


def _role_users(roles):
	if not roles:
		return []
	return frappe.get_all("Has Role", filters={"parenttype": "User", "role": ["in", roles]}, pluck="parent")


def recipients(doc, matched) -> list[str]:
	roles = [line.strip() for rule in matched for line in cstr(rule.alert_roles).splitlines() if line.strip()]
	users = _network_users(doc.department) + _department_role_users(doc.department) + _role_users(roles)
	return [user for user in dict.fromkeys(users) if user]


def _alert(doc, matched):
	precautions = ", ".join(dict.fromkeys(_(rule.precaution_type) for rule in matched))
	history = mdro_history(
		[{"name": doc.name, "patient_code_hash": doc.patient_code_hash, "collected_on": doc.collected_on}]
	)[doc.name]
	message = _(
		"Isolate {0}: {1} ({2}), patient {3}, department {4}. Recommended isolation precaution: {5}."
	).format(
		doc.name,
		doc.mdro_flags,
		doc.organism_name or doc.organism,
		doc.patient_code_masked,
		doc.department_name or doc.department,
		precautions,
	)
	if history:
		message += " " + _("Previously carried a multidrug-resistant organism: {0}.").format(
			", ".join(history)
		)
	notification.emit(
		MDRO_EVENT,
		doc=doc,
		subject=_("New multidrug-resistant isolate {0} in {1}").format(
			doc.mdro_flags, doc.department_name or doc.department
		),
		message=message,
		users=recipients(doc, matched),
		link=SCREEN_LINK,
	)


# --- tiền sử đa kháng (FR-M14-05) ----------------------------------------------------------------------------------


def mdro_history(rows) -> dict:
	"""{tên chủng: [nhãn đa kháng của chủng KHÁC cùng hash mã BN, lấy mẫu không muộn hơn]} — so bằng hash."""
	hashes = {row.get("patient_code_hash") for row in rows if row.get("patient_code_hash")}
	previous = (
		frappe.get_all(
			DOCTYPE,
			filters={"patient_code_hash": ["in", list(hashes)], "is_mdro": 1},
			fields=["name", "patient_code_hash", "mdro_flags", "collected_on"],
			order_by="collected_on asc",
		)
		if hashes
		else []
	)
	out = {}
	for row in rows:
		labels = []
		for other in previous:
			if other.patient_code_hash != row.get("patient_code_hash") or other.name == row.get("name"):
				continue
			if row.get("collected_on") and getdate(other.collected_on) > getdate(row.get("collected_on")):
				continue
			labels += [label.strip() for label in cstr(other.mdro_flags).split(",") if label.strip()]
		out[row.get("name")] = list(dict.fromkeys(labels))
	return out


def history_by_hash(hashes) -> dict:
	"""{hash: [nhãn đa kháng đã từng có]} cho module khác (M13) tra theo hash, không giải mã."""
	hashes = [value for value in dict.fromkeys(hashes or ()) if value]
	if not hashes:
		return {}
	out: dict = {value: [] for value in hashes}
	for row in frappe.get_all(
		DOCTYPE,
		filters={"patient_code_hash": ["in", hashes], "is_mdro": 1},
		fields=["patient_code_hash", "mdro_flags"],
		order_by="collected_on asc",
	):
		for label in cstr(row.mdro_flags).split(","):
			if label.strip() and label.strip() not in out[row.patient_code_hash]:
				out[row.patient_code_hash].append(label.strip())
	return out
