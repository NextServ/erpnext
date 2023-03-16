# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr, formatdate, get_datetime, getdate, nowdate

from erpnext.hr.utils import get_holiday_dates_for_employee, validate_active_employee
from erpnext.hr.doctype.employee_checkin.employee_checkin import get_employees
from erpnext.hr.doctype.shift_assignment.shift_assignment import get_employee_shift
import json
from datetime import datetime, timedelta


class Attendance(Document):
	def validate(self):
		from erpnext.controllers.status_updater import validate_status
		validate_status(self.status, ["Present", "Absent", "On Leave", "Half Day", "Work From Home"])
		validate_active_employee(self.employee)
		self.validate_attendance_date()
		self.validate_duplicate_record()
		self.validate_employee_status()
		self.check_leave_record()

	def validate_attendance_date(self):
		date_of_joining = frappe.db.get_value("Employee", self.employee, "date_of_joining")

		# leaves can be marked for future dates
		if self.status != 'On Leave' and not self.leave_application and getdate(self.attendance_date) > getdate(nowdate()):
			frappe.throw(_("Attendance can not be marked for future dates"))
		elif date_of_joining and getdate(self.attendance_date) < getdate(date_of_joining):
			frappe.throw(_("Attendance date can not be less than employee's joining date"))

	def validate_duplicate_record(self):
		res = frappe.db.sql("""
			select name from `tabAttendance`
			where employee = %s
				and attendance_date = %s
				and name != %s
				and docstatus != 2
		""", (self.employee, getdate(self.attendance_date), self.name))
		if res:
			frappe.throw(_("Attendance for employee {0} is already marked for the date {1}").format(
				frappe.bold(self.employee), frappe.bold(self.attendance_date)))

	def validate_employee_status(self):
		if frappe.db.get_value("Employee", self.employee, "status") == "Inactive":
			frappe.throw(_("Cannot mark attendance for an Inactive employee {0}").format(self.employee))

	def check_leave_record(self):
		leave_record = frappe.db.sql("""
			select leave_type, half_day, half_day_date
			from `tabLeave Application`
			where employee = %s
				and %s between from_date and to_date
				and status = 'Approved'
				and docstatus = 1
		""", (self.employee, self.attendance_date), as_dict=True)
		if leave_record:
			for d in leave_record:
				self.leave_type = d.leave_type
				if d.half_day_date == getdate(self.attendance_date):
					self.status = 'Half Day'
					frappe.msgprint(_("Employee {0} on Half day on {1}")
						.format(self.employee, formatdate(self.attendance_date)))
				else:
					self.status = 'On Leave'
					frappe.msgprint(_("Employee {0} is on Leave on {1}")
						.format(self.employee, formatdate(self.attendance_date)))

#		if self.status in ("On Leave", "Half Day"):
#			if not leave_record:
#				frappe.msgprint(_("No leave record found for employee {0} on {1}")
#					.format(self.employee, formatdate(self.attendance_date)), alert=1)
#		elif self.leave_type:
#			self.leave_type = None
#			self.leave_application = None

	def validate_employee(self):
		emp = frappe.db.sql("select name from `tabEmployee` where name = %s and status = 'Active'",
		 	self.employee)
		if not emp:
			frappe.throw(_("Employee {0} is not active or does not exist").format(self.employee))

@frappe.whitelist()
def get_events(start, end, filters=None):
	events = []

	employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user})

	if not employee:
		return events

	from frappe.desk.reportview import get_filters_cond
	conditions = get_filters_cond("Attendance", filters, [])
	add_attendance(events, start, end, conditions=conditions)
	return events

def add_attendance(events, start, end, conditions=None):
	query = """select name, attendance_date, status
		from `tabAttendance` where
		attendance_date between %(from_date)s and %(to_date)s
		and docstatus < 2"""
	if conditions:
		query += conditions

	for d in frappe.db.sql(query, {"from_date":start, "to_date":end}, as_dict=True):
		e = {
			"name": d.name,
			"doctype": "Attendance",
			"start": d.attendance_date,
			"end": d.attendance_date,
			"title": cstr(d.status),
			"docstatus": d.docstatus
		}
		if e not in events:
			events.append(e)

def mark_attendance(employee, attendance_date, status, shift=None, leave_type=None, ignore_validate=False):
	if not frappe.db.exists('Attendance', {'employee':employee, 'attendance_date':attendance_date, 'docstatus':('!=', '2')}):
		company = frappe.db.get_value('Employee', employee, 'company')
		attendance = frappe.get_doc({
			'doctype': 'Attendance',
			'employee': employee,
			'attendance_date': attendance_date,
			'status': status,
			'company': company,
			'shift': shift,
			'leave_type': leave_type
		})
		attendance.flags.ignore_validate = ignore_validate
		attendance.insert()
		attendance.submit()
		return attendance.name

