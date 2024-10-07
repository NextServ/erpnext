import frappe
from frappe.lark import get_lark_settings
import requests

def create_lark_department(department, method):
  lark_settings = get_lark_settings()

  if not department.get('sync_id') and lark_settings:
    lark_tenant = department.get_lark_tenant()
    lark_settings.for_tenant(lark_tenant)
    tenant_access_token = lark_settings.get_tenant_access_token()
    parent_sync_id = '0'

    if department.get_parent_lark_tenant() == lark_tenant:
      if department.get('parent_department') and frappe.db.exists('Department', department.get('parent_department')):
        parent_sync_id = frappe.db.get_value('Department', filters={ 'name': department.get('parent_department') }, fieldname='sync_id')

    r = requests.post('https://open.larksuite.com/open-apis/contact/v3/departments?department_id_type=open_department_id', headers={
      'Authorization': 'Bearer ' + tenant_access_token
    }, json={
      'name': department.get('department_name'),
      'parent_department_id': parent_sync_id or '0',
    }).json()

    if r.get('code') == 43022:
      # Duplicate department name, use suffixed version instead
      r = requests.post('https://open.larksuite.com/open-apis/contact/v3/departments?department_id_type=open_department_id', headers={
        'Authorization': 'Bearer ' + tenant_access_token
      }, json={
        'name': department.get('name'),
        'parent_department_id': parent_sync_id or '0',
      }).json()

    lark_settings.handle_response_error(r)
    department.sync_id = r.get('data').get('department').get('open_department_id')
    department.save(ignore_permissions=True)

def update_lark_department(department, method):
  lark_settings = get_lark_settings()

  if lark_settings and department.get('sync_id'):
    lark_tenant = department.get_lark_tenant()
    lark_settings.for_tenant(lark_tenant)
    tenant_access_token = lark_settings.get_tenant_access_token()
    parent_sync_id = '0'

    if department.get_parent_lark_tenant() == lark_tenant:
      if department.get('parent_department') and frappe.db.exists('Department', department.get('parent_department')):
        parent_sync_id = frappe.db.get_value('Department', filters={ 'name': department.get('parent_department') }, fieldname='sync_id')

    r = requests.patch('https://open.larksuite.com/open-apis/contact/v3/departments/' + department.get('sync_id') + '?department_id_type=open_department_id', headers={
      'Authorization': 'Bearer ' + tenant_access_token
    }, json={
      'name': department.get('department_name'),
      'parent_department_id': parent_sync_id,
    }).json()

    if r.get('code') == 43022:
      # Duplicate department name, use suffixed version instead
      r = requests.patch('https://open.larksuite.com/open-apis/contact/v3/departments/' + department.get('sync_id') + '?department_id_type=open_department_id', headers={
        'Authorization': 'Bearer ' + tenant_access_token
      }, json={
        'name': department.get('name'),
        'parent_department_id': parent_sync_id,
      }).json()

    lark_settings.handle_response_error(r)

def delete_lark_department(department, method):
  lark_settings = get_lark_settings()

  if lark_settings:
    lark_settings.for_tenant(department.get_lark_tenant())
    tenant_access_token = lark_settings.get_tenant_access_token()

    r = requests.delete('https://open.larksuite.com/open-apis/contact/v3/departments/' + department.get('sync_id') + '?department_id_type=open_department_id', headers={
      'Authorization': 'Bearer ' + tenant_access_token
    }).json()

    lark_settings.handle_response_error(r)

def update_lark_user_from_employee(employee, method):
  lark_settings = get_lark_settings()

  if lark_settings and employee.get('user_id') and frappe.db.exists('User Social Login', { 'provider': 'lark', 'parent': employee.get('user_id') }):
    lark_id = frappe.db.get_value('User Social Login', { 'provider': 'lark', 'parent': employee.get('user_id') }, fieldname='userid')
    tenant = employee.get_lark_tenant()
    lark_settings.for_tenant(tenant)
    tenant_access_token = lark_settings.get_tenant_access_token()
    department = 0

    if employee.get('department'):
      employee_department = frappe.get_doc('Department', employee.get('department'))

      if employee_department.get_lark_tenant() == tenant and employee_department.get('sync_id'):
        department = employee_department.get('sync_id')

    r = requests.patch('https://open.larksuite.com/open-apis/contact/v3/users/' + lark_id + ('?department_id_type=open_department_id' if department != 0 else ''), headers={
      'Authorization': 'Bearer ' + tenant_access_token
    }, json={
      'name': employee.employee_name,
      'email': employee.prefered_email,
      'mobile': employee.cell_number,
    #   'department_ids': [department]
    }).json()

    lark_settings.handle_response_error(r)
