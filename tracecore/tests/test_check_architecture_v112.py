"""Lint không-import-chéo phủ 7 package KSNK toàn viện (FEAT-056, A-113 a, implementation-plan FEAT-056)."""

import importlib.util
import os
import tempfile
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

SCRIPT = Path(__file__).parents[2] / "scripts" / "check_architecture.py"
KSNK_PACKAGES = (
	"infection_program",
	"compliance_audit",
	"hai_surveillance",
	"microbiology",
	"environmental_hygiene",
	"occupational_safety",
	"food_safety",
)


def _lint():
	spec = importlib.util.spec_from_file_location("tc_check_architecture", SCRIPT)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def _tree(files):
	root = tempfile.mkdtemp()
	for rel, text in files.items():
		path = os.path.join(root, rel)
		os.makedirs(os.path.dirname(path), exist_ok=True)
		Path(path).write_text(text, encoding="utf-8")
	return root


class TestArchitectureLintV112(FrappeTestCase):
	def test_ksnk_packages_are_business_modules(self):
		lint = _lint()
		for package in KSNK_PACKAGES:
			self.assertIn(package, lint.BUSINESS)
			self.assertTrue((SCRIPT.parents[1] / "tracecore" / package / "__init__.py").exists(), msg=package)

	def test_cross_import_between_ksnk_modules_is_reported(self):
		lint = _lint()
		root = _tree(
			{
				"tracecore/infection_program/plan.py": "from tracecore.hai_surveillance import cases\n",
				"tracecore/microbiology/isolate.py": "import tracecore.waste.store\n",
				"tracecore/food_safety/ok.py": "from tracecore.core import extension\n",
			}
		)
		rules = [(v.path.split(os.sep)[1], v.rule) for v in lint.check(root)]
		self.assertIn(("infection_program", "R1"), rules)
		self.assertIn(("microbiology", "R1"), rules)
		self.assertNotIn(("food_safety", "R1"), rules)
