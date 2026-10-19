"""Service worker /sw.js cho shell trạm (ADR-002).

Tên cache gắn với URL có hash của bundle CSS → mỗi lần build/deploy SW mới thay cache cũ.
"""

import hashlib

from frappe.utils.jinja_globals import bundled_asset

no_cache = 1
base_template_path = "www/sw.js"


def get_context(context):
	context.bundle = bundled_asset("tracecore.bundle.css")
	context.version = hashlib.sha256(context.bundle.encode()).hexdigest()[:12]
