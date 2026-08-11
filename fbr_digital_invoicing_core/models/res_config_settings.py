from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Stored per-company via ir.config_parameter (see get_values/set_values below) rather than
    # the standard single-key config_parameter=... shortcut, since the key needs the company id
    # baked in - a plain config_parameter field would be shared across all companies.
    # FBR issues a SEPARATE security token per environment (confirmed directly - a real
    # production token was provided distinct from the sandbox one already configured), so
    # these are two independent fields rather than one token shared across both URLs.
    fbr_environment = fields.Selection([
        ('validation', 'Validation'),
        ('production', 'Production'),
    ], string='FBR Mode', default='validation')
    fbr_security_token = fields.Char(string='FBR Security Token (Sandbox/Validation)')
    fbr_security_token_production = fields.Char(string='FBR Security Token (Production)')

    def set_values(self):
        super().set_values()
        company_id = self.env.company.id
        set_param = self.env['ir.config_parameter'].sudo().set_param
        set_param(f'fbr.environment.{company_id}', self.fbr_environment or 'validation')
        set_param(f'fbr.security_token.{company_id}', self.fbr_security_token or '')
        set_param(f'fbr.security_token_production.{company_id}', self.fbr_security_token_production or '')

    @api.model
    def get_values(self):
        res = super().get_values()
        company_id = self.env.company.id
        get_param = self.env['ir.config_parameter'].sudo().get_param
        res.update(
            fbr_environment=get_param(f'fbr.environment.{company_id}', default='validation'),
            fbr_security_token=get_param(f'fbr.security_token.{company_id}', default=''),
            fbr_security_token_production=get_param(f'fbr.security_token_production.{company_id}', default=''),
        )
        return res

    def action_fbr_sync_reference_data(self):
        """Pulls the 6 flat FBR reference lists (UoM, HS codes, provinces, sale types, doc
        types, SRO items) live and upserts them locally. Save Settings first so the token
        you just typed is actually persisted before this runs."""
        counts = self.env['fbr.api.client'].sync_reference_data()
        message = ', '.join(f'{k}: {v}' for k, v in counts.items())
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': 'FBR reference data synced', 'message': message, 'type': 'success', 'sticky': True},
        }
