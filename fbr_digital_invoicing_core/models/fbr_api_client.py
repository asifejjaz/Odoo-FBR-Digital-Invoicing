import json
import logging

import requests

from odoo import models

_logger = logging.getLogger(__name__)

# All URLs below were confirmed live (probed directly, responses inspected) rather than taken
# from PRAL's Technical Specification PDF, which documents a different, numeric-coded payload
# schema that does NOT match what the user's own working production integration (AxiomSquare)
# actually sends. The human-readable schema here (saleType/rate/uoM as descriptive text,
# separate seller/buyer blocks) is what's confirmed real.
SANDBOX_VALIDATE_URL = 'https://gw.fbr.gov.pk/di_data/v1/di/validateinvoicedata_sb'
PRODUCTION_URL = 'https://gw.fbr.gov.pk/pdi/v1/api/DigitalInvoicing/PostInvoiceData_v1'
REG_TYPE_URL = 'https://gw.fbr.gov.pk/dist/v1/Get_Reg_Type'

REFERENCE_ENDPOINTS = {
    'uom': 'https://gw.fbr.gov.pk/pdi/v1/uom',
    'hs_codes': 'https://gw.fbr.gov.pk/pdi/v1/itemdesccode',
    'provinces': 'https://gw.fbr.gov.pk/pdi/v1/provinces',
    'transaction_types': 'https://gw.fbr.gov.pk/pdi/v1/transtypecode',
    'doc_types': 'https://gw.fbr.gov.pk/pdi/v1/doctypecode',
    'sro_items': 'https://gw.fbr.gov.pk/pdi/v1/sroitemcode',
}
HS_UOM_URL = 'https://gw.fbr.gov.pk/pdi/v2/HS_UOM'
SALE_TYPE_TO_RATE_URL = 'https://gw.fbr.gov.pk/pdi/v2/SaleTypeToRate'
SRO_SCHEDULE_URL = 'https://gw.fbr.gov.pk/pdi/v1/SroSchedule'
SRO_ITEM_CASCADE_URL = 'https://gw.fbr.gov.pk/pdi/v2/SROItem'

REQUEST_TIMEOUT = 30  # seconds
LOOKUP_TIMEOUT = 45   # reference/cascading GETs have been observed to be slower than the POST


