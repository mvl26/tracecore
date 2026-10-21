"""Cài đặt app: định dạng Việt Nam (F-13, NFR-L10N-01), mẫu nhãn gói mẫu (FR-M2-08.4), khung khu-trạm (FR-M9-03)."""

import frappe

from tracecore.setup.label_templates import ensure_sample_templates
from tracecore.setup.seed import ensure_zone_stations

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
	ensure_zone_stations()


def apply_system_settings():
	settings = frappe.get_single("System Settings")
	settings.update(SYSTEM_SETTINGS)
	settings.flags.ignore_mandatory = True
	settings.save(ignore_permissions=True)
