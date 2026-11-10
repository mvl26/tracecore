"""Cài đặt app: định dạng Việt Nam (F-13, NFR-L10N-01), mẫu nhãn gói, nhãn QR đối tượng, thẻ kim loại và nhãn khay
(FR-M2-08.4, FR-M9-07, FR-M1-05), khung khu-trạm (FR-M9-03)."""

import frappe

from tracecore.compliance_audit.seed import ensure_seed as ensure_compliance_seed  # FEAT-061
from tracecore.core.notification import ensure_default_rules
from tracecore.costing.setup import ensure_categories
from tracecore.equipment.daily_test import ensure_settings as ensure_daily_test_settings
from tracecore.hr.permissions import ensure_permissions as ensure_hr_permissions
from tracecore.infection_program.structure_seed import ensure_seed as ensure_structure_seed  # FEAT-094
from tracecore.inventory.permissions import ensure_permissions
from tracecore.microbiology.seed import ensure_seed as ensure_microbiology_seed
from tracecore.setup.error_codes import ensure_error_codes
from tracecore.setup.label_templates import (
	ensure_object_templates,
	ensure_sample_templates,
	ensure_set_templates,
)
from tracecore.setup.seed import ensure_zone_stations
from tracecore.ui.permissions import ensure_permissions as ensure_ui_permissions
from tracecore.ui.station_help import ensure_station_help

SYSTEM_SETTINGS = {
	"language": "vi",
	"time_zone": "Asia/Ho_Chi_Minh",
	"date_format": "dd/mm/yyyy",
	"time_format": "HH:mm",
	"number_format": "#.###,##",
	"first_day_of_the_week": "Monday",
	# Frappe v15 uses strict > comparisons: day 90 / failure 5 are first blocked.
	"force_user_to_reset_password": 89,
	"allow_consecutive_login_attempts": 4,
	"allow_login_after_fail": 300,
	"enable_password_policy": 1,
	"minimum_password_score": 2,
	"enable_two_factor_auth": 1,
	"two_factor_method": "OTP App",
	"bypass_2fa_for_retricted_ip_users": 0,
	"logout_on_password_reset": 1,
}


def after_install():
	apply_system_settings()
	ensure_sample_templates()
	ensure_object_templates()
	ensure_set_templates()
	ensure_zone_stations()
	ensure_permissions()
	ensure_default_rules()
	ensure_hr_permissions()
	ensure_categories()
	ensure_ui_permissions()
	ensure_station_help()
	ensure_error_codes()
	ensure_daily_test_settings()
	ensure_microbiology_seed()
	ensure_compliance_seed()  # FEAT-061: 8 mẫu phiếu giám sát Nháp (FR-M12-02)
	ensure_structure_seed()  # FEAT-094: bộ tiêu chí cơ cấu KSNK Nháp (FR-M11-01.8)


TEST_GENDERS = ("Male", "Female", "Other")


def before_tests():
	"""Chuẩn bị site mới (CI: ``install-app`` rồi ``run-tests``) trước khi Frappe dựng test record (hook ``before_tests``).

	`bench run-tests --app tracecore` chỉ gọi hook của chính app (``get_hooks("before_tests", app_name=app)``) nên không
	chạy ``erpnext.setup.utils.before_tests``. Không chạy setup wizard của ERPNext ở đây: nó tạo Company mặc định,
	đổi ngôn ngữ/múi giờ và làm lệch các test kho (`tests.factories.ensure_stock_masters` giả định site chưa có Company).
	Chỉ tạo các bản ghi mà wizard sẽ tạo và test cần: loại kho "Transit" (test record Company của ERPNext tạo kho
	Goods In Transit kiểu Transit) và Gender (Employee của test trạm khai giới tính "Male"). Idempotent.
	"""
	if not frappe.db.exists("Warehouse Type", "Transit"):
		frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(ignore_permissions=True)
	for gender in TEST_GENDERS:
		if not frappe.db.exists("Gender", gender):
			frappe.get_doc({"doctype": "Gender", "gender": gender}).insert(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep


KSNK_ROLE_PROFILES = ("TC R11", "TC R12", "TC R13")


def ensure_role_profiles():
	"""A-113 (FEAT-056): mỗi vai trò KSNK toàn viện có Role Profile cùng tên; chỉ tạo khi chưa có, không ghi đè.

	Role Profile.on_update xếp hàng job cập nhật người dùng; chạy ngay trong tiến trình (như lúc cài app) để không để lại
	khóa bản ghi khi site chưa có worker.
	"""
	previous = frappe.flags.in_install
	frappe.flags.in_install = True
	try:
		for role in KSNK_ROLE_PROFILES:
			if frappe.db.exists("Role Profile", role) or not frappe.db.exists("Role", role):
				continue
			frappe.get_doc(
				{"doctype": "Role Profile", "role_profile": role, "roles": [{"role": role}]}
			).insert(ignore_permissions=True)
	finally:
		frappe.flags.in_install = previous


def apply_system_settings():
	settings = frappe.get_single("System Settings")
	settings.update(SYSTEM_SETTINGS)
	settings.flags.ignore_mandatory = True
	settings.save(ignore_permissions=True)
	# A-113 a: thêm 2FA cho R11 (Giám sát viên KSNK) và R13 (Hội đồng KSNK & BGĐ); R12 như R08
	for number in range(1, 14):
		frappe.db.set_value(
			"Role", f"TC R{number:02d}", "two_factor_auth", int(number in (1, 2, 9, 10, 11, 13))
		)
	frappe.clear_cache()
