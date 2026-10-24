import os
import traceback

import frappe

from tracecore.v1.home import context

frappe.set_user(os.environ["TC_E2E_USER"])
try:
    result = context()
    print("Home API OK", result["capabilities"])
except Exception:
    traceback.print_exc()
