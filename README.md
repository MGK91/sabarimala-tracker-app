# Sabarimala Route Risk Poller + PWA + WhatsApp

Comprehensive risk monitoring for the **Chennai → Sabarimala** pilgrimage route. 
Polls 7 sources, aggregates district and route-point level risk, and alerts via Telegram/WhatsApp.

## Route Monitored

```
Chennai → Theni → Bodinayakanur → Kumily → Vandiperiyar → Gavi Pass → Erumely → Pamba → Sabarimala Temple
     ↑ Tamil Nadu                ↑ Kerala (Western Ghats)                    ↑ Sabarimala
```

## Features

- 🗺️ **Interactive Route Map** — Dark Leaflet map with all 9 route points, colour-coded by risk, dashed trail line
- 📍 **Route Tab** — Ordered list of all points with per-point rainfall (Chennai → Temple)
- 📊 **District Dashboard** — 5 districts with 24h/3d/7d rainfall + landslide risk badge
- 🤖 **Telegram** — Instant push alerts
- 💬 **WhatsApp** — Meta Cloud API, webhook relay, or click-to-chat
- 🌊 **7 Data Sources** — Sachet/NDMA, IMD (3 pages), GSI Bhusanket, Kerala SDMA, INCOIS, CWC, Open-Meteo

## Architecture

```
GitHub Actions (hourly)
        │
        ▼
   ┌─────────┐    ┌──────────┐    ┌─────────┐
   │ Sachet  │    │   IMD    │    │  GSI    │
   │  NDMA   │    │Warnings  │    │Bhusanket│
   └────┬────┘    │Nowcast   │    └────┬────┘
        │         │Subdiv    │         │
        │         └────┬─────┘         │
        │              │               │
   ┌────┴──────────────┴───────────────┴────┐
   │           poller.py (Python)            │
   │  • District aggregation                 │
   │  • Route point rainfall                 │
   │  • Landslide risk scoring               │
   │  • Level transition detection           │
   └────┬───────────────────────────────────┘
        │
   ┌────┴────┐    ┌─────────┐    ┌─────────┐
   │Telegram │    │WhatsApp │    │ ntfy.sh │
   └─────────┘    └─────────┘    └─────────┘
        │
        ▼
   state.json (committed to repo)
        │
        ▼
   GitHub Pages ──▶ PWA Dashboard
```

## Data Sources

| Source | What it provides | Coverage |
|--------|-----------------|----------|
| **Sachet (NDMA)** | CAP/XML disaster alerts | National, district-tagged |
| **IMD** | District warnings + nowcast + subdivision warnings | Kerala, Tamil Nadu |
| **GSI Bhusanket** | Landslide bulletins | ~21 districts incl. Idukki |
| **Kerala SDMA** | Daily bulletins + landslide alerts | Kerala |
| **INCOIS** | Coastal swell / Kallakkadal warnings | Kerala coast |
| **CWC** | River level / flood forecasting | National rivers |
| **Open-Meteo** | 7-day rainfall forecast per lat/lon | Any point globally |

## Risk Model

### Rainfall Triggers (Western Ghats landslide thresholds)

| Period | Threshold | Alert |
|--------|-----------|-------|
| 24h | ≥ 115 mm | 🔴 Red |
| 3-day | ≥ 200 mm | 🔴 Red |
| 7-day | ≥ 350 mm | 🔴 Red |
| 24h | ≥ 80 mm | 🟠 Orange |
| 3-day | ≥ 140 mm | 🟠 Orange |

### Landslide Risk

Computed per district based on rainfall + external alerts:
- **Low** — No triggers, no external warnings
- **Moderate** — Orange rainfall or external warning
- **High** — Red rainfall or landslide-specific alert from GSI/Kerala SDMA

### Escalation

- 🟢 → 🟠: One alert, "Risk elevated"
- 🟠 → 🔴: One alert, "🚨 DECIDE BY TONIGHT"
- De-duplicated: Same source+district+level within 30 min = suppressed

## Quick Start

### 1. Fork / create repo

Push all files to a new GitHub repository.

### 2. Configure secrets

**Settings → Secrets and variables → Actions → New repository secret**

