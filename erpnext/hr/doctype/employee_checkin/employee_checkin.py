# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, flt
from datetime import datetime
import json
import requests

from erpnext.hr.doctype.shift_assignment.shift_assignment import (
	get_actual_start_end_datetime_of_shift,
)
from erpnext.hr.utils import validate_active_employee


class EmployeeCheckin(Document):
	def validate(self):
		validate_active_employee(self.employee)
		self.validate_duplicate_log()
		self.fetch_shift()

	def validate_duplicate_log(self):
		doc = frappe.db.exists('Employee Checkin', {
			'employee': self.employee,
			'time': self.time,
			'name': ['!=', self.name]})
		if doc:
			doc_link = frappe.get_desk_link('Employee Checkin', doc)
			frappe.throw(_('This employee already has a log with the same timestamp.{0}')
				.format("<Br>" + doc_link))

	def fetch_shift(self):
		shift_actual_timings = get_actual_start_end_datetime_of_shift(self.employee, get_datetime(self.time), True)
		if shift_actual_timings[0] and shift_actual_timings[1]:
			if shift_actual_timings[2].shift_type.determine_check_in_and_check_out == 'Strictly based on Log Type in Employee Checkin' and not self.log_type and not self.skip_auto_attendance:
				frappe.throw(_('Log Type is required for check-ins falling in the shift: {0}.').format(shift_actual_timings[2].shift_type.name))
			if not self.attendance:
				self.shift = shift_actual_timings[2].shift_type.name
				self.shift_actual_start = shift_actual_timings[0]
				self.shift_actual_end = shift_actual_timings[1]
				self.shift_start = shift_actual_timings[2].start_datetime
				self.shift_end = shift_actual_timings[2].end_datetime
		else:
			self.shift = None

@frappe.whitelist()
def add_log_based_on_employee_field(employee_field_value, timestamp, device_id=None, log_type=None, skip_auto_attendance=0, employee_fieldname='attendance_device_id'):
	"""Finds the relevant Employee using the employee field value and creates a Employee Checkin.

	:param employee_field_value: The value to look for in employee field.
	:param timestamp: The timestamp of the Log. Currently expected in the following format as string: '2019-05-08 10:48:08.000000'
	:param device_id: (optional)Location / Device ID. A short string is expected.
	:param log_type: (optional)Direction of the Punch if available (IN/OUT).
	:param skip_auto_attendance: (optional)Skip auto attendance field will be set for this log(0/1).
	:param employee_fieldname: (Default: attendance_device_id)Name of the field in Employee DocType based on which employee lookup will happen.
	"""

	if not employee_field_value or not timestamp:
		frappe.throw(_("'employee_field_value' and 'timestamp' are required."))

	employee = frappe.db.get_values("Employee", {employee_fieldname: employee_field_value}, ["name", "employee_name", employee_fieldname], as_dict=True)
	if employee:
		employee = employee[0]
	else:
		frappe.throw(_("No Employee found for the given employee field value. '{}': {}").format(employee_fieldname,employee_field_value))

	doc = frappe.new_doc("Employee Checkin")
	doc.employee = employee.name
	doc.employee_name = employee.employee_name
	doc.time = timestamp
	doc.device_id = device_id
	doc.log_type = log_type
	if cint(skip_auto_attendance) == 1: doc.skip_auto_attendance = '1'
	doc.insert()

	return doc


