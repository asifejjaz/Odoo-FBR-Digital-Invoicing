# Odoo FBR Digital Invoicing

An Odoo 18 addon that connects Invoicing to Pakistan's FBR (Federal Board of Revenue) Digital
Invoicing system — live reference-data sync, cascading field selection on invoice lines, and a
full submission audit trail.

## Why this exists

Most FBR/Odoo connectors on the market are built against PRAL's published Technical
Specification PDF. That document's JSON schema does not match what FBR's live API
(`gw.fbr.gov.pk`) actually accepts — a fact confirmed directly by probing the real endpoints and
comparing responses, not assumed from the documentation. This module is built and verified
against the real, live API: real HS codes (7,800+, synced live), real UoM/province/sale-type/SRO
lists, and a real submission that returned FBR's actual `"status": "Valid"` response.

## What it does

- **Live reference-data sync** — pulls the current UoM, HS code, province, sale type, document
  type, and SRO item lists directly from FBR (`/pdi/v1/...`) rather than shipping a static,
  eventually-stale snapshot.
- **Cascading field selection on invoice lines** — picking an HS Code narrows the UoM dropdown
  to what FBR actually allows for that code (`HS_UOM`); picking a Sale Type narrows the Rate
  dropdown (`SaleTypeToRate`); picking a Rate narrows the SRO Schedule dropdown (`SroSchedule`);
  picking an SRO Schedule narrows the SRO Item dropdown (`SROItem`) — each step is a live call,
  not a static list.
- **Buyer registration lookup** — a button on the customer form that checks FBR's real-time
  registration status (`Get_Reg_Type`) for a given NTN/CNIC.
- **Validation vs. Production toggle** — same payload, same token, switches only the endpoint
  (`validateinvoicedata_sb` for pre-submit checks with no real tax record created, vs. the real
  `PostInvoiceData_v1` for actual filings) — so you can test safely before going live.
- **Full submission audit trail** — every attempt (request JSON, response JSON, status, errors)
  is logged to a dedicated model, with automatic retries for transient failures (FBR's own API
  does not retry on your behalf).

## Installation

1. Clone this repository into your Odoo addons path:
   ```bash
   git clone https://github.com/asifejjaz/Odoo-FBR-Digital-Invoicing.git
   ```
2. Add the cloned folder's parent directory to your `addons_path` in `odoo.conf`, or copy
   `fbr_digital_invoicing_core/` directly into an existing addons folder.
3. Restart Odoo, then in **Apps**, search for **FBR Digital Invoicing** and click **Install**.
   (Dependencies `account` and `product` install automatically.)

## Configuration

1. **Settings → Users & Companies → Companies** — set **FBR Province** on your company record.
   This is required: every rate/SRO lookup needs a seller province to send FBR, and without it
   the cascading fields silently have nothing to narrow.
2. **Settings → Invoicing → FBR Digital Invoicing** — set your **FBR Security Token** (issued by
   FBR/PRAL during registration via IRIS), choose **Validation** or **Production** mode, save,
   then click **Sync Reference Data Now**.
3. On each **Product**, set the FBR HS Code, UoM, Sale Type, and default Rate/SRO on the new
   **FBR Digital Invoicing** tab — these default onto invoice lines and stay overridable there.
4. On each **Contact**, set **NTN/CNIC (FBR)** and use **Check FBR Registration** to verify
   status live.

## Compliance note

This module is a technical connector. It does not make you a licensed FBR integrator — under
FBR's rules, invoice submission must go through a licensed integrator (PRAL, free of cost, or a
private licensed firm). Route this module's requests through your own valid integrator
credentials; consult FBR/PRAL directly or a tax advisor for your specific registration and
compliance obligations.

## License

LGPL-3.0, matching Odoo Community's own license. See [LICENSE](LICENSE).

## Contributing

Issues and pull requests welcome — particularly around FBR schema changes (their live API has
already diverged from their own published documentation once; it will likely happen again) and
POS (`point_of_sale`) integration, which isn't covered by this module yet.
