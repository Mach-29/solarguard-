"""
SolarGuard Monitoring Engine
============================
Scans all systems, detects underperformance, logs alerts,
and (optionally) sends email notifications. This module is
designed to be run as a daily cron job as well as on-demand
from the web UI.
"""
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Tuple

import pandas as pd

from config import (
    DEFAULT_DROP_THRESHOLD, EXPECTED_LOOKBACK_DAYS,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
    ALERT_FROM_EMAIL, SEND_EMAILS, TIERS,
)
from db import (
    load_systems, load_production, load_installers, load_alerts,
    create_alert, mark_alert_sent, get_system_production,
)


# ── Detection ────────────────────────────────────────────────────────
def check_system(system_row: pd.Series, threshold: float = DEFAULT_DROP_THRESHOLD,
                 lookback_days: int = EXPECTED_LOOKBACK_DAYS) -> dict | None:
    """
    Check the most recent production reading for a system.
    Returns an alert dict if underperforming, else None.
    """
    prod = get_system_production(system_row["system_id"])
    if prod.empty:
        return None

    # Use yesterday's reading (today may be partial)
    today = datetime.utcnow().date()
    usable = prod[pd.to_datetime(prod["date"]).dt.date < today]
    if usable.empty:
        return None
    latest = usable.iloc[-1]
    latest_date = pd.to_datetime(latest["date"]).date()

    # Baseline = avg production over lookback window ending 2 days ago
    # (so we don't include recent faults in the baseline)
    window_end = latest_date - timedelta(days=2)
    window_start = window_end - timedelta(days=lookback_days)
    history = usable[
        (pd.to_datetime(usable["date"]).dt.date >= window_start) &
        (pd.to_datetime(usable["date"]).dt.date <= window_end)
    ]
    if history.empty or len(history) < 3:
        # Fall back to system's rated expectation
        expected = system_row["expected_daily_kwh"]
    else:
        expected = history["kwh_produced"].mean()

    actual = latest["kwh_produced"]
    if expected <= 0:
        return None
    drop_pct = (expected - actual) / expected
    if drop_pct > threshold:
        return {
            "system_id": system_row["system_id"],
            "customer_name": system_row["customer_name"],
            "customer_email": system_row["customer_email"],
            "date": latest_date.isoformat(),
            "actual": actual,
            "expected": round(expected, 2),
            "drop_pct": drop_pct,
            "address": system_row.get("address", ""),
            "panel_kw": system_row.get("panel_kw", ""),
        }
    return None


def scan_all_systems(installer_id: str | None = None,
                     threshold: float = DEFAULT_DROP_THRESHOLD) -> list[dict]:
    """Scan every system (optionally filtered by installer). Returns list of findings."""
    systems = load_systems()
    if installer_id:
        systems = systems[systems["installer_id"] == installer_id]
    findings = []
    for _, sys_row in systems.iterrows():
        result = check_system(sys_row, threshold)
        if result:
            findings.append(result)
    return findings


# ── Email delivery ───────────────────────────────────────────────────
def _send_email(to_addr: str, subject: str, html_body: str) -> bool:
    """Send an email via SMTP. Returns True if successful."""
    if not SEND_EMAILS:
        print(f"[EMAIL DISABLED] Would send to {to_addr}: {subject}")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = ALERT_FROM_EMAIL
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(ALERT_FROM_EMAIL, to_addr, msg.as_string())
        return True
    except Exception as e:
        print(f"Email send failed to {to_addr}: {e}")
        return False