def mark_attendance_and_link_log(logs, attendance_status, attendance_date, working_hours=None, late_entry=False, early_exit=False, in_time=None, out_time=None, shift=None):
	"""Creates an attendance and links the attendance to the Employee Checkin.
	Note: If attendance is already present for the given date, the logs are marked as skipped and no exception is thrown.

	:param logs: The List of 'Employee Checkin'.
	:param attendance_status: Attendance status to be marked. One of: (Present, Absent, Half Day, Skip). Note: 'On Leave' is not supported by this function.
	:param attendance_date: Date of the attendance to be created.
	:param working_hours: (optional)Number of working hours for the given date.
	"""
	log_names = [x.name for x in logs]
	employee = logs[0].employee
	if attendance_status == 'Skip':
		frappe.db.sql("""update `tabEmployee Checkin`
			set skip_auto_attendance = %s
			where name in %s""", ('1', log_names))
		return None
	elif attendance_status in ('Present', 'Absent', 'Half Day'):
		employee_doc = frappe.get_doc('Employee', employee)
		if not frappe.db.exists('Attendance', {'employee':employee, 'attendance_date':attendance_date, 'docstatus':('!=', '2')}):
			doc_dict = {
				'doctype': 'Attendance',
				'employee': employee,
				'attendance_date': attendance_date,
				'status': attendance_status,
				'working_hours': working_hours,
				'company': employee_doc.company,
				'shift': shift,
				'late_entry': late_entry,
				'early_exit': early_exit,
				'in_time': in_time,
				'out_time': out_time
			}
			attendance = frappe.get_doc(doc_dict).insert()
			attendance.submit()
			frappe.db.sql("""update `tabEmployee Checkin`
				set attendance = %s
				where name in %s""", (attendance.name, log_names))
			return attendance
		else:
			frappe.db.sql("""update `tabEmployee Checkin`
				set skip_auto_attendance = %s
				where name in %s""", ('1', log_names))
			return None
	else:
		frappe.throw(_('{} is an invalid Attendance Status.').format(attendance_status))


def calculate_working_hours(logs, check_in_out_type, working_hours_calc_type):
	"""Given a set of logs in chronological order calculates the total working hours based on the parameters.
	Zero is returned for all invalid cases.

	:param logs: The List of 'Employee Checkin'.
	:param check_in_out_type: One of: 'Alternating entries as IN and OUT during the same shift', 'Strictly based on Log Type in Employee Checkin'
	:param working_hours_calc_type: One of: 'First Check-in and Last Check-out', 'Every Valid Check-in and Check-out'
	"""
	total_hours = 0
	in_time = out_time = None
	if check_in_out_type == 'Alternating entries as IN and OUT during the same shift':
		in_time = logs[0].time
		if len(logs) >= 2:
			out_time = logs[-1].time
		if working_hours_calc_type == 'First Check-in and Last Check-out':
			# assumption in this case: First log always taken as IN, Last log always taken as OUT
			total_hours = time_diff_in_hours(in_time, logs[-1].time)
		elif working_hours_calc_type == 'Every Valid Check-in and Check-out':
			logs = logs[:]
			while len(logs) >= 2:
				total_hours += time_diff_in_hours(logs[0].time, logs[1].time)
				del logs[:2]

	elif check_in_out_type == 'Strictly based on Log Type in Employee Checkin':
		if working_hours_calc_type == 'First Check-in and Last Check-out':
			first_in_log_index = find_index_in_dict(logs, 'log_type', 'IN')
			first_in_log = logs[first_in_log_index] if first_in_log_index or first_in_log_index == 0 else None
			last_out_log_index = find_index_in_dict(reversed(logs), 'log_type', 'OUT')
			last_out_log = logs[len(logs)-1-last_out_log_index] if last_out_log_index or last_out_log_index == 0 else None
			if first_in_log and last_out_log:
				in_time, out_time = first_in_log.time, last_out_log.time
				total_hours = time_diff_in_hours(in_time, out_time)
		elif working_hours_calc_type == 'Every Valid Check-in and Check-out':
			in_log = out_log = None
			for log in logs:
				if in_log and out_log:
					if not in_time:
						in_time = in_log.time
					out_time = out_log.time
					total_hours += time_diff_in_hours(in_log.time, out_log.time)
					in_log = out_log = None
				if not in_log:
					in_log = log if log.log_type == 'IN'  else None
				elif not out_log:
					out_log = log if log.log_type == 'OUT'  else None
			if in_log and out_log:
				out_time = out_log.time
				total_hours += time_diff_in_hours(in_log.time, out_log.time)
	return total_hours, in_time, out_time

def time_diff_in_hours(start, end):
	return round((end-start).total_seconds() / 3600, 1)

def find_index_in_dict(dict_list, key, value):
	return next((index for (index, d) in enumerate(dict_list) if d[key] == value), None)

