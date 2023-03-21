// Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Attendance Calculation', {
	setup(frm) {
		frappe.realtime.on("calculation_progress_update", (data) => {
			if (data.attendance_calculation === frm.doc.name) {
				frappe.model.clear_doc("Attendance Calculation", frm.doc.name);
				frappe.model.with_doc("Attendance Calculation", frm.doc.name).then(() => {
					frm.refresh();
				});
			}
		});
	},
	refresh: function(frm) {
		if (frm.doc.name) {
			frm.add_custom_button(__('View Logs'), function() {
				frappe.route_options = { 'attendance_calculation': frm.doc.name };
				frappe.set_route("List", 'Attendance Calculation Log', "List");
			});
		}
		frm.trigger("update_primary_action");
	},
	onload_post_render(frm) {
		frm.trigger("update_primary_action");
	},

	update_primary_action(frm) {
		if (frm.is_dirty()) {
			frm.enable_save();
			return;
		}
		frm.disable_save();

		if (frm.doc.status !== 'In Progress') {
			let label = frm.doc.status === "Pending" ? __("Start Calculation") : __("Retry");
			frm.page.set_primary_action(label, () => frm.events.do_calculation(frm));
		} else {
			frm.page.set_primary_action(__("Save"), () => frm.save());
		}
	},

	do_calculation(frm) {
		frm.call({
			method: "dispatch_calculation",
			args: { calculation: frm.doc.name },
			btn: frm.page.btn_primary,
		}).then((r) => {
			if (r.message === false) {
				frappe.msgprint("This calculation is already running.");
			}

			frappe.model.clear_doc("Attendance Calculation", frm.doc.name);
			frappe.model.with_doc("Attendance Calculation", frm.doc.name).then(() => {
				frm.refresh();
			});
		});
	},
});
