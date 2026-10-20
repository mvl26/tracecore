"""Cài đặt app: đặt định dạng Việt Nam cho site (F-13, NFR-L10N-01) và tạo mẫu nhãn gói mẫu (FR-M2-08.4)."""

import frappe

from tracecore.setup.label_templates import ensure_sample_templates

SYSTEM_SETTINGS = {
	"language": "vi",
	"time_zone": "Asia/Ho_Chi_Minh",
	"date_format": "dd/mm/yyyy",
	"time_format": "HH:mm",
	"number_format": "#.###,##",
	"first_day_of_the_week": "Monday",
}


def after_install():
	apply_system_settings()
	ensure_sample_templates()


def apply_system_settings():
	settings = frappe.get_single("System Settings")
	settings.update(SYSTEM_SETTINGS)
	settings.flags.ignore_mandatory = True
	settings.save(ignore_permissions=True)