@frappe.whitelist()
def start_import_lark_checkin(date_from, date_to, filters):
	filters_obj = json.loads(filters)
	employees = get_employees(grade=filters_obj.get('grade'), department=filters_obj.get('department'), designation=filters_obj.get('designation'), name=filters_obj.get('employee'))

	if employees:
		#import_lark_checkin(date_from, date_to, employees)
		frappe.enqueue(import_lark_checkin, date_from=date_from, date_to=date_to, employees=employees, timeout=600)
		frappe.msgprint('Import started.')
	else:
		frappe.msgprint('No employees found.')

def convert_lark_punch_time_rules(rules):
	return {
		'start_time': rules.get('on_time'),
		'end_time': rules.get('off_time'),
		'grace_period': rules.get('late_minutes_as_late'),
		'absent_grace_period': rules.get('late_minutes_as_lack'),
		'maximum_early_clockin': rules.get('on_advance_minutes'),
		'early_out_grace_period': rules.get('early_minutes_as_early'),
		'early_out_absent_grace_period': rules.get('early_minutes_as_lack'),
		'maximum_late_clockout': rules.get('off_delay_minutes'),
	}

def import_lark_checkin(date_from, date_to, employees=[]):
	frappe.publish_progress(percent=0, title=_("Importing checkins from Lark..."))

	for i, employee_name in enumerate(employees):
		frappe.publish_progress(percent=i / len(employees) * 100, title=_("Importing checkins from Lark..."))
		employee = frappe.get_doc('Employee', employee_name)

		# Get lark user info
		lark_user_info = frappe.db.get_value('User Social Login', { 'parent': employee.get('user_id'), 'provider': 'lark' }, ['userid', 'tenantid'])
		synced_shift_tenants = []

		if lark_user_info:
			lark_settings = frappe.get_doc('Lark Settings')

			try:
				if lark_user_info[1]:
					lark_settings.for_tenant(lark_user_info[1])

				tenant_access_token = lark_settings.get_tenant_access_token()

				# Get lark user data
				r = requests.get('https://open.larksuite.com/open-apis/contact/v3/users/' + lark_user_info[0], headers={
					'Authorization': 'Bearer ' + tenant_access_token,
				}).json()
				lark_settings.handle_response_error(r)

				lark_user_id = r.get('data').get('user').get('user_id')

				try:
					r = requests.post('https://open.larksuite.com/open-apis/attendance/v1/user_tasks/query?employee_type=employee_id', headers={
						'Authorization': 'Bearer ' + tenant_access_token,
					}, json={
						'user_ids': [lark_user_id],
						'check_date_from': frappe.utils.getdate(date_from).strftime('%Y%m%d'),
						'check_date_to': frappe.utils.getdate(date_to).strftime('%Y%m%d')
					}).json()
					lark_settings.handle_response_error(r)

					for day in r.get('data').get('user_task_results'):
						# Delete all attendance for this result day
						frappe.db.delete('Employee Checkin', {
							'lark_result_id': day.get('result_id'),
						})

						# Create records for the days
						for record in day.get('records'):
							if record.get('check_in_record_id'):
								checkin_record = frappe.new_doc('Employee Checkin')
								checkin_record.employee = employee_name
								checkin_record.log_type = 'IN'
								checkin_record.lark_result_id = day.get('result_id')
								checkin_record.time = frappe.utils.convert_utc_to_user_timezone(
									datetime.utcfromtimestamp(int(record.get('check_in_record').get('check_time')))
								).strftime('%Y-%m-%d %H:%M:%S')
								checkin_record.save()

							if record.get('check_out_record_id'):
								checkin_record = frappe.new_doc('Employee Checkin')
								checkin_record.employee = employee_name
								checkin_record.log_type = 'OUT'
								checkin_record.lark_result_id = day.get('result_id')
								checkin_record.time = frappe.utils.convert_utc_to_user_timezone(
									datetime.utcfromtimestamp(int(record.get('check_out_record').get('check_time')))
								).strftime('%Y-%m-%d %H:%M:%S')
								checkin_record.save()

					r = requests.post('https://open.larksuite.com/open-apis/attendance/v1/user_stats_datas/query?employee_type=employee_id', headers={
						'Authorization': 'Bearer ' + tenant_access_token,
					}, json={
						'user_ids': [lark_user_id],
						'start_date': frappe.utils.getdate(date_from).strftime('%Y%m%d'),
						'end_date': frappe.utils.getdate(date_to).strftime('%Y%m%d'),
						'stats_type': 'daily',
						'locale': 'en'
					}).json()
					lark_settings.handle_response_error(r)

					for day in r.get('data').get('user_datas'):
						date = None
						leave_type = None
						leave_time = None
						expected_time = None
						sync_id = None
						approved_ot = None

						for data in day.get('datas'):
							if data.get('code') == '51201':
								date = data.get('value')

							if data.get('code') == '51402':
								leave_type = data.get('value')

							if data.get('code') == '51503-1-1':
								for feature in data.get('features'):
									if feature.get('key') == 'TaskId':
										sync_id = feature.get('value')

							if data.get('code') == '51401':
								leave_time = data.get('value')
							if data.get('code') == '51302':
								expected_time = flt(data.get('value').split(' ')[0])
							if data.get('code') == '51307' and data.get('value') != '-':
								approved_ot = flt(data.get('value').split(' ')[0])

						frappe.db.delete('Lark Leave Record', {
							'name': sync_id,
						})
						frappe.db.delete('Lark Approved OT', {
							'name': sync_id,
						})

						if date and leave_type and leave_time:
							leave_time_data = leave_time.split(' ')

							if leave_time_data[1] == 'days':
								leave_time = flt(leave_time_data[0]) * expected_time
							else:
								leave_time = flt(leave_time_data[0])

							leave_record = frappe.new_doc('Lark Leave Record')
							leave_record.name = sync_id
							leave_record.employee = employee_name
							leave_record.type = leave_type
							leave_record.date = date[0:4] + '-' + date[4:6] + '-' + date[6:8]
							leave_record.hours = leave_time
							leave_record.save()

						if date and approved_ot:
							approved_ot_record = frappe.new_doc('Lark Approved OT')
							approved_ot_record.name = sync_id
							approved_ot_record.date = date[0:4] + '-' + date[4:6] + '-' + date[6:8]
							approved_ot_record.hours = approved_ot
							approved_ot_record.save()
				except Exception as e:
					frappe.logger('import').error('Failed to import attendance for ' + employee_name, exc_info=e)

				# Import shifts
				r = requests.post('https://open.larksuite.com/open-apis/attendance/v1/user_daily_shifts/query?employee_type=employee_id', headers={
					'Authorization': 'Bearer ' + tenant_access_token,
				}, json={
					'user_ids': [lark_user_id],
					'check_date_from': frappe.utils.getdate(date_from).strftime('%Y%m%d'),
					'check_date_to': frappe.utils.getdate(date_to).strftime('%Y%m%d')
				}).json()
				lark_settings.handle_response_error(r)

				for date in r.get('data').get('user_daily_shifts'):
					try:
						assignment_date = datetime(int(str(date.get('month'))[0:4]), int(str(date.get('month'))[5:7]), int(date.get('day_no')))

						# Sync in the Shift Type first
						if not len(synced_shift_tenants) or not lark_user_info[1] in synced_shift_tenants:
							shifts = []
							page_token = None

							# Retrieve all shifts for the tenant
							while page_token or page_token == None:
								sr = requests.get('https://open.larksuite.com/open-apis/attendance/v1/shifts/' + (('?page_token=' + page_token) if page_token else ''), headers={
									'Authorization': 'Bearer ' + tenant_access_token,
								}).json()
								lark_settings.handle_response_error(sr)

								for shift in sr.get('data').get('shift_list'):
									shifts.append(shift)

								page_token = sr.get('data').get('page_token')

							for lark_shift in shifts:
								shift_type = None

								if frappe.db.exists('Shift Type', { 'lark_id': ((lark_user_info[1] + '-') if lark_user_info[1] else '') + lark_shift.get('shift_id') }):
									shift_type = frappe.get_doc('Shift Type', frappe.db.get_value('Shift Type', { 'lark_id': lark_shift.get('shift_id') }, 'name'))
								else:
									shift_type = frappe.new_doc('Shift Type')
									shift_type.name = 'Lark-Shift - ' + ((lark_user_info[1] + ' - ') if lark_user_info[1] else '') + lark_shift.get('shift_name')
									shift_type.enable_attendance_calculation = True
									shift_type.lark_id = ((lark_user_info[1] + '-') if lark_user_info[1] else '') + lark_shift.get('shift_id')

								shift_type.update(convert_lark_punch_time_rules(lark_shift.get('punch_time_rule')[0]))

								if lark_shift.get('is_flexible'):
									shift_type.computation_method = 'Flexible'
								else:
									shift_type.computation_method = 'Fixed'

								shift_type.additional_clock_times = []

								for punch_rule in lark_shift.get('punch_time_rule')[1:]:
									shift_type.append('additional_clock_times', convert_lark_punch_time_rules(punch_rule))

								if lark_shift.get('rest_time_rule'):
									shift_type.break_time_start = lark_shift.get('rest_time_rule')[0].get('rest_begin_time')
									shift_type.break_time_end = lark_shift.get('rest_time_rule')[0].get('rest_end_time')
								else:
									shift_type.break_time_start = None
									shift_type.break_time_end = None

								shift_type.save()

							synced_shift_tenants.append(lark_user_info[1])

						if int(date.get('shift_id')):
							# Find existing shift assignment for this date
							if frappe.db.exists('Shift Assignment', [['employee', '=', employee_name], ['end_date', '>=', assignment_date], ['start_date', '<=', assignment_date], ['synced_from_lark', '=', False], ['docstatus', '=', 1]]):
								frappe.logger('import').error('Failed to create shift assignment for ' + employee_name + ' on ' + str(assignment_date) + ' (collision)')
							else:
								shift_type = frappe.db.get_value('Shift Type', { 'lark_id': ((lark_user_info[1] + '-') if lark_user_info[1] else '') + date.get('shift_id') }, 'name')

								# Check if there is already an assignment for this date
								existing_assignment_name = frappe.db.get_value('Shift Assignment', [['employee', '=', employee_name], ['end_date', '>=', assignment_date], ['start_date', '<=', assignment_date], ['synced_from_lark', '=', True]], 'name')

								# And if that assignment is correct
								if existing_assignment_name and frappe.db.get_value('Shift Assignment', existing_assignment_name, 'shift_type') != shift_type:
									existing_assignment = frappe.get_doc('Shift Assignment', existing_assignment_name)
									existing_assignment.cancel()

								new_assignment = frappe.new_doc('Shift Assignment')
								new_assignment.employee = employee_name
								new_assignment.shift_type = shift_type
								new_assignment.status = 'Active'
								new_assignment.company = frappe.db.get_value('Employee', employee_name, 'company')
								new_assignment.start_date = assignment_date
								new_assignment.end_date = assignment_date
								new_assignment.amended_from = existing_assignment_name
								new_assignment.synced_from_lark = True
								new_assignment.save()
								new_assignment.submit()
					except Exception as e:
						frappe.logger('import').error('Failed to import shift assignments for ' + employee_name + ' on ' + str(date), exc_info=e)
			except Exception as e:
				frappe.logger('import').error('Failed to import ' + employee_name, exc_info=e)

		frappe.publish_progress(percent=(i + 1) / len(employees) * 100, title=_("Importing checkins from Lark..."))

	frappe.msgprint('Import completed.')

def get_employees(**kwargs):
	conditions, values = [], []
	for field, value in kwargs.items():
		if value:
			if isinstance(value, list):
				if len(value):
					conditions.append(("{0} IN (" + ', '.join(map(lambda x: '%s', value)) + ")").format(field))

					for val in value:
						values.append(val['value'])
			else:
				conditions.append("{0}=%s".format(field))
				values.append(value)

	condition_str = " and " + " and ".join(conditions) if conditions else ""

	employees = frappe.db.sql_list("select name from tabEmployee where status='Active' {condition}"
		.format(condition=condition_str), tuple(values))
 
	return employees
