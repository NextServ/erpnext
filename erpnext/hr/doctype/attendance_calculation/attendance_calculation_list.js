let imports_in_progress = [];

frappe.listview_settings["Attendance Calculation"] = {
	onload(listview) {
		frappe.realtime.on("calculation_progress_update", (data) => {
			if (!imports_in_progress.includes(data.attendance_calculation)) {
				imports_in_progress.push(data.attendance_calculation);
			}
		});
	},
	get_indicator: function (doc) {
		var colors = {
			Pending: "orange",
			"Not Started": "orange",
			"Partial Success": "orange",
			Success: "green",
			"In Progress": "orange",
			Error: "red",
		};
		let status = doc.status;

		if (imports_in_progress.includes(doc.name)) {
			status = "In Progress";
		}
		if (status == "Pending") {
			status = "Not Started";
		}

		return [__(status), colors[status], "status,=," + doc.status];
	},
	formatters: {
		import_type(value) {
			return {
				"Insert New Records": __("Insert"),
				"Update Existing Records": __("Update"),
			}[value];
		},
	},
	hide_name_column: true,
};
