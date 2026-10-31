import glob
import json
import os

import frappe
from frappe.test_runner import get_dependencies
from frappe.tests.utils import FrappeTestCase

# Bản ghi test của ERPNext cần cây dữ liệu của setup wizard; CI không chạy wizard nên kéo chúng là cả phần test dừng
ERPNEXT_RECORDS = {"Batch", "Brand", "Item", "Supplier", "Supplier Group"}


def _reachable(doctype, seen):
	found = []
	for option in get_dependencies(doctype):
		if option == "[Select]" or option in seen:
			continue
		seen.add(option)
		if option in ERPNEXT_RECORDS:
			found.append(option)
		found.extend(_reachable(option, seen))
	return found


class TestDocTypeTestRecords(FrappeTestCase):
	def test_doctype_tests_do_not_pull_erpnext_test_records(self):
		root = frappe.get_app_path("tracecore")
		offenders = {}
		for path in glob.glob(os.path.join(root, "*", "doctype", "*", "test_*.py")):
			definition = os.path.join(os.path.dirname(path), os.path.basename(path)[5:-3] + ".json")
			if not os.path.exists(definition):
				continue
			with open(definition, encoding="utf-8") as handle:
				doctype = json.load(handle).get("name")
			found = _reachable(doctype, {doctype})
			if found:
				offenders[doctype] = found
		self.assertFalse(offenders, "thêm vào test_ignore của DocType chứa Link")
