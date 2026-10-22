import frappe

frappe.init(site="tracecore-codex.local", sites_path="/home/tien2003/tracecore-codex/sites")
frappe.connect()
try:
	for user in ("station-t3@tracecore.local", "station-t4@tracecore.local"):
		print(user, frappe.get_roles(user))
	print("2FA roles", frappe.get_all("Role", filters={"two_factor_auth": 1}, pluck="name"))
	print("Explicit admin roles", frappe.get_all("Has Role", filters={"parent": "Administrator"}, pluck="role"))
finally:
	frappe.destroy()
