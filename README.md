# LastBite — AI food management & surplus marketplace

A Flask + SQLite prototype with two distinct experiences: **Individual** and **Business**. It uses Gemini for multi-product image scanning, Elasticsearch for optional listing search, and PayPal REST APIs in Sandbox mode.

## Included

- Separate role-based registration, navigation and dashboards.
- SmartScan: Gemini vision extraction for multiple products; expiry dates are only accepted when explicitly evidenced by clear expiry/use-by labels. User review is required before saving.
- Personal fridge and structured business inventory stored in SQLite.
- Business surplus listings with quantity, original/sale price, date and pickup information.
- Rule-based discount suggestions using confirmed date proximity. This is a prototype heuristic, **not** a trained demand-prediction model.
- Preferences and listing recommendations; optional Elasticsearch search with SQLite fallback.
- PayPal Sandbox order creation/capture, completed payment records, refund endpoint, donation checkout and PayPal subscription plan checkout.

## Run locally

Requires Python 3.10+.

```bash
# Windows PowerShell
py -m venv .venv
.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

```bash
# macOS / Linux / WSL
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and add the API credentials you want to test. Then run:

```bash
python app.py
```

Open http://127.0.0.1:5000. Register one Individual account and one Business account to test both dashboards. The SQLite database is created automatically in `data/lastbite.db`.

## Gemini setup

1. Create an API key in Google AI Studio.
2. Add it to `GEMINI_API_KEY` in `.env`.
3. Set `GEMINI_MODEL` to a vision-capable model available to your AI Studio project.

The scanner requires `google-genai`. Without a key, it returns a clear configuration error; manual inventory entry still works. The model is instructed not to infer expiry dates from manufacturing/packing dates or ambiguous date strings. Always review scan results.

## PayPal Sandbox setup

1. Create a REST app in the PayPal Developer Dashboard Sandbox.
2. Put the Sandbox Client ID and Secret in `.env` as `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET`.
3. Keep `PAYPAL_MODE=sandbox` and choose a currency supported by the Sandbox account.
4. Use a PayPal Sandbox buyer account to approve checkout.

The app calculates listing amounts on the server, captures payment after PayPal returns to `/payments/return`, and only marks orders complete after successful capture. Refunds call the PayPal capture-refund API.

### Important PayPal limitations

- This prototype uses a **single platform merchant integration**. It does not automatically split funds or pay independent sellers.
- Marketplace seller payouts / multiparty payments generally require PayPal partner approval, seller onboarding and the appropriate product access. The current Business Hub can track orders and sales but does not perform real seller payouts.
- Subscription checkout requires PayPal billing plans created in the merchant account. Set `PAYPAL_PLUS_PLAN_ID` and `PAYPAL_FAMILY_PLAN_ID` after creating those plans. PayPal subscription availability and supported currencies depend on merchant-country eligibility.
- Donation flow is a simple one-time payment to the configured platform merchant. Production requires a verified recipient/charity and a proper donation record/receipt process.
- The app is a hackathon prototype. Before production, add CSRF protection, rate limiting, email verification, robust webhook verification/idempotency, seller verification, tax/food-safety compliance, refund policy enforcement, and production secret management.

## AI pricing / surplus prediction status

The current AI Insights screen uses a transparent date-proximity heuristic on **confirmed dates only** (up to 1 day: 35%; 2 days: 25%; 3–4 days: 15%). It does not claim to predict future surplus from sales history yet. To implement a genuine model, collect consented historical stock, sales, waste and seasonality data, then train and evaluate a demand/surplus forecasting model. Never auto-publish a discount without seller approval.

## Project structure

```text
LastBite/
├── app.py
├── services/
│   ├── gemini_service.py
│   ├── elastic_service.py
│   └── paypal_service.py
├── templates/              # public, auth, individual and business views
├── static/css/app.css
├── static/js/               # scanner, checkout and order actions
├── data/                    # SQLite database created at runtime
├── .env.example
├── requirements.txt
└── LICENSE
```
