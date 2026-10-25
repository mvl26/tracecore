"""Permission-filtered data for the standalone Vue shell. No impersonation."""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.ui.admin_registry import ROLES, SCREENS

LABEL_CONTEXT = "TraceCore Admin"


def _label(text):
	"""Nhãn registry (chuỗi nguồn tiếng Anh) theo ngôn ngữ người dùng."""
	return _(text, context=LABEL_CONTEXT) if text else text


MASTER_FIELDS = {
	"instruments": [
		"instrument_code",
		"instrument_name",
		"manufacturer",
		"model",
		"instrument_group",
		"spaulding_class",
		"maint_interval_cycles",
		"maint_type",
		"max_cycles",
		"value",
		"item",
	],
	"set-types": [
		"set_type_name",
		"method",
		"department",
		"default_pack_type",
		"shelf_life_days",
		"assembly_minutes",
		"is_implant",
		"gtin",
	],
}


def _signed_in():
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to open TraceCore."), frappe.PermissionError)


def available_roles():
	_signed_in()
	if frappe.session.user == "Administrator":
		return list(ROLES)
	assigned = set(frappe.get_roles())
	# get_roles synthesizes every role for Administrator, handled explicitly above.
	if "TC Admin Overview" in assigned:
		return list(ROLES)
	return [role for role in ROLES if f"TC {role}" in assigned]


def _screen(role, screen):
	if role not in available_roles() or screen not in ROLES[role][2] or screen not in SCREENS:
		frappe.throw(_("This workspace is not available for this account."), frappe.PermissionError)
	return SCREENS[screen]


def _schema(doctype, requested):
	meta = frappe.get_meta(doctype)
	roles = set(frappe.get_roles())
	levels = {cint(perm.permlevel) for perm in meta.permissions if perm.role in roles and perm.get("read")}
	return [
		field
		for field in requested
		if meta.has_field(field) and cint(getattr(meta.get_field(field), "permlevel", 0)) in levels
	]


def _availability(doctype):
	if not doctype or not frappe.db.exists("DocType", doctype):
		return "not_implemented"
	return "ready" if frappe.has_permission(doctype, ptype="read") else "forbidden"


@frappe.whitelist(methods=["GET"])
def bootstrap():
	roles = available_roles()
	spaces = []
	for role in roles:
		title, description, screens = ROLES[role]
		spaces.append(
			{
				"id": role,
				"title": _label(title),
				"description": _label(description),
				"screens": [
					{
						"id": screen,
						"title": _label(SCREENS[screen][0]),
						"state": _availability(SCREENS[screen][1]),
					}
					if screen != "dashboard"
					else {"id": "dashboard", "title": _("Overview"), "state": "ready"}
					for screen in screens
				],
			}
		)
	return {
		"user": frappe.session.user,
		"full_name": frappe.db.get_value("User", frappe.session.user, "full_name"),
		"roles": spaces,
		"csrf_token": frappe.sessions.get_csrf_token(),
		"admin_overview": frappe.session.user == "Administrator" or "TC Admin Overview" in frappe.get_roles(),
	}


def _readable(role, screen):
	title, doctype, requested = _screen(role, screen)
	if _availability(doctype) != "ready":
		frappe.throw(_("This screen is unavailable or you do not have permission."), frappe.PermissionError)
	return title, doctype, _schema(doctype, requested)


def _filters(screen, search):
	filters = {}
	if screen == "sterile-stock":
		filters["status"] = "In Sterile Stock"
	if screen == "items":
		filters["tc_item_group_cssd"] = ["!=", ""]
	if search:
		# Escape SQL LIKE wildcards: search is a literal fragment, not a wildcard query.
		fragment = str(search)[:140].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
		filters["name"] = ["like", f"%{fragment}%"]
	return filters


@frappe.whitelist(methods=["GET"])
def records(role, screen, search="", start=0):
	title, doctype, fields = _readable(role, screen)
	offset = max(0, min(cint(start), 100000))
	rows = frappe.get_list(
		doctype,
		fields=["name", "modified", *fields],
		filters=_filters(screen, search),
		order_by="modified desc, name asc",
		start=offset,
		page_length=26,
	)
	return {
		"title": _label(title),
		"doctype": doctype,
		"fields": fields,
		"rows": rows[:25],
		"has_more": len(rows) > 25,
		"start": offset,
		"can_create": screen in MASTER_FIELDS and bool(frappe.has_permission(doctype, ptype="create")),
		"can_issue": screen == "set-units"
		and bool(set(frappe.get_roles()) & {"TC R02", "TC R10", "System Manager"}),
	}


@frappe.whitelist(methods=["GET"])
def detail(role, screen, name):
	title, doctype, fields = _readable(role, screen)
	# Query membership as well as document permission, preserving User Permissions/department filters.
	if not frappe.get_list(doctype, filters={"name": name}, pluck="name", page_length=1):
		frappe.throw(_("You do not have permission to read this record."), frappe.PermissionError)
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	fields = [
		field
		for field in fields
		if not doc.meta.get_field(field) or doc.has_permlevel_access_to(field, permission_type="read")
	]
	return {
		"title": _label(title),
		"doctype": doctype,
		"record": {field: doc.get(field) for field in ["name", "modified", *fields]},
	}


