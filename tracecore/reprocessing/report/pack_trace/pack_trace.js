// Pack Trace (SCR-14, FR-M2-19): tra cứu chuỗi T1→T8 theo một hoặc nhiều tiêu chí; mã bệnh nhân tra bằng hash.
frappe.query_reports["Pack Trace"] = {
	filters: [
		{ fieldname: "patient_code", label: __("Patient Code"), fieldtype: "Data" },
		{ fieldname: "set_id", label: __("Set ID"), fieldtype: "Link", options: "Set Unit" },
		{ fieldname: "cycle_id", label: __("Cycle ID"), fieldtype: "Link", options: "Pack" },
		{
			fieldname: "load",
			label: __("Sterilization Load"),
			fieldtype: "Link",
			options: "Sterilization Load",
		},
		{
			fieldname: "equipment",
			label: __("Equipment"),
			fieldtype: "Link",
			options: "Equipment",
		},
		{ fieldname: "user", label: __("User"), fieldtype: "Link", options: "User" },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
	],
};
