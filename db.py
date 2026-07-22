"""
SolarGuard Database Layer
=========================
Uses CSV files for persistence (per the v1 tech stack).
Each function returns pandas DataFrames and handles file
creation/initialization so the app works out of the box.
"""
import hashlib
import secrets
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    INSTALLERS_CSV, SYSTEMS_CSV, PRODUCTION_CSV, ALERTS_CSV,
    AVG_KWH_PER_KW_PER_DAY, NOISE_STD,
)


# ── Helpers ──────────────────────────────────────────────────────────
def _read_csv(path: Path, columns: list) -> pd.DataFrame:
    """Read a CSV, returning an empty DataFrame with correct cols if missing."""
    if path.exists():
        df = pd.read_csv(path)
        # Ensure all expected columns exist (forward-compatible schema)
        for c in columns:
            if c not in df.columns:
                df[c] = None
        return df[columns]
    return pd.DataFrame(columns=columns)


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False)


def _hash_password(password: str, salt: str | None = None) -> str:
    """SHA-256 hash — fine for a prototype; swap for bcrypt in production."""
    salt = salt or secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${h}"


def _verify_password(password: str, stored: str) -> bool:
    salt, h = stored.split("$", 1)
    return _hash_password(password, salt) == stored


# ── Installers ───────────────────────────────────────────────────────
INSTALLER_COLS = [
    "installer_id", "company_name", "email", "password_hash",
    "tier", "phone", "created_at",
]


def load_installers() -> pd.DataFrame:
    return _read_csv(INSTALLERS_CSV, INSTALLER_COLS)


def save_installers(df: pd.DataFrame) -> None:
    _write_csv(df, INSTALLERS_CSV)


