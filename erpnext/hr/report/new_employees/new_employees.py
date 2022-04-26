# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _

def execute(filters=None):
	if filters.to_date <= filters.from_date:
		frappe.throw(_('"From Date" can not be greater than or equal to "To Date"'))

	columns = get_columns()
	data = get_data(filters)
	return columns, data

def get_columns():
	columns = [{
		'label': _('Employee'),
		'fieldtype': 'Link',
		'fieldname': 'name',
		'width': 200,
		'options': 'Employee'
	}, {
		'label': _('Employee Name'),
		'fieldtype': 'Dynamic Link',
		'fieldname': 'employee_name',
		'width': 200,
		'options': 'employee'
	}, {
		'label': _('Company'),
		'fieldtype': 'Link',
		'fieldname': 'company',
		'width': 200,
		'options': 'Company'
	}, {
		'label': _('Department'),
		'fieldtype': 'Link',
		'fieldname': 'department',
		'width': 200,
		'options': 'Department'
	}, {
		'label': _('Date of Joining'),
		'fieldtype': 'Date',
		'fieldname': 'date_of_joining',
		'width': 200
	}, {
		'label': _('Designation'),
		'fieldtype': 'Link',
		'fieldname': 'designation',
		'width': 200,
		'options': 'Designation'
	}]

	return columns

def get_data(filters=None):
	conditions = get_conditions(filters)
	return frappe.get_list('Employee',
		filters=conditions,
		fields=['name', 'employee_name', 'company', 'department', 'date_of_joining', 'designation'],
		order_by='date_of_joining ASC')

def get_conditions(filters):
	conditions=[
		['status', '=', 'Active']
	]
	if filters.get('employee'):
		conditions.append(['employee', '=', filters.get('employee')])

	if filters.get('company'):
		conditions.append(['company', '=', filters.get('company')])

	if filters.get('department'):
		conditions.append(['department', '=', filters.get('department')])

	if filters.get('from_date'):
		conditions.append(['date_of_joining', '>=', filters.get('from_date')])

	if filters.get('to_date'):
		conditions.append(['date_of_joining', '<=', filters.get('to_date')])

	return conditions
