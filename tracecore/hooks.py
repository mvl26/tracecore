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
# FEAT-018: Custom Field Item-tc_* cho nhóm CSSD, phương pháp, chỉ thị hóa học, hạn lưu loại gói;
# FEAT-041: thêm Stock Entry-tc_*, Stock Entry Detail-tc_* cho nhập kho theo lô/hạn).
# Khung khu-trạm KHÔNG là fixtures (migrate nhập lại với force, xóa sửa của R10): tracecore.setup.seed
# ------------------
fixtures = [
	{"dt": "Role", "filters": [["name", "like", "TC %"]]},
	{"dt": "Custom DocPerm", "filters": [["role", "like", "TC R%"]]},
	{
		"dt": "Custom Field",
		"or_filters": [
			["name", "like", "Item-tc_%"],
			["name", "like", "Stock Entry-tc_%"],
			["name", "like", "Stock Entry Detail-tc_%"],
			["name", "like", "Employee-tc_%"],
			["name", "like", "Department-tc_%"],
			["name", "like", "Shift Assignment-tc_%"],  # FEAT-037: Khu làm việc của ca
			["name", "like", "Stock Reconciliation Item-tc_%"],  # FEAT-043: lý do chênh lệch kiểm kê
			["name", "like", "Stock Reconciliation-tc_%"],  # FEAT-043: phiếu kiểm kê bỏ dở
		],
	},
	# FEAT-036: nhân viên mới đặt tên theo series NV- (giữ HR-EMP- trong danh sách để nhân viên cũ vẫn lưu được)
	{"dt": "Property Setter", "filters": [["name", "like", "Employee-naming_series-%"]]},
	# Phân ca: ẩn Shift Location (chấm công GPS của HRMS); khu của ca là tc_zone
	{"dt": "Property Setter", "filters": [["name", "=", "Shift Assignment-shift_location-hidden"]]},
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
# Hàm dùng chung tracecore.codes.* (in nhãn QR đối tượng, cấp mã cuộn — FEAT-005): bundle có hash nhập tc_codes.js
app_include_js = ["tracecore.bundle.js"]

# include js, css files in header of web template
# web_include_css = "/assets/tracecore/css/tracecore.css"
# web_include_js = "/assets/tracecore/js/tracecore.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "tracecore/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# Màn T4 đóng gói (SCR-08, FEAT-018), T6 kho vô khuẩn (SCR-11, FEAT-025), T2 lô rửa (SCR-06, FEAT-021),
# T1 tiếp nhận (SCR-05, SCR-34, FEAT-019), T3 kiểm đếm (SCR-07, FEAT-020), T5 nạp mẻ (SCR-09, SCR-35, FEAT-022),
# T5b dỡ mẻ, giải phóng (SCR-10, FEAT-023), T7 cấp phát (SCR-12/SCR-36, FEAT-026) và T8 quét sử dụng (SCR-37,
# FEAT-027): Frappe nối các file này sau station.js trong script của Page station
page_js = {
	"station": [
		"public/js/station_t4.js",
		"public/js/station_t6.js",
		"public/js/station_t2.js",
		"public/js/station_t1.js",
		"public/js/station_t3.js",
		"public/js/station_t5.js",
		"public/js/station_t5b.js",
		"public/js/station_daily_test.js",
		"public/js/station_t7.js",
		"public/js/station_t8.js",
		# FEAT-033: thu gom đồ vải (SCR-16) và component dòng cân dùng chung (FEAT-047 dùng lại)
		"public/js/tc_weigh_line.js",
		"public/js/station_linen.js",
		# FEAT-034: lô giặt theo kg (SCR-17) trong trạm đồ vải
		"public/js/station_laundry.js",
		# FEAT-035: cấp phát đồ vải (SCR-18), lớp con của LinenCollect nên nạp sau station_linen.js
		"public/js/station_linen_issue.js",
		# FEAT-009: hàng đợi offline IndexedDB + phát lại theo client_ts (TcOutbox, tcSync)
		"public/js/tc_outbox.js",
	]
}

# include js in doctype views
# Form Item (ERPNext): nút "Cấp mã cuộn" cho Item nhóm Nhãn (FEAT-005, A-05 R3) và khai báo vật tư CSSD (FEAT-041);
# Stock Entry: phiếu nhập kho vật tư theo lô/hạn và nhập từ Excel (FEAT-041, SCR-24);
# Employee (HRMS): nút "Đặt PIN trạm" cho R10/R02 (FR-M9-09.1)
doctype_js = {
	"Item": "public/js/item.js",
	"Stock Entry": "public/js/stock_entry.js",
	"Employee": "public/js/employee.js",
}
doctype_list_js = {"Stock Entry": "public/js/stock_entry_list.js"}
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
# Print Format "TC Count Sheet" (FEAT-015 S9) gọi tc_count_sheet_context(doc.name) khi in từ Desk. Chỉ trỏ tới MỘT hàm
# (không cả module) để không đưa hàm khác của count_sheet vào môi trường Jinja chung của site.
jinja = {
	"methods": [
		"tracecore.instrument.count_sheet.tc_count_sheet_context",
		# Print Format "TC Issue Note" (FEAT-026 C10): phiếu cấp phát T7
		"tracecore.ui.issue_print.tc_issue_note_context",
		# Print Format "TC Loaner Receipt" / "TC Loaner Return" (FEAT-017, A-38): biên bản nhận / trả bộ mượn
		"tracecore.instrument.loaner.tc_loaner_context",
		# Print Format "TC Linen Receipt" (FEAT-033, FR-M3-01.5): biên nhận thu gom đồ vải
		"tracecore.ui.linen_print.tc_linen_receipt_context",
		# Print Format "TC Linen Issue Receipt" (FEAT-035, FR-M3-05.1): biên nhận cấp phát đồ vải
		"tracecore.ui.linen_print.tc_linen_issue_context",
		# Print Format "TC Stock Count Sheet" (FEAT-043, FR-M6-05): phiếu kiểm kê kho
		"tracecore.ui.stock_count_print.tc_stock_count_context",
	]
}

# Installation
# ------------

# before_install = "tracecore.install.before_install"
after_install = "tracecore.setup.install.after_install"
# Quyền R09/R06/R10/R02 cho Item, Batch, Stock Entry (FEAT-041, A-07 V11): Custom DocPerm idempotent
after_migrate = [
	"tracecore.inventory.permissions.ensure_permissions",
	"tracecore.setup.install.apply_system_settings",
	# FEAT-010: Notification Rule mặc định cho mọi loại sự kiện (không ghi đè chỉnh sửa của R10)
	"tracecore.core.notification.ensure_default_rules",
	# FEAT-037: quyền R02/R10/R01 cho HRMS Shift Assignment và Shift Type
	"tracecore.hr.permissions.ensure_permissions",
]

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

# Thông báo (FEAT-010): mỗi người chỉ thấy thông báo của mình; R10 và System Manager thấy tất cả
permission_query_conditions = {
	"Notification Delivery": "tracecore.core.notification.delivery_query_conditions",
}

has_permission = {
	"Notification Delivery": "tracecore.core.notification.delivery_has_permission",
}

# DocType Class
# ---------------
# Override standard doctype classes

# File: kiểm ảnh/IFU của dụng cụ và ảnh bộ đã xếp của loại bộ trước khi Frappe đọc nội dung (SVG đổi đuôi .jpg, HTML
# đổi đuôi .pdf → lỗi sạch thay vì HTTP 500; FEAT-014 A-06 I11, FEAT-015 S6). Chỉ File đính vào đích của
# media.TARGETS bị kiểm; File khác đi nguyên đường của Frappe. Chưa app nào khác trong bench ghi đè File.
override_doctype_class = {"File": "tracecore.instrument.media.InstrumentMediaFile"}

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
	"User": {
		"before_validate": "tracecore.core.account.validate_user",
		"after_insert": "tracecore.core.account.user_updated",
		"on_update": "tracecore.core.account.user_updated",
		"on_trash": "tracecore.core.audit.block_delete",
	},
	"Employee": {
		"onload": "tracecore.core.account.employee_onload",
		# FEAT-036: mã NV- vào Code Registry, thẻ mặc định, đặt lại mức nhắc khi đổi ngày hạn
		"after_insert": "tracecore.hr.employees.after_insert",
		"before_save": "tracecore.hr.employees.before_save",
		"before_validate": "tracecore.core.account.validate_employee",
		"on_update": "tracecore.core.account.employee_updated",
		"on_trash": "tracecore.core.audit.block_delete",
	},
	"Set Unit": dict(_AUDIT_EVENTS),
	"Instrument": dict(_AUDIT_EVENTS),
	"Instrument Group": dict(_AUDIT_EVENTS),
	# loại bộ: Create/Update có old/new (ảnh, hạn lưu, phương pháp, GTIN), không xóa (FEAT-015 S14)
	"Instrument Set Type": dict(_AUDIT_EVENTS),
	"Set BOM Item": dict(_AUDIT_EVENTS),
	# bộ mượn (FEAT-017, A-38): nhận/trả/gia hạn ghi Audit Update kèm lý do, không hủy, không xóa
	"Loaner Set": dict(_AUDIT_EVENTS),
	# chứng chỉ nhân viên (FEAT-036): Create/Update có old/new, không xóa (giữ lịch sử gia hạn)
	"Certificate": dict(_AUDIT_EVENTS),
	# ca làm việc (FEAT-037): xếp ca vào khu cần năng lực trạm của khu đó (FR-M4-04.1); ghi sổ/hủy có Audit
	"Shift Assignment": {"validate": "tracecore.hr.shifts.validate_assignment", **_AUDIT_EVENTS},
	# cơ số: Create/Update có old/new, không xóa (FEAT-031, FR-M8-01.3)
	"Par Level": dict(_AUDIT_EVENTS),
	# ghi đè cơ số (FEAT-032, WF-08): quyết định và bộ đếm đổi sau khi ghi sổ (on_update_after_submit), không xóa
	"Par Override": {**_AUDIT_EVENTS, "on_update_after_submit": "tracecore.core.audit.on_document_event"},
	"Instrument Maintenance": dict(_AUDIT_EVENTS),
	"Step Gate Result": dict(_AUDIT_EVENTS),
	"Assembly Record": dict(_AUDIT_EVENTS),
	# sự cố / NC / CAPA (FEAT-030, WF-06): chuyển trạng thái có old/new, không xóa (FR-M2-21.4)
	"Incident CAPA": dict(_AUDIT_EVENTS),
	# lệnh thu hồi (FEAT-029, WF-05): xác nhận từng gói có old/new, không xóa
	"Recall Order": dict(_AUDIT_EVENTS),
	# lô rửa T2 (FEAT-021): tạo khi Hoàn thành nạp, ghi sổ khi có kết luận
	"Wash Batch": dict(_AUDIT_EVENTS),
	# mẻ tiệt khuẩn T5 (FEAT-022): tạo khi Hoàn thành nạp, cập nhật khi nhập tay dữ liệu chu trình
	"Sterilization Load": dict(_AUDIT_EVENTS),
	# phiếu tiếp nhận T1 (FEAT-019): nháp tạo khi quét thẻ người giao, ghi sổ khi hoàn tất; không xóa
	"Dirty Receipt": dict(_AUDIT_EVENTS),
	# Pack đổi status/void_reason/label_print_count sau khi ghi sổ (on_update_after_submit)
	"Pack": {**_AUDIT_EVENTS, "on_update_after_submit": "tracecore.core.audit.on_document_event"},
	# kho vô khuẩn (FEAT-025): kệ KE- và chứng từ nhập kho / chuyển vị trí
	"Sterile Location": dict(_AUDIT_EVENTS),
	"Sterile Putaway": dict(_AUDIT_EVENTS),
	# phiếu cấp phát T7 (FEAT-026): nháp đổi danh sách gói/người nhận, ghi sổ khi xác nhận; không xóa
	"Issue Note": dict(_AUDIT_EVENTS),
	# quét sử dụng T8 (FEAT-027): mã bệnh nhân (Password) bị bỏ khỏi Audit; bổ sung mã sau ghi sổ (ca cấp cứu)
	"Usage Record": {**_AUDIT_EVENTS, "on_update_after_submit": "tracecore.core.audit.on_document_event"},
	"Printer": dict(_AUDIT_EVENTS),
	"Label Template": dict(_AUDIT_EVENTS),
	"Zone Station": dict(_AUDIT_EVENTS),
	"Equipment": dict(_AUDIT_EVENTS),
	# test hằng ngày (FEAT-040): ghi một lần, không sửa, không xóa
	"Daily Test": dict(_AUDIT_EVENTS),
	# nhật ký môi trường khu (FEAT-008, A-55): ghi sổ/hủy có old/new, không xóa
	"Environment Log": dict(_AUDIT_EVENTS),
	# hồ sơ bảo trì/kiểm định/hiệu chuẩn/sự cố (FEAT-039, A-43): ghi sổ có old/new, không xóa
	"Maintenance Record": dict(_AUDIT_EVENTS),
	# chi phí theo kỳ (FEAT-044, A-47): ghi sổ có old/new, không xóa; khóa kỳ và danh mục khoản mục cũng ghi vết
	"Cost Entry": dict(_AUDIT_EVENTS),
	"Cost Category": dict(_AUDIT_EVENTS),
	"Cost Settings": dict(_AUDIT_EVENTS),
	# đồ vải (FEAT-033, A-49): loại đồ vải và phiếu thu gom ghi vết, không xóa
	"Linen Type": dict(_AUDIT_EVENTS),
	"Linen Collection": dict(_AUDIT_EVENTS),
	"Laundry Batch": dict(_AUDIT_EVENTS),  # FEAT-034, A-50: lô giặt ghi vết, không xóa
	"Linen Issue": dict(_AUDIT_EVENTS),  # FEAT-035, A-51
	"Process Program": dict(_AUDIT_EVENTS),
	"Equipment Type Norm": dict(_AUDIT_EVENTS),
	# cờ tính năng toàn site (FEAT-014 A-06 I7): đổi cờ ghi Audit Log, không xóa
	"TraceCore Settings": dict(_AUDIT_EVENTS),
	# vật tư tiêu hao CSSD trên Item ERPNext (FEAT-041, A-07): chặn trùng mã; nhóm, nhãn, hạn dùng, tồn tối thiểu
	"Item": {
		"before_insert": "tracecore.inventory.items.check_duplicate_code",
		"validate": "tracecore.inventory.items.validate_item",
		"after_insert": "tracecore.inventory.audit.on_cssd_event",
		"on_update": [
			"tracecore.inventory.audit.on_cssd_event",
			# nhóm Packaging đổi hạn lưu loại gói qua form Item → Audit Log Update, không chặn (FEAT-015 S7)
			"tracecore.instrument.shelf_life.audit_item_change",
		],
	},
	# Batch và phiếu nhập kho vật tư: Audit Log chỉ khi liên quan Item CSSD; xóa bị chặn ở permission (không on_trash)
	"Batch": {
		"after_insert": "tracecore.inventory.audit.on_cssd_event",
		"on_update": "tracecore.inventory.audit.on_cssd_event",
	},
	# phiếu kiểm kê: lý do khi lệch > 10 %, một kho một phiếu mở (FEAT-043, FR-M6-05)
	"Stock Reconciliation": {
		"validate": "tracecore.inventory.count.validate",
		"before_submit": "tracecore.inventory.count.before_submit",
	},
	# đề nghị mua tạo từ cảnh báo tồn: chỉ bản Nháp xóa được (FEAT-043, A-52 C12)
	"Material Request": {"on_trash": "tracecore.inventory.count.only_draft_deletable"},
	"Stock Entry": {
		# nhập kho vật tư theo lô/hạn (FEAT-041, FR-M6-01): kiểm dòng, tạo Batch khi ghi sổ
		"before_validate": "tracecore.inventory.receipt.prepare_receipt",
		# khóa xuất nhập thủ công khi kho đang kiểm kê (FEAT-043, FR-M6-05.2)
		"validate": "tracecore.inventory.count.check_warehouse_lock",
		"after_insert": "tracecore.inventory.audit.on_cssd_event",
		"on_update": "tracecore.inventory.audit.on_cssd_event",
		"on_submit": "tracecore.inventory.audit.on_cssd_event",
		"on_cancel": "tracecore.inventory.audit.on_cssd_event",
	},
	# ảnh/IFU của dụng cụ, ảnh khay loại bộ (media.TARGETS): kiểm nội dung, giới hạn cỡ, luôn riêng tư; File có sẵn đính
	# lại cũng kiểm (FEAT-014 A-06 I11, FEAT-015 S6)
	"File": {
		"before_insert": "tracecore.instrument.media.check_upload",
		"validate": "tracecore.instrument.media.validate_file",
	},
	"Station Competency": dict(_AUDIT_EVENTS),
}

