# Ewash WhatsApp Agent

Minimal echo bot over the Meta Cloud API (v21.0). Receives messages via webhook
and replies `You said: <text>`. This is milestone **v0.1** — proves the loop
end-to-end before we add the LLM brain and booking flow.

## Architecture

```
Customer WhatsApp
      │
      ▼
 Meta Cloud API  ──▶  POST /webhook  (this app on Railway)
      ▲                      │
      └─ send_text ◀─────────┘
```

## Endpoints

| Method | Path       | Purpose                                     |
|--------|------------|---------------------------------------------|
| GET    | `/health`  | Liveness probe for Railway                  |
| GET    | `/webhook` | Meta one-time verification challenge        |
| POST   | `/webhook` | Inbound messages (HMAC-SHA256 verified)     |

## Local dev

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in META_APP_SECRET and META_ACCESS_TOKEN
uvicorn app.main:app --reload
```

Then expose it with ngrok and paste the `/webhook` URL into Meta.

## Deploy to Railway

1. **Push this repo to GitHub** (private recommended)
2. Railway dashboard → **New Project** → **Deploy from GitHub repo**
3. Pick `ewash-agent` repo — Railway auto-detects Nixpacks + Python
4. **Variables** tab → add all keys from `.env.example` (minus `PORT`, Railway sets it)
5. Deploy. Watch logs for `Application startup complete`
6. Settings → **Networking** → **Generate Domain**. Copy e.g. `https://ewash-agent-production.up.railway.app`
7. **Register the webhook in Meta:**
   - developers.facebook.com → `ewash agent` → WhatsApp → **Configuration**
   - Callback URL: `https://<your-railway-domain>/webhook`
   - Verify token: the exact value of `META_VERIFY_TOKEN`
   - Click **Vérifier et enregistrer** — Railway logs should show `webhook verified ✓`
   - Under **Champs de webhook**, subscribe to **messages**
8. From your phone (+212 665 883062), send "hello" to the Meta test number.
   You should get back "You said: hello" within a second.

## Token lifecycle

The token shown in Meta's "Configuration de l'API" expires after **24 hours**.
Once the echo works, create a long-lived System User token:

- business.facebook.com → Paramètres → Utilisateurs système → **Ajouter**
- Role: Admin. Assign the `ewash agent` app with `whatsapp_business_messaging`
  and `whatsapp_business_management` permissions.
- Generate token → **never expires** → paste into Railway's `META_ACCESS_TOKEN`
  → redeploy.

## Logs & debugging

- Railway → **Deploy Logs** and **HTTP Logs** tabs
- `webhook verified ✓` — GET /webhook succeeded
- `inbound text from=212... body=...` — POST handled
- `Meta send failed status=...` — look at the body field Meta returned
- `invalid signature, rejecting` — `META_APP_SECRET` wrong or webhook hit
  from something other than Meta

## Staff booking alerts

The admin portal exposes `/admin/notifications` for the internal WhatsApp alert
sent when a customer confirms a booking. Configure:

- the staff WhatsApp phone number, stored as digits only, e.g. `212665883062`
- the approved template name, e.g. `new_booking_alert`
- the template language, e.g. `fr`

The template body must accept these parameters in order:
`{{1}}` type, `{{2}}` reference, `{{3}}` customer, `{{4}}` phone,
`{{5}}` vehicle, `{{6}}` service, `{{7}}` date/slot, `{{8}}` location,
`{{9}}` price, `{{10}}` note.

## What's next (roadmap)

- [x] **v0.1** Echo bot ← we are here
- [ ] v0.2 Claude as brain — route every message through an LLM with a
  light Ewash system prompt
- [ ] v0.3 Intent router — Flow for bookings, LLM for everything else
- [ ] v0.4 Odoo integration — create quotes / appointments
- [ ] v0.5 Swap test number → `+212 611-204502` via Coexistence
