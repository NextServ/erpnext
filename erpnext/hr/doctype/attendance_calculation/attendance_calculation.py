# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt
from dateutil.parser import parse

from erpnext.hr.utils import get_holidays_for_employee
from datetime import datetime, timedelta
import traceback
import requests
import json

from erpnext.hr.doctype.shift_assignment.shift_assignment import (
	get_employee_shift
)

class AttendanceCalculation(Document):
	def dispatch(self):
		from frappe.core.page.background_jobs.background_jobs import get_info
		from frappe.utils.scheduler import is_scheduler_inactive

		if is_scheduler_inactive() and not frappe.flags.in_test:
			frappe.throw(_("Scheduler is inactive. Cannot perform calculation."), title=_("Scheduler Inactive"))

		enqueued_jobs = [d.get("job_name") for d in get_info()]

		if self.name not in enqueued_jobs:
			frappe.enqueue(
				start_calculation,
				calculation=self.name,
				job_name=self.name,
				now=frappe.conf.developer_mode or frappe.flags.in_test
			)

			return True

		return False

	def update_progress(self, processed_employees=None, total_employees=None, status=None, message=None):
		if processed_employees != None:
			self.processed_employees = processed_employees

		if total_employees != None:
			self.total_employees = total_employees

		if status != None and status != 'In Progress':
			self.status = status

		if message != None:
			self.message = message

		self.save()
		frappe.publish_realtime("calculation_progress_update", { "attendance_calculation": self.name })

	def log(self, employee, success, date=None, error=None, response=None):
		log = frappe.new_doc('Attendance Calculation Log')
		log.attendance_calculation = self.name
		log.date = date
		log.employee = employee
		log.success = success

		if error:
			log.error = str(error)
			log.trace = traceback.format_exc()

			if response:
				log.trace = log.trace + '\n\n' + str(response)

			self.has_failure = True

		if success:
			self.has_success = True

		log.save()

	def start(self):
		try:
			frappe.db.delete('Attendance Calculation Log', { 'attendance_calculation': self.name })

			self.update_progress(status='In Progress')
			employees = get_employees(company=self.get('company'), branch=self.get('branch'), grade=self.get('grade'), department=self.get('department'), designation=self.get('designation'), name=self.get('employee'))
			self.update_progress(processed_employees=0, total_employees=len(employees))
			self.has_failure = False
			self.has_success = False

			if self.import_from_lark:
				self.import_lark_checkin(self.date_from, self.date_to, employees)
			else:
				self.compute_attendance(self.date_from, self.date_to, employees)

			if self.has_success:
				if self.has_failure:
					self.update_progress(status='Partial Success', message='')
				else:
					self.update_progress(status='Success', message='')
			else:
				self.update_progress(status='Error', message='No attendance calculated')
		except Exception as e:
			self.update_progress(status='Error', message=str(e) + '\n' + traceback.format_exc())

	def import_lark_checkin(self, date_from, date_to, employees=[]):
		for i, employee_name in enumerate(employees):
			frappe.publish_progress(percent=i / len(employees) * 100, title=_("Importing checkins from Lark..."))
			employee = frappe.get_doc('Employee', employee_name)

			# Get lark user info
			lark_user_info = frappe.db.get_value('User Social Login', { 'parent': employee.get('user_id'), 'provider': 'lark' }, ['userid', 'tenantid'])

			if lark_user_info:
				lark_settings = frappe.get_doc('Lark Settings')
				r = None

				try:
					if lark_user_info[1]:
						lark_settings.for_tenant(lark_user_info[1])

					tenant_access_token = lark_settings.get_tenant_access_token()

					r = requests.get('https://open.larksuite.com/open-apis/contact/v3/users/' + lark_user_info[0], headers={
						'Authorization': 'Bearer ' + tenant_access_token,
					})
					r = r.json()
					lark_settings.handle_response_error(r)
					lark_user_id = r.get('data').get('user').get('user_id')

					# Retrieve all columns
					r = requests.post('https://open.larksuite.com/open-apis/attendance/v1/user_stats_views/query?employee_type=employee_id', headers={
						'Authorization': 'Bearer ' + tenant_access_token,
					}, json={
						'user_ids': [lark_user_id],
						'user_id': lark_user_id,
						'start_date': frappe.utils.getdate(date_from).strftime('%Y%m%d'),
						'end_date': frappe.utils.getdate(date_to).strftime('%Y%m%d'),
						'stats_type': 'daily',
						'locale': 'en'
					})
					r = r.json()
					lark_settings.handle_response_error(r)

					for field in r.get('data', { }).get('view', { }).get('items', []):
						for child_item in field.get('child_items', []):
							child_item['value'] = '1'

					r = requests.put('https://open.larksuite.com/open-apis/attendance/v1/user_stats_views/query?employee_type=employee_id', headers={
						'Authorization': 'Bearer ' + tenant_access_token,
					}, json={
						'view': r.get('data').get('view')
					})
					r = r.json()
					lark_settings.handle_response_error(r)

					r = requests.post('https://open.larksuite.com/open-apis/attendance/v1/user_stats_datas/query?employee_type=employee_id', headers={
						'Authorization': 'Bearer ' + tenant_access_token,
					}, json={
						'user_ids': [lark_user_id],
						'user_id': lark_user_id,
						'start_date': frappe.utils.getdate(date_from).strftime('%Y%m%d'),
						'end_date': frappe.utils.getdate(date_to).strftime('%Y%m%d'),
						'stats_type': 'daily',
						'locale': 'en'
					})
					r = r.json()
					lark_settings.handle_response_error(r)

					for day in r.get('data').get('user_datas'):
						date = None
						working_hours = None
						expected_hours = None
						overtime = None
						leave = None
						in_result = None
						out_result = None
						time_in = None
						time_out = None
						shift_in = None
						shift_out = None
						leave_type = None

						try:
							for data in day.get('datas'):
								if data.get('code') == '51201':
									date = data.get('value')

									if len(date) == 10:
										date = date[0:4] + date[5:7] + date[8:]

								if data.get('code') == '51303':
									working_hours = flt(data.get('value').split(' ')[0])

								if data.get('code') == '51302':
									expected_hours = flt(data.get('value').split(' ')[0])

								if data.get('code') == '51307' and data.get('value') != '-':
									overtime = flt(data.get('value').split(' ')[0])

								if data.get('code') == '51401' and data.get('value') != '-':
									leave = data.get('value')

								if data.get('code') == '51402' and data.get('value') != '-':
									leave_type = data.get('value')

								if data.get('code') == '51503-1-1' and data.get('value') != '-':
									for feature in data.get('features'):
										if feature.get('key') == 'StatusMsg':
											in_result = feature.get('value')

										if feature.get('key') == 'ShiftTime' and feature.get('value') != '-':
											shift_in = datetime.strptime(feature.get('value'), "%H:%M")

											if shift_in:
												shift_in = timedelta(hours=shift_in.hour, minutes=shift_in.minute)

								if data.get('code') == '51503-1-2' and data.get('value') != '-':
									for feature in data.get('features'):
										if feature.get('key') == 'StatusMsg':
											out_result = feature.get('value')

										if feature.get('key') == 'ShiftTime' and feature.get('value') != '-':
											shift_out = datetime.strptime(feature.get('value'), "%H:%M")

											if shift_out:
												shift_out = timedelta(hours=shift_out.hour, minutes=shift_out.minute)

								if data.get('code') == '51502-1-1' and data.get('value') != '-':
									time_in = datetime.strptime(data.get('value'), "%H:%M")

									if time_in:
										time_in = timedelta(hours=time_in.hour, minutes=time_in.minute)

								if data.get('code') == '51502-1-2' and data.get('value') != '-':
									time_out = datetime.strptime(data.get('value'), "%H:%M")

									if time_out:
										time_out = timedelta(hours=time_out.hour, minutes=time_out.minute)

							if date:
								date = date[0:4] + '-' + date[4:6] + '-' + date[6:8]

							if expected_hours and leave:
								leave_time_data = leave.split(' ')

								if leave_time_data[1] == 'days':
									leave = flt(leave_time_data[0]) * expected_hours
								else:
									leave = flt(leave_time_data[0])

							if time_in and time_out and time_out <= time_in:
								time_out = time_out + timedelta(hours=24)

							if shift_in and shift_out and shift_out <= shift_in:
								shift_out = shift_out + timedelta(hours=24)

							attendance = frappe.new_doc('Attendance')
							attendance.employee = employee_name
							attendance.company = frappe.db.get_value('Employee', employee_name, 'company')
							attendance.attendance_date = date
							attendance.working_hours = working_hours or 0
							attendance.expected_working_hours = expected_hours or 0
							attendance.leave = leave or 0
							attendance.overtime = overtime or 0
							attendance.paid_leave = 0
							attendance.undertime = 0
							attendance.night_differential = 0
							attendance.night_differential_overtime = 0
							attendance.rest_day = False

							attendance.late_entry = in_result == 'Late in'
							attendance.early_exit = out_result == 'Early out'

							if in_result == 'Late in':
								attendance.late_in = (time_in - shift_in).seconds / 3600

							if (in_result == 'Optional' or out_result == 'Optional') and not leave_type:
								attendance.rest_day = True

								if not working_hours and not leave and not overtime:
									attendance.status = 'Rest day'

							if attendance.leave > 0:
								if attendance.working_hours > 0 or attendance.overtime > 0:
									attendance.status = 'Half Day'
								else:
									attendance.status = 'On Leave'
								
								# Find leave type
								if leave_type and leave_type[:2] == 'PL':
									attendance.paid_leave = attendance.leave
									attendance.leave = 0
							else:
								if in_result == 'No record' or out_result == 'No record' or not in_result or not out_result:
									attendance.status = 'Absent'
									attendance.undertime = 0
									attendance.working_hours = 0
								else:
									attendance.status = 'Present'
									attendance.undertime = max((expected_hours or 0) - (working_hours or 0), 0)

							# Assume night differential based on in/out
							if time_in and time_out:
								night_differential_clock_times = [
									[
										datetime.combine(parse(date), datetime.min.time()) + timedelta(hours=21),
										datetime.combine(parse(date), datetime.min.time()) + timedelta(hours=30)
									]
								]

								night_differential_times = overlap_times([[datetime.combine(parse(date), datetime.min.time()) + time_in, datetime.combine(parse(date), datetime.min.time()) + time_out]], night_differential_clock_times)
								attendance.night_differential = compute_time_total(night_differential_times).seconds / 3600

								overtime_in = time_out - timedelta(hours=(overtime or 0))
								night_differential_ot_times = overlap_times([[datetime.combine(parse(date), datetime.min.time()) + overtime_in, datetime.combine(parse(date), datetime.min.time()) + time_out]], night_differential_clock_times)
								attendance.night_differential_ot = compute_time_total(night_differential_ot_times).seconds / 3600

							holidays_for_date = get_holidays_for_employee(employee_name, date, date, False, True)

							for holiday in holidays_for_date:
								if holiday.category in ['Regular Holiday']:
									attendance.legal_holiday = True
								if holiday.category in ['Special Non-working Holiday', 'Special Working Holiday']:
									attendance.special_holiday = True

							attendance.save()

							self.log(employee_name, True, date=date)
						except Exception as e:
							self.log(employee_name, False, error=e, date=date)
				except Exception as e:
					self.log(employee_name, False, error=e, response=r)

			self.update_progress(status='In Progress', processed_employees=i + 1)

	def compute_attendance(self, date_from, date_to, employees=[]):
		for i, employee_name in enumerate(employees):
			try:
				self.update_progress(status='In Progress', processed_employees=i)

				current_date = frappe.utils.get_datetime(date_from)
				last_date = frappe.utils.get_datetime(date_to)

				while current_date <= last_date:
					try:
						employee_shift = get_employee_shift(employee_name, current_date.date())

						if employee_shift:
							shift_type = employee_shift.get('shift_type')

							if shift_type.get('enable_attendance_calculation'):
								clockin_time = datetime.combine(current_date, datetime.min.time()) + shift_type.get('start_time')
								clockout_time = datetime.combine(current_date, datetime.min.time()) + shift_type.get('end_time')
								min_time = clockin_time - timedelta(minutes=shift_type.get('maximum_early_clockin', default=0))
								max_time = clockout_time + timedelta(minutes=shift_type.get('maximum_late_clockout', default=0))
								total_working_hours = clockout_time - clockin_time
								total_break_time = (shift_type.get('break_time_end') - shift_type.get('break_time_start')) if shift_type.get('break_time_start') else timedelta(0)

								# clock_times stores all time that is considered "regular working hours"
								clock_times = [
									[clockin_time, clockout_time]
								]

								for clockin in shift_type.get('additional_clock_times'):
									clockin_in_time = datetime.combine(current_date, datetime.min.time()) + clockin.get('start_time')
									clockin_out_time = datetime.combine(current_date, datetime.min.time()) + clockin.get('end_time')
									total_working_hours += clockin_out_time - clockin_in_time
									clock_min_time = clockin_in_time - timedelta(minutes=clockin.get('maximum_early_clockin', default=0))
									clock_max_time = clockin_out_time + timedelta(minutes=clockin.get('maximum_late_clockout', default=0))
									min_time = min(min_time, clock_min_time)
									max_time = max(max_time, clock_max_time)
									clockin_time = min(clockin_time, clockin_in_time)
									clockout_time = max(clockout_time, clockin_out_time)
									clock_times.append([clockin_in_time, clockin_out_time])

								# overtime_clock_times stores all the time that is considered "overtime hours"
								overtime_clock_times = [
									[datetime.min, clockin_time],
									[clockout_time, datetime.max]
								]

								# For breaks
								break_clock_times = []

								if shift_type.get('break_time_start'):
									break_clock_times.append([
										datetime.combine(current_date, datetime.min.time()) + shift_type.get('break_time_start'),
										datetime.combine(current_date, datetime.min.time()) + shift_type.get('break_time_end')
									])

								# For night differential
								night_differential_clock_times = [
									[
										datetime.combine(current_date, datetime.min.time()) + timedelta(hours=21),
										datetime.combine(current_date, datetime.min.time()) + timedelta(hours=30)
									]
								]

								total_working_hours -= total_break_time

								# Retrieve checkin and sort into pairs
								employee_checkins = frappe.db.get_list(
									'Employee Checkin',
									filters=[
										['time', '>=', min_time],
										['time', '<=', max_time],
										['employee', '=', employee_name]
									],
									fields=['name', 'time', 'log_type', 'lark_result_id'],
									order_by='time asc'
								)

								checkin_pairs = []

								for checkin in employee_checkins:
									if checkin.get('lark_result_id'):
										is_lark = True

									if checkin.get('log_type') == 'IN':
										if not len(checkin_pairs) or len(checkin_pairs[-1]) == 2:
											checkin_pairs.append([
												checkin
											])
									
									if checkin.get('log_type') == 'OUT':
										if checkin_pairs[-1] and len(checkin_pairs[-1]) == 1:
											checkin_pairs[-1].append(checkin)

								checkin_time_pairs = []

								for pair in checkin_pairs:
									if len(pair) == 2:
										checkin_time_pairs.append([
											pair[0].get('time'),
											pair[1].get('time')
										])

								# Calculate and create attendance
								attendance = frappe.new_doc('Attendance')
								attendance.employee = employee_name
								attendance.company = frappe.db.get_value('Employee', employee_name, 'company')
								attendance.attendance_date = current_date
								attendance.working_hours = 0
								attendance.leave = 0
								attendance.overtime = 0
								attendance.expected_working_hours = total_working_hours.seconds / 3600
								attendance.undertime = total_working_hours.seconds / 3600
								attendance.night_differential = 0
								attendance.night_differential_overtime = 0
								attendance.late_in = 0
								attendance.shift = shift_type.get('name')
								approved_attendance_ot = -1

								if len(checkin_time_pairs) == 0:
									if attendance.leave:
										attendance.status = 'On Leave'
									else:
										attendance.status = 'Absent'
										attendance.undertime = 0
								else:
									attendance.status = 'Present'

									if shift_type.get('computation_method') == 'Flexible':
										attendance.undertime = 0

									# Regular fixed schedule
									# Calculate regular working hours
									# Check if the first in is within the grace period
									if checkin_time_pairs[0][0] > clockin_time:
										if checkin_time_pairs[0][0] - clockin_time <= timedelta(minutes=shift_type.get('grace_period')):
											checkin_time_pairs[0][0] = clockin_time
										else:
											if shift_type.get('computation_method') == 'Fixed':
												attendance.late_entry = True

										# Check if they should be considered absent
										if checkin_time_pairs[0][0] - clockin_time > timedelta(minutes=shift_type.get('absent_grace_period')):
											attendance.status = 'Absent'

									# Check if the last out is within the grace period
									if checkin_time_pairs[-1][1] < clockout_time:
										if clockout_time - checkin_time_pairs[-1][1] <= timedelta(minutes=shift_type.get('early_out_grace_period')):
											checkin_time_pairs[-1][1] = clockout_time
										else:
											if shift_type.get('computation_method') == 'Fixed':
												attendance.early_exit = True

										if clockout_time - checkin_time_pairs[-1][1] > timedelta(minutes=shift_type.get('early_out_absent_grace_period')):
											attendance.status = 'Absent'

									# Calculate regular working hours
									working_times = overlap_times(checkin_time_pairs, clock_times)
									working_time = compute_time_total(working_times)

									# Calculate overtime
									overtime_times = overlap_times(checkin_time_pairs, overtime_clock_times)
									overtime_time = compute_time_total(overtime_times)

									# Calculate break time
									break_times = overlap_times(checkin_time_pairs, break_clock_times)
									break_time = compute_time_total(break_times)

									# Calculate night differential
									night_differential_times = overlap_times(working_times, night_differential_clock_times)
									night_differential_time = compute_time_total(night_differential_times)

									# Calculate OT night differential
									night_differential_overtimes = overlap_times(overtime_times, night_differential_clock_times)
									night_differential_overtime = compute_time_total(night_differential_overtimes)

									working_time -= break_time

									if shift_type.get('computation_method') == 'Fixed':
										attendance.undertime = max(attendance.undertime - working_time.seconds / 3600, 0)

									attendance.working_hours = working_time.seconds / 3600
									attendance.overtime = overtime_time.seconds / 3600
									attendance.night_differential = night_differential_time.seconds / 3600
									attendance.night_differential_overtime = night_differential_overtime.seconds / 3600

								if approved_attendance_ot > -1:
									attendance.overtime = min(approved_attendance_ot, attendance.overtime)

								attendance.save()

						self.log(employee_name, True, date=current_date)
					except Exception as e:
						self.log(employee_name, False, date=current_date, error=e)

					current_date += timedelta(days=1)
			except Exception as e:
					self.log(employee_name, False, error=e)

			self.update_progress(status='In Progress', processed_employees=i + 1)