# Hook mở rộng giữa các phân hệ (ADR-001, FEAT-018 D9)
# ---------------
# M2 đóng gói gọi tracecore.core.extension.run("<hook>", …) và không import M1/M8:
#  - context:   (ctx) -> dict gộp vào ngữ cảnh T4 (BOM, nhắc bảo dưỡng, mức dùng cơ số)
#  - prechecks: (ctx) -> Block | None, chạy trước kiểm tra bảo dưỡng (cơ số)
#  - checks:    (ctx) -> Block | None (bảo dưỡng)
#  - after:     (pack_doc, ctx) -> None, chạy sau khi sinh Cycle ID (cập nhật bộ đếm bảo dưỡng)
#  - release:   (ctx) -> None, sau khi mẻ giải phóng Đạt (FEAT-014 I16; +1 chu trình kể từ lần bảo dưỡng)

tracecore_pack_context = [
	"tracecore.instrument.bom.pack_context",
	"tracecore.instrument.maintenance.pack_context",
	"tracecore.par.check.pack_context",
]
tracecore_pack_prechecks = ["tracecore.par.check.check_pack"]
# FEAT-037, FR-M4-03.1: chứng chỉ bắt buộc của năng lực trạm còn thiếu/hết hạn khi đăng nhập trạm (core không import hr)
tracecore_competency_missing_certificates = ["tracecore.hr.competency.missing_certificate_types"]
tracecore_pack_checks = ["tracecore.instrument.maintenance.check_pack"]
tracecore_after_cycle_id = [
	"tracecore.instrument.maintenance.apply_pack",
	# FEAT-032: Cycle ID sinh dưới ghi đè cơ số trừ một chu trình của ghi đè (A-18 Q9)
	"tracecore.par.override.consume",
]
# M2 (FEAT-023) gọi ĐÚNG MỘT LẦN cho mỗi lần giải phóng Đạt: (ctx {set_unit, set_type, bom_version, cycle_id}) -> None,
# +1 bộ đếm bảo dưỡng. cycle_id bắt buộc theo hợp đồng: cùng cycle_id gọi lại không đếm thêm (last_release_cycle);
# thiếu cycle_id thì không chống trùng.
tracecore_after_release = ["tracecore.instrument.maintenance.on_set_released"]
# core.step_gate.start_cycle (FEAT-015 S3): (ctx {set_unit, set_type, cycle_no, on}) -> int | None, phiên bản BOM ghim
# cho chu trình mới (số nguyên đầu tiên được ghi vào Set Unit.cycle_bom_version; không có → 0)
tracecore_cycle_bom_version = ["tracecore.instrument.bom_versions.pin_cycle_version"]
# M2 tiếp nhận T1 (FEAT-019, A-32): (ctx {set_unit, set_type, on}) -> {bom_version, bom, tray_images}, BOM + ảnh áp dụng
# tại ngày tiếp nhận (cùng phiên bản `tracecore_cycle_bom_version` sẽ ghim); M2 không import M1
tracecore_receipt_context = ["tracecore.instrument.bom.receipt_context"]
# M2 (FEAT-019, A-33) gọi sau khi R02 tiếp nhận cưỡng bức một bộ: (ctx {receipt, set_unit, reason, by}) -> None.
# FEAT-030 đăng ký để tự tạo NC (FR-M2-02.2).
tracecore_after_force_receive = []
# core.step_gate gọi sau mỗi lần Set Unit.status thực sự đổi (FEAT-016, A-13 G13): (payload {set_unit, old_status,
# new_status, event, client_ts, ref_doctype, ref_name}) -> None.
# FEAT-017 (A-38 e): bộ mượn trả hãng → M2 hủy gói còn trong kho của chu trình hiện hành.
tracecore_after_set_status = ["tracecore.reprocessing.storage.on_set_status"]
# M1 trả bộ mượn thiếu dụng cụ (FEAT-017, A-38 e): (ctx {loaner, set_unit, missing[{instrument, name, qty}], note})
# -> tên Incident CAPA; M2 tạo NC Missing Instrument (M1 không import M2).
tracecore_loaner_returned = ["tracecore.reprocessing.incidents.on_loaner_returned"]
# M1 cấp Set ID (FEAT-016, A-13 G5): (ctx {set_type}) -> {value, source} | None, cơ số tối đa nguồn của loại bộ;
# M8 trả Par Level riêng của loại bộ, nếu không thì cơ số thấp nhất của dụng cụ trong BOM (không import chéo M1 ↔ M8).
tracecore_set_type_cap = ["tracecore.par.config.set_type_cap"]
# M2 (FEAT-021) gọi khi lô rửa đóng: (ctx {batch, equipment, program, sets, chemicals, result}) -> None.
#  - wash_complete: sau khi kết luận Đạt (FEAT-042 trừ hóa chất theo định mức, FEAT-046 chi phí lô)
#  - wash_failed:   sau khi kết luận Không đạt (FEAT-030 tự tạo NC)
tracecore_after_wash_complete = [
	"tracecore.inventory.consume.on_wash_complete",
	# FEAT-046: chi phí lô rửa
	"tracecore.costing.sheet.on_wash_complete",
]
tracecore_after_wash_failed = ["tracecore.reprocessing.incidents.on_wash_failed"]
# lô giặt hoàn tất (FEAT-034, A-50): M6 trừ hóa chất, M7 tính chi phí/kg; M3 không import hai module này
tracecore_after_laundry_complete = [
	"tracecore.inventory.consume.on_laundry_complete",
	"tracecore.costing.from_laundry.on_laundry_complete",
]
# M2 (FEAT-026, A-17 C5) gọi khi cấp phát T7: (ctx {department, set_type, stock, adding}) -> dict, so tồn khoa + số
# gói cấp với cơ số khoa (Par Level Department Stock); không hàm nào trả dict → coi như khoa chưa cấu hình cơ số
tracecore_issue_par_check = ["tracecore.par.stock.issue_par"]
# M2 T5 nạp mẻ (FEAT-022, UC-09):
#  - load_equipment_checks: (equipment) -> Block | None, điều kiện chọn máy tiệt khuẩn (FEAT-040: test ngày, kiểm định)
#  - after_load_complete:   (ctx) sau khi Hoàn thành nạp (ctx: load, equipment, program, packs, sets)
# M5 (FEAT-040): test hằng ngày và kiểm định chặn tạo mẻ/lô; M2 không import M5
tracecore_load_equipment_checks = ["tracecore.equipment.daily_test.equipment_block"]
#  - wash_equipment_checks: (equipment) -> Block | None, như load_equipment_checks cho máy rửa (T2)
tracecore_wash_equipment_checks = ["tracecore.equipment.daily_test.equipment_block"]
#  - load_daily_indicator: (equipment, indicator, on) -> dict | None, chỉ thị của mẻ lấy từ test hằng ngày của máy trong
#    ngày chạy mẻ (A-23: Bowie-Dick không nhập lại ở T5b)
tracecore_load_daily_indicator = ["tracecore.equipment.daily_test.load_indicator"]
# M5 (FEAT-039, A-43 M8) gọi khi lưu hồ sơ sự cố thiết bị: (equipment, record) -> [{load_doctype, load}], M2 đánh dấu mẻ/lô
# chưa dỡ trên máy `needs_review` và trả danh sách để ghi vào hồ sơ (FR-M5-04.2); M5 không import M2
tracecore_equipment_incident = ["tracecore.reprocessing.equipment_incident.flag_open_on"]
# M5 (FEAT-039) gọi sau khi ghi sổ hồ sơ bảo trì: (record) -> None; M7 lập Cost Entry Nháp từ chi phí hồ sơ (FEAT-044,
# A-47 C9, FR-M5-04.3); M5 không import M7
tracecore_after_maintenance_submit = ["tracecore.costing.from_maintenance.on_maintenance_submit"]
tracecore_after_load_complete = []
# M2 T5b dỡ mẻ và giải phóng (FEAT-023, UC-10); ctx là dict, mọi hook chạy trong cùng transaction:
#  - after_release:       (ctx {set_unit, set_type, bom_version, cycle_id}) mỗi bộ khi giải phóng Đạt (đã khai báo ở trên)
#  - after_load_release:  (ctx {load, equipment, program, sets, packs}) sau khi mẻ giải phóng (FEAT-042 tiêu hao, FEAT-046 chi phí)
#  - after_load_failed:   (ctx {load, equipment, program, sets, redo_from}) mẻ Không đạt (FEAT-030 NC)
#  - bi_positive:         (ctx {load, equipment, packs[{cycle_id, set_unit, status}]}) BI dương tính (FEAT-029 thu hồi, FEAT-010 thông báo)
tracecore_after_load_release = [
	"tracecore.inventory.consume.on_load_release",
	# FEAT-046 (A-53 h): Cost Sheet mẻ, job sau commit
	"tracecore.costing.sheet.on_load_release",
]
tracecore_after_load_failed = [
	"tracecore.reprocessing.incidents.on_load_failed",
	# FEAT-029: chỉ lập lệnh khi mẻ có gói đã giải phóng trở đi (sau NC để lệnh dùng lại NC của mẻ)
	"tracecore.reprocessing.recall.on_load_failed",
	# FEAT-046 (FR-M7-05.1): mẻ Không đạt vẫn ghi chi phí, tính vào chi phí chất lượng
	"tracecore.costing.sheet.on_load_failed",
]
tracecore_bi_positive = ["tracecore.reprocessing.recall.on_bi_positive"]
# core.importer (FEAT-011, A-41): mỗi hàm trả list `importer.ImportKind` (loại import danh mục từ Excel của module)
tracecore_import_kinds = [
	"tracecore.admin_reports.imports.import_kinds",
	"tracecore.instrument.imports.import_kinds",
	"tracecore.equipment.imports.import_kinds",
	"tracecore.inventory.imports.import_kinds",
	"tracecore.par.imports.import_kinds",
]
# core.sync (FEAT-009, A-40 Q2) gọi khi phát lại offline bị từ chối: (Sync Conflict doc) -> tên Incident NC
tracecore_after_sync_conflict = ["tracecore.reprocessing.incidents.on_sync_conflict"]
# M2 (FEAT-020, A-35) kiểm đếm tại T3:
#  - assembly_context: (ctx {set_unit, set_type, station, receipt_notes}) -> dict gộp vào ngữ cảnh T3 (BOM + ảnh từ M1,
#                      mức dùng cơ số từ M8; khóa receipt_notes do FEAT-019 đóng góp)
#  - assembly_nc:      (ctx {assembly, set_unit, kind, items}) -> None, khi bản nháp lần đầu có dòng thiếu hoặc quét
#                      dụng cụ lạ (FEAT-030 tạo Incident CAPA thật, idempotent theo assembly)
#  - after_assembly:   (ctx {assembly, set_unit, result, branch, branch_reason, station, shortage, damaged}) -> None,
#                      sau khi ghi sổ (dụng cụ hỏng sang Sửa chữa/Thanh lý ở M1/FEAT-032)
tracecore_assembly_context = [
	"tracecore.instrument.bom.pack_context",
	"tracecore.par.check.pack_context",
]
tracecore_assembly_nc = ["tracecore.reprocessing.incidents.on_assembly_nc"]
tracecore_after_assembly = []

