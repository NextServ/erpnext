import frappe
from frappe.lark import get_lark_settings
import requests

def create_lark_department(department, method):
  lark_settings = get_lark_settings()

  if lark_settings:
    tenant_access_token = lark_settings.get_tenant_access_token()
    parent_sync_id = '0'

    if department.get('parent_department') and frappe.db.exists('Department', department.get('parent_department')):
      parent_sync_id = frappe.db.get_value('Department', filters={ 'name': department.get('parent_department') }, fieldname='sync_id')

    r = requests.post('https://open.larksuite.com/open-apis/contact/v3/departments?department_id_type=open_department_id', headers={
      'Authorization': 'Bearer ' + tenant_access_token
    }, json={
      'name': department.get('department_name'),
      'parent_department_id': parent_sync_id or '0',
    }).json()

    lark_settings.handle_response_error(r)
    department.sync_id = r.get('data').get('department').get('open_department_id')
    department.save(ignore_permissions=True)

def update_lark_department(department, method):
  lark_settings = get_lark_settings()

  if lark_settings and department.get('sync_id'):
    tenant_access_token = lark_settings.get_tenant_access_token()
    parent_sync_id = '0'

    if department.get('parent_department') and frappe.db.exists('Department', department.get('parent_department')):
      parent_sync_id = frappe.db.get_value('Department', filters={ 'name': department.get('parent_department') }, fieldname='sync_id')

    r = requests.patch('https://open.larksuite.com/open-apis/contact/v3/departments/' + department.get('sync_id') + '?department_id_type=open_department_id', headers={
      'Authorization': 'Bearer ' + tenant_access_token
    }, json={
      'name': department.get('department_name'),
      'parent_department_id': parent_sync_id,
    }).json()

    lark_settings.handle_response_error(r)

def delete_lark_department(department, method):
  lark_settings = get_lark_settings()

  if lark_settings:
    tenant_access_token = lark_settings.get_tenant_access_token()

    r = requests.delete('https://open.larksuite.com/open-apis/contact/v3/departments/' + department.get('sync_id') + '?department_id_type=open_department_id', headers={
      'Authorization': 'Bearer ' + tenant_access_token
    }).json()

    lark_settings.handle_response_error(r)

def update_lark_user_from_employee(employee, method):
  lark_settings = get_lark_settings()

  if lark_settings and employee.get('user_id') and frappe.db.exists('User Social Login', { 'provider': 'lark', 'parent': employee.get('user_id') }):
    user = frappe.get_doc('User', employee.get('user_id'))
    lark_id = frappe.db.get_value('User Social Login', { 'provider': 'lark', 'parent': employee.get('user_id') }, fieldname='userid')
    tenant_access_token = lark_settings.get_tenant_access_token()
    department = 0

    if employee.get('department'):
      department_sync_id = frappe.db.get_value('Department', filters={ 'name': employee.get('department') }, fieldname='sync_id')

      if department_sync_id:
        department = department_sync_id

    r = requests.patch('https://open.larksuite.com/open-apis/contact/v3/users/' + lark_id + ('?department_id_type=open_department_id' if department != 0 else ''), headers={
      'Authorization': 'Bearer ' + tenant_access_token
    }, json={
      'name': employee.employee_name,
      'email': employee.prefered_email,
      'mobile': employee.cell_number,
      'department_ids': [department]
    }).json()

    lark_settings.handle_response_error(r)
