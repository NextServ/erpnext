frappe.listview_settings['Attendance'] = {
	add_fields: ["status", "attendance_date"],
	get_indicator: function (doc) {
		if (["Present", "Work From Home"].includes(doc.status)) {
			return [__(doc.status), "green", "status,=," + doc.status];
		} else if (["Absent", "On Leave"].includes(doc.status)) {
			return [__(doc.status), "red", "status,=," + doc.status];
		} else if (doc.status == "Half Day") {
			return [__(doc.status), "orange", "status,=," + doc.status];
		}
	},

	onload: function(list_view) {
		let me = this;
		const months = moment.months();
		list_view.page.add_inner_button(__("Mark Attendance"), function() {
			let dialog = new frappe.ui.Dialog({
				title: __("Mark Attendance"),
				fields: [{
					fieldname: 'employee',
					label: __('For Employee'),
					fieldtype: 'Link',
					options: 'Employee',
					get_query: () => {
						return {query: "erpnext.controllers.queries.employee_query"};
					},
					reqd: 1,
					onchange: function() {
						dialog.set_df_property("unmarked_days", "hidden", 1);
						dialog.set_df_property("status", "hidden", 1);
						dialog.set_df_property("exclude_holidays", "hidden", 1);
						dialog.set_df_property("month", "value", '');
						dialog.set_df_property("unmarked_days", "options", []);
						dialog.no_unmarked_days_left = false;
					}
				},
				{
					label: __("For Month"),
					fieldtype: "Select",
					fieldname: "month",
					options: months,
					reqd: 1,
					onchange: function() {
						if (dialog.fields_dict.employee.value && dialog.fields_dict.month.value) {
							dialog.set_df_property("status", "hidden", 0);
							dialog.set_df_property("exclude_holidays", "hidden", 0);
							dialog.set_df_property("unmarked_days", "options", []);
							dialog.no_unmarked_days_left = false;
							me.get_multi_select_options(
								dialog.fields_dict.employee.value,
								dialog.fields_dict.month.value,
								dialog.fields_dict.exclude_holidays.get_value()
							).then(options => {
								if (options.length > 0) {
									dialog.set_df_property("unmarked_days", "hidden", 0);
									dialog.set_df_property("unmarked_days", "options", options);
								} else {
									dialog.no_unmarked_days_left = true;
								}
							});
						}
					}
				},
				{
					label: __("Status"),
					fieldtype: "Select",
					fieldname: "status",
					options: ["Present", "Absent", "Half Day", "Work From Home"],
					hidden: 1,
					reqd: 1,

				},
				{
					label: __("Exclude Holidays"),
					fieldtype: "Check",
					fieldname: "exclude_holidays",
					hidden: 1,
					onchange: function() {
						if (dialog.fields_dict.employee.value && dialog.fields_dict.month.value) {
							dialog.set_df_property("status", "hidden", 0);
							dialog.set_df_property("unmarked_days", "options", []);
							dialog.no_unmarked_days_left = false;
							me.get_multi_select_options(
								dialog.fields_dict.employee.value,
								dialog.fields_dict.month.value,
								dialog.fields_dict.exclude_holidays.get_value()
							).then(options => {
								if (options.length > 0) {
									dialog.set_df_property("unmarked_days", "hidden", 0);
									dialog.set_df_property("unmarked_days", "options", options);
								} else {
									dialog.no_unmarked_days_left = true;
								}
							});
						}
					}
				},
				{
					label: __("Unmarked Attendance for days"),
					fieldname: "unmarked_days",
					fieldtype: "MultiCheck",
					options: [],
					columns: 2,
					hidden: 1
				}],
				primary_action(data) {
					if (cur_dialog.no_unmarked_days_left) {
						frappe.msgprint(__("Attendance for the month of {0} , has already been marked for the Employee {1}",
							[dialog.fields_dict.month.value, dialog.fields_dict.employee.value]));
					} else {
						frappe.confirm(__('Mark attendance as {0} for {1} on selected dates?', [data.status, data.month]), () => {
							frappe.call({
								method: "erpnext.hr.doctype.attendance.attendance.mark_bulk_attendance",
								args: {
									data: data
								},
								callback: function (r) {
									if (r.message === 1) {
										frappe.show_alert({
											message: __("Attendance Marked"),
											indicator: 'blue'
										});
										cur_dialog.hide();
									}
								}
							});
						});
					}
					dialog.hide();
					list_view.refresh();
				},
				primary_action_label: __('Mark Attendance')

			});
			dialog.show();
		});

    list_view.page.add_inner_button(__("Compute Attendance"), async function () {
      await Promise.all([
        frappe.model.with_doctype('Salary Structure Assignment Employee Grade', function(){}, true),
        frappe.model.with_doctype('Salary Structure Assignment Department', function(){}, true),
        frappe.model.with_doctype('Salary Structure Assignment Designation', function(){}, true),
        frappe.model.with_doctype('Salary Structure Assignment Employee', function(){}, true),
      ]);

      var d = new frappe.ui.Dialog({
        title: __("Compute Attendance"),
        fields: [
          { fieldname: 'sec_break_2', fieldtype: 'Section Break', label: __("Date") },
          { fieldname: 'date_from', fieldtype: 'Date', label: __('Date From'), reqd: 1 },
          { fieldname: 'date_to', fieldtype: 'Date', label: __('Date To'), reqd: 1 },
          { fieldname: "sec_break", fieldtype: "Section Break", label: __("Filter Employees By (Optional)") },
          { fieldname: "grade", fieldtype: "Table MultiSelect", options: "Salary Structure Assignment Employee Grade", label: __("Employee Grade") },
          { fieldname: 'department', fieldtype: 'Table MultiSelect', options: 'Salary Structure Assignment Department', label: __('Department') },
          { fieldname: 'designation', fieldtype: 'Table MultiSelect', options: 'Salary Structure Assignment Designation', label: __('Designation') },
          { fieldname: "employee", fieldtype: "Table MultiSelect", options: "Salary Structure Assignment Employee", label: __("Employee") },
        ],
        primary_action: function () {
          var data = d.get_values();
          frappe.xcall("erpnext.hr.doctype.attendance.attendance.start_compute_attendance", (({
            date_from,
            date_to,
            ...filters
          }) => ({
            date_from,
            date_to,
            filters,
          }))(data)).then(function() {
            d.hide();
          });
        },
        primary_action_label: __('Compute Attendance')
      });


      d.show();
    });
	},

	get_multi_select_options: function(employee, month, exclude_holidays) {
		return new Promise(resolve => {
			frappe.call({
				method: 'erpnext.hr.doctype.attendance.attendance.get_unmarked_days',
				async: false,
				args: {
					employee: employee,
					month: month,
					exclude_holidays: exclude_holidays
				}
			}).then(r => {
				var options = [];
				for (var d in r.message) {
					var momentObj = moment(r.message[d], 'YYYY-MM-DD');
					var date = momentObj.format('DD-MM-YYYY');
					options.push({
						"label": date,
						"value": r.message[d],
						"checked": 1
					});
				}
				resolve(options);
			});
		});
	}
};