@frappe.whitelist()
def mark_bulk_attendance(data):
	import json
	if isinstance(data, str):
		data = json.loads(data)
	data = frappe._dict(data)
	company = frappe.get_value('Employee', data.employee, 'company')
	if not data.unmarked_days:
		frappe.throw(_("Please select a date."))
		return

	for date in data.unmarked_days:
		doc_dict = {
			'doctype': 'Attendance',
			'employee': data.employee,
			'attendance_date': get_datetime(date),
			'status': data.status,
			'company': company,
		}
		attendance = frappe.get_doc(doc_dict).insert()
		attendance.submit()


def get_month_map():
	return frappe._dict({
		"January": 1,
		"February": 2,
		"March": 3,
		"April": 4,
		"May": 5,
		"June": 6,
		"July": 7,
		"August": 8,
		"September": 9,
		"October": 10,
		"November": 11,
		"December": 12
		})

@frappe.whitelist()
def get_unmarked_days(employee, month, exclude_holidays=0):
	import calendar
	month_map = get_month_map()

	today = get_datetime()

	dates_of_month = ['{}-{}-{}'.format(today.year, month_map[month], r) for r in range(1, calendar.monthrange(today.year, month_map[month])[1] + 1)]

	length = len(dates_of_month)
	month_start, month_end = dates_of_month[0], dates_of_month[length-1]


	records = frappe.get_all("Attendance", fields = ['attendance_date', 'employee'] , filters = [
		["attendance_date", ">=", month_start],
		["attendance_date", "<=", month_end],
		["employee", "=", employee],
		["docstatus", "!=", 2]
	])

	marked_days = [get_datetime(record.attendance_date) for record in records]
	if cint(exclude_holidays):
		holiday_dates = get_holiday_dates_for_employee(employee, month_start, month_end)
		holidays = [get_datetime(record) for record in holiday_dates]
		marked_days.extend(holidays)

	unmarked_days = []

	for date in dates_of_month:
		date_time = get_datetime(date)
		if today.day == date_time.day and today.month == date_time.month:
			break
		if date_time not in marked_days:
			unmarked_days.append(date)

	return unmarked_days

@frappe.whitelist()
def start_compute_attendance(date_from, date_to, filters):
	filters_obj = json.loads(filters)
	employees = get_employees(grade=filters_obj.get('grade'), department=filters_obj.get('department'), designation=filters_obj.get('designation'), name=filters_obj.get('employee'))

	if employees:
		compute_attendance(date_from=date_from, date_to=date_to, employees=employees)
		#frappe.enqueue(compute_attendance, date_from=date_from, date_to=date_to, employees=employees, timeout=600)
		frappe.msgprint('Computation started.')
	else:
		frappe.msgprint('No employees found.')

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

def compute_attendance(date_from, date_to, employees=[]):
	frappe.publish_progress(percent=0, title=_("Computing attendance..."))

	for i, employee_name in enumerate(employees):
		try:
			frappe.publish_progress(percent=i / len(employees) * 100, title=_("Computing attendance..."))

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
							is_lark = False

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
							attendance.attendance_date = current_date
							attendance.working_hours = 0
							attendance.leave = 0
							attendance.overtime = 0
							attendance.undertime = total_working_hours.seconds / 3600
							attendance.night_differential = 0
							attendance.night_differential_overtime = 0
							attendance.shift = shift_type.get('name')
							approved_attendance_ot = -1

							# Find any Lark records
							if is_lark:
								leave_record = frappe.db.get_value('Lark Leave Record', { 'date': current_date, 'employee': attendance.employee }, 'name')

								if leave_record:
									attendance.leave += frappe.db.get_value('Lark Leave Record', leave_record, 'hours')

								attendance.undertime = max(0, attendance.undertime - attendance.leave)
								approved_ot = frappe.db.get_value('Lark Approved OT', { 'date': current_date, 'employee': attendance.employee }, 'name')

								if approved_ot:
									approved_attendance_ot = frappe.db.get_value('Lark Approved OT', leave_record, 'hours')
								else:
									approved_attendance_ot = 0

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
									print(checkin_time_pairs[-1][1])
									print(clockout_time)
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

					current_date += timedelta(days=1)
				except Exception as e:
					frappe.logger('compute').error('Failed to compute attendance for ' + employee_name + ' on ' + str(current_date), exc_info=e)
		except Exception as e:
			frappe.logger('compute').error('Failed to compute attendance for ' + employee_name, exc_info=e)

		frappe.publish_progress(percent=(i + 1) / len(employees) * 100, title=_("Computing attendance..."))
