#!/usr/bin/env python3
"""Đối chiếu marker ``@bru("BRU-…")`` trong test với danh sách BRU của docs/srs.md (ADR-012, F-5).

- Marker trỏ BRU không có trong SRS → exit 1 (luôn kiểm, chạy trong pre-commit/CI).
- ``--strict``: thêm exit 1 khi còn BRU chưa có test (cổng trước release, NFR-MAINT-02).
"""

import argparse
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SRS = os.path.join(REPO, "docs", "srs.md")
DEFAULT_PATHS = [os.path.join(REPO, "tracecore"), os.path.join(REPO, "tracecore_agent")]

BRU_ID = re.compile(r"BRU-[A-Z]+-\d{3}")
# Dải viết gọn trong SRS: "BRU-ID-001…006", "BRU-WST-001..004"
BRU_RANGE = re.compile(r"BRU-([A-Z]+)-(\d{3})\s*(?:\u2026|\.{2,3}|\u2013)\s*(\d{3})")
MARKER = re.compile(r"@bru\(([^)]*)\)")


def known_brus(srs_text):
	known = set(BRU_ID.findall(srs_text))
	for group, start, end in BRU_RANGE.findall(srs_text):
		known.update(f"BRU-{group}-{n:03d}" for n in range(int(start), int(end) + 1))
	return known


def markers(paths):
	"""{BRU: [file:line, ...]} từ các file test_*.py."""
	found = {}
	for base in paths:
		for root, dirs, files in os.walk(base):
			dirs[:] = [d for d in dirs if d not in ("node_modules", "__pycache__")]
			for name in files:
				if not (name.startswith("test_") and name.endswith(".py")):
					continue
				path = os.path.join(root, name)
				with open(path, encoding="utf-8") as handle:
					for lineno, line in enumerate(handle, 1):
						# chỉ tính decorator thật (đầu dòng), không tính chuỗi "@bru(" trong code
						if not line.lstrip().startswith("@bru("):
							continue
						for args in MARKER.findall(line):
							for bru in re.findall(r"[\"']([^\"']+)[\"']", args):
								found.setdefault(bru, []).append(f"{os.path.relpath(path, REPO)}:{lineno}")
	return found


def main(argv=None):
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument("--srs", default=DEFAULT_SRS)
	parser.add_argument("--strict", action="store_true", help="fail while any BRU has no test")
	parser.add_argument("paths", nargs="*", default=DEFAULT_PATHS)
	args = parser.parse_args(argv)

	with open(args.srs, encoding="utf-8") as handle:
		known = known_brus(handle.read())
	found = markers(args.paths)

	status = 0
	for bru in sorted(set(found) - known):
		print(f"Unknown BRU marker {bru}: {', '.join(found[bru])}", file=sys.stderr)
		status = 1
	covered = sorted(set(found) & known)
	print(f"BRU covered {len(covered)}/{len(known)}: {', '.join(covered) or '-'}")
	if args.strict and len(covered) < len(known):
		print(f"Missing tests for: {', '.join(sorted(known - set(found)))}", file=sys.stderr)
		status = 1
	return status


if __name__ == "__main__":
	sys.exit(main())
