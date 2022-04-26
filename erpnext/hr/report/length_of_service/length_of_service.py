# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder.custom import CustomSqlColumn

def execute(filters=None):
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
		'width': 150,
		'options': 'Company'
	}, {
		'label': _('Department'),
		'fieldtype': 'Link',
		'fieldname': 'department',
		'width': 150,
		'options': 'Department'
	}, {
		'label': _('Date of Joining'),
		'fieldtype': 'Date',
		'fieldname': 'date_of_joining',
		'width': 150,
	}, {
		'label': _('Designation'),
		'fieldtype': 'Link',
		'fieldname': 'designation',
		'width': 150,
		'options': 'Designation'
	}, {
		'label': _('Years of Service'),
		'fieldtype': 'Float',
		'fieldname': 'years_of_service',
		'width': 150,
	}]

	return columns

def get_data(filters=None):
	conditions = get_conditions(filters)
	employee = frappe.qb.DocType('Employee')
	as_of_date = frappe.db.escape(filters['as_of_date'])

	query = frappe.qb.from_(employee).select(
		employee.name,
		employee.employee_name,
		employee.company,
		employee.department,
		employee.date_of_joining,
		employee.designation,
		CustomSqlColumn('TIMESTAMPDIFF(YEAR, date_of_joining, GREATEST(' + as_of_date + ', COALESCE(relieving_date, ' + as_of_date + ')))').as_('years_of_service')
	)

	for condition in conditions.keys():
		query = query.where(employee.__getattr__(condition) == conditions[condition])

	return query.run()

def get_conditions(filters):
	conditions={
		'status': 'Active'
	}

	if filters.get('employee'):
		conditions['name'] = filters.get('employee')

	if filters.get('company'):
		conditions['company'] = filters.get('company')

	if filters.get('department'):
		conditions['department'] = filters.get('department')

	return conditions
