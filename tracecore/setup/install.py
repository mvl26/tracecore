"""Cài đặt app: định dạng Việt Nam (F-13, NFR-L10N-01), mẫu nhãn gói và nhãn QR đối tượng (FR-M2-08.4, FR-M9-07),
khung khu-trạm (FR-M9-03)."""

import frappe

from tracecore.inventory.permissions import ensure_permissions
from tracecore.setup.label_templates import ensure_object_templates, ensure_sample_templates
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
	ensure_zone_stations()
	ensure_permissions()


def apply_system_settings():
	settings = frappe.get_single("System Settings")
	settings.update(SYSTEM_SETTINGS)
	settings.flags.ignore_mandatory = True
	settings.save(ignore_permissions=True)
	for number in range(1, 11):
		frappe.db.set_value("Role", f"TC R{number:02d}", "two_factor_auth", int(number in (1, 2, 9, 10)))
	frappe.clear_cache()