@frappe.whitelist()
def dispatch_calculation(calculation):
	return frappe.get_doc("Attendance Calculation", calculation).dispatch()

def start_calculation(calculation):
	frappe.get_doc("Attendance Calculation", calculation).start()

def get_employees(**kwargs):
	conditions, values = [], []
	for field, value in kwargs.items():
		if value:
			if isinstance(value, list):
				if len(value):
					conditions.append(("{0} IN (" + ', '.join(map(lambda x: '%s', value)) + ")").format(field))

					for val in value:
						values.append(val.get('value'))
			else:
				conditions.append("{0}=%s".format(field))
				values.append(value)

	condition_str = " and " + " and ".join(conditions) if conditions else ""

	employees = frappe.db.sql_list("select name from tabEmployee where status='Active' {condition}"
		.format(condition=condition_str), tuple(values))
 
	return employees

def overlap_times(set_a=[], set_b=[]):
	overlaps = []

	for a in set_a:
		for b in set_b:
			new_set = [max(a[0], b[0]), min(a[1], b[1])]

			if new_set[1] > new_set[0]:
				overlaps.append(new_set)

	return overlaps

def compute_time_total(pairs=[]):
	time = timedelta(0)

	for pair in pairs:
		time += (pair[1] - pair[0])

	return time
