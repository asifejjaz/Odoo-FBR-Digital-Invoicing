import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


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

    # Odoo 18's web client does NOT enforce a `domain` key returned from @api.onchange on
    # Many2one fields (confirmed empirically - the field still let you pick/search options
    # outside that domain). The reliable, standard mechanism is a real domain expression in the
    # view referencing a field on the record - these Many2many fields hold exactly the ids each
    # cascade step returned, and the views set e.g. domain="[('id','in', fbr_uom_allowed_ids)]".
    fbr_uom_allowed_ids = fields.Many2many('fbr.uom', 'fbr_product_uom_allowed_rel', string='FBR UoM (allowed)')
    fbr_rate_allowed_ids = fields.Many2many('fbr.tax.rate', 'fbr_product_rate_allowed_rel', string='FBR Rate (allowed)')
    fbr_sro_schedule_allowed_ids = fields.Many2many(
        'fbr.sro.schedule', 'fbr_product_sro_schedule_allowed_rel', string='FBR SRO Schedule (allowed)')
    fbr_sro_item_allowed_ids = fields.Many2many(
        'fbr.sro.item', 'fbr_product_sro_item_allowed_rel', string='FBR SRO Item (allowed)')

    # Products aren't tied to one invoice/date/province the way an invoice line is, so these
    # defaults are looked up against "today" and the current company's FBR province - a
    # reasonable basis for a default that a real invoice line can still override later.
    def _fbr_cascade_context(self):
        return fields.Date.context_today(self), self.env.company.fbr_province_id

    @api.onchange('fbr_hs_code_id')
    def _onchange_fbr_hs_code_id(self):
        """Cascade 1: HS code -> UoM options (live FBR call: HS_UOM)."""
        for product in self:
            if not product.fbr_hs_code_id:
                product.fbr_uom_allowed_ids = [(5, 0, 0)]
                continue
            try:
                uom_ids = product.env['fbr.api.client']._fetch_uom_for_hs_code(product.fbr_hs_code_id.code)
            except Exception as exc:
                _logger.exception('FBR HS_UOM lookup failed for %s', product.fbr_hs_code_id.code)
                return {'warning': {'title': 'FBR UoM lookup failed', 'message': str(exc)}}
            allowed = product.env['fbr.uom'].search([('fbr_id', 'in', uom_ids)])
            product.fbr_uom_allowed_ids = [(6, 0, allowed.ids)]
            if allowed and (not product.fbr_uom_id or product.fbr_uom_id.fbr_id not in uom_ids):
                product.fbr_uom_id = allowed[0]

    @api.onchange('fbr_transaction_type_id')
    def _onchange_fbr_transaction_type_id(self):
        """Cascade 2: Sale Type (+ company's FBR province + today) -> Rate options (SaleTypeToRate)."""
        for product in self:
            if not product.fbr_transaction_type_id:
                product.fbr_rate_allowed_ids = [(5, 0, 0)]
                continue
            date_str, province = product._fbr_cascade_context()
            if not province:
                return {'warning': {
                    'title': 'FBR Province not set',
                    'message': 'Rate/SRO defaults can\'t be fetched from FBR without a company FBR '
                               'province. Set it under Settings > Users & Companies > Companies > FBR Province.',
                }}
            try:
                rate_ids = product.env['fbr.api.client']._fetch_rates_for_sale_type(
                    date_str.strftime('%d-%b-%Y'), product.fbr_transaction_type_id.fbr_id, province.fbr_id,
                )
            except Exception as exc:
                _logger.exception('FBR SaleTypeToRate lookup failed for transaction type %s', product.fbr_transaction_type_id.fbr_id)
                return {'warning': {'title': 'FBR rate lookup failed', 'message': str(exc)}}
            allowed = product.env['fbr.tax.rate'].search([('fbr_id', 'in', rate_ids)])
            product.fbr_rate_allowed_ids = [(6, 0, allowed.ids)]

    @api.onchange('fbr_rate_id')
    def _onchange_fbr_rate_id(self):
        """Cascade 3: Rate (+ company's FBR province + today) -> SRO Schedule options (SroSchedule)."""
        for product in self:
            if not product.fbr_rate_id:
                product.fbr_sro_schedule_allowed_ids = [(5, 0, 0)]
                continue
            date_str, province = product._fbr_cascade_context()
            if not province:
                continue
            try:
                sro_ids = product.env['fbr.api.client']._fetch_sro_schedules_for_rate(
                    product.fbr_rate_id.fbr_id, date_str.strftime('%d-%b-%Y'), province.fbr_id,
                )
            except Exception as exc:
                _logger.exception('FBR SroSchedule lookup failed for rate %s', product.fbr_rate_id.fbr_id)
                return {'warning': {'title': 'FBR SRO schedule lookup failed', 'message': str(exc)}}
            allowed = product.env['fbr.sro.schedule'].search([('fbr_id', 'in', sro_ids)])
            product.fbr_sro_schedule_allowed_ids = [(6, 0, allowed.ids)]

    @api.onchange('fbr_sro_schedule_id')
    def _onchange_fbr_sro_schedule_id(self):
        """Cascade 4: SRO Schedule (+ today) -> SRO Item options (SROItem)."""
        for product in self:
            if not product.fbr_sro_schedule_id:
                product.fbr_sro_item_allowed_ids = [(5, 0, 0)]
                continue
            date_str, _province = product._fbr_cascade_context()
            try:
                item_ids = product.env['fbr.api.client']._fetch_sro_items_for_schedule(
                    date_str.strftime('%Y-%m-%d'), product.fbr_sro_schedule_id.fbr_id,
                )
            except Exception as exc:
                _logger.exception('FBR SROItem lookup failed for schedule %s', product.fbr_sro_schedule_id.fbr_id)
                return {'warning': {'title': 'FBR SRO item lookup failed', 'message': str(exc)}}
            allowed = product.env['fbr.sro.item'].search([('fbr_id', 'in', item_ids)])
            product.fbr_sro_item_allowed_ids = [(6, 0, allowed.ids)]
