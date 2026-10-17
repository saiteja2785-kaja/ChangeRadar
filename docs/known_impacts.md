# Known impacts (answer key, never given to the agent)

- invoice_service/invoice.py: calculate_total and format_invoice_line treat price as rupees. High risk.
- checkout_service/checkout.py: shipping_fee uses calculate_total with a rupee threshold of 500, so shipping is always free. Indirect, high risk.
- checkout_service/checkout.py: checkout_summary passes price straight through to the UI. Medium risk.
- Tests: no invoice or checkout test checks the unit. Coverage gap.
- api/schema.md was updated to say paise, so the contract is the evidence.