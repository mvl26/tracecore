"""Giá trị token ``--tc-*`` cho bản in PDF (wkhtmltopdf không hiểu CSS custom property; design.md, F-11).

Đọc ``:root`` của ``tracecore/public/css/tokens.css`` đã sinh; thêm font dự phòng có chữ Việt trên server Linux (A-07).
Cùng cách làm với phiếu kiểm đếm (`instrument.count_sheet.token_values`); module này dùng cho bản in của M9 (FEAT-007)
để M9 không import M1.
"""

import re

import frappe

TOKENS_PATH = ("public", "css", "tokens.css")
# khóa trong template → biến --tc-* (đen trắng khi in)
TOKEN_VARS = {
	"text": "text",
	"muted": "text-muted",
	"heading": "text-heading",
	"border": "frame",
	"line": "border-input",
	"zebra": "zebra",
	"font_sans": "font-sans",
	"font_mono": "font-mono",
	"fw_bold": "fw-bold",
	"fs_xs": "fs-xs",
	"fs_sm": "fs-sm",
	"fs_md": "fs-md",
	"fs_lg": "fs-lg",
	"fs_2xl": "fs-2xl",
	"lh_snug": "lh-snug",
	"ls_code": "ls-code",
	"sp_1": "sp-1",
	"sp_2": "sp-2",
	"sp_3": "sp-3",
	"sp_4": "sp-4",
	"bw_hair": "bw-hair",
	"bw_thick": "bw-thick",
}
PRINT_FONT_FALLBACK = {
	"font_sans": ('"Liberation Sans"', '"DejaVu Sans"'),
	"font_mono": ('"Liberation Mono"', '"DejaVu Sans Mono"'),
}
_ROOT_VAR = re.compile(r"--tc-([a-z0-9-]+)\s*:\s*([^;}]+);")
_SAFE_VALUE = re.compile(r'[#A-Za-z0-9 ,."().%-]+')
_cache: dict = {}


class TokenError(RuntimeError):
	"""tokens.css thiếu biến hoặc có giá trị lạ: lỗi build (F-11)."""


def _with_fallback(stack, extra):
	families = [family.strip() for family in stack.split(",") if family.strip()]
	generic = families.pop() if families and families[-1] in ("sans-serif", "monospace", "serif") else None
	families += [family for family in extra if family not in families]
	return ",".join(families + ([generic] if generic else []))


def token_values():
	"""``{khóa của TOKEN_VARS: giá trị}``; cache trong tiến trình."""
	if "tokens" not in _cache:
		with open(frappe.get_app_path("tracecore", *TOKENS_PATH), encoding="utf-8") as handle:
			css = handle.read()
		root = css[css.find(":root") :] if ":root" in css else ""
		found = {name: value.strip() for name, value in _ROOT_VAR.findall(root)}
		values = {}
		for key, var in TOKEN_VARS.items():
			value = found.get(var)
			if not value or not _SAFE_VALUE.fullmatch(value):
				raise TokenError(f"tokens.css has no usable --tc-{var}; run scripts/build_tokens.py (F-11).")
			values[key] = (
				_with_fallback(value, PRINT_FONT_FALLBACK[key]) if key in PRINT_FONT_FALLBACK else value
			)
		_cache["tokens"] = values
	return dict(_cache["tokens"])
