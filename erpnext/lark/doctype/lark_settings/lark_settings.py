# Copyright (c) 2021, JC Gurango and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import requests

class LarkSettings(Document):
	def get_app_access_token(self):
		r = requests.post('https://open.larksuite.com/open-apis/auth/v3/app_access_token/internal', json={
			'app_id': self.app_id,
			'app_secret': self.app_secret,
		})

		r = r.json()

		return r['app_access_token']

	def get_tenant_access_token(self):
		r = requests.post('https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal', json={
			'app_id': self.app_id,
			'app_secret': self.app_secret,
		})

		r = r.json()

		return r['tenant_access_token']

	def handle_response_error(self, response):
		if response.get('code') != 0:
			print(response)
			frappe.throw(response.get('msg'))
