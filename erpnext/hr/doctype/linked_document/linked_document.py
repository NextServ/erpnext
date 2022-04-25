# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
import frappe
from frappe import utils
from frappe.model.document import Document

class LinkedDocument(Document):
	def set_basic_fields(self):
		if not self.linked_by:
			self.linked_by = frappe.session.user

		if not self.date:
			self.date = utils.nowdate()

	def db_insert(self):
		self.set_basic_fields()
		super().db_insert()

	def db_update(self):
		self.set_basic_fields()
		super().db_update()
