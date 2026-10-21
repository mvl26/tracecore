app_name = "tracecore"
app_title = "TraceCore"
app_publisher = "Miyano Vietnam"
app_description = "Instrument traceability and CSSD / infection control management on Frappe v15"
app_email = "info@miyano.com.vn"
app_license = "gpl-3.0"

# Apps
# ------------------

required_apps = ["erpnext", "hrms"]

# Fixtures (F-7: 10 vai trò TC R01..R10 + TC Agent;
# FEAT-018: Custom Field Item-tc_* cho nhóm CSSD, phương pháp, chỉ thị hóa học, hạn lưu loại gói).
# Khung khu-trạm KHÔNG là fixtures (migrate nhập lại với force, xóa sửa của R10): tracecore.setup.seed
# ------------------
fixtures = [
	{"dt": "Role", "filters": [["name", "like", "TC %"]]},
	{"dt": "Custom DocPerm", "filters": [["role", "like", "TC R%"]]},
	{"dt": "Custom Field", "filters": [["name", "like", "Item-tc_%"]]},
]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "tracecore",
# 		"logo": "/assets/tracecore/logo.png",
# 		"title": "TraceCore",
# 		"route": "/tracecore",
# 		"has_permission": "tracecore.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# Biến --tc-* sinh từ docs/tokens.json (scripts/build_tokens.py) + ánh xạ biến Frappe Desk
app_include_css = ["tracecore.bundle.css"]  # bundle có hash: tokens.css + tracecore-theme.css
# app_include_js = "/assets/tracecore/js/tracecore.js"

# include js, css files in header of web template
# web_include_css = "/assets/tracecore/css/tracecore.css"
# web_include_js = "/assets/tracecore/js/tracecore.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "tracecore/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# Màn T4 đóng gói (SCR-08, FEAT-018): Frappe nối file này sau station.js trong script của Page station
page_js = {"station": "public/js/station_t4.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "tracecore/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "tracecore.utils.jinja_methods",
# 	"filters": "tracecore.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "tracecore.install.before_install"
after_install = "tracecore.setup.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "tracecore.uninstall.before_uninstall"
# after_uninstall = "tracecore.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "tracecore.utils.before_app_install"
# after_app_install = "tracecore.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "tracecore.utils.before_app_uninstall"
# after_app_uninstall = "tracecore.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "tracecore.build.after_build"

# To hook into the build process of other apps
# The list of apps being built is passed as an argument

# after_app_build = "tracecore.build.after_app_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "tracecore.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["tracecore.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

_AUDIT_EVENTS = {
	"after_insert": "tracecore.core.audit.on_document_event",
	"on_update": "tracecore.core.audit.on_document_event",
	"on_submit": "tracecore.core.audit.on_document_event",
	"on_cancel": "tracecore.core.audit.on_document_event",
	"on_trash": "tracecore.core.audit.block_delete",
}

doc_events = {
	"Set Unit": dict(_AUDIT_EVENTS),
	"Instrument": dict(_AUDIT_EVENTS),
	"Set BOM Item": dict(_AUDIT_EVENTS),
	"Instrument Maintenance": dict(_AUDIT_EVENTS),
	"Step Gate Result": dict(_AUDIT_EVENTS),
	"Assembly Record": dict(_AUDIT_EVENTS),
	# Pack đổi status/void_reason/label_print_count sau khi ghi sổ (on_update_after_submit)
	"Pack": {**_AUDIT_EVENTS, "on_update_after_submit": "tracecore.core.audit.on_document_event"},
	"Printer": dict(_AUDIT_EVENTS),
	"Label Template": dict(_AUDIT_EVENTS),
	"Zone Station": dict(_AUDIT_EVENTS),
	"Equipment": dict(_AUDIT_EVENTS),
	"Process Program": dict(_AUDIT_EVENTS),
	"Equipment Type Norm": dict(_AUDIT_EVENTS),
}

# Hook mở rộng giữa các phân hệ (ADR-001, FEAT-018 D9)
# ---------------
# M2 đóng gói gọi tracecore.core.extension.run("<hook>", …) và không import M1/M8:
#  - context:   (ctx) -> dict gộp vào ngữ cảnh T4 (BOM, nhắc bảo dưỡng, mức dùng cơ số)
#  - prechecks: (ctx) -> Block | None, chạy trước kiểm tra bảo dưỡng (cơ số)
#  - checks:    (ctx) -> Block | None (bảo dưỡng)
#  - after:     (pack_doc, ctx) -> None, chạy sau khi sinh Cycle ID (cập nhật bộ đếm bảo dưỡng)

tracecore_pack_context = [
	"tracecore.instrument.bom.pack_context",
	"tracecore.instrument.maintenance.pack_context",
	"tracecore.par.check.pack_context",
]
tracecore_pack_prechecks = ["tracecore.par.check.check_pack"]
tracecore_pack_checks = ["tracecore.instrument.maintenance.check_pack"]
tracecore_after_cycle_id = ["tracecore.instrument.maintenance.apply_pack"]

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily": [
		"tracecore.core.idempotency.purge_expired",
	],
}

# scheduler_events = {
# 	"all": [
# 		"tracecore.tasks.all"
# 	],
# 	"daily": [
# 		"tracecore.tasks.daily"
# 	],
# 	"hourly": [
# 		"tracecore.tasks.hourly"
# 	],
# 	"weekly": [
# 		"tracecore.tasks.weekly"
# 	],
# 	"monthly": [
# 		"tracecore.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "tracecore.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "tracecore.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "tracecore.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["tracecore.utils.before_request"]
# after_request = ["tracecore.utils.after_request"]

# Job Events
# ----------
# before_job = ["tracecore.utils.before_job"]
# after_job = ["tracecore.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"tracecore.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