def create_installer(company_name: str, email: str, password: str,
                     tier: str = "Basic", phone: str = "") -> str:
    df = load_installers()
    if email in df["email"].values:
        raise ValueError(f"An account with {email} already exists.")
    installer_id = f"inst_{len(df) + 1:04d}"
    new_row = {
        "installer_id": installer_id,
        "company_name": company_name,
        "email": email,
        "password_hash": _hash_password(password),
        "tier": tier,
        "phone": phone,
        "created_at": datetime.utcnow().isoformat(),
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    save_installers(df)
    return installer_id


def authenticate_installer(email: str, password: str) -> dict | None:
    df = load_installers()
    row = df[df["email"] == email]
    if row.empty:
        return None
    record = row.iloc[0]
    if _verify_password(password, record["password_hash"]):
        return record.to_dict()
    return None


def seed_demo_installer() -> dict:
    """Create a demo installer account if none exists. Returns the installer record dict."""
    df = load_installers()
    if not df.empty:
        row = df.iloc[0]
        return {col: row[col] for col in df.columns}
    inst_id = create_installer(
        company_name="Bright Horizon Solar",
        email="demo@solarguard.app",
        password="demo1234",
        tier="Pro",
        phone="555-0100",
    )
    new_df = load_installers()
    row = new_df[new_df["installer_id"] == inst_id].iloc[0]
    return {col: row[col] for col in new_df.columns}


# ── Systems (solar installations / customers) ────────────────────────
SYSTEM_COLS = [
    "system_id", "installer_id", "customer_name", "customer_email",
    "customer_phone", "address", "panel_kw", "install_date",
    "inverter_brand", "notes", "expected_daily_kwh",
]


def load_systems() -> pd.DataFrame:
    return _read_csv(SYSTEMS_CSV, SYSTEM_COLS)


def save_systems(df: pd.DataFrame) -> None:
    _write_csv(df, SYSTEMS_CSV)


def get_installer_systems(installer_id: str) -> pd.DataFrame:
    return load_systems()[lambda d: d["installer_id"] == installer_id]


def add_system(installer_id: str, customer_name: str, customer_email: str,
               panel_kw: float, address: str = "", customer_phone: str = "",
               inverter_brand: str = "", notes: str = "",
               install_date: str = "") -> str:
    df = load_systems()
    system_id = f"sys_{len(df) + 1:05d}"
    new_row = {
        "system_id": system_id,
        "installer_id": installer_id,
        "customer_name": customer_name,
        "customer_email": customer_email,
        "customer_phone": customer_phone,
        "address": address,
        "panel_kw": panel_kw,
        "install_date": install_date or datetime.utcnow().date().isoformat(),
        "inverter_brand": inverter_brand,
        "notes": notes,
        "expected_daily_kwh": round(panel_kw * AVG_KWH_PER_KW_PER_DAY, 2),
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    save_systems(df)
    return system_id


def delete_system(system_id: str) -> None:
    df = load_systems()
    df = df[df["system_id"] != system_id]
    save_systems(df)
    # Also remove its production data & alerts
    prod = load_production()
    save_production(prod[prod["system_id"] != system_id])
    al = load_alerts()
    save_alerts(al[al["system_id"] != system_id])


def seed_demo_systems(installer_id: str) -> None:
    """Add 5 sample customer systems and ~60 days of synthetic data."""
    sys_df = load_systems()
    if not sys_df[sys_df["installer_id"] == installer_id].empty:
        return
    customers = [
        ("Anderson Family",  "anderson@example.com",  "555-1001", "6.6"),
        ("Martinez Home",    "martinez@example.com",  "555-1002", "8.0"),
        ("Johnson Residence","johnson@example.com",   "555-1003", "5.0"),
        ("Lee Household",    "lee@example.com",       "555-1004", "10.0"),
        ("Patel House",      "patel@example.com",     "555-1005", "7.2"),
    ]
    for name, email, phone, kw in customers:
        add_system(
            installer_id=installer_id,
            customer_name=name,
            customer_email=email,
            customer_phone=phone,
            panel_kw=float(kw),
            address="123 Solar St, Melbourne",
            inverter_brand=np.random.choice(["Enphase", "SolarEdge", "Fronius"]),
            install_date="2024-06-15",
        )
    # Generate production history
    systems = get_installer_systems(installer_id)
    prod_rows = []
    today = datetime.utcnow().date()
    for _, sys_row in systems.iterrows():
        expected = sys_row["expected_daily_kwh"]
        # Introduce a fault on one system (last 5 days at 55% output)
        faulty = sys_row["customer_name"] == "Martinez Home"
        for i in range(60):
            day = today - timedelta(days=59 - i)
            # Weekly seasonal variation + noise
            seasonal = 1.0 + 0.05 * np.sin(2 * np.pi * i / 30)
            noise = np.random.normal(1.0, NOISE_STD)
            actual = expected * seasonal * noise
            if faulty and i >= 55:  # last 5 days underperforming
                actual *= 0.55  # 45% drop — definitely exceeds 10% threshold
            actual = max(0, round(actual, 2))
            prod_rows.append({
                "system_id": sys_row["system_id"],
                "date": day.isoformat(),
                "kwh_produced": actual,
                "kwh_expected": round(expected * seasonal, 2),
            })
    prod_df = pd.DataFrame(prod_rows)
    existing = load_production()
    save_production(pd.concat([existing, prod_df], ignore_index=True))


# ── Production data ──────────────────────────────────────────────────
PROD_COLS = ["system_id", "date", "kwh_produced", "kwh_expected"]


def load_production() -> pd.DataFrame:
    return _read_csv(PRODUCTION_CSV, PROD_COLS)


def save_production(df: pd.DataFrame) -> None:
    _write_csv(df, PRODUCTION_CSV)


def get_system_production(system_id: str) -> pd.DataFrame:
    df = load_production()
    return df[df["system_id"] == system_id].sort_values("date").reset_index(drop=True)


def add_production_reading(system_id: str, date: str, kwh_produced: float,
                           kwh_expected: float | None = None) -> None:
    df = load_production()
    if kwh_expected is None:
        sys_row = load_systems().set_index("system_id").loc[system_id]
        kwh_expected = sys_row["expected_daily_kwh"]
    # Update if exists, else insert
    mask = (df["system_id"] == system_id) & (df["date"] == date)
    if mask.any():
        df.loc[mask, "kwh_produced"] = kwh_produced
        df.loc[mask, "kwh_expected"] = kwh_expected
    else:
        new_row = pd.DataFrame([{
            "system_id": system_id, "date": date,
            "kwh_produced": kwh_produced, "kwh_expected": kwh_expected,
        }])
        df = pd.concat([df, new_row], ignore_index=True)
    save_production(df)


# ── Alerts ───────────────────────────────────────────────────────────
ALERT_COLS = [
    "alert_id", "system_id", "date_detected", "kwh_actual", "kwh_expected",
    "drop_pct", "status", "notified_customer", "notified_installer", "message",
]


def load_alerts() -> pd.DataFrame:
    return _read_csv(ALERTS_CSV, ALERT_COLS)


def save_alerts(df: pd.DataFrame) -> None:
    _write_csv(df, ALERTS_CSV)


def create_alert(system_id: str, kwh_actual: float, kwh_expected: float,
                 drop_pct: float, message: str = "") -> str:
    df = load_alerts()
    alert_id = f"alt_{len(df) + 1:05d}"
    new_row = {
        "alert_id": alert_id,
        "system_id": system_id,
        "date_detected": datetime.utcnow().date().isoformat(),
        "kwh_actual": kwh_actual,
        "kwh_expected": kwh_expected,
        "drop_pct": round(drop_pct * 100, 1),
        "status": "open",
        "notified_customer": False,
        "notified_installer": False,
        "message": message,
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    save_alerts(df)
    return alert_id


def mark_alert_sent(alert_id: str, customer_notified: bool = True) -> None:
    df = load_alerts()
    mask = df["alert_id"] == alert_id
    df.loc[mask, "notified_customer"] = customer_notified
    df.loc[mask, "notified_installer"] = True
    save_alerts(df)


def resolve_alert(alert_id: str) -> None:
    df = load_alerts()
    df.loc[df["alert_id"] == alert_id, "status"] = "resolved"
    save_alerts(df)
