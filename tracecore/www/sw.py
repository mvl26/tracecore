"""Service worker /sw.js cho shell trạm (ADR-002); phiên bản app làm tên cache."""

import tracecore

no_cache = 1
base_template_path = "www/sw.js"


def get_context(context):
	context.version = tracecore.__version__