@frappe.whitelist(methods=["GET"])
def master_form(role, screen, name=None):
	if screen not in MASTER_FIELDS:
		frappe.throw(_("This screen cannot be edited here."), frappe.PermissionError)
	_title, doctype, _fields = _readable(role, screen)
	doc = frappe.get_doc(doctype, name) if name else frappe.new_doc(doctype)
	doc.check_permission("read" if name else "create")
	meta = frappe.get_meta(doctype)
	fields = []
	form_fields = (["type_code"] if screen == "set-types" and not name else []) + MASTER_FIELDS[screen]
	for field in form_fields:
		df = meta.get_field(field)
		if not df or not doc.has_permlevel_access_to(field, permission_type="read"):
			continue
		fields.append(
			{
				"name": field,
				"label": _(df.label),
				"type": df.fieldtype,
				"options": df.options if df.fieldtype == "Select" else None,
				"required": bool(df.reqd),
				"readonly": bool(name and df.set_only_once)
				or not doc.has_permlevel_access_to(field, permission_type="write"),
			}
		)
	values = {field["name"]: doc.get(field["name"]) for field in fields}
	if screen == "instruments" and doc.has_permlevel_access_to("compatible_methods", permission_type="read"):
		values["compatible_methods"] = [row.method for row in doc.get("compatible_methods", [])]
	return {
		"fields": fields,
		"values": values,
		"modified": str(doc.modified or ""),
		"can_write": bool(doc.has_permission("write" if name else "create")),
		"can_write_methods": screen == "instruments"
		and doc.has_permlevel_access_to("compatible_methods", permission_type="write"),
	}


@frappe.whitelist(methods=["POST"])
def save_master(role, screen, values, name=None, modified=None):
	if screen not in MASTER_FIELDS:
		frappe.throw(_("This screen cannot be edited here."), frappe.PermissionError)
	_title, doctype, _fields = _readable(role, screen)
	values = frappe.parse_json(values) if isinstance(values, str) else values
	allowed = set(MASTER_FIELDS[screen]) | ({"compatible_methods"} if screen == "instruments" else set())
	if not isinstance(values, dict) or set(values) - allowed:
		frappe.throw(_("This request contains fields that cannot be edited."))
	if screen == "set-types" and not name:
		frappe.throw(_("Create a set type together with its BOM."), frappe.PermissionError)
	doc = frappe.get_doc(doctype, name) if name else frappe.new_doc(doctype)
	doc.check_permission("write" if name else "create")
	if name and (not modified or str(doc.modified) != str(modified)):
		frappe.throw(_("The record has changed. Reload before saving."), frappe.TimestampMismatchError)
	for key, value in values.items():
		if not doc.has_permlevel_access_to(key, permission_type="write") and value != doc.get(key):
			frappe.throw(_("You do not have permission to edit this field."), frappe.PermissionError)
		if key == "compatible_methods":
			if (
				not isinstance(value, list)
				or len(value) > 4
				or not all(isinstance(item, str) for item in value)
			):
				frappe.throw(_("Compatible methods must be a list of methods."))
			doc.set(key, [{"method": item} for item in value])
		else:
			doc.set(key, value)
	doc.save()
	return {"name": doc.name, "modified": str(doc.modified)}


@frappe.whitelist(methods=["GET"])
def dashboard(role):
	if role not in available_roles():
		frappe.throw(_("This workspace is not available for this account."), frappe.PermissionError)
	counts = []
	for screen in ROLES[role][2]:
		if screen == "dashboard":
			continue
		title, doctype, _fields = SCREENS[screen]
		if _availability(doctype) == "ready":
			# Bounded, permission-aware counts, explicitly label saturation.
			rows = frappe.get_list(doctype, fields=["name"], filters=_filters(screen, ""), page_length=1001)
			counts.append(
				{
					"screen": screen,
					"title": _label(title),
					"count": min(len(rows), 1000),
					"capped": len(rows) > 1000,
				}
			)
	attention = []
	for screen, statuses in [
		("overrides", ["Requested"]),
		("recalls", ["Open", "In Progress"]),
		("equipment", ["Locked"]),
	]:
		if screen not in ROLES[role][2]:
			continue
		title, doctype, _fields = SCREENS[screen]
		if _availability(doctype) == "ready" and frappe.get_meta(doctype).has_field("status"):
			rows = frappe.get_list(
				doctype,
				fields=["name", "status"],
				filters={"status": ["in", statuses]},
				page_length=6,
				order_by="modified desc",
			)
			attention.extend(
				{"screen": screen, "title": _label(title), "name": row.name, "status": row.status}
				for row in rows
			)
	return {"counts": counts, "attention": attention}
