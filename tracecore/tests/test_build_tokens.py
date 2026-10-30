import importlib.util
import json
import os
import re
import shutil
import tempfile

import frappe
from frappe.tests.utils import FrappeTestCase

APP_ROOT = os.path.abspath(frappe.get_app_path("tracecore", ".."))


def load_build_tokens():
	path = os.path.join(APP_ROOT, "scripts", "build_tokens.py")
	spec = importlib.util.spec_from_file_location("build_tokens", path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def block(css, selector):
	match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
	return match.group(1) if match else ""


def declarations(body):
	return dict(re.findall(r"(--tc-[\w-]+):([^;]+);", body))


class TestBuildTokens(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.bt = load_build_tokens()
		with open(os.path.join(APP_ROOT, "docs", "tokens.json"), encoding="utf-8") as handle:
			cls.tokens = json.load(handle)
		cls.css, cls.theme = cls.bt.build(cls.tokens)

	def test_generated_css_matches_design(self):
		root = declarations(block(self.css, ":root"))
		expected = {
			"--tc-primary": "#1F4E79",
			"--tc-warn-fill": "#B85A00",
			"--tc-warn": "#E36C09",
			"--tc-neutral-fill": "#6B6B6B",
			"--tc-zone-clean": "#E36C09",
			"--tc-touch-min": "48px",
			"--tc-touch-station": "56px",
			"--tc-zonebar-h": "8px",
			"--tc-fs-base": "15px",
			"--tc-r-xl": "8px",
			"--tc-bw-focus": "3px",
			"--tc-dur-fast": "120ms",
			"--tc-font-mono": '"Courier New",Consolas,monospace',
			"--tc-shadow-overlay": "0 8px 32px rgba(0,0,0,0.30)",
			"--tc-ease": "cubic-bezier(0.2,0,0,1)",
		}
		for name, value in expected.items():
			self.assertEqual(root.get(name), value, msg=name)

	def test_station_surface_override(self):
		stn = declarations(block(self.css, '[data-surface="STN"]'))
		for name, value in {
			"--tc-fs-base": "19px",
			"--tc-fs-2xl": "24px",
			"--tc-fs-3xl": "24px",
			"--tc-fs-4xl": "32px",
			"--tc-fs-sm": "16px",
			"--tc-checkbox": "32px",
			"--tc-touch-table": "48px",
		}.items():
			self.assertEqual(stn.get(name), value, msg=name)

	def test_station_fonts_never_below_16px(self):
		effective = declarations(block(self.css, ":root"))
		effective.update(declarations(block(self.css, '[data-surface="STN"]')))
		sizes = {k: int(v[:-2]) for k, v in effective.items() if k.startswith("--tc-fs-")}
		self.assertTrue(sizes)
		self.assertTrue(all(px >= 16 for px in sizes.values()), msg=sizes)

	def test_every_var_reference_defined(self):
		defined = set(re.findall(r"(--tc-[\w-]+):", self.css))
		referenced = set(re.findall(r"var\((--tc-[\w-]+)\)", self.css + self.theme))
		self.assertFalse(referenced - defined)
		self.assertNotIn("{color-raw", self.css)

	def test_accessibility_rules_present(self):
		self.assertIn("prefers-reduced-motion:reduce", self.css)
		self.assertIn(":focus-visible", self.css)

	def test_theme_maps_frappe_variables(self):
		self.assertIn("--primary-color:var(--tc-primary)", self.theme)
		self.assertIn("--btn-primary:var(--tc-primary)", self.theme)
		self.assertIn("--font-stack:var(--tc-font-sans)", self.theme)
		self.assertIn(':root:not([data-theme="dark"])', self.theme)

	def test_committed_css_up_to_date(self):
		css_dir = os.path.join(APP_ROOT, "tracecore", "public", "css")
		for filename, content in self.bt.outputs(self.css, self.theme).items():
			with open(os.path.join(css_dir, filename), encoding="utf-8") as handle:
				self.assertEqual(handle.read(), content, msg=f"{filename}: chạy scripts/build_tokens.py")

	def test_bundle_concatenates_tokens_and_theme(self):
		outputs = self.bt.outputs(self.css, self.theme)
		self.assertEqual(set(outputs), {"tokens.css", "tracecore-theme.css", "tracecore.bundle.css"})
		bundle = outputs["tracecore.bundle.css"]
		self.assertNotIn("@import", bundle)
		self.assertIn(self.css.split("\n", 1)[1], bundle)
		self.assertIn(self.theme.split("\n", 1)[1], bundle)

	def test_check_mode_detects_drift(self):
		out_dir = tempfile.mkdtemp()
		try:
			tokens = os.path.join(APP_ROOT, "docs", "tokens.json")
			self.assertEqual(self.bt.main(["--tokens", tokens, "--out-dir", out_dir, "--check"]), 1)
			self.assertEqual(self.bt.main(["--tokens", tokens, "--out-dir", out_dir]), 0)
			self.assertEqual(self.bt.main(["--tokens", tokens, "--out-dir", out_dir, "--check"]), 0)
		finally:
			shutil.rmtree(out_dir)
