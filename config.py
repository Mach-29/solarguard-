"""
SolarGuard Configuration
========================
Central settings for the SolarGuard monitoring platform.
Update .env or override values here for your environment.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

INSTALLERS_CSV = DATA_DIR / "installers.csv"
SYSTEMS_CSV = DATA_DIR / "systems.csv"
PRODUCTION_CSV = DATA_DIR / "production.csv"
ALERTS_CSV = DATA_DIR / "alerts.csv"

# ── Monitoring thresholds ────────────────────────────────────────────
# An alert fires when actual production drops below EXPECTED by more
# than this fraction (default 10% = 0.10).
DEFAULT_DROP_THRESHOLD = float(os.getenv("DEFAULT_DROP_THRESHOLD", 0.10))

# Days of history we look at when computing "expected" production.
EXPECTED_LOOKBACK_DAYS = int(os.getenv("EXPECTED_LOOKBACK_DAYS", 14))

# ── Email / SMTP settings (Gmail by default — use an App Password) ──
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ALERT_FROM_EMAIL = os.getenv("ALERT_FROM_EMAIL", SMTP_USER)
SEND_EMAILS = bool(SMTP_USER and SMTP_PASSWORD)  # auto-enable when creds are set

# ── Subscription tiers ───────────────────────────────────────────────
TIERS = {
    "Basic":  {"price": 99,  "max_systems": 50,  "sms_alerts": False, "white_label": False},
    "Pro":    {"price": 299, "max_systems": 200, "sms_alerts": True,  "white_label": True},
    "Enterprise": {"price": None, "max_systems": None, "sms_alerts": True, "white_label": True},
}

# ── Demo / simulation defaults ───────────────────────────────────────
# When generating synthetic production data, panel kW rating is used
# to scale expected daily kWh output (US avg ~4-5 kWh per kW per day).
AVG_KWH_PER_KW_PER_DAY = 4.5
NOISE_STD = 0.08   # ±8% day-to-day noise is normal
