import frappe
from frappe.utils import cint

def boot_session(bootinfo):
  bootinfo.attendance_import_enabled = not not cint(frappe.get_value('Attendance Calculation Settings', None, 'lark_import_enabled'))
