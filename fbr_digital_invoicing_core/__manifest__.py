{
    'name': 'FBR Digital Invoicing - Core',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'PRAL Digital Invoicing (FBR) API integration - shared core',
    'description': """
FBR Digital Invoicing Core
===========================
Field definitions, live reference-data sync (UoM/HS codes/provinces/sale
types/doc types/SRO items via gw.fbr.gov.pk), the cascading lookup chain
(HS code -> UoM, sale type -> rate, rate -> SRO schedule, SRO schedule ->
SRO item), API client, and submission log for FBR's Digital Invoicing
system (PRAL).

Field/endpoint names match FBR's live API as directly confirmed against a
real working integration - NOT the older numeric-coded schema documented
in PRAL's Technical Specification PDF, which does not match what FBR's
API actually accepts.

Reference-data lists are NOT seeded as static XML data (they're FBR-
maintained and change over time) - use Settings > Invoicing > FBR Digital
Invoicing > Sync Reference Data Now after setting a security token.
    """,
    'depends': ['account', 'product'],
    'data': [
        'security/ir.model.access.csv',
        'data/fbr_cron.xml',
        'views/product_template_views.xml',
        'views/res_partner_views.xml',
        'views/res_company_views.xml',
        'views/account_move_views.xml',
        'views/fbr_invoice_log_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
