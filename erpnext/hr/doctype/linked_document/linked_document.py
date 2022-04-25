# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
import frappe
from frappe.model.document import Document

class LinkedDocument(Document):
	def db_insert(self):
		if not self.linked_by:
			self.linked_by = frappe.session.user
		super().db_insert()

	def db_update(self):
		if not self.linked_by:
			self.linked_by = frappe.session.user
		super().db_update()
