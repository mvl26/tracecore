"""Giao diện không còn mã tài liệu nội bộ: FEAT-…, BRU-…, UC-…, FR-…, SCR-…, A-…, ADR-… (A-88, D7, #1844 T5-09, #1836 T5-04)."""

import csv
import json
import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

CODE = re.compile(
	r"\b(?:FEAT-\d+|BRU-[A-Z]+-\d+|UC-\d+|FR-M\d+|NFR-[A-Z]+-\d+|SCR-\d+|A-\d{2,3}|ADR-\d+|WF-\d+|DT-[A-Z]+|OTH-RET-\d+|EI-UI-\d+)"
)
UI_CALL = re.compile(r"(?<![\w.])_{1,2}\(\s*f?\"((?:[^\"\\]|\\.)*)\"", re.S)


def _files(*suffixes):
	root = frappe.get_app_path("tracecore")
	for folder, dirs, names in os.walk(root):
		dirs[:] = [name for name in dirs if name not in ("__pycache__", "tests", "node_modules", "dist")]
		for name in names:
			if name.endswith(suffixes) and not name.startswith("test_"):
				yield os.path.join(folder, name)


class TestNoInternalCodes(FrappeTestCase):
	def test_translated_strings_in_code(self):
		found = []
		for path in _files(".js", ".py"):
			with open(path, encoding="utf-8") as handle:
				found += [(path, text) for text in UI_CALL.findall(handle.read()) if CODE.search(text)]
		self.assertEqual(found, [])

	def test_translations(self):
		with open(frappe.get_app_path("tracecore", "translations", "vi.csv"), encoding="utf-8") as handle:
			found = [row[:2] for row in csv.reader(handle) if row and CODE.search(" ".join(row[:2]))]
		self.assertEqual(found, [])

	def test_doctype_descriptions(self):
		found = []

		def walk(path, node):
			if isinstance(node, dict):
				for key, value in node.items():
					if key == "description" and isinstance(value, str) and CODE.search(value):
						found.append((path, value))
					walk(path, value)
			elif isinstance(node, list):
				for value in node:
					walk(path, value)

		for path in _files(".json"):
			with open(path, encoding="utf-8") as handle:
				walk(path, json.load(handle))
		self.assertEqual(found, [])

	def test_test_markers_stay(self):
		with open(
			frappe.get_app_path("tracecore", "reprocessing", "tests", "test_releasing.py"), encoding="utf-8"
		) as handle:
			self.assertIn('@bru("BRU-REP-015")', handle.read())
