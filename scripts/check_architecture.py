#!/usr/bin/env python3
"""Lint quy tắc kiến trúc TraceCore (CLAUDE.md, F-2, ADR-001/005):

R1  Không import chéo giữa package nghiệp vụ M1-M10 (chỉ qua tracecore.core hoặc Link/hook).
R2  Chỉ tracecore/core/step_gate.py được ghi ``status`` của Set Unit.
R3  Không có chuỗi tiếng Việt trong code .py/.js/.html ngoài ``_()``/``__()`` (bản dịch ở translations/vi.csv).
R4  CSS viết tay của Page không gõ hex/px — chỉ dùng biến ``--tc-*``.
"""

import ast
import os
import re
import sys
from dataclasses import dataclass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUSINESS = (
	"instrument",
	"reprocessing",
	"linen",
	"hr",
	"equipment",
	"inventory",
	"costing",
	"par",
	"admin_reports",
	"waste",
)
SCAN_DIRS = ("tracecore", "tracecore_agent")
SKIP_DIRS = {"node_modules", "__pycache__", "dist", "tests", "translations", "fixtures"}
GENERATED_CSS = {"tokens.css", "tracecore-theme.css"}
STEP_GATE = os.path.join("tracecore", "core", "step_gate.py")

_VI_LOWER = "àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"
VIETNAMESE = re.compile(f"[{_VI_LOWER}{_VI_LOWER.upper()}]")
IMPORT = re.compile(r"^\s*(?:from|import)\s+tracecore\.(\w+)", re.MULTILINE)
SET_UNIT_STATUS = re.compile(
	r"set_value\(\s*[\"']Set Unit[\"'](?:[^()]|\([^()]*\))*?[\"']status[\"']", re.DOTALL
)
DB_SET_STATUS = re.compile(r"db_set\(\s*[\"']status[\"']")
CSS_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|(?<![\w-])\d+(?:\.\d+)?px\b")


@dataclass
class Violation:
	path: str
	line: int
	rule: str
	message: str

	def __str__(self):
		return f"{self.path}:{self.line}: {self.rule} {self.message}"


def _line_of(text, offset):
	return text.count("\n", 0, offset) + 1


def _files(root):
	for top in SCAN_DIRS:
		for current, dirs, files in os.walk(os.path.join(root, top)):
			dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
			for name in files:
				if not name.startswith("test_"):
					yield os.path.join(current, name)


def _module_of(rel):
	parts = rel.split(os.sep)
	return parts[1] if len(parts) > 2 and parts[0] == "tracecore" else None


def _check_imports(rel, text):
	module = _module_of(rel)
	if module not in BUSINESS:
		return []
	return [
		Violation(rel, _line_of(text, m.start()), "R1", f"{module} imports tracecore.{m.group(1)}")
		for m in IMPORT.finditer(text)
		if m.group(1) in BUSINESS and m.group(1) != module
	]


def _check_status_writes(rel, text):
	if rel == STEP_GATE:
		return []
	hits = [m.start() for m in SET_UNIT_STATUS.finditer(text)]
	if rel.startswith(os.path.join("tracecore", "instrument", "doctype", "set_unit")):
		hits += [m.start() for m in DB_SET_STATUS.finditer(text)]
	return [
		Violation(rel, _line_of(text, o), "R2", "only core.step_gate may change Set Unit.status")
		for o in hits
	]


def _docstring_nodes(tree):
	nodes = set()
	for node in ast.walk(tree):
		if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.body:
			first = node.body[0]
			if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
				nodes.add(id(first.value))
	return nodes


def _check_python_strings(rel, text):
	tree = ast.parse(text)
	allowed = _docstring_nodes(tree)
	for node in ast.walk(tree):
		if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("_", "__"):
			allowed.update(id(arg) for arg in node.args)
	return [
		Violation(rel, node.lineno, "R3", "Vietnamese text outside _() — move to translations/vi.csv")
		for node in ast.walk(tree)
		if isinstance(node, ast.Constant)
		and isinstance(node.value, str)
		and id(node) not in allowed
		and VIETNAMESE.search(node.value)
	]


def _strip_comments(text, html):
	def blank(match):
		return re.sub(r"[^\n]", " ", match.group(0))

	text = re.sub(r"/\*.*?\*/", blank, text, flags=re.DOTALL)
	if html:
		text = re.sub(r"<!--.*?-->", blank, text, flags=re.DOTALL)
	return re.sub(r"(^|\s)//[^\n]*", lambda m: m.group(1), text)


def _check_markup_strings(rel, text):
	clean = _strip_comments(text, rel.endswith(".html"))
	return [
		Violation(rel, lineno, "R3", "Vietnamese text outside __() — move to translations/vi.csv")
		for lineno, line in enumerate(clean.splitlines(), 1)
		if VIETNAMESE.search(line) and "__(" not in line
	]


def _check_css(rel, text):
	if os.path.basename(rel) in GENERATED_CSS:
		return []
	clean = _strip_comments(text, html=False)
	violations = []
	for lineno, line in enumerate(clean.splitlines(), 1):
		declaration = line.split(":", 1)[1] if ":" in line and "{" not in line.split(":", 1)[0] else line
		if "{" in line:
			declaration = line[line.index("{") + 1 :]
		if CSS_LITERAL.search(declaration):
			violations.append(Violation(rel, lineno, "R4", "use --tc-* tokens instead of hex/px"))
	return violations


def check(root=REPO):
	violations = []
	for path in _files(root):
		rel = os.path.relpath(path, root)
		ext = os.path.splitext(path)[1]
		if ext not in (".py", ".js", ".html", ".css"):
			continue
		with open(path, encoding="utf-8") as handle:
			text = handle.read()
		if ext == ".py":
			violations += _check_imports(rel, text) + _check_status_writes(rel, text)
			violations += _check_python_strings(rel, text)
		elif ext in (".js", ".html"):
			violations += _check_markup_strings(rel, text)
		elif ext == ".css":
			violations += _check_css(rel, text)
	return sorted(violations, key=lambda v: (v.path, v.line))


def main(argv=None):
	root = (argv or sys.argv[1:] or [REPO])[0]
	violations = check(root)
	for violation in violations:
		print(violation, file=sys.stderr)
	return 1 if violations else 0


if __name__ == "__main__":
	sys.exit(main())
