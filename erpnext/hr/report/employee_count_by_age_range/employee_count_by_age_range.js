frappe.query_reports['Employee Count by Age Range'] = {
  filters: [
    {
      fieldname: 'first_age',
      label: 'First Age',
      fieldtype: 'Int',
      width: '80',
      default: 20,
      reqd: true
    },
    {
      fieldname: 'interval',
      label: 'Interval',
      fieldtype: 'Int',
      width: '80',
      default: 5,
      reqd: true
    }
  ]
};
