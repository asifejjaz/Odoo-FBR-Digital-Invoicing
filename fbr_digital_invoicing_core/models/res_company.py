from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Authoritative source for the seller-side FBR cascade (SaleTypeToRate/SroSchedule both
    # need "origination_supplier" = the seller's province code). Previously this was inferred by
    # fuzzy-matching company.state_id.name against fbr.province, which silently produced nothing
    # for companies whose state isn't a Pakistani province (e.g. a demo/US company) - set once
    # here instead, during company setup (see README Part 2, Step 3).
    fbr_province_id = fields.Many2one('fbr.province', string='FBR Province')