# Scheduled Tasks
# ---------------

scheduler_events = {
	"cron": {
		# đường in từ server (A-05 R1): gửi lại Print Job còn Queued của máy in có host
		"* * * * *": [
			"tracecore.core.print_server.dispatch_pending",
		],
		# FEAT-010, FR-M9-10.1, UC-38 E1/E3: gửi lại email/SMS lỗi (tối đa 3 lần), leo thang thông báo khẩn chưa đọc
		"*/5 * * * *": [
			"tracecore.core.notification.retry_failed",
			"tracecore.core.notification.escalate_unread",
		],
		# FEAT-029, UC-14 E3: lệnh thu hồi chưa xác nhận quá 2 giờ → nhắc khoa và R01
		"*/15 * * * *": [
			"tracecore.reprocessing.recall.remind_pending",
			# FEAT-008, FR-M9-04.2: khu theo dõi chưa có lần đo môi trường trước mốc giờ nhắc → nhắc R02
			"tracecore.admin_reports.environment.remind_missing",
		],
		# FEAT-043, FR-M6-06: 06:00 cảnh báo tồn dưới tối thiểu và lô sắp hết hạn (email R09)
		"0 6 * * *": ["tracecore.inventory.alerts.run_daily"],
		# 00:00 giờ hệ thống (Asia/Ho_Chi_Minh): một khóa cron nên mọi việc nửa đêm nằm chung một danh sách
		"0 0 * * *": [
			# FEAT-015 S2: kích hoạt phiên bản BOM đã lên lịch
			"tracecore.instrument.bom_versions.roll_effective_versions",
			# FEAT-025, FR-M2-14: gói trong kho vô khuẩn quá hạn (hết ngày `expiry`) → Hết hiệu lực, bộ Chờ tiếp nhận
			"tracecore.reprocessing.storage.run_expiry",
			# FEAT-032, FR-M8-04.2: ghi đè cơ số quá thời hạn → Hết hiệu lực
			"tracecore.par.override.expire_overdue",
			# FEAT-039, FR-M5-03.1: máy Sẵn sàng quá hạn kiểm định/hiệu chuẩn → Khóa, báo R02 và R10
			"tracecore.equipment.maintenance.lock_overdue",
			# FEAT-036, FR-M4-02.1/.2, FR-M4-01.4: chứng chỉ hết hạn, nhắc 60/30/7 ngày, khám sức khỏe, tiêm chủng
			"tracecore.hr.reminders.run_daily",
			# FEAT-035, FR-M3-06.1: đồ vải chênh lệch tháng > 5 % hoặc tồn khoa dưới tối thiểu → báo R02
			"tracecore.linen.reconcile.run_daily",
		],
	},
	"daily": [
		"tracecore.core.idempotency.purge_expired",
		# FEAT-039, FR-M5-03: nhắc R02 và R10 trước 30 và 7 ngày khi hồ sơ bảo trì/kiểm định/hiệu chuẩn đến hạn
		"tracecore.equipment.maintenance.remind_due",
		# FEAT-030, FR-M2-22.1: nhắc hành động CAPA quá hạn (người phụ trách + R02)
		"tracecore.reprocessing.incidents.remind_overdue",
		# FEAT-017, FR-M1-07.4: bộ mượn quá ngày trả → nhắc R02 mỗi ngày
		"tracecore.instrument.loaner.remind_overdue",
	],
	"monthly": [
		# FEAT-032, FR-M8-04.3: báo R01 báo cáo ghi đè tháng trước
		"tracecore.par.override.notify_monthly_report",
	],
}

on_login = "tracecore.core.account.on_login"
override_whitelisted_methods = {
	"frappe.core.doctype.user.user.update_password": "tracecore.core.account.update_web_password",
	"frappe.core.doctype.user.user.reset_password": "tracecore.core.account.reject_email_reset",
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

before_tests = "tracecore.setup.install.before_tests"

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

# Audit Log (lịch sử) và Code Registry (sổ mã, mã bị vô hiệu chứ không xóa) không phải giao dịch: không chặn R10 xóa
# danh mục chưa dùng (FEAT-004, A-37 d, FR-M9-16)
ignore_links_on_delete = ["Audit Log", "Code Registry"]

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
