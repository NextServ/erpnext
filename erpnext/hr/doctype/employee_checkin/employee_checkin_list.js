frappe.listview_settings['Employee Checkin'] = {
  onload: function (list_view) {
    list_view.page.add_inner_button(__("Import Lark Attendance"), async function () {
      await Promise.all([
        frappe.model.with_doctype('Salary Structure Assignment Employee Grade', function(){}, true),
        frappe.model.with_doctype('Salary Structure Assignment Department', function(){}, true),
        frappe.model.with_doctype('Salary Structure Assignment Designation', function(){}, true),
        frappe.model.with_doctype('Salary Structure Assignment Employee', function(){}, true),
      ]);

      var d = new frappe.ui.Dialog({
        title: __("Import Lark Attendance"),
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
          frappe.xcall("erpnext.hr.doctype.employee_checkin.employee_checkin.start_import_lark_checkin", (({
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
        primary_action_label: __('Start Import')
      });


      d.show();
    });
  },
};
