from odoo import fields, models


class FbrInvoiceLog(models.Model):
    _name = 'fbr.invoice.log'
    _description = 'FBR Digital Invoicing submission log'
    _order = 'create_date desc'

    # Generic reference so both account.move (invoicing) and pos.order (POS, for orders
    # that are NOT separately invoiced - see fbr_pos_integration) can log against this model
    # without a hard dependency between the two integration modules.
    res_model = fields.Char(required=True, index=True)
    res_id = fields.Integer(required=True, index=True)

    environment = fields.Selection([
        ('validation', 'Validation'),
        ('production', 'Production'),
    ], required=True, default='validation')

    state = fields.Selection([
        ('success', 'Success'),
        ('failed', 'Failed'),
    ], required=True, index=True)

    # FBR returns this as a string ("00", "03", ...) not a real integer - stored as Char so the
    # trace is faithful (an Integer field would silently coerce "00" to 0, losing information).
    status_code = fields.Char(string='FBR Status Code')
    error_message = fields.Char(string='FBR Error Message')
    fbr_invoice_number = fields.Char(string='FBR Invoice No. (result)',
        help='The unique fiscal invoice number FBR returns on success - must be printed on the receipt with the QR code.')
    errors = fields.Text(string='FBR Errors (raw)')

    request_payload = fields.Text(string='Request JSON')
    response_payload = fields.Text(string='Response JSON')

    attempt_no = fields.Integer(default=1, help='Which retry attempt this log entry represents.')
