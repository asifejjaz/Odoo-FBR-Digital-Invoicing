import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    fbr_ntn_cnic = fields.Char(string='NTN/CNIC (FBR)')
    fbr_province_id = fields.Many2one('fbr.province', string='FBR Province')

    # Populated by the "Check FBR Registration" button below (POST /dist/v1/Get_Reg_Type),
    # matching how AxiomSquare fetches client registration status at creation time - not
    # something the taxpayer enters by hand.
    fbr_registration_status = fields.Selection([
        ('registered', 'Registered'),
        ('unregistered', 'Unregistered'),
        ('unknown', 'Unknown'),
    ], string='FBR Registration Status', default='unknown', readonly=True)

    def action_fbr_check_registration(self):
        self.ensure_one()
        if not self.fbr_ntn_cnic:
            raise UserError('Set the NTN/CNIC (FBR) field before checking registration status.')
        today_str = fields.Date.context_today(self).strftime('%Y-%m-%d')
        try:
            result = self.env['fbr.api.client']._get_registration_type(self.fbr_ntn_cnic, today_str)
        except Exception as exc:
            _logger.exception('FBR Get_Reg_Type failed for partner %s', self.id)
            raise UserError(f'Could not reach FBR to check registration status: {exc}') from exc

        reg_type = (result.get('REGISTRATION_TYPE') or '').strip().lower()
        self.fbr_registration_status = 'registered' if reg_type == 'registered' else (
            'unregistered' if reg_type == 'unregistered' else 'unknown'
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'FBR Registration Status',
                'message': f'{self.name}: {result.get("REGISTRATION_TYPE", "Unknown")}',
                'type': 'success' if reg_type in ('registered', 'unregistered') else 'warning',
            },
        }
