import importlib.util
import os
import shutil
import tempfile
import textwrap

import frappe
from frappe.tests.utils import FrappeTestCase

APP_ROOT = os.path.abspath(frappe.get_app_path("tracecore", ".."))


def load_script(name):
	spec = importlib.util.spec_from_file_location(name, os.path.join(APP_ROOT, "scripts", f"{name}.py"))
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


class TempRepo:
	def __init__(self):
		self.root = tempfile.mkdtemp()

	def write(self, path, content):
		full = os.path.join(self.root, path)
		os.makedirs(os.path.dirname(full), exist_ok=True)
		with open(full, "w", encoding="utf-8") as handle:
			handle.write(textwrap.dedent(content))
		return full

	def cleanup(self):
		shutil.rmtree(self.root)


class TestCheckBruCoverage(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.bru = load_script("check_bru_coverage")
		with open(os.path.join(APP_ROOT, "docs", "srs.md"), encoding="utf-8") as handle:
			cls.srs = handle.read()

	def test_known_brus_count_49(self):
		known = self.bru.known_brus(self.srs)
		self.assertEqual(len(known), 49, msg=sorted(known))
		self.assertTrue({"BRU-ID-001", "BRU-ID-006", "BRU-REP-016", "BRU-WST-004"} <= known)

	def test_unknown_marker_fails(self):
		repo = TempRepo()
		try:
			repo.write("tracecore/tests/test_x.py", '@bru("BRU-XYZ-999")\ndef test_a():\n\tpass\n')
			srs = repo.write("docs/srs.md", "BRU-ID-001…006")
			self.assertEqual(self.bru.main(["--srs", srs, os.path.join(repo.root, "tracecore")]), 1)
		finally:
			repo.cleanup()

	def test_repo_markers_valid(self):
		self.assertEqual(self.bru.main([]), 0)

	def test_strict_mode_requires_full_coverage(self):
		self.assertEqual(self.bru.main(["--strict"]), 1)


class TestCheckArchitecture(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.arch = load_script("check_architecture")

	def setUp(self):
		self.repo = TempRepo()

	def tearDown(self):
		self.repo.cleanup()

	def rules(self):
		return [v.rule for v in self.arch.check(self.repo.root)]

	def test_cross_module_import_detected(self):
		self.repo.write("tracecore/instrument/x.py", "from tracecore.reprocessing import y\n")
		self.repo.write("tracecore/waste/z.py", "import tracecore.linen.api\n")
		self.assertEqual(self.rules(), ["R1", "R1"])

	def test_core_import_allowed(self):
		self.repo.write(
			"tracecore/instrument/x.py",
			"from tracecore.core import gs1\nfrom tracecore.instrument import y\n",
		)
		self.assertEqual(self.rules(), [])

	def test_set_unit_status_write_detected(self):
		self.repo.write(
			"tracecore/reprocessing/x.py",
			'import frappe\nfrappe.db.set_value("Set Unit", name, "status", "Sterile")\n',
		)
		self.repo.write(
			"tracecore/instrument/doctype/set_unit/set_unit.py",
			'def f(doc):\n\tdoc.db_set("status", "Reprocess")\n',
		)
		self.repo.write(
			"tracecore/core/step_gate.py",
			'import frappe\nfrappe.db.set_value("Set Unit", name, "status", "Sterile")\n'
			"doc.flags.tc_step_gate = True\n",
		)
		self.repo.write("tracecore/waste/y.py", "def g(doc):\n\tdoc.flags.tc_step_gate = True\n")
		self.assertEqual(self.rules(), ["R2", "R2", "R2"])

	def test_vietnamese_literal_detected_but_docstring_allowed(self):
		self.repo.write(
			"tracecore/core/x.py",
			'''\
			"""Mô-đun ví dụ."""
			from frappe import _


			def f():
				"""Hàm ví dụ."""
				label = _("Hello")
				return "Xin chào", label
			''',
		)
		violations = self.arch.check(self.repo.root)
		self.assertEqual([(v.rule, v.line) for v in violations], [("R3", 8)])

	def test_js_vietnamese_outside_translation_detected(self):
		self.repo.write(
			"tracecore/ui/page/p/p.js",
			'// chú thích tiếng Việt\nconst a = __("Scan");\nconst b = "Quét";\n/* khối\n chú thích */\n',
		)
		self.assertEqual([(v.rule, v.line) for v in self.arch.check(self.repo.root)], [("R3", 3)])

	def test_css_literal_detected(self):
		self.repo.write(
			"tracecore/ui/page/p/p.css",
			".a { color: #fff; }\n.b { padding: 4px; }\n.c { margin: var(--tc-sp-1); }\n#tc-id { margin: 0; }\n",
		)
		self.assertEqual([(v.rule, v.line) for v in self.arch.check(self.repo.root)], [("R4", 1), ("R4", 2)])

	def test_repo_is_clean(self):
		violations = self.arch.check(APP_ROOT)
		self.assertEqual(violations, [], msg="\n".join(str(v) for v in violations))
