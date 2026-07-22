# 🔆 SolarGuard

**Proactive solar monitoring for small-to-mid installers.** Stop reacting to angry customer calls — catch underperforming panels *before* the homeowner notices on their power bill.

## What It Does

1. **Monitors** daily energy production (kWh) for every system you install.
2. **Detects** when output drops >10% below expected (configurable threshold).
3. **Alerts** both you (the installer) and the homeowner automatically.

## Quick Start

```bash
cd solarguard

# (Recommended) Create a virtual environment
python -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Optional: copy .env.example to .env and fill in SMTP credentials for real emails
cp .env.example .env

# Run the app
streamlit run app.py
```

Then open **http://localhost:8501** in your browser.

**Demo credentials** (pre-seeded with 5 sample systems + 60 days of data):
- Email: `demo@solarguard.app`
- Password: `demo1234`

## Project Structure

```
solarguard/
├── app.py              # Streamlit web UI (dashboard, customers, alerts, settings)
├── monitor.py          # Monitoring engine — run daily via cron
├── db.py               # CSV-based data layer (installers, systems, production, alerts)
├── config.py           # Configuration & environment variables
├── requirements.txt    # Python dependencies
├── .env.example        # Template for SMTP / threshold settings
├── run_daily.sh        # Cron-ready shell script for automatic daily scans
├── README.md
└── data/               # CSV files live here (auto-created on first run)
    ├── installers.csv
    ├── systems.csv
    ├── production.csv
    └── alerts.csv
```

## Pages in the Web UI

| Page | What you can do |
|---|---|
| **📊 Dashboard** | Fleet KPIs, recent alerts, fleet production chart, one-click scan |
| **👥 Customers** | View all systems, add new customers, inspect individual system charts, delete systems |
| **🔔 Alerts** | Filter open/resolved issues, mark as resolved, trigger email send, adjust threshold |
| **📈 Production Data** | Interactive per-system charts, manually log daily readings |
| **⚙️ Settings** | Switch plans (Basic/Pro/Enterprise), configure SMTP, view version info |

## Automatic Daily Alerts (Cron)

To scan automatically every morning at 8 AM:

### Linux / Mac
```bash
crontab -e
```
Add this line (update path to match your install):
```
0 8 * * * cd /home/user/solarguard && ./run_daily.sh >> logs/cron.log 2>&1
```

### Windows
Use **Task Scheduler** to run `run_daily.sh` (or `python monitor.py`) daily at 8 AM.

### Cloud option (no server required)
Deploy to a free tier of **Render**, **Railway**, **Fly.io**, or **Streamlit Community Cloud** and use their built-in scheduled jobs, or set up a free cron at [cron-job.org](https://cron-job.org) that hits a (future) webhook endpoint.

## Enabling Real Emails (Gmail)

1. Enable 2FA on your Gmail account.
2. Create an **App Password** (Google Account → Security → App Passwords).
3. Copy `.env.example` to `.env` and paste the app password into `SMTP_PASSWORD`.
4. Restart the app — emails will send automatically on each daily scan.

Until SMTP is configured, the app runs in "demo mode" and prints email content to the console/log instead of sending.

## Subscription Tiers (Built In)

| Tier | Price | Systems | SMS Alerts | White-Label |
|---|---|---|---|---|
| Basic | $99/mo | Up to 50 | ❌ | ❌ |
| Pro | $299/mo | Up to 200 | ✅ | ✅ |
| Enterprise | Custom | Unlimited | ✅ | ✅ |

## Roadmap Status

- ✅ **Stage 1** — Python monitoring script with CSV data
- ✅ **Stage 2** — Streamlit web form for adding customers
- ✅ **Stage 3** — Automated daily alerts (cron-ready `monitor.py` + shell script)
- ✅ **Stage 4** — Multi-installer authentication (per-installer data isolation)
- ⏳ **Stage 5** — Inverter API integrations (Enphase, SolarEdge, Fronius)
- ⏳ **Stage 6** — Stripe billing

## Tech Stack

- **Backend:** Python 3.10+
- **UI:** Streamlit
- **Data:** Pandas + CSV (easy swap to PostgreSQL/SQLite later)
- **Charts:** Plotly
- **Email:** smtplib (Gmail-compatible, STARTTLS on port 587)
