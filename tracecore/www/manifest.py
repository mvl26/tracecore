"""Web app manifest /manifest.json cho PDA/kiosk (ADR-002); màu lấy từ tokens.css đã sinh."""

import os
import re

import frappe

no_cache = 1
base_template_path = "www/manifest.json"


def _token(css, name):
	match = re.search(rf"{re.escape(name)}:(#[0-9A-Fa-f]{{6}});", css)
	return match.group(1) if match else ""


def get_context(context):
	with open(
		os.path.join(frappe.get_app_path("tracecore"), "public", "css", "tokens.css"), encoding="utf-8"
	) as handle:
		css = handle.read()
	context.background_color = _token(css, "--tc-bg")
	context.theme_color = _token(css, "--tc-primary")