| Secret | Required | How to get |
|--------|----------|-----------|
| `TELEGRAM_BOT_TOKEN` | Optional* | [@BotFather](https://t.me/botfather) → `/newbot` |
| `TELEGRAM_CHAT_ID` | Optional* | [@userinfobot](https://t.me/userinfobot) |
| `WHATSAPP_ACCESS_TOKEN` | Optional* | [developers.facebook.com](https://developers.facebook.com) → WhatsApp → API Setup |
| `WHATSAPP_PHONE_NUMBER_ID` | Optional* | Same page → "Phone Number ID" |

*At least one channel recommended. ntfy.sh works with zero secrets.

### 3. Configure `config.yaml`

Edit in your repo. Key fields:

```yaml
# WhatsApp
whatsapp:
  enabled: true
  mode: "cloud_api"          # or "webhook_relay" or "click_to_chat"
  access_token: "${WHATSAPP_ACCESS_TOKEN}"
  phone_number_id: "${WHATSAPP_PHONE_NUMBER_ID}"
  recipient_phone: "919876543210"   # ← hardcode your number

# Route points (already configured for Chennai → Sabarimala)
route_points:
  - name: "Chennai"
    lat: 13.0827
    lon: 80.2707
    district: "Chennai"
    state: "Tamil Nadu"
    type: "city"
  # ... (9 points total, see config.yaml)
```

### 4. Enable GitHub Pages

**Settings → Pages** → Source: Deploy from a branch → `main` → `/pwa`

Dashboard: `https://YOURUSER.github.io/REPO/pwa/`

### 5. Run manually

**Actions → Sabarimala Route Risk Poller → Run workflow**

## PWA Dashboard

Four tabs:

| Tab | Content |
|-----|---------|
| **Dashboard** | 5 district cards with 24h/3d/7d rainfall bars, landslide risk badge, threshold progress |
| **Route** | Ordered Chennai→Temple list with per-point 24h rainfall and type icons |
| **Map** | Dark Leaflet with all 9 points, colour-coded pins, dashed trail line, popup details |
| **Alerts** | Full alert history from all 7 sources, severity colour-coded |

### Install as App

- **Android Chrome**: Menu → "Add to Home screen"
- **iOS Safari**: Share → "Add to Home Screen"

## WhatsApp Setup

### Option A: Meta Cloud API (Recommended)

1. [developers.facebook.com](https://developers.facebook.com) → Create App → Business → WhatsApp
2. API Setup → copy **Access Token** + **Phone Number ID**
3. Add your phone number to "To" field (must have WhatsApp installed)
4. Add secrets to GitHub, set `mode: "cloud_api"`

> Test numbers can only message verified numbers. For production messaging, apply for Business Verification.

### Option B: Webhook Relay

Deploy a small relay (Node.js/Express on Render/Railway):

```javascript
app.post('/send', async (req, res) => {
  const { phone, message, secret } = req.body;
  if (secret !== process.env.WEBHOOK_SECRET) return res.sendStatus(403);
  await sendWhatsApp(phone, message);  // Your WhatsApp sending logic
  res.sendStatus(200);
});
```

Set `mode: "webhook_relay"` and `webhook_url: "https://your-relay.com/send"`.

### Option C: Click-to-Chat (Zero setup)

```yaml
whatsapp:
  enabled: true
  mode: "click_to_chat"
  click_to_chat_number: "919876543210"
```

Generates `wa.me` URLs in GitHub Actions logs. No API needed.

## Customisation

### Add a route point

Edit `config.yaml`:

```yaml
route_points:
  - name: "YourTown"
    lat: 9.5
    lon: 77.0
    district: "Idukki"
    state: "Kerala"
    type: "town"   # city | town | base | temple | pass | river
```

Then add to `app.js` → `routeOrder` array for display order.

### Change thresholds

```yaml
thresholds:
  daily_max: 115
  three_day_max: 200
  seven_day_max: 350
```

### Disable a source

```yaml
sources:
  incois:
    enabled: false
```

## File Structure

```
.
├── .github/workflows/poll.yml
├── poller.py              # Main: 7 sources, aggregation, notifications
├── config.yaml            # Route points, thresholds, secrets mapping
├── state.json             # Persisted state (committed each run)
├── requirements.txt
├── pwa/
│   ├── index.html         # 4-tab dashboard
│   ├── app.js             # Tabs, map, route list, charts
│   ├── sw.js              # Service worker (offline)
│   ├── manifest.json      # PWA manifest
│   └── data.json          # Generated by poller
└── README.md
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| WhatsApp 403/401 | Token expired. Regenerate at Meta Developers Console |
| WhatsApp "recipient not allowed" | Test numbers only message verified numbers. Add yours in Meta Console |
| Map blank offline | Visit once online — Leaflet CDN cached by SW |
| No IMD alerts | IMD pages are scraped; if layout changes, alerts may lag. Open-Meteo provides independent signal |
| GSI no alerts | GSI portal is change-detected; only alerts when content updates |
| No alerts at all | Check Open-Meteo lat/lon values; verify at least one source `enabled: true` |

## License

MIT — decision-support tool. Always follow directives from NDMA, IMD, Kerala SDMA, and local authorities.
