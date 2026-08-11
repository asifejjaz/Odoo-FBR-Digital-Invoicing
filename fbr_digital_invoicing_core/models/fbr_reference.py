from odoo import api, fields, models

# These models mirror FBR's LIVE reference-data endpoints (gw.fbr.gov.pk/pdi/...), confirmed
# by directly probing them - NOT the numeric "T1000017"/"S1000012"-style codes documented in
# PRAL's Technical Specification PDF, which turned out not to match what the real API returns.
# Populate via fbr.api.client._sync_reference_data() (Settings > Technical > FBR > Sync Now),
# not via static XML seed data - these lists are FBR-maintained and change over time, and the
# numeric IDs are only meaningful as returned live by FBR, not something to hardcode.


class FbrUom(models.Model):
    _name = 'fbr.uom'
    _description = 'FBR Unit of Measurement (live: /pdi/v1/uom)'
    _rec_name = 'description'

    fbr_id = fields.Integer(required=True, index=True, help='uoM_ID as returned by FBR')
    description = fields.Char(required=True)

    _sql_constraints = [('fbr_id_uniq', 'unique(fbr_id)', 'This UoM already exists.')]


class FbrHsCode(models.Model):
    _name = 'fbr.hs.code'
    _description = 'FBR HS Code (live: /pdi/v1/itemdesccode)'
    _rec_name = 'display_name'

    code = fields.Char(required=True, index=True, help='hS_CODE, dotted format e.g. "8432.1010"')
    description = fields.Char(required=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    _sql_constraints = [('code_uniq', 'unique(code)', 'This HS code already exists.')]

    def recompute_display_names(self):
        """One-off/maintenance fix: records bulk-created before the @api.depends fix below was
        added have a stale, empty display_name (shows as "Unnamed" in the UI). Safe to call any
        time - e.g. after a fresh sync, or once to backfill records synced before this fix."""
        self.search([])._compute_display_name()

    @api.depends('code', 'description')
    def _compute_display_name(self):
        # Without @api.depends, Odoo has no trigger to run this compute - it silently never
        # fired for records bulk-created via sync_reference_data(), leaving display_name empty
        # (shown as "Unnamed" in any list/dropdown). Caught via live browser testing.
        for rec in self:
            rec.display_name = f'{rec.code} - {rec.description}'[:120]


class FbrProvince(models.Model):
    _name = 'fbr.province'
    _description = 'FBR Province / origination of supplier (live: /pdi/v1/provinces)'
    _rec_name = 'description'

    fbr_id = fields.Integer(required=True, index=True, help='stateProvinceCode as returned by FBR')
    description = fields.Char(required=True)

    _sql_constraints = [('fbr_id_uniq', 'unique(fbr_id)', 'This province already exists.')]


class FbrTransactionType(models.Model):
    _name = 'fbr.transaction.type'
    _description = 'FBR Transaction/Sale Type (live: /pdi/v1/transtypecode)'
    _rec_name = 'description'

    fbr_id = fields.Integer(required=True, index=True, help='transactioN_TYPE_ID as returned by FBR')
    description = fields.Char(required=True, help='This exact text is what gets submitted as "saleType" on invoice items.')

    _sql_constraints = [('fbr_id_uniq', 'unique(fbr_id)', 'This transaction type already exists.')]


class FbrDocType(models.Model):
    _name = 'fbr.doc.type'
    _description = 'FBR Document/Invoice Type (live: /pdi/v1/doctypecode)'
    _rec_name = 'description'

    fbr_id = fields.Integer(required=True, index=True, help='docTypeId as returned by FBR')
    description = fields.Char(required=True, help='This exact text is what gets submitted as "invoiceType".')

    _sql_constraints = [('fbr_id_uniq', 'unique(fbr_id)', 'This document type already exists.')]


class FbrTaxRate(models.Model):
    _name = 'fbr.tax.rate'
    _description = 'FBR Tax Rate (live, cascaded: /pdi/v2/SaleTypeToRate)'
    _rec_name = 'description'

    # NOT globally static like the other lookups - FBR returns rate options scoped to a
    # (transaction type, province, date) combination. Records are upserted as they're
    # encountered via the cascade rather than bulk-synced up front.
    fbr_id = fields.Integer(required=True, index=True, help='ratE_ID as returned by FBR')
    description = fields.Char(required=True, help='e.g. "18%" - this exact text is what gets submitted as "rate".')
    value = fields.Float(help='ratE_VALUE, numeric form of the rate, for computing tax amounts locally.')

    _sql_constraints = [('fbr_id_uniq', 'unique(fbr_id)', 'This tax rate already exists.')]


class FbrSroSchedule(models.Model):
    _name = 'fbr.sro.schedule'
    _description = 'FBR SRO Schedule (live, cascaded: /pdi/v1/SroSchedule)'
    _rec_name = 'description'

    fbr_id = fields.Integer(required=True, index=True, help='srO_ID as returned by FBR')
    description = fields.Char(required=True, help='srO_DESC - submitted as "sroScheduleNo".')

    _sql_constraints = [('fbr_id_uniq', 'unique(fbr_id)', 'This SRO schedule already exists.')]


class FbrSroItem(models.Model):
    _name = 'fbr.sro.item'
    _description = 'FBR SRO Item (live: /pdi/v1/sroitemcode, cascaded: /pdi/v2/SROItem)'
    _rec_name = 'description'

    fbr_id = fields.Integer(required=True, index=True, help='srO_ITEM_ID as returned by FBR')
    description = fields.Char(required=True, help='srO_ITEM_DESC - submitted as "sroItemSerialNo".')

    _sql_constraints = [('fbr_id_uniq', 'unique(fbr_id)', 'This SRO item already exists.')]
