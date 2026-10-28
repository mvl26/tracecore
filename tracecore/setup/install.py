"""Cài đặt app: định dạng Việt Nam (F-13, NFR-L10N-01), mẫu nhãn gói, nhãn QR đối tượng, thẻ kim loại và nhãn khay
(FR-M2-08.4, FR-M9-07, FR-M1-05), khung khu-trạm (FR-M9-03)."""

import frappe

from tracecore.core.notification import ensure_default_rules
from tracecore.hr.permissions import ensure_permissions as ensure_hr_permissions
from tracecore.inventory.permissions import ensure_permissions
from tracecore.setup.label_templates import (
	ensure_object_templates,
	ensure_sample_templates,
	ensure_set_templates,
)
from tracecore.setup.seed import ensure_zone_stations

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


def apply_system_settings():
	settings = frappe.get_single("System Settings")
	settings.update(SYSTEM_SETTINGS)
	settings.flags.ignore_mandatory = True
	settings.save(ignore_permissions=True)
	for number in range(1, 11):
		frappe.db.set_value("Role", f"TC R{number:02d}", "two_factor_auth", int(number in (1, 2, 9, 10)))
	frappe.clear_cache()