def _installer_email(installer: pd.Series, findings: list[dict]) -> Tuple[str, str]:
    subject = f"⚡ SolarGuard Alert: {len(findings)} system(s) underperforming"
    rows = ""
    for f in findings:
        rows += (
            f"<tr><td><b>{f['customer_name']}</b></td>"
            f"<td>{f['date']}</td>"
            f"<td>{f['actual']} kWh</td>"
            f"<td>{f['expected']} kWh</td>"
            f"<td style='color:#c0392b'>-{f['drop_pct']*100:.0f}%</td></tr>"
        )
    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;">
    <h2 style="color:#e67e22;">🔆 SolarGuard Daily Alert</h2>
    <p>Hi {installer['company_name']} team,</p>
    <p>Our monitoring detected <b>{len(findings)}</b> solar system(s) producing
    significantly below expected levels. Proactive outreach is recommended:</p>
    <table border="1" cellpadding="8" cellspacing="0"
           style="border-collapse:collapse;width:100%;">
    <tr style="background:#f4f6f7;"><th>Customer</th><th>Date</th>
    <th>Actual</th><th>Expected</th><th>Drop</th></tr>
    {rows}
    </table>
    <p>Log in to your SolarGuard dashboard to view details and resolve.</p>
    <p style="color:#95a5a6;font-size:12px;">SolarGuard — Proactive Solar Protection</p>
    </body></html>"""
    return subject, html


def _customer_email(finding: dict, installer: pd.Series) -> Tuple[str, str]:
    subject = f"☀️ Quick heads-up about your solar system ({installer['company_name']})"
    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;">
    <h2 style="color:#27ae60;">Hi {finding['customer_name']},</h2>
    <p>We noticed that your solar system produced <b>{finding['actual']} kWh</b>
    on {finding['date']}, which is below the expected
    <b>{finding['expected']} kWh</b> for your {finding['panel_kw']} kW installation.</p>
    <p>This could be due to shading, a dirty panel, or a minor inverter issue.
    Our team at <b>{installer['company_name']}</b> is already aware and will be
    in touch shortly — no need to call us!</p>
    <p>Thanks for trusting us with your solar investment.</p>
    <p style="color:#95a5a6;font-size:12px;">Sent via SolarGuard on behalf of
    {installer['company_name']}</p>
    </body></html>"""
    return subject, html


# ── Full daily run (cron entry point) ────────────────────────────────
def run_daily_check(installer_id: str | None = None,
                    notify_customers: bool = True) -> dict:
    """
    Run the full daily monitoring cycle:
      1. Scan all systems
      2. Log alerts for new underperformances
      3. Email the installer a summary
      4. Optionally email each affected customer
    Returns a summary dict.
    """
    findings = scan_all_systems(installer_id)
    if not findings:
        return {"scanned": 0, "alerts_created": 0, "emails_sent": 0, "findings": []}

    installers_df = load_installers()
    # Group findings by installer
    by_installer: dict[str, list] = {}
    for f in findings:
        systems_df = load_systems()
        sys_row = systems_df[systems_df["system_id"] == f["system_id"]].iloc[0]
        inst_id = sys_row["installer_id"]
        by_installer.setdefault(inst_id, []).append(f)

    alerts_created = 0
    emails_sent = 0
    existing_alerts = load_alerts()

    for inst_id, inst_findings in by_installer.items():
        installer = installers_df[installers_df["installer_id"] == inst_id].iloc[0]
        new_findings = []
        for f in inst_findings:
            # Skip if already an open alert for this system+date
            dup = existing_alerts[
                (existing_alerts["system_id"] == f["system_id"]) &
                (existing_alerts["date_detected"] == f["date"]) &
                (existing_alerts["status"] == "open")
            ]
            if dup.empty:
                create_alert(
                    system_id=f["system_id"],
                    kwh_actual=f["actual"],
                    kwh_expected=f["expected"],
                    drop_pct=f["drop_pct"],
                    message=f"Production dropped {f['drop_pct']*100:.0f}%",
                )
                alerts_created += 1
                new_findings.append(f)

        if new_findings:
            # Email installer summary
            subject, html = _installer_email(installer, new_findings)
            if _send_email(installer["email"], subject, html):
                emails_sent += 1
            # Email each customer (if tier allows)
            tier_info = TIERS.get(installer["tier"], TIERS["Basic"])
            if notify_customers and tier_info["sms_alerts"] is not None:  # all tiers email
                for f in new_findings:
                    c_subject, c_html = _customer_email(f, installer)
                    if _send_email(f["customer_email"], c_subject, c_html):
                        emails_sent += 1
                        # Mark customer notified on the alert
                        al = load_alerts()
                        latest_alert = al[al["system_id"] == f["system_id"]].iloc[-1]
                        mark_alert_sent(latest_alert["alert_id"], customer_notified=True)

    return {
        "scanned": len(load_systems() if installer_id is None else
                       load_systems()[lambda d: d["installer_id"] == installer_id]),
        "alerts_created": alerts_created,
        "emails_sent": emails_sent,
        "findings": findings,
    }


if __name__ == "__main__":
    # CLI usage: python monitor.py [installer_id]
    import sys
    iid = sys.argv[1] if len(sys.argv) > 1 else None
    result = run_daily_check(installer_id=iid)
    print(f"Scan complete: {result['alerts_created']} new alerts, "
          f"{result['emails_sent']} emails sent.")
    for f in result["findings"]:
        print(f"  ⚠ {f['customer_name']}: {f['actual']} vs {f['expected']} kWh "
              f"(-{f['drop_pct']*100:.0f}%)")