class FbrApiClient(models.AbstractModel):
    """Shared FBR Digital Invoicing HTTP client - both invoice submission and reference-data lookups."""
    _name = 'fbr.api.client'
    _description = 'FBR Digital Invoicing API client'

    # ---------------------------------------------------------------- config / auth

    def _get_config(self, company):
        get_param = self.env['ir.config_parameter'].sudo().get_param
        company_id = company.id
        environment = get_param(f'fbr.environment.{company_id}', default='validation')
        token = get_param(f'fbr.security_token.{company_id}', default='')
        return environment, token

    def _headers(self, token):
        return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    def _get_token_for_lookups(self, company=None):
        """Reference-data lookups need *a* valid token, not necessarily the environment-selected
        one - they're read-only and don't submit/validate an invoice either way."""
        company = company or self.env.company
        _environment, token = self._get_config(company)
        return token

    # ---------------------------------------------------------------- invoice payload / submission

    def _build_payload(self, move):
        lines = move.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        payload = {
            'invoiceType': move.fbr_doc_type_id.description or '',
            'invoiceDate': move.invoice_date.strftime('%Y-%m-%d') if move.invoice_date else False,
            'sellerNTNCNIC': move.fbr_seller_ntn_cnic or '',
            'sellerBusinessName': move.fbr_seller_business_name or '',
            'sellerProvince': move.fbr_seller_province_id.description or '',
            'sellerAddress': move.fbr_seller_address or '',
            'buyerNTNCNIC': move.fbr_buyer_ntn_cnic or '',
            'buyerBusinessName': move.fbr_buyer_business_name or '',
            'buyerProvince': move.fbr_buyer_province_id.description or '',
            'buyerAddress': move.fbr_buyer_address or '',
            'buyerRegistrationType': move.fbr_buyer_registration_type or '',
            'invoiceRefNo': move.fbr_invoice_ref_no or '',
            'items': [{
                'hsCode': line.fbr_hs_code_id.code or '',
                'productDescription': line.name or '',
                'rate': line.fbr_rate_id.description or '',
                'uoM': line.fbr_uom_id.description or '',
                'quantity': line.quantity,
                'totalValues': line.fbr_total_values,
                'valueSalesExcludingST': line.fbr_value_sales_excluding_st,
                'fixedNotifiedValueOrRetailPrice': line.fbr_fixed_notified_value,
                'salesTaxApplicable': line.fbr_sales_tax_applicable,
                'salesTaxWithheldAtSource': line.fbr_st_withheld_at_source,
                'extraTax': line.fbr_extra_tax,
                'furtherTax': line.fbr_further_tax,
                'sroScheduleNo': line.fbr_sro_schedule_id.description or '',
                'fedPayable': line.fbr_fed_payable,
                'discount': line.fbr_discount,
                'saleType': line.fbr_transaction_type_id.description or '',
                'sroItemSerialNo': line.fbr_sro_item_id.description or '',
            } for line in lines],
        }
        # scenarioId is only meaningful for sandbox scenario-based testing (PRAL User Manual);
        # omit it in production so we're not sending sandbox-only metadata on a real submission.
        if move.fbr_scenario_id:
            payload['scenarioId'] = move.fbr_scenario_id
        return payload

    def _submit_invoice(self, move, res_model):
        """Submit one account.move to FBR (sandbox validate or production, per Settings) and log the result.

        Never raises past this point in normal operation - failures are written to
        fbr.invoice.log and to move.fbr_status/fbr_last_error so the retry cron can
        pick them up. FBR provides no server-side retry, so this module owns it.
        """
        environment, token = self._get_config(move.company_id)
        url = SANDBOX_VALIDATE_URL if environment != 'production' else PRODUCTION_URL
        payload = self._build_payload(move)
        log_vals = {
            'res_model': res_model,
            'res_id': move.id,
            'environment': environment,
            'request_payload': json.dumps(payload, indent=2, default=str),
            'attempt_no': self.env['fbr.invoice.log'].search_count([
                ('res_model', '=', res_model), ('res_id', '=', move.id),
            ]) + 1,
        }

        if not token:
            log_vals.update(state='failed', error_message='No FBR security token configured for this company.')
            self.env['fbr.invoice.log'].sudo().create(log_vals)
            move.write({'fbr_status': 'failed', 'fbr_last_error': log_vals['error_message']})
            return False

        try:
            response = requests.post(url, data=json.dumps(payload, default=str),
                                      headers=self._headers(token), timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            _logger.warning('FBR submission network error for %s #%s: %s', res_model, move.id, exc)
            log_vals.update(state='failed', error_message=str(exc))
            self.env['fbr.invoice.log'].sudo().create(log_vals)
            move.write({'fbr_status': 'failed', 'fbr_last_error': str(exc)[:255]})
            return False

        # A separate try/except from the one above: requests' own JSONDecodeError is a
        # subclass of RequestException (as well as ValueError), so if this were merged into
        # the try block above it would be swallowed by that handler instead - which never
        # captures response.text, discarding the one thing that would explain why FBR sent
        # back something unparseable (confirmed - that's exactly what happened here).
        try:
            response_json = response.json()
        except ValueError:
            log_vals.update(state='failed', error_message='Non-JSON response from FBR', response_payload=response.text[:5000])
            self.env['fbr.invoice.log'].sudo().create(log_vals)
            move.write({'fbr_status': 'failed', 'fbr_last_error': 'Non-JSON response from FBR'})
            return False

        # Confirmed real shape for validateinvoicedata_sb: {"dated": ..., "validationResponse":
        # {"statusCode": "00", "status": "Valid", "error": "", "invoiceStatuses": [{"itemSNo",
        # "statusCode", "status", "invoiceNo", "errorCode", "error"}]}} - NOT the flat
        # statusCode/errorMessage/result shape PRAL's PDF documents. Production's real shape is
        # NOT yet confirmed, so this checks both the nested and flat forms defensively rather
        # than assuming either.
        validation = response_json.get('validationResponse') or {}
        item_statuses = validation.get('invoiceStatuses') or []
        status_code = validation.get('statusCode') or response_json.get('statusCode')
        status_text = validation.get('status') or response_json.get('status')
        error_message = validation.get('error') or response_json.get('errorMessage') or ''
        result = (response_json.get('result') or response_json.get('invoiceNumber')
                  or (item_statuses[0].get('invoiceNo') if item_statuses else None))
        errors = (response_json.get('errors') or response_json.get('validationErrors')
                  or [s for s in item_statuses if s.get('error')] or None)

        is_success = status_code in (200, '00') or status_text in ('Valid', 'Success')

        log_vals.update(
            response_payload=json.dumps(response_json, indent=2, default=str),
            status_code=status_code,
            error_message=error_message,
            errors=json.dumps(errors, default=str) if errors else False,
            fbr_invoice_number=result if (is_success and result) else False,
        )

        if is_success:
            log_vals['state'] = 'success'
            move.write({'fbr_status': 'success', 'fbr_invoice_number': result or '', 'fbr_last_error': False})
        else:
            log_vals['state'] = 'failed'
            move.write({'fbr_status': 'failed', 'fbr_last_error': (error_message or 'FBR rejected the invoice')[:255]})

        self.env['fbr.invoice.log'].sudo().create(log_vals)
        return log_vals['state'] == 'success'

    def retry_failed_now(self):
        """Public wrapper for manual/on-demand use (Odoo blocks calling underscore-prefixed
        methods remotely) - same logic the cron runs on its own 2-minute interval."""
        return self._cron_retry_failed()

    def _cron_retry_failed(self):
        """FBR provides no server-side retry (invoices must be resubmitted), so this cron
        is what stands between a transient outage and a permanently unreported invoice."""
        stuck_moves = self.env['account.move'].search([
            ('fbr_status', 'in', ('pending', 'failed')),
            ('state', '=', 'posted'),
        ])
        for move in stuck_moves:
            self._submit_invoice(move, 'account.move')
        return len(stuck_moves)

    # ---------------------------------------------------------------- reference-data lookups

    def _get(self, url, token, params=None):
        response = requests.get(url, headers=self._headers(token), params=params, timeout=LOOKUP_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def sync_reference_data(self):
        """Public wrapper - Odoo blocks calling underscore-prefixed methods remotely
        (XML-RPC/JSON-RPC), and the Settings button also needs a callable name."""
        return self._sync_reference_data()

    def _sync_reference_data(self):
        """Bulk-fetch the 6 flat FBR reference lists and upsert them locally, mirroring how
        AxiomSquare's own backend syncs-then-serves (its bundle exposes the same pattern via
        /api/fbr/sync/with-token). Call from Settings > Technical > FBR > Sync Now, or a cron."""
        token = self._get_token_for_lookups()
        if not token:
            raise ValueError('No FBR security token configured - set one in Settings before syncing.')

        data = {key: self._get(url, token) for key, url in REFERENCE_ENDPOINTS.items()}

        self._upsert(self.env['fbr.uom'], data['uom'], 'uoM_ID', {'description': 'description'})
        self._upsert(self.env['fbr.hs.code'], data['hs_codes'], 'hS_CODE', {'description': 'description'}, key_field='code')
        self._upsert(self.env['fbr.province'], data['provinces'], 'stateProvinceCode', {'description': 'stateProvinceDesc'})
        self._upsert(self.env['fbr.transaction.type'], data['transaction_types'], 'transactioN_TYPE_ID', {'description': 'transactioN_DESC'})
        self._upsert(self.env['fbr.doc.type'], data['doc_types'], 'docTypeId', {'description': 'docDescription'})
        self._upsert(self.env['fbr.sro.item'], data['sro_items'], 'srO_ITEM_ID', {'description': 'srO_ITEM_DESC'})

        return {model: len(rows) for model, rows in data.items()}

    def _upsert(self, model, rows, id_field, field_map, key_field='fbr_id'):
        existing = {rec[key_field]: rec for rec in model.search_read([], [key_field, 'description'])}
        to_create = []
        for row in rows:
            key_value = row.get(id_field)
            vals = {key_field: key_value}
            for odoo_field, fbr_field in field_map.items():
                vals[odoo_field] = row.get(fbr_field)
            if key_value in existing:
                if existing[key_value]['description'] != vals.get('description'):
                    model.browse(existing[key_value]['id']).write(vals)
            else:
                to_create.append(vals)
        if to_create:
            model.create(to_create)

    def _fetch_uom_for_hs_code(self, hs_code):
        token = self._get_token_for_lookups()
        rows = self._get(HS_UOM_URL, token, params={'hs_code': hs_code, 'annexure_id': 3})
        self._upsert(self.env['fbr.uom'], rows, 'uoM_ID', {'description': 'description'})
        return [r['uoM_ID'] for r in rows]

    def _fetch_rates_for_sale_type(self, date_str, trans_type_id, province_id):
        token = self._get_token_for_lookups()
        rows = self._get(SALE_TYPE_TO_RATE_URL, token, params={
            'date': date_str, 'transTypeId': trans_type_id, 'originationSupplier': province_id,
        })
        self._upsert(self.env['fbr.tax.rate'], rows, 'ratE_ID', {'description': 'ratE_DESC', 'value': 'ratE_VALUE'})
        return [r['ratE_ID'] for r in rows]

    def _fetch_sro_schedules_for_rate(self, rate_id, date_str, province_id):
        token = self._get_token_for_lookups()
        rows = self._get(SRO_SCHEDULE_URL, token, params={
            'rate_id': rate_id, 'date': date_str, 'origination_supplier_csv': province_id,
        })
        self._upsert(self.env['fbr.sro.schedule'], rows, 'srO_ID', {'description': 'srO_DESC'})
        return [r['srO_ID'] for r in rows]

    def _fetch_sro_items_for_schedule(self, date_str, sro_id):
        token = self._get_token_for_lookups()
        rows = self._get(SRO_ITEM_CASCADE_URL, token, params={'date': date_str, 'sro_id': sro_id})
        self._upsert(self.env['fbr.sro.item'], rows, 'srO_ITEM_ID', {'description': 'srO_ITEM_DESC'})
        return [r['srO_ITEM_ID'] for r in rows]

    def _get_registration_type(self, regno, date_str):
        """Wraps POST /dist/v1/Get_Reg_Type - used from res.partner's 'Check FBR Registration'
        button, matching how AxiomSquare fetches client registration at creation time."""
        token = self._get_token_for_lookups()
        response = requests.post(REG_TYPE_URL, headers=self._headers(token),
                                  json={'regno': regno, 'date': date_str}, timeout=LOOKUP_TIMEOUT)
        response.raise_for_status()
        return response.json()
