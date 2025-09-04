# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt
from dateutil.parser import parse
import math
from datetime import datetime, timedelta
import traceback
import requests
import json

from erpnext.hr.utils import get_holidays_for_employee
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
        if processed_employees is not None:
            self.processed_employees = processed_employees
        if total_employees is not None:
            self.total_employees = total_employees
        if status is not None and status != 'In Progress':
            self.status = status
        if message is not None:
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
                    frappe.msgprint(f"Lark response: {json.dumps(r, indent=2)}")
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
                        actual_attendance = None
                        missed_clock_ins = 0
                        missed_clock_outs = 0
                        duration_late_in = 0
                        duration_undertime = 0
                        undertime_count = 0
                        shift_type = None
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
                                    overtime_value = data.get('value').split(' ')[0]
                                    try:
                                        overtime = flt(overtime_value) / 60 if 'min' in data.get('value') else flt(overtime_value)
                                        frappe.msgprint(f"Parsed overtime from 51307: {overtime} hours")
                                    except Exception as e:
                                        frappe.msgprint(f"Error parsing overtime: {e}")
                                        overtime = None
                                if data.get('code') == '51401' and data.get('value') != '-':
                                    leave = data.get('value')
                                if data.get('code') == '51402' and data.get('value') != '-':
                                    leave_type = data.get('value')
                                if data.get('code') == '51305' and data.get('value') != '-':
                                    duration_late_in = flt(data.get('value').split(' ')[0])
                                if data.get('code') == '51306' and data.get('value') != '-':
                                    duration_undertime = flt(data.get('value').split(' ')[0])
                                if data.get('code') == '51408' and data.get('value') != '-':
                                    missed_clock_ins = flt(data.get('value'))
                                if data.get('code') == '51409' and data.get('value') != '-':
                                    missed_clock_outs = flt(data.get('value'))
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
                                            try:
                                                shift_out = datetime.strptime(feature.get('value'), "%H:%M")
                                                if shift_out:
                                                    if feature.get('value') == '00:00':
                                                        shift_out = timedelta(hours=24)
                                                        frappe.msgprint(f"Shift_out set to 24:00 for midnight: {shift_out}")
                                                    else:
                                                        shift_out = timedelta(hours=shift_out.hour, minutes=shift_out.minute)
                                            except Exception as e:
                                                frappe.msgprint(f"Shift out parsing error: {e}, Raw value: {feature.get('value')}")
                                                shift_out = None
                                if data.get('code') == '51502-1-1' and data.get('value') != '-':
                                    time_in = datetime.strptime(data.get('value'), "%H:%M")
                                    if time_in:
                                        time_in = timedelta(hours=time_in.hour, minutes=time_in.minute)
                                if data.get('code') == '51502-1-2' and data.get('value') != '-':
                                    time_out = datetime.strptime(data.get('value'), "%H:%M")
                                    if time_out:
                                        time_out = timedelta(hours=time_out.hour, minutes=time_out.minute)
                                if data.get('code') == '51309' and data.get('value') != '-':
                                    actual_attendance = flt(data.get('value'))
                                    frappe.msgprint(f"Actual Attendance data: {actual_attendance}")
                                if data.get('code') == '61' and data.get('value') != '-':
                                    absent_days = flt(data.get('value'))
                                    frappe.msgprint(f"Absent Days: {absent_days}")
                                if data.get('code') == '51314' and data.get('value') != '-':
                                    undertime_count = flt(data.get('value'))
                                if data.get('code') == '51202' and data.get('value') != '-':
                                    shift_type = data.get('value').split(' ')[0]
                                    frappe.msgprint(f"Shift type from API: {shift_type}")

                            if date:
                                date = date[0:4] + '-' + date[4:6] + '-' + date[6:8]
                            if expected_hours and leave:
                                leave_time_data = leave.split(' ')
                                if leave_time_data[1] == 'days':
                                    leave = flt(leave_time_data[0]) * expected_hours
                                else:
                                    leave = flt(leave_time_data[0])
                            elif not expected_hours and leave:
                                leave_time_data = leave.split(' ')
                                if leave_time_data[1] == 'days':
                                    leave = flt(leave_time_data[0]) * 8
                                else:
                                    leave = flt(leave_time_data[0])
                            else:
                                leave = 0
                            if time_in and time_out and shift_in and shift_out:
                                if time_out <= time_in:
                                    time_out = time_out + timedelta(hours=24)
                                    frappe.msgprint(f"Adjusted time_out to next day: {time_out}")
                                if shift_out <= shift_in:
                                    shift_out = shift_out + timedelta(hours=24)
                                    frappe.msgprint(f"Adjusted shift_out to next day: {shift_out}")

                            attendance = frappe.new_doc('Attendance')
                            attendance.employee = employee_name
                            attendance.company = frappe.db.get_value('Employee', employee_name, 'company')
                            attendance.attendance_date = date
                            attendance.working_hours = working_hours or 0
                            attendance.expected_working_hours = expected_hours or 0
                            attendance.leave = leave or 0
                            attendance.overtime = overtime or 0
                            attendance.paid_leave = 0
                            attendance.late_in = 0
                            attendance.undertime = 0
                            attendance.night_differential = 0
                            attendance.night_differential_overtime = 0
                            attendance.rest_day = False
                            attendance.time_in = time_in
                            attendance.time_out = time_out
                            attendance.shift_in = shift_in
                            attendance.shift_out = shift_out
                            attendance.in_result = in_result
                            attendance.out_result = out_result
                            attendance.missed_clock_count = 0
                            attendance.hours_deducted_per_missed_clock = 0.0
                            attendance.leave_type = leave_type
                            attendance.late_entry = in_result == 'Late in'
                            if duration_late_in > 0:
                                attendance.late_entry = True
                                attendance.late_in = duration_late_in
                            attendance.early_exit = out_result == 'Early out'
                            if duration_undertime > 0:
                                attendance.early_exit = True
                                attendance.undertime = duration_undertime
                            if (in_result == 'Optional' or out_result == 'Optional') and not leave_type:
                                attendance.rest_day = True
                                if not working_hours and not leave and not overtime:
                                    attendance.status = 'Rest day'
                            frappe.msgprint(f"attendance.leave: {attendance.leave}")
                            if attendance.leave > 0:
                                if attendance.working_hours > 0 or attendance.overtime > 0:
                                    attendance.status = 'Half Day'
                                else:
                                    attendance.status = 'On Leave'
                                paid_leave_hours = 0
                                if leave_type and leave_type[:2] == 'PL':
                                    paid_leave_hours = leave
                                    if leave != expected_hours:
                                        paid_leave_hours = leave
                                        if undertime_count == 0:
                                            attendance.undertime = 0
                                    attendance.paid_leave = paid_leave_hours
                                    attendance.leave -= paid_leave_hours
                                else:
                                    attendance.paid_leave = 0
                            hours_deducted_per_missed_clock = 0.0
                            if missed_clock_ins > 0 or missed_clock_outs > 0:
                                attendance.missed_clock_count = missed_clock_ins + missed_clock_outs
                                missed_clock_count = attendance.missed_clock_count
                                attendance.status = 'Present'
                                if missed_clock_count == 1:
                                    hours_deducted_per_missed_clock = .25 * expected_hours
                                elif missed_clock_count == 2:
                                    hours_deducted_per_missed_clock = .5 * expected_hours
                                    if actual_attendance or absent_days > 0:
                                        if actual_attendance == 0 or absent_days:
                                            attendance.status = 'Absent'
                                            frappe.msgprint(f"Actual Attendance: {actual_attendance}")
                                            frappe.msgprint(f"Absent Days: {absent_days}")
                                            hours_deducted_per_missed_clock = 0
                                elif missed_clock_count == 3:
                                    hours_deducted_per_missed_clock = .75 * expected_hours
                                elif missed_clock_count == 4:
                                    attendance.status = 'Absent'
                                if attendance.status != 'Absent':
                                    attendance.hours_deducted_per_missed_clock = hours_deducted_per_missed_clock
                            holidays_for_date = get_holidays_for_employee(employee_name, date, date, False, True)
                            attendance.legal_holiday = False
                            attendance.special_holiday = False
                            for holiday in holidays_for_date:
                                if holiday.category in ['Regular Holiday']:
                                    attendance.legal_holiday = True
                                if holiday.category in ['Special Non-working Holiday', 'Special Working Holiday']:
                                    attendance.special_holiday = True
                            if attendance.legal_holiday:
                                prev_working_day = self.get_previous_working_day(employee_name, date)
                                prev_attendance = frappe.db.get_value('Attendance', {
                                    'employee': employee_name,
                                    'attendance_date': prev_working_day.strftime('%Y-%m-%d')
                                }, 'status')
                                if prev_attendance == 'Absent':
                                    formatted_date = frappe.utils.getdate(date).strftime('%m-%d-%Y')
                                    frappe.msgprint(f"{formatted_date} is a legal holiday but {employee_name} is absent: Absent before the holiday")
                                    attendance.status = 'Absent'
                                else:
                                    if working_hours > 0:
                                        attendance.status = 'Present'
                                    else:
                                        attendance.status = 'Holiday Off'
                            if in_result == 'No record' and attendance.status != 'Holiday Off':
                                if in_result == 'No record' and out_result == 'No record' or not in_result and not out_result:
                                    attendance.status = 'Absent'
                                    attendance.undertime = 0
                                    attendance.working_hours = 0
                                else:
                                    attendance.status = 'Present'
                                    frappe.msgprint("The employee is present")
                            if (in_result == 'Optional' or out_result == 'Optional') and not leave_type:
                                if attendance.status == 'Present':
                                    attendance.late_entry = False
                                    attendance.early_exit = False
                                    attendance.undertime = 0
                                    attendance.late_in = 0
                            if time_in and time_out and shift_in and shift_out and date and isinstance(shift_out, timedelta):
                                try:
                                    parsed_date = parse(date)
                                    night_differential_clock_times = [
                                        [datetime.combine(parsed_date, datetime.min.time()) + timedelta(hours=22),
                                         datetime.combine(parsed_date, datetime.min.time()) + timedelta(hours=30)]
                                    ]
                                    frappe.msgprint(f"Time in: {time_in}, Time out: {time_out}")
                                    frappe.msgprint(f"Shift in: {shift_in}, Shift out: {shift_out}")
                                    shift_type_db = frappe.db.get_value('Shift Assignment', {
                                        'employee': employee_name,
                                        'start_date': ['<=', date],
                                        'end_date': ['>=', date]
                                    }, 'shift_type') or ''
                                    shift_type = shift_type_db or shift_type
                                    frappe.msgprint(f"Shift type (DB: {shift_type_db}, API: {shift_type}): Final {shift_type}")
                                    shift_periods = []
                                    break_period = []
                                    shift_definition = None
                                    for data in day.get('datas'):
                                        if data.get('code') == '51202' and data.get('value') != '-':
                                            shift_definition = data.get('value')
                                            break
                                    if shift_definition:
                                        frappe.msgprint(f"Parsing shift definition: {shift_definition}")
                                        shift_period_str = shift_definition.split(' ')[1].split(';')
                                        last_end_time = None
                                        for i, period in enumerate(shift_period_str):
                                            try:
                                                start_str, end_str = period.split('-')
                                                start_time_str = start_str.replace('Next day ', '')
                                                end_time_str = end_str.replace('Next day ', '')
                                                start_time = datetime.strptime(start_time_str, "%H:%M")
                                                end_time = datetime.strptime(end_time_str, "%H:%M")
                                                start_days = 1 if 'Next day' in start_str else 0
                                                end_days = 1 if 'Next day' in end_str else 0
                                                shift_periods.append([
                                                    timedelta(days=start_days, hours=start_time.hour, minutes=start_time.minute),
                                                    timedelta(days=end_days, hours=end_time.hour, minutes=end_time.minute)
                                                ])
                                                if i > 0:
                                                    break_period.append([
                                                        datetime.combine(parsed_date, datetime.min.time()) + last_end_time,
                                                        datetime.combine(parsed_date, datetime.min.time()) + timedelta(days=start_days, hours=start_time.hour, minutes=start_time.minute)
                                                    ])
                                                last_end_time = timedelta(days=end_days, hours=end_time.hour, minutes=end_time.minute)
                                            except Exception as e:
                                                frappe.msgprint(f"Error parsing period {period}: {e}")
                                                continue
                                        if shift_periods:
                                            shift_out = last_end_time
                                            attendance.shift_out = shift_out
                                            frappe.msgprint(f"Adjusted shift_out for {shift_type}: {shift_out}")
                                        else:
                                            frappe.msgprint("No valid shift periods parsed; using default shift times")
                                            shift_periods = [[shift_in, shift_out]]
                                    else:
                                        frappe.msgprint("No shift definition found; using default shift times")
                                        shift_periods = [[shift_in, shift_out]]
                                        break_period = []
                                    employee_checkins = frappe.db.get_list(
                                        'Employee Checkin',
                                        filters=[
                                            ['time', '>=', datetime.combine(parsed_date, datetime.min.time()) + shift_in - timedelta(hours=1)],
                                            ['time', '<=', datetime.combine(parsed_date, datetime.min.time()) + shift_out + timedelta(hours=1)],
                                            ['employee', '=', employee_name]
                                        ],
                                        fields=['name', 'time', 'log_type'],
                                        order_by='time asc'
                                    )
                                    frappe.msgprint(f"Employee Checkin: {employee_checkins}")
                                    checkin_pairs = []
                                    current_pair = []
                                    for checkin in employee_checkins:
                                        if checkin.get('log_type') == 'IN':
                                            if not current_pair or len(current_pair) == 2:
                                                current_pair = [checkin.get('time')]
                                        elif checkin.get('log_type') == 'OUT' and current_pair:
                                            current_pair.append(checkin.get('time'))
                                            checkin_pairs.append(current_pair)
                                            current_pair = []
                                    if not checkin_pairs:
                                        checkin_pairs = [[datetime.combine(parsed_date, datetime.min.time()) + time_in,
                                                         datetime.combine(parsed_date, datetime.min.time()) + time_out]]
                                    frappe.msgprint(f"Checkin pairs: {checkin_pairs}")
                                    total_working_hours = working_hours or 0
                                    total_overtime = overtime if overtime is not None else 0
                                    if total_overtime == 0 and working_hours > expected_hours:
                                        total_overtime = working_hours - expected_hours
                                        frappe.msgprint(f"Fallback overtime calculation: {total_overtime} hours (working_hours - expected_hours)")
                                    attendance.working_hours = total_working_hours
                                    attendance.overtime = total_overtime
                                    frappe.msgprint(f"Calculated working hours: {attendance.working_hours}, Overtime: {attendance.overtime}")
                                    total_night_differential = 0
                                    for pair in checkin_pairs:
                                        clock_period = [[pair[0], pair[1]]]
                                        if clock_period[0][1] > clock_period[0][0]:
                                            break_overlap = overlap_times(clock_period, break_period)
                                            break_time = compute_time_total(break_overlap).seconds / 3600
                                            night_diff_times = overlap_times(clock_period, night_differential_clock_times)
                                            night_diff = compute_time_total(night_diff_times).seconds / 3600
                                            night_diff -= break_time
                                            total_night_differential += max(0, night_diff)
                                            frappe.msgprint(f"Pair {pair}: Night diff {night_diff}, Break {break_time}")
                                    attendance.night_differential = math.ceil(total_night_differential)
                                    frappe.msgprint(f"Night differential: {attendance.night_differential} hours")
                                    if total_overtime > 0:
                                        overtime_start = datetime.combine(parsed_date, datetime.min.time()) + shift_out
                                        overtime_end = datetime.combine(parsed_date, datetime.min.time()) + time_out
                                        night_differential_ot_times = overlap_times([[overtime_start, overtime_end]], night_differential_clock_times)
                                        night_differential_overtime = compute_time_total(night_differential_ot_times).seconds / 3600
                                        rounded_night_differential_overtime = math.ceil(night_differential_overtime)
                                        attendance.night_differential_overtime = rounded_night_differential_overtime
                                        frappe.msgprint(f"Night differential overtime: {night_differential_overtime} hours, Rounded: {rounded_night_differential_overtime}")
                                    else:
                                        attendance.night_differential_overtime = 0
                                    if missed_clock_ins > 0 or missed_clock_outs > 0:
                                        attendance.overtime = 0
                                        attendance.night_differential_overtime = 0
                                    attendance.save()
                                    self.log(employee_name, True, date=date)
                                except Exception as e:
                                    frappe.msgprint(f"Night differential calculation error: {e}")
                                    attendance.night_differential = 0
                                    attendance.night_differential_overtime = 0
                                    attendance.save()
                                    self.log(employee_name, True, date=date)
                        except Exception as e:
                            self.log(employee_name, False, error=e, date=date)
                except Exception as e:
                    self.log(employee_name, False, error=e, response=r)
            self.update_progress(status='In Progress', processed_employees=i + 1)

    def compute_attendance(self, date_from, date_to, employees=[]):
        for i, employee_name in enumerate(employees):
            frappe.publish_progress(percent=i / len(employees) * 100, title=_("Computing attendance..."))
            employee = frappe.get_doc('Employee', employee_name)
            current_date = frappe.utils.getdate(date_from)
            end_date = frappe.utils.getdate(date_to)
            while current_date <= end_date:
                try:
                    shift = get_employee_shift(employee_name, current_date, True)
                    if not shift:
                        self.log(employee_name, False, date=current_date.strftime('%Y-%m-%d'), error="No shift found")
                        current_date += timedelta(days=1)
                        continue
                    shift_type = frappe.get_doc('Shift Type', shift.shift_type)
                    employee_checkins = frappe.db.get_list('Employee Checkin', filters=[
                        ['employee', '=', employee_name],
                        ['time', '>=', datetime.combine(current_date, datetime.min.time())],
                        ['time', '<=', datetime.combine(current_date, datetime.min.time()) + timedelta(hours=24)]
                    ], fields=['name', 'time', 'log_type'], order_by='time asc')
                    checkin_pairs = []
                    current_pair = []
                    for checkin in employee_checkins:
                        if checkin.get('log_type') == 'IN':
                            if not current_pair or len(current_pair) == 2:
                                current_pair = [checkin.get('time')]
                        elif checkin.get('log_type') == 'OUT' and current_pair:
                            current_pair.append(checkin.get('time'))
                            checkin_pairs.append(current_pair)
                            current_pair = []
                    night_differential_clock_times = []
                    for period in shift_type.night_differential_period:
                        night_differential_clock_times.append([datetime.combine(current_date, period.start_time),
                                                              datetime.combine(current_date, period.end_time)])
                    total_night_differential = 0
                    attendance = frappe.new_doc('Attendance')
                    attendance.employee = employee_name
                    attendance.company = employee.company
                    attendance.attendance_date = current_date.strftime('%Y-%m-%d')
                    attendance.status = 'Present'
                    total_working_hours = 0
                    for pair in checkin_pairs:
                        clock_period = [[pair[0], pair[1]]]
                        working_time = compute_time_total(clock_period).seconds / 3600
                        total_working_hours += working_time
                        night_differential_times = overlap_times(clock_period, night_differential_clock_times)
                        night_differential = compute_time_total(night_differential_times).seconds / 3600
                        total_night_differential += night_differential
                    attendance.working_hours = total_working_hours
                    attendance.night_differential = math.floor(total_night_differential)
                    holidays_for_date = get_holidays_for_employee(employee_name, current_date, current_date, False, True)
                    attendance.legal_holiday = False
                    attendance.special_holiday = False
                    for holiday in holidays_for_date:
                        if holiday.category in ['Regular Holiday']:
                            attendance.legal_holiday = True
                        if holiday.category in ['Special Non-working Holiday', 'Special Working Holiday']:
                            attendance.special_holiday = True
                    if attendance.legal_holiday:
                        prev_working_day = self.get_previous_working_day(employee_name, current_date)
                        prev_attendance = frappe.db.get_value('Attendance', {
                            'employee': employee_name,
                            'attendance_date': prev_working_day.strftime('%Y-%m-%d')
                        }, 'status')
                        if prev_attendance == 'Absent':
                            formatted_date = current_date.strftime('%m-%d-%Y')
                            frappe.msgprint(f"{formatted_date} is a legal holiday but {employee_name} is absent: Absent before the holiday")
                            attendance.status = 'Absent'
                        else:
                            if total_working_hours > 0:
                                attendance.status = 'Present'
                            else:
                                attendance.status = 'Holiday Off'
                    if not checkin_pairs:
                        attendance.status = 'Absent'
                        attendance.working_hours = 0
                    attendance.save()
                    self.log(employee_name, True, date=current_date.strftime('%Y-%m-%d'))
                except Exception as e:
                    self.log(employee_name, False, date=current_date.strftime('%Y-%m-%d'), error=e)
                current_date += timedelta(days=1)
            self.update_progress(status='In Progress', processed_employees=i + 1)

    def get_previous_working_day(self, employee_name, current_date):
        date = frappe.utils.getdate(current_date) - timedelta(days=1)
        while True:
            holidays = get_holidays_for_employee(employee_name, date, date, False, True)
            is_holiday = any(holiday.category in ['Regular Holiday', 'Special Non-working Holiday', 'Special Working Holiday'] for holiday in holidays)
            is_weekend = date.weekday() >= 5
            if not is_holiday and not is_weekend:
                return date
            date -= timedelta(days=1)

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
