import importlib.util
import json
import os
import tempfile

import frappe
from frappe.parallel_test_runner import get_all_tests, split_by_weight
from frappe.tests.utils import FrappeTestCase

APP_ROOT = os.path.abspath(frappe.get_app_path("tracecore", ".."))
TOTAL_SHARDS = 6


def load_ci_shard():
	path = os.path.join(APP_ROOT, "scripts", "ci_shard.py")
	spec = importlib.util.spec_from_file_location("ci_shard", path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


class TestCiShard(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.ci_shard = load_ci_shard()

	def test_log_gives_seconds_per_file_with_fast_tests_counted(self):
		log = [
			"tracecore.v1.tests.test_a.TestOne",
			"   ✔  test_slow (4.5s)",
			"   ✔  test_fast",
			"tracecore.v1.tests.test_a.TestTwo",
			"   ✖  test_broken (2.5s)",
			"noise line",
			"tracecore.core.tests.test_b.TestThree",
			"   ✔  test_fast",
		]
		self.assertEqual(
			self.ci_shard.timings_from_logs([log]),
			{"tracecore/core/tests/test_b.py": 0.2, "tracecore/v1/tests/test_a.py": 7.2},
		)

	def test_newer_log_replaces_the_same_test_only(self):
		older = ["tracecore.a.test_x.T", "   ✔  test_one (10.0s)", "   ✔  test_two (3.0s)"]
		newer = ["tracecore.a.test_x.T", "   ✔  test_one (5.0s)"]
		self.assertEqual(self.ci_shard.timings_from_logs([older, newer]), {"tracecore/a/test_x.py": 8.0})

	def test_file_without_timing_is_weighed_by_its_test_count(self):
		with tempfile.TemporaryDirectory() as folder:
			with open(os.path.join(folder, "test_new.py"), "w") as handle:
				handle.write("def test_a():\n\tpass\n\ndef test_b():\n\tpass\n")
			self.assertEqual(self.ci_shard.file_weight("x/test_new.py", folder + "/test_new.py", {}), 3.0)
			self.assertEqual(
				self.ci_shard.file_weight("x/test_new.py", folder + "/test_new.py", {"x/test_new.py": 9}), 9
			)

	def test_committed_timings_balance_the_real_suite(self):
		tests = get_all_tests("tracecore")
		with open(os.path.join(APP_ROOT, "scripts", "ci_test_timings.json")) as handle:
			timings = json.load(handle)
		weights = self.ci_shard.weights_for(tests, timings, APP_ROOT)
		chunks = split_by_weight(tests, weights, chunk_count=TOTAL_SHARDS)
		self.assertEqual(sum(len(chunk) for chunk in chunks), len(tests))
		by_file = {tuple(test): weight for test, weight in zip(tests, weights, strict=True)}
		totals = [sum(by_file[tuple(test)] for test in chunk) for chunk in chunks]
		self.assertLess(max(totals), sum(totals) / TOTAL_SHARDS * 1.3, totals)
