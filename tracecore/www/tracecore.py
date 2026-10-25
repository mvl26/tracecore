"""Standalone SPA entry, without Desk or Website navigation."""

import json
from pathlib import Path

import frappe

no_cache = 1


def get_context(context):
	manifest = Path(frappe.get_app_path("tracecore", "public", "admin", ".vite", "manifest.json"))
	context.built = manifest.exists()
	context.scripts = []
	context.styles = []
	if context.built:
		entry = json.loads(manifest.read_text())["index.html"]
		context.scripts = ["/assets/tracecore/admin/" + entry["file"]]
		context.styles = ["/assets/tracecore/admin/" + item for item in entry.get("css", [])]
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.no_cache = 1
