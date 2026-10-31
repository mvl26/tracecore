#!/usr/bin/env python3
"""Chạy một phần bộ test trong CI, chia theo thời gian chạy thay vì số test như `bench run-parallel-tests`.

    python ci_shard.py run --site test_site --shard 1 --total 6       # chạy từ thư mục sites của bench
    python ci_shard.py refresh older.log newer.log                    # cập nhật ci_test_timings.json từ log job CI

Giữ nguyên thứ tự file và thuật toán chia của Frappe, chỉ đổi trọng số. File chưa có số liệu (test mới) tính theo số test.
Số liệu cũ chỉ làm lệch thời gian giữa các phần, không làm sót test.
"""

import argparse
import json
import os
import re

TIMINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ci_test_timings.json")
# Frappe chỉ in thời gian của test từ 2 giây trở lên; test nhanh tính theo mức trung bình đo được trên log CI
FAST_TEST_SECONDS = 0.2
UNKNOWN_TEST_SECONDS = 1.5

CLASS_LINE = re.compile(r"^(tracecore(?:\.\w+)+)\.\w+$")
TEST_LINE = re.compile(r"^\s*[✔✖]\s+(\w+)(?: \(([\d.]+)s\))?")


def timings_from_logs(logs):
	"""Giây theo file test, từ các log xếp cũ đến mới; test có ở log sau thì lấy số của log sau."""
	seconds = {}
	for lines in logs:
		current = None
		for line in lines:
			line = line.rstrip()
			found = CLASS_LINE.match(line)
			if found:
				current = found.group(1).replace(".", "/") + ".py"
				continue
			found = TEST_LINE.match(line)
			if found and current:
				seconds[(current, found.group(1))] = float(found.group(2) or FAST_TEST_SECONDS)
	timings = {}
	for (path, _test), value in seconds.items():
		timings[path] = timings.get(path, 0) + value
	return {path: round(value, 1) for path, value in sorted(timings.items())}


def file_weight(relative_path, full_path, timings):
	if relative_path in timings:
		return timings[relative_path]
	with open(full_path, encoding="utf8") as handle:
		return handle.read().count("def test_") * UNKNOWN_TEST_SECONDS


def weights_for(tests, timings, app_root):
	"""`tests` là danh sách [thư mục, tên file] của `get_all_tests`."""
	weights = []
	for path, filename in tests:
		full_path = os.path.join(path, filename)
		relative_path = os.path.relpath(full_path, app_root).replace(os.sep, "/")
		weights.append(file_weight(relative_path, full_path, timings))
	return weights


def refresh(log_paths):
	logs = []
	for path in log_paths:
		with open(path, encoding="utf8", errors="ignore") as handle:
			logs.append(handle.readlines())
	with open(TIMINGS_FILE, "w", encoding="utf8") as handle:
		json.dump(timings_from_logs(logs), handle, indent=2)
		handle.write("\n")


def run(site, shard, total, dry_run):
	# Frappe chỉ có trong env của bench; lệnh refresh và phần tính trọng số không cần
	import frappe
	import frappe.utils.scheduler
	from frappe.coverage import CodeCoverage
	from frappe.parallel_test_runner import ParallelTestRunner, get_all_tests, split_by_weight
	from traceback_with_variables import activate_by_import

	with open(TIMINGS_FILE, encoding="utf8") as handle:
		timings = json.load(handle)

	class TimedTestRunner(ParallelTestRunner):
		def get_test_file_list(self):
			tests = get_all_tests(self.app)
			app_root = os.path.abspath(frappe.get_app_path(self.app, ".."))
			weights = weights_for(tests, timings, app_root)
			return split_by_weight(tests, weights, chunk_count=self.total_builds)[self.build_number - 1]

	with CodeCoverage(not dry_run, "tracecore"):
		TimedTestRunner("tracecore", site=site, build_number=shard, total_builds=total, dry_run=dry_run)


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	commands = parser.add_subparsers(dest="command", required=True)
	run_parser = commands.add_parser("run")
	run_parser.add_argument("--site", required=True)
	run_parser.add_argument("--shard", type=int, required=True)
	run_parser.add_argument("--total", type=int, required=True)
	run_parser.add_argument("--dry-run", action="store_true")
	refresh_parser = commands.add_parser("refresh")
	refresh_parser.add_argument("logs", nargs="+")
	args = parser.parse_args()
	if args.command == "refresh":
		refresh(args.logs)
	else:
		run(args.site, args.shard, args.total, args.dry_run)


if __name__ == "__main__":
	main()
