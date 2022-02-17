import frappe
import requests
import frappe.utils.oauth
import urllib

__version__ = '0.0.1'

@frappe.whitelist(allow_guest=True)
def login():
  lark_settings = frappe.get_doc('Lark Settings')
  redirect_url = frappe.utils.get_url('/api/method/erpnext.lark.login_callback')
  redirect_url = urllib.parse.quote_plus(redirect_url)

  frappe.local.response['type'] = 'redirect'
  frappe.local.response['location'] = 'https://open.larksuite.com/open-apis/authen/v1/index?redirect_uri=' + redirect_url + '&app_id=' + lark_settings.app_id
  return

@frappe.whitelist(allow_guest=True)
def login_callback():
  lark_settings = frappe.get_doc('Lark Settings')
  app_access_token = lark_settings.get_app_access_token()
  code = frappe.local.request.args.get('code')
  r = requests.post('https://open.larksuite.com/open-apis/authen/v1/access_token', json={
    'app_access_token': app_access_token,
    'grant_type': 'authorization_code',
    'code': code,
  })
  r = r.json()

  if (r['code'] == 0):
    user = r['data']
    
    if frappe.db.exists('User Social Login', { 'provider': 'lark', 'userid': user['open_id'] }):
      # Fill in sub field for OAuth compliance
      user['sub'] = user['open_id']
      user['gender'] = ''

      frappe.utils.oauth.login_oauth_user(user, provider='lark', state={
        'token': user['access_token']
      })
      return
    else:
      frappe.throw('You don\'t have permission to access Lemonade.')

  return r

def get_lark_settings():
  return frappe.get_doc('Lark Settings')

def create_lark_user(user, method):
  lark_settings = get_lark_settings()

  if lark_settings:
    tenant_access_token = lark_settings.get_tenant_access_token()
    r = requests.post('https://open.larksuite.com/open-apis/contact/v3/users', headers={
      'Authorization': 'Bearer ' + tenant_access_token
    }, json={
      'name': user.full_name,
      'email': user.email,
      'mobile': user.mobile_no,
      'employee_type': 1,
      'department_ids': [0]
    }).json()

    lark_settings.handle_response_error(r)
    lark_user_id = r.get('data').get('user').get('open_id')
    user.append('social_logins', {
      'provider': 'lark',
      'userid': lark_user_id,
    })
    user.save(ignore_permissions=True)

def delete_lark_user(user, method):
  for login in user.social_logins:
    if login.provider == 'lark':
      lark_settings = get_lark_settings()

      if lark_settings:
        tenant_access_token = lark_settings.get_tenant_access_token()
        r = requests.delete('https://open.larksuite.com/open-apis/contact/v3/users/' + login.get('userid'), headers={
          'Authorization': 'Bearer ' + tenant_access_token
        }).json()
        lark_settings.handle_response_error(r)

      return

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
      'parent_department_id': parent_sync_id,
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
