import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Field set below matches the REAL FBR invoice payload (confirmed against the user's own
# working production integration and a live sandbox-validate call), not the numeric-coded
# schema documented in PRAL's Technical Specification PDF. Key differences from that PDF:
#   - saleType lives on each item, not the invoice header
#   - seller and buyer are separate blocks (NTN/CNIC, business name, province, address each)
#   - rate/uoM/saleType/sroScheduleNo/sroItemSerialNo are all human-readable text, not codes
#   - no cvt / whiT_* / bposId / distributor_* fields exist in the confirmed real payload


class AccountMove(models.Model):
    _inherit = 'account.move'

    fbr_doc_type_id = fields.Many2one('fbr.doc.type', string='FBR Invoice Type',
        compute='_compute_fbr_doc_type', store=True, readonly=False)

    # Seller = the tenant/company issuing the invoice.
    fbr_seller_ntn_cnic = fields.Char(string='FBR Seller NTN/CNIC', compute='_compute_fbr_seller_defaults', store=True, readonly=False)
    fbr_seller_business_name = fields.Char(string='FBR Seller Business Name', compute='_compute_fbr_seller_defaults', store=True, readonly=False)
    fbr_seller_province_id = fields.Many2one('fbr.province', string='FBR Seller Province', compute='_compute_fbr_seller_defaults', store=True, readonly=False)
    fbr_seller_address = fields.Char(string='FBR Seller Address', compute='_compute_fbr_seller_defaults', store=True, readonly=False)

    # Buyer = the customer/partner on the invoice.
    fbr_buyer_ntn_cnic = fields.Char(string='FBR Buyer NTN/CNIC', compute='_compute_fbr_buyer_defaults', store=True, readonly=False)
    fbr_buyer_business_name = fields.Char(string='FBR Buyer Business Name', compute='_compute_fbr_buyer_defaults', store=True, readonly=False)
    fbr_buyer_province_id = fields.Many2one('fbr.province', string='FBR Buyer Province', compute='_compute_fbr_buyer_defaults', store=True, readonly=False)
    fbr_buyer_address = fields.Char(string='FBR Buyer Address', compute='_compute_fbr_buyer_defaults', store=True, readonly=False)
    fbr_buyer_registration_type = fields.Selection([
        ('Registered', 'Registered'),
        ('Unregistered', 'Unregistered'),
    ], string='FBR Buyer Registration Type', compute='_compute_fbr_buyer_defaults', store=True, readonly=False)

    fbr_invoice_ref_no = fields.Char(string='FBR Invoice Ref No.')
    fbr_scenario_id = fields.Char(string='FBR Scenario ID',
        help='Only used for sandbox scenario-based testing (e.g. SN001) - left blank on production submissions.')

    # Totals, computed from lines - matches the fields that actually exist in the confirmed
    # real item schema (no CVT / withholding-income-tax fields there, so none here either).
    fbr_total_sales_tax_applicable = fields.Float(compute='_compute_fbr_totals', store=True, readonly=False)
    fbr_total_retail_price = fields.Float(compute='_compute_fbr_totals', store=True, readonly=False)
    fbr_total_st_withheld = fields.Float(compute='_compute_fbr_totals', store=True, readonly=False)
    fbr_total_extra_tax = fields.Float(compute='_compute_fbr_totals', store=True, readonly=False)
    fbr_total_fed_payable = fields.Float(compute='_compute_fbr_totals', store=True, readonly=False)
    fbr_total_discount = fields.Float(compute='_compute_fbr_totals', store=True, readonly=False)

    fbr_status = fields.Selection([
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ], string='FBR Status', default='pending', copy=False, index=True)
    fbr_invoice_number = fields.Char(string='FBR Invoice No.', readonly=True, copy=False)
    fbr_last_error = fields.Char(string='FBR Last Error', readonly=True, copy=False)
    fbr_log_count = fields.Integer(compute='_compute_fbr_log_count')

    @api.depends('move_type')
    def _compute_fbr_doc_type(self):
        # Live /pdi/v1/doctypecode currently only exposes "Sale Invoice" and "Debit Note" -
        # match by description text since that's what's actually submitted.
        doc_type_model = self.env['fbr.doc.type']
        mapping = {'out_invoice': 'Sale Invoice', 'out_refund': 'Debit Note'}
        for move in self:
            desc = mapping.get(move.move_type)
            move.fbr_doc_type_id = doc_type_model.search([('description', '=', desc)], limit=1) if desc else False

    @staticmethod
    def _fbr_clean_address(raw_address):
        # contact_address pads in a blank line for every unset address component (city/state/
        # country) - e.g. a partner with only `street` set renders as "Street\n\n  \n". FBR's
        # parser rejects that as malformed JSON (confirmed directly - this exact pattern broke
        # a real submission), so collapse it to just the non-empty lines instead of trusting
        # contact_address verbatim.
        if not raw_address:
            return False
        lines = [line.strip() for line in raw_address.split('\n')]
        return ', '.join(line for line in lines if line) or False

    @api.depends('company_id', 'company_id.vat', 'company_id.name', 'company_id.fbr_province_id',
                 'company_id.partner_id.contact_address')
    def _compute_fbr_seller_defaults(self):
        for move in self:
            move.fbr_seller_ntn_cnic = move.company_id.vat or False
            move.fbr_seller_business_name = move.company_id.name or False
            move.fbr_seller_address = move._fbr_clean_address(move.company_id.partner_id.contact_address)
            # Sourced directly from res.company.fbr_province_id (set once during company setup -
            # see README Part 2), not inferred from company.state_id by fuzzy name-matching.
            # That old approach silently produced nothing for non-Pakistani company records and
            # was the actual root cause of "the cascading fields aren't working": with no seller
            # province, every downstream cascade (Sale Type -> Rate -> SRO Schedule -> SRO Item)
            # has nothing to send FBR and silently no-ops - see the onchange methods below.
            move.fbr_seller_province_id = move.company_id.fbr_province_id

    @api.depends('partner_id', 'partner_id.fbr_ntn_cnic', 'partner_id.name',
                 'partner_id.fbr_province_id', 'partner_id.contact_address', 'partner_id.fbr_registration_status')
    def _compute_fbr_buyer_defaults(self):
        for move in self:
            move._set_fbr_buyer_defaults_from_partner()

    def _set_fbr_buyer_defaults_from_partner(self):
        self.fbr_buyer_ntn_cnic = self.partner_id.fbr_ntn_cnic or False
        self.fbr_buyer_business_name = self.partner_id.name or False
        self.fbr_buyer_province_id = self.partner_id.fbr_province_id.id or False
        self.fbr_buyer_address = self._fbr_clean_address(self.partner_id.contact_address)
        self.fbr_buyer_registration_type = (
            'Registered' if self.partner_id.fbr_registration_status == 'registered' else 'Unregistered'
        )

    @api.onchange('partner_id')
    def _onchange_partner_id_fbr_buyer_defaults(self):
        # Belt-and-suspenders alongside the compute above: switching partner_id on an existing
        # draft invoice in the browser was observed to leave a stale buyer province from the
        # previous customer (a store=True/readonly=False computed Many2one doesn't always clear
        # to False through the client's onchange diff) - this onchange forces a clean reset.
        for move in self:
            move._set_fbr_buyer_defaults_from_partner()

    @api.depends(
        'invoice_line_ids.fbr_sales_tax_applicable', 'invoice_line_ids.fbr_fixed_notified_value',
        'invoice_line_ids.fbr_st_withheld_at_source', 'invoice_line_ids.fbr_extra_tax',
        'invoice_line_ids.fbr_fed_payable', 'invoice_line_ids.fbr_discount')
    def _compute_fbr_totals(self):
        for move in self:
            lines = move.invoice_line_ids
            move.fbr_total_sales_tax_applicable = sum(lines.mapped('fbr_sales_tax_applicable'))
            move.fbr_total_retail_price = sum(lines.mapped('fbr_fixed_notified_value'))
            move.fbr_total_st_withheld = sum(lines.mapped('fbr_st_withheld_at_source'))
            move.fbr_total_extra_tax = sum(lines.mapped('fbr_extra_tax'))
            move.fbr_total_fed_payable = sum(lines.mapped('fbr_fed_payable'))
            move.fbr_total_discount = sum(lines.mapped('fbr_discount'))

    def _compute_fbr_log_count(self):
        log_model = self.env['fbr.invoice.log']
        for move in self:
            move.fbr_log_count = log_model.search_count([
                ('res_model', '=', 'account.move'), ('res_id', '=', move.id),
            ])

    def action_view_fbr_logs(self):
        self.ensure_one()
        return {
            'name': 'FBR Submission Log',
            'type': 'ir.actions.act_window',
            'res_model': 'fbr.invoice.log',
            'view_mode': 'list,form',
            'domain': [('res_model', '=', 'account.move'), ('res_id', '=', self.id)],
        }

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        for move in posted.filtered(lambda m: m.is_invoice() and m.fbr_status != 'success'):
            try:
                move.env['fbr.api.client']._submit_invoice(move, 'account.move')
            except Exception:
                # Never let an FBR outage block the accounting entry itself - the retry
                # cron (data/fbr_cron.xml) will pick this up. See fbr_invoice_log for the
                # actual failure reason.
                _logger.exception('FBR submission failed for account.move %s, will retry via cron', move.id)
        return posted


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    fbr_hs_code_id = fields.Many2one('fbr.hs.code', string='FBR HS Code')
    fbr_product_code = fields.Char(string='FBR Product Code')
    fbr_transaction_type_id = fields.Many2one('fbr.transaction.type', string='FBR Sale Type',
        help='Per-item on the real FBR payload (not header-level).')
    fbr_rate_id = fields.Many2one('fbr.tax.rate', string='FBR Rate',
        help='Options depend on Sale Type + Province + invoice date - fetched live from FBR, see the Refresh Rates button.')
    fbr_uom_id = fields.Many2one('fbr.uom', string='FBR UoM')
    # Defaulted from the line's real computed amounts (price_subtotal/price_total, which Odoo
    # itself derives from quantity x unit price x applied taxes) - previously these were plain,
    # never-populated Float fields defaulting to 0, so every real invoice sent FBR a payload
    # claiming zero sales value and zero tax regardless of the actual transaction amount. Still
    # store=True/readonly=False so a line can override if the real FBR-reportable value needs
    # to differ from Odoo's own tax computation.
    fbr_value_sales_excluding_st = fields.Float(
        string='FBR Value Excl. ST', compute='_compute_fbr_amounts', store=True, readonly=False)
    fbr_sales_tax_applicable = fields.Float(
        string='FBR Sales Tax', compute='_compute_fbr_amounts', store=True, readonly=False)
    fbr_fixed_notified_value = fields.Float(string='FBR Fixed/Retail Price')
    fbr_st_withheld_at_source = fields.Float(string='FBR ST Withheld')
    fbr_extra_tax = fields.Float(string='FBR Extra Tax')
    fbr_further_tax = fields.Float(string='FBR Further Tax')
    fbr_sro_schedule_id = fields.Many2one('fbr.sro.schedule', string='FBR SRO Schedule',
        help='Options depend on Rate + Province + invoice date - fetched live from FBR.')
    fbr_sro_item_id = fields.Many2one('fbr.sro.item', string='FBR SRO Item',
        help='Options depend on the selected SRO Schedule + invoice date - fetched live from FBR.')
    fbr_fed_payable = fields.Float(string='FBR FED Payable')
    fbr_discount = fields.Float(string='FBR Discount')
    fbr_total_values = fields.Float(
        string='FBR Total Values', compute='_compute_fbr_total_values', store=True, readonly=False)

    # Odoo 18's client does NOT enforce a `domain` key returned from @api.onchange on Many2one
    # fields (confirmed empirically - the field still let you search/pick options outside that
    # domain). The reliable mechanism is a real domain expression in the view referencing a
    # field on the record - these Many2many fields hold exactly what each cascade step returned,
    # and account_move_views.xml sets e.g. domain="[('id','in', fbr_uom_allowed_ids)]".
    fbr_uom_allowed_ids = fields.Many2many('fbr.uom', 'fbr_line_uom_allowed_rel', string='FBR UoM (allowed)')
    fbr_rate_allowed_ids = fields.Many2many('fbr.tax.rate', 'fbr_line_rate_allowed_rel', string='FBR Rate (allowed)')
    fbr_sro_schedule_allowed_ids = fields.Many2many(
        'fbr.sro.schedule', 'fbr_line_sro_schedule_allowed_rel', string='FBR SRO Schedule (allowed)')
    fbr_sro_item_allowed_ids = fields.Many2many(
        'fbr.sro.item', 'fbr_line_sro_item_allowed_rel', string='FBR SRO Item (allowed)')

    @api.depends('price_subtotal', 'price_total')
    def _compute_fbr_amounts(self):
        for line in self:
            line.fbr_value_sales_excluding_st = line.price_subtotal
            # price_total - price_subtotal is Odoo's own tax amount for the line; correct for
            # the common case of a single sales-tax-type charge, which is what every line built
            # so far in this module actually has.
            line.fbr_sales_tax_applicable = line.price_total - line.price_subtotal

    # Same bug as _compute_fbr_amounts above: was a plain, never-populated Float, so every
    # payload reported totalValues=0 regardless of the line's actual value - which is exactly
    # the "totalvalues... not set in the payload" case FBR rejected. FBR's own schema treats
    # this as the line's grand total, so it's the sum of the excl-ST value, the sales tax, and
    # any of the extra manually-entered FBR tax components, net of discount.
    @api.depends('fbr_value_sales_excluding_st', 'fbr_sales_tax_applicable', 'fbr_extra_tax',
                 'fbr_further_tax', 'fbr_fed_payable', 'fbr_discount')
    def _compute_fbr_total_values(self):
        for line in self:
            line.fbr_total_values = (
                line.fbr_value_sales_excluding_st + line.fbr_sales_tax_applicable
                + line.fbr_extra_tax + line.fbr_further_tax + line.fbr_fed_payable
                - line.fbr_discount
            )

    @api.onchange('product_id')
    def _onchange_product_id_fbr_defaults(self):
        for line in self:
            if not line.product_id:
                continue
            product = line.product_id.product_tmpl_id
            line.fbr_hs_code_id = product.fbr_hs_code_id
            line.fbr_uom_id = product.fbr_uom_id
            line.fbr_transaction_type_id = product.fbr_transaction_type_id
            line.fbr_rate_id = product.fbr_rate_id
            line.fbr_sro_schedule_id = product.fbr_sro_schedule_id
            line.fbr_sro_item_id = product.fbr_sro_item_id
            line.fbr_product_code = line.product_id.default_code

    @api.onchange('fbr_hs_code_id')
    def _onchange_fbr_hs_code_id(self):
        """Cascade 1: HS code -> UoM options (live FBR call: HS_UOM)."""
        for line in self:
            if not line.fbr_hs_code_id:
                line.fbr_uom_allowed_ids = [(5, 0, 0)]
                continue
            try:
                uom_ids = line.env['fbr.api.client']._fetch_uom_for_hs_code(line.fbr_hs_code_id.code)
            except Exception:
                _logger.exception('FBR HS_UOM lookup failed for %s', line.fbr_hs_code_id.code)
                continue
            allowed = line.env['fbr.uom'].search([('fbr_id', 'in', uom_ids)])
            line.fbr_uom_allowed_ids = [(6, 0, allowed.ids)]
            if allowed and (not line.fbr_uom_id or line.fbr_uom_id.fbr_id not in uom_ids):
                line.fbr_uom_id = allowed[0]

    def _fbr_cascade_date(self, move):
        # invoice_date shows "Today" as a placeholder in the UI but is NOT actually set on a
        # fresh draft until the user explicitly picks it or the record is saved - falling back
        # to today's real date here means the rate/SRO cascades still fire instead of silently
        # no-op'ing just because the placeholder hadn't been turned into a real value yet.
        return move.invoice_date or fields.Date.context_today(move)

    @api.onchange('fbr_transaction_type_id')
    def _onchange_fbr_transaction_type_id(self):
        """Cascade 2: Sale Type (+ seller province + invoice date) -> Rate options (SaleTypeToRate)."""
        for line in self:
            move = line.move_id
            if not line.fbr_transaction_type_id:
                line.fbr_rate_allowed_ids = [(5, 0, 0)]
                continue
            if not move.fbr_seller_province_id:
                return {'warning': {
                    'title': 'FBR Seller Province not set',
                    'message': (
                        'Rate/SRO options can\'t be fetched from FBR without a seller province. '
                        'Set it on the FBR Digital Invoicing tab, or once for all invoices under '
                        'Settings > Users & Companies > Companies > FBR Province.'
                    ),
                }}
            try:
                rate_ids = line.env['fbr.api.client']._fetch_rates_for_sale_type(
                    self._fbr_cascade_date(move).strftime('%d-%b-%Y'),
                    line.fbr_transaction_type_id.fbr_id,
                    move.fbr_seller_province_id.fbr_id,
                )
            except Exception as exc:
                _logger.exception('FBR SaleTypeToRate lookup failed for transaction type %s', line.fbr_transaction_type_id.fbr_id)
                return {'warning': {'title': 'FBR rate lookup failed', 'message': str(exc)}}
            allowed = line.env['fbr.tax.rate'].search([('fbr_id', 'in', rate_ids)])
            line.fbr_rate_allowed_ids = [(6, 0, allowed.ids)]

    @api.onchange('fbr_rate_id')
    def _onchange_fbr_rate_id(self):
        """Cascade 3: Rate (+ seller province + invoice date) -> SRO Schedule options (SroSchedule)."""
        for line in self:
            move = line.move_id
            if not line.fbr_rate_id or not move.fbr_seller_province_id:
                line.fbr_sro_schedule_allowed_ids = [(5, 0, 0)]
                continue
            try:
                sro_ids = line.env['fbr.api.client']._fetch_sro_schedules_for_rate(
                    line.fbr_rate_id.fbr_id,
                    self._fbr_cascade_date(move).strftime('%d-%b-%Y'),
                    move.fbr_seller_province_id.fbr_id,
                )
            except Exception as exc:
                _logger.exception('FBR SroSchedule lookup failed for rate %s', line.fbr_rate_id.fbr_id)
                return {'warning': {'title': 'FBR SRO schedule lookup failed', 'message': str(exc)}}
            allowed = line.env['fbr.sro.schedule'].search([('fbr_id', 'in', sro_ids)])
            line.fbr_sro_schedule_allowed_ids = [(6, 0, allowed.ids)]

    @api.onchange('fbr_sro_schedule_id')
    def _onchange_fbr_sro_schedule_id(self):
        """Cascade 4: SRO Schedule (+ invoice date) -> SRO Item options (SROItem)."""
        for line in self:
            move = line.move_id
            if not line.fbr_sro_schedule_id:
                line.fbr_sro_item_allowed_ids = [(5, 0, 0)]
                continue
            try:
                item_ids = line.env['fbr.api.client']._fetch_sro_items_for_schedule(
                    self._fbr_cascade_date(move).strftime('%Y-%m-%d'), line.fbr_sro_schedule_id.fbr_id,
                )
            except Exception as exc:
                _logger.exception('FBR SROItem lookup failed for schedule %s', line.fbr_sro_schedule_id.fbr_id)
                return {'warning': {'title': 'FBR SRO item lookup failed', 'message': str(exc)}}
            allowed = line.env['fbr.sro.item'].search([('fbr_id', 'in', item_ids)])
            line.fbr_sro_item_allowed_ids = [(6, 0, allowed.ids)]
