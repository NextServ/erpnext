frappe.query_reports["Length of Service"] = {
	"filters": [
		{
			"fieldname":"as_of_date",
			"label": __("As of Date"),
			"fieldtype": "Date",
			"reqd": 1,
			"default": frappe.datetime.now_date()
		},
		{
			"fieldname":"company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"reqd": 1,
			"default": frappe.defaults.get_user_default("Company")
		},
		{
			"fieldname":"department",
			"label": __("Department"),
			"fieldtype": "Link",
			"options": "Department",
		},
		{
			"fieldname":"employee",
			"label": __("Employee"),
			"fieldtype": "Link",
			"options": "Employee",
		}
	],
}
