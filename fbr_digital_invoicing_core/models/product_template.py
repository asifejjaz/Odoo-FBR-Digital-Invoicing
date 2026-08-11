from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Product-level FBR defaults, mirroring the filterable columns on AxiomSquare's own
    # product list (Sale Type / Tax Rate / Province / SRO Schedule) - these get copied onto
    # invoice lines as starting points (see account_move.py's onchange) and stay overridable
    # per line, since the real cascade (rate/SRO options) is scoped to invoice date + province.
    fbr_hs_code_id = fields.Many2one('fbr.hs.code', string='FBR HS Code')
    fbr_uom_id = fields.Many2one('fbr.uom', string='FBR UoM')
    fbr_transaction_type_id = fields.Many2one('fbr.transaction.type', string='FBR Sale Type')
    fbr_rate_id = fields.Many2one('fbr.tax.rate', string='FBR Default Rate')
    fbr_sro_schedule_id = fields.Many2one('fbr.sro.schedule', string='FBR Default SRO Schedule')
    fbr_sro_item_id = fields.Many2one('fbr.sro.item', string='FBR Default SRO Item')
