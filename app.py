"""
SolarGuard — Streamlit Web Application
======================================
A B2B SaaS dashboard for solar installers to proactively monitor
customer systems. Run with:  streamlit run app.py
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import TIERS, DEFAULT_DROP_THRESHOLD, SEND_EMAILS, DATA_DIR
from db import (
    seed_demo_installer, seed_demo_systems,
    load_installers, save_installers, create_installer, authenticate_installer,
    load_systems, add_system, delete_system, get_installer_systems,
    load_production, get_system_production, add_production_reading,
    load_alerts, resolve_alert,
)
from monitor import scan_all_systems, run_daily_check, check_system


# ── Page config ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="SolarGuard — Proactive Solar Monitoring",
    page_icon="🔆",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Session state initialization ─────────────────────────────────────
def init_session():
    if "installer" not in st.session_state:
        st.session_state.installer = None
    # Ensure demo data exists
    demo = seed_demo_installer()
    seed_demo_systems(demo["installer_id"])


init_session()


# ── Styling ──────────────────────────────────────────────────────────
st.markdown("""
<style>
    .block-container {padding-top: 1.5rem;}
    .big-number {font-size:2.2rem; font-weight:700; margin:0;}
    .metric-label {color:#7f8c8d; font-size:0.9rem; text-transform:uppercase; letter-spacing:1px;}
    .alert-banner {background:#fdecea; border-left:4px solid #e74c3c; padding:1rem;
                   border-radius:0.3rem; margin-bottom:1rem;}
    .ok-banner {background:#e8f8f5; border-left:4px solid #27ae60; padding:1rem;
                border-radius:0.3rem; margin-bottom:1rem;}
    .hero {background:linear-gradient(135deg,#f39c12 0%,#e67e22 100%);
           padding:2rem; border-radius:0.5rem; color:white; margin-bottom:1.5rem;}
    .hero h1 {color:white; margin:0 0 0.5rem 0;}
    .hero p {margin:0; opacity:0.95; font-size:1.1rem;}
</style>
""", unsafe_allow_html=True)


# ── Sidebar / Auth ───────────────────────────────────────────────────
def render_sidebar():
    with st.sidebar:
        st.image("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><circle cx='50' cy='50' r='45' fill='%23f39c12'/><text x='50' y='65' font-size='50' text-anchor='middle' fill='white'>☀</text></svg>", width=80)
        st.markdown("## 🔆 SolarGuard")
        st.caption("Proactive Solar Monitoring")

        if st.session_state.installer:
            inst = st.session_state.installer
            st.success(f"Logged in as:\n**{inst['company_name']}**")
            tier_badge = {"Basic": "🔵 Basic", "Pro": "🟣 Pro", "Enterprise": "🟠 Enterprise"}
            st.caption(tier_badge.get(inst["tier"], inst["tier"]))
            st.divider()
            nav = st.radio("Navigation",
                           ["📊 Dashboard", "👥 Customers", "🔔 Alerts",
                            "📈 Production Data", "⚙️ Settings"],
                           label_visibility="collapsed")
            if st.button("🚪 Log Out", use_container_width=True):
                st.session_state.installer = None
                st.rerun()
            return nav
        else:
            st.divider()
            tab_login, tab_signup = st.tabs(["Log In", "Sign Up"])
            with tab_login:
                email = st.text_input("Email", key="login_email")
                password = st.text_input("Password", type="password", key="login_pw")
                if st.button("Log In", type="primary", use_container_width=True):
                    inst = authenticate_installer(email, password)
                    if inst:
                        st.session_state.installer = inst
                        st.rerun()
                    else:
                        st.error("Invalid email or password.")
                st.caption("Demo: `demo@solarguard.app` / `demo1234`")
            with tab_signup:
                company = st.text_input("Company Name")
                email2 = st.text_input("Email", key="signup_email")
                password2 = st.text_input("Password", type="password", key="signup_pw")
                tier = st.selectbox("Plan", ["Basic", "Pro"],
                                    format_func=lambda t: f"{t} — ${TIERS[t]['price']}/mo")
                if st.button("Create Account", type="primary", use_container_width=True):
                    if company and email2 and password2:
                        try:
                            inst_id = create_installer(company, email2, password2, tier)
                            st.success("Account created! Log in above.")
                        except ValueError as e:
                            st.error(str(e))
                    else:
                        st.warning("Please fill in all fields.")
            return None


# ── Dashboard page ───────────────────────────────────────────────────
def page_dashboard():
    inst = st.session_state.installer
    systems = get_installer_systems(inst["installer_id"])
    alerts = load_alerts()
    sys_alerts = alerts[alerts["system_id"].isin(systems["system_id"])]
    open_alerts = sys_alerts[sys_alerts["status"] == "open"]

    st.markdown(f"""
    <div class="hero">
        <h1>Welcome back, {inst['company_name']} 👋</h1>
        <p>Here's the health of your solar fleet as of {datetime.utcnow().strftime('%B %d, %Y')}.</p>
    </div>""", unsafe_allow_html=True)

    # KPI cards
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f'<p class="metric-label">Systems Monitored</p><p class="big-number">{len(systems)}</p>',
                    unsafe_allow_html=True)
    with c2:
        total_kw = systems["panel_kw"].sum() if not systems.empty else 0
        st.markdown(f'<p class="metric-label">Total Capacity (kW)</p><p class="big-number">{total_kw:.1f}</p>',
                    unsafe_allow_html=True)
    with c3:
        color = "#e74c3c" if len(open_alerts) > 0 else "#27ae60"
        st.markdown(f'<p class="metric-label">Open Alerts</p><p class="big-number" style="color:{color}">{len(open_alerts)}</p>',
                    unsafe_allow_html=True)
    with c4:
        # Today's fleet production
        prod = load_production()
        if not prod.empty and not systems.empty:
            fleet_prod = prod[prod["system_id"].isin(systems["system_id"])]
            last_date = fleet_prod["date"].max()
            today_total = fleet_prod[fleet_prod["date"] == last_date]["kwh_produced"].sum()
        else:
            today_total = 0
        st.markdown(f'<p class="metric-label">Latest Day (kWh)</p><p class="big-number">{today_total:.0f}</p>',
                    unsafe_allow_html=True)

    st.divider()

    # Quick scan button
    col_a, col_b = st.columns([2, 1])
    with col_a:
        st.subheader("🔍 Run Health Scan")
        st.caption("Check all systems right now for underperformance.")
    with col_b:
        if st.button("🚨 Run Scan Now", type="primary", use_container_width=True):
            with st.spinner("Scanning systems..."):
                findings = scan_all_systems(inst["installer_id"])
            if findings:
                st.session_state.last_findings = findings
                st.warning(f"Found {len(findings)} underperforming system(s). See Alerts page.")
            else:
                st.success("✅ All systems performing within healthy range.")

    if SEND_EMAILS:
        st.caption("📧 Email alerts are enabled — customers and installers will be notified automatically.")
    else:
        st.caption("📧 Email alerts are currently in demo mode — add SMTP credentials in `.env` to enable sending.")

    # Alerts preview
    st.subheader("Recent Open Alerts")
    if open_alerts.empty:
        st.markdown('<div class="ok-banner">✅ No open alerts — all systems healthy!</div>',
                    unsafe_allow_html=True)
    else:
        alert_rows = []
        for _, a in open_alerts.iterrows():
            sys_row = systems[systems["system_id"] == a["system_id"]]
            cname = sys_row.iloc[0]["customer_name"] if not sys_row.empty else a["system_id"]
            alert_rows.append({
                "Customer": cname,
                "Detected": a["date_detected"],
                "Actual": f"{a['kwh_actual']} kWh",
                "Expected": f"{a['kwh_expected']} kWh",
                "Drop": f"-{a['drop_pct']}%",
            })
        st.dataframe(pd.DataFrame(alert_rows), use_container_width=True, hide_index=True)

    # Fleet production chart (last 30 days)
    st.subheader("Fleet Production — Last 30 Days")
    prod = load_production()
    if not prod.empty and not systems.empty:
        fleet = prod[prod["system_id"].isin(systems["system_id"])].copy()
        fleet["date"] = pd.to_datetime(fleet["date"])
        last30 = fleet[fleet["date"] >= fleet["date"].max() - timedelta(days=30)]
        daily = last30.groupby("date")["kwh_produced"].sum().reset_index()
        fig = px.area(daily, x="date", y="kwh_produced",
                      labels={"kwh_produced": "Total kWh", "date": "Date"},
                      color_discrete_sequence=["#f39c12"])
        fig.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No production data yet. Add systems and log readings on the Production Data page.")


# ── Customers page ───────────────────────────────────────────────────
def page_customers():
    inst = st.session_state.installer
    systems = get_installer_systems(inst["installer_id"])
    tier_info = TIERS[inst["tier"]]
    max_sys = tier_info["max_systems"] if tier_info["max_systems"] else "∞"

    st.title("👥 Customer Systems")
    st.caption(f"Plan: {inst['tier']} — {len(systems)}/{max_sys} systems used")

    tab_view, tab_add = st.tabs(["📋 View Systems", "➕ Add New System"])

    with tab_view:
        if systems.empty:
            st.info("No systems yet. Add your first customer system →")
        else:
            # Summary table
            display = systems[[
                "customer_name", "customer_email", "customer_phone",
                "panel_kw", "install_date", "inverter_brand", "address", "system_id",
            ]].rename(columns={
                "customer_name": "Customer", "customer_email": "Email",
                "customer_phone": "Phone", "panel_kw": "Size (kW)",
                "install_date": "Install Date", "inverter_brand": "Inverter",
                "address": "Address", "system_id": "ID",
            })
            st.dataframe(display, use_container_width=True, hide_index=True)

            st.divider()
            st.subheader("System Details")
            selected_name = st.selectbox("Select a customer to view details",
                                         systems["customer_name"].tolist())
            sel = systems[systems["customer_name"] == selected_name].iloc[0]

            cc1, cc2, cc3 = st.columns(3)
            with cc1:
                st.markdown(f"**Customer:** {sel['customer_name']}")
                st.markdown(f"**Email:** {sel['customer_email']}")
                st.markdown(f"**Phone:** {sel['customer_phone']}")
            with cc2:
                st.markdown(f"**System Size:** {sel['panel_kw']} kW")
                st.markdown(f"**Expected Daily:** {sel['expected_daily_kwh']} kWh")
                st.markdown(f"**Inverter:** {sel['inverter_brand']}")
            with cc3:
                st.markdown(f"**Install Date:** {sel['install_date']}")
                st.markdown(f"**Address:** {sel['address']}")
                if sel["notes"]:
                    st.markdown(f"**Notes:** {sel['notes']}")

            # Mini chart
            sprod = get_system_production(sel["system_id"])
            if not sprod.empty:
                sprod["date"] = pd.to_datetime(sprod["date"])
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=sprod["date"], y=sprod["kwh_expected"],
                                         name="Expected", line=dict(dash="dash", color="#95a5a6")))
                fig.add_trace(go.Bar(x=sprod["date"], y=sprod["kwh_produced"],
                                     name="Actual", marker_color="#f39c12"))
                fig.update_layout(title=f"{sel['customer_name']} — Daily Production",
                                  height=300, margin=dict(l=20, r=20, t=40, b=20),
                                  yaxis_title="kWh")
                st.plotly_chart(fig, use_container_width=True)

            if st.button("🗑️ Delete This System", type="secondary"):
                delete_system(sel["system_id"])
                st.warning("System deleted.")
                st.rerun()

    with tab_add:
        if tier_info["max_systems"] and len(systems) >= tier_info["max_systems"]:
            st.error(f"You've reached your plan limit ({max_sys} systems). Upgrade to Pro for 200.")
        else:
            with st.form("add_system_form"):
                st.subheader("Add New Customer System")
                c1, c2 = st.columns(2)
                with c1:
                    c_name = st.text_input("Customer Name *")
                    c_email = st.text_input("Customer Email *")
                    c_phone = st.text_input("Customer Phone")
                    c_addr = st.text_input("Install Address")
                with c2:
                    c_kw = st.number_input("System Size (kW) *", min_value=1.0,
                                           max_value=100.0, value=6.6, step=0.1)
                    c_inv = st.selectbox("Inverter Brand",
                                         ["Enphase", "SolarEdge", "Fronius",
                                          "SMA", "Huawei", "Other"])
                    c_date = st.date_input("Install Date", value=datetime.utcnow())
                c_notes = st.text_area("Notes")
                submitted = st.form_submit_button("➕ Add System", type="primary")
                if submitted:
                    if not c_name or not c_email:
                        st.error("Customer name and email are required.")
                    else:
                        sid = add_system(
                            installer_id=inst["installer_id"],
                            customer_name=c_name,
                            customer_email=c_email,
                            customer_phone=c_phone,
                            panel_kw=c_kw,
                            address=c_addr,
                            inverter_brand=c_inv,
                            install_date=c_date.isoformat(),
                            notes=c_notes,
                        )
                        st.success(f"✅ System added for {c_name} ({sid})")
                        st.rerun()


# ── Alerts page ──────────────────────────────────────────────────────
def page_alerts():
    inst = st.session_state.installer
    systems = get_installer_systems(inst["installer_id"])
    alerts = load_alerts()
    sys_alerts = alerts[alerts["system_id"].isin(systems["system_id"])].copy()

    st.title("🔔 Alerts & Issues")
    st.caption("Systems producing below threshold are flagged here so you can reach out proactively.")

    col1, col2 = st.columns([1, 3])
    with col1:
        status_filter = st.selectbox("Filter by status", ["All", "Open", "Resolved"], index=1)
    with col2:
        threshold = st.slider("Underperformance threshold",
                              min_value=5, max_value=30, value=int(DEFAULT_DROP_THRESHOLD*100),
                              step=1, format="%d %%") / 100

    if status_filter != "All":
        sys_alerts = sys_alerts[sys_alerts["status"] == status_filter.lower()]

    open_count = len(alerts[(alerts["system_id"].isin(systems["system_id"])) &
                            (alerts["status"] == "open")])

    if open_count > 0:
        st.markdown(f'<div class="alert-banner"><b>⚠️ {open_count} open alert(s)</b> — '
                    f'Customers may be experiencing underperformance. We recommend reaching out today.</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<div class="ok-banner">✅ All alerts resolved. Fleet is healthy.</div>',
                    unsafe_allow_html=True)

    if st.button("📨 Send Daily Alert Emails Now", type="primary"):
        with st.spinner("Running daily check and sending emails..."):
            result = run_daily_check(installer_id=inst["installer_id"])
        st.success(f"Done — {result['alerts_created']} new alerts, {result['emails_sent']} emails sent.")
        st.rerun()

    st.divider()

    if sys_alerts.empty:
        st.info("No alerts match your filter.")
        return

    # Render each alert as a card
    sys_alerts = sys_alerts.sort_values("date_detected", ascending=False)
    for _, a in sys_alerts.iterrows():
        sys_row = systems[systems["system_id"] == a["system_id"]]
        cname = sys_row.iloc[0]["customer_name"] if not sys_row.empty else a["system_id"]
        cemail = sys_row.iloc[0]["customer_email"] if not sys_row.empty else ""

        status_color = "#e74c3c" if a["status"] == "open" else "#27ae60"
        with st.container(border=True):
            hcol1, hcol2, hcol3 = st.columns([3, 1, 1])
            with hcol1:
                st.markdown(f"### {'🔴' if a['status']=='open' else '🟢'} {cname}")
                st.caption(f"Detected {a['date_detected']} • {cemail}")
            with hcol2:
                st.metric("Drop", f"-{a['drop_pct']}%", delta=None)
            with hcol3:
                st.metric("Actual vs Expected",
                          f"{a['kwh_actual']} / {a['kwh_expected']} kWh")
            if a["message"]:
                st.caption(f"Note: {a['message']}")
            notified = []
            if a["notified_installer"]:
                notified.append("Installer ✉️")
            if a["notified_customer"]:
                notified.append("Customer ✉️")
            if notified:
                st.caption("Notified: " + ", ".join(notified))
            if a["status"] == "open":
                if st.button("✅ Mark Resolved", key=f"resolve_{a['alert_id']}"):
                    resolve_alert(a["alert_id"])
                    st.success("Alert resolved.")
                    st.rerun()


# ── Production Data page ─────────────────────────────────────────────
def page_production():
    inst = st.session_state.installer
    systems = get_installer_systems(inst["installer_id"])

    st.title("📈 Production Data")
    st.caption("View and log daily energy production readings per system.")

    tab_view, tab_log = st.tabs(["📊 View & Chart", "✏️ Log Reading"])

    with tab_view:
        if systems.empty:
            st.info("Add customer systems first.")
            return
        selected = st.selectbox("Select system", systems["customer_name"].tolist(), key="view_sel")
        sel = systems[systems["customer_name"] == selected].iloc[0]
        prod = get_system_production(sel["system_id"])

        if prod.empty:
            st.warning("No production data logged for this system yet.")
        else:
            prod["date"] = pd.to_datetime(prod["date"])
            # Stats
            avg_actual = prod["kwh_produced"].mean()
            avg_expected = prod["kwh_expected"].mean()
            perf = (avg_actual / avg_expected * 100) if avg_expected else 0
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Avg Daily Production", f"{avg_actual:.1f} kWh")
            c2.metric("Expected", f"{avg_expected:.1f} kWh")
            c3.metric("Performance Ratio", f"{perf:.0f}%")
            c4.metric("Days Logged", str(len(prod)))

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=prod["date"], y=prod["kwh_expected"],
                                     name="Expected", line=dict(dash="dash", color="#95a5a6")))
            # Color bars by health
            colors = ["#27ae60" if a >= e * (1 - DEFAULT_DROP_THRESHOLD) else "#e74c3c"
                      for a, e in zip(prod["kwh_produced"], prod["kwh_expected"])]
            fig.add_trace(go.Bar(x=prod["date"], y=prod["kwh_produced"],
                                 name="Actual", marker_color=colors))
            fig.update_layout(title=f"{selected} — Daily kWh (red = below threshold)",
                              height=400, yaxis_title="kWh",
                              margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig, use_container_width=True)

            with st.expander("📋 Raw Data"):
                st.dataframe(prod.sort_values("date", ascending=False),
                             use_container_width=True, hide_index=True)

    with tab_log:
        with st.form("log_reading"):
            st.subheader("Log a Production Reading")
            l1, l2, l3 = st.columns(3)
            with l1:
                sys_names = systems["customer_name"].tolist()
                pick = st.selectbox("Customer System", sys_names)
            with l2:
                rdate = st.date_input("Date", value=datetime.utcnow() - timedelta(days=1))
            with l3:
                kwh = st.number_input("kWh Produced", min_value=0.0, step=0.1, value=20.0)
            note = st.caption("This simulates a reading you'd eventually receive automatically from the inverter API.")
            if st.form_submit_button("📥 Log Reading", type="primary"):
                sel_sys = systems[systems["customer_name"] == pick].iloc[0]
                add_production_reading(sel_sys["system_id"], rdate.isoformat(), kwh)
                st.success(f"Logged {kwh} kWh for {pick} on {rdate}.")
                st.rerun()


# ── Settings page ────────────────────────────────────────────────────
def page_settings():
    inst = st.session_state.installer
    st.title("⚙️ Settings")

    tab_plan, tab_email, tab_about = st.tabs(["💼 Plan & Billing", "📧 Email Config", "ℹ️ About"])

    with tab_plan:
        st.subheader("Your Subscription")
        tier = inst["tier"]
        info = TIERS[tier]
        price = f"${info['price']}/month" if info["price"] else "Custom"
        st.markdown(f"**Current plan:** {tier} ({price})")
        if info["max_systems"]:
            systems = get_installer_systems(inst["installer_id"])
            st.markdown(f"**Systems used:** {len(systems)} / {info['max_systems']}")
        st.markdown(f"**SMS alerts:** {'✅' if info['sms_alerts'] else '❌'}")
        st.markdown(f"**White-label reports:** {'✅' if info['white_label'] else '❌'}")

        st.divider()
        st.markdown("**Upgrade / Downgrade**")
        col_b, col_p, col_e = st.columns(3)
        with col_b:
            st.markdown("### 🔵 Basic — $99/mo")
            st.markdown("- Up to 50 systems")
            st.markdown("- Email alerts")
            if tier != "Basic":
                if st.button("Switch to Basic", key="sw_b"):
                    df = load_installers()
                    df.loc[df["installer_id"] == inst["installer_id"], "tier"] = "Basic"
                    save_installers(df)
                    st.session_state.installer = df[df["installer_id"] == inst["installer_id"]].iloc[0].to_dict()
                    st.rerun()
        with col_p:
            st.markdown("### 🟣 Pro — $299/mo")
            st.markdown("- Up to 200 systems")
            st.markdown("- SMS + email alerts")
            st.markdown("- White-label reports")
            if tier != "Pro":
                if st.button("Switch to Pro", key="sw_p"):
                    df = load_installers()
                    df.loc[df["installer_id"] == inst["installer_id"], "tier"] = "Pro"
                    save_installers(df)
                    st.session_state.installer = df[df["installer_id"] == inst["installer_id"]].iloc[0].to_dict()
                    st.rerun()
        with col_e:
            st.markdown("### 🟠 Enterprise")
            st.markdown("- Unlimited systems")
            st.markdown("- API access")
            st.markdown("- Custom integrations")
            st.markdown("[Contact sales](mailto:sales@solarguard.app)")

        st.divider()
        st.caption("🔒 Stripe billing integration coming soon (Stage 6).")

    with tab_email:
        st.subheader("Email Alert Configuration")
        if SEND_EMAILS:
            st.success(f"✅ Email sending is active via {SMTP_HOST} as user `{SMTP_USER}`.")
        else:
            st.warning("⚠️ Email sending is disabled. Configure SMTP in your `.env` file to enable.")
            st.code("""# .env file in /home/user/solarguard/
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-alerts@yourcompany.com
SMTP_PASSWORD=your-app-password
ALERT_FROM_EMAIL=alerts@yourcompany.com
DEFAULT_DROP_THRESHOLD=0.10""", language="ini")
            st.caption("For Gmail, create an **App Password** (requires 2FA enabled).")

    with tab_about:
        st.subheader("About SolarGuard")
        st.markdown("""
        **Version:** 0.3 (Stage 3 — Automated Daily Alerts)

        SolarGuard transforms solar installers from *reactive fixers* into
        *proactive protectors* by continuously monitoring fleet performance
        and flagging underperforming systems **before** the customer notices
        on their power bill.

        **Tech stack:** Python · Pandas · Streamlit · SMTP email
        **Roadmap status:**
        1. ✅ CSV-based monitoring script
        2. ✅ Web form for customer management
        3. ✅ Automated daily alerts (cron-ready `monitor.py`)
        4. ✅ Multi-installer authentication
        5. ⏳ Inverter API integrations (Enphase, SolarEdge)
        6. ⏳ Stripe billing
        """)
        st.markdown(f"**Data directory:** `{DATA_DIR}`")


# ── Routing ──────────────────────────────────────────────────────────
nav = render_sidebar()
if nav is None:
    # Landing page for logged-out users
    st.markdown("""
    <div class="hero" style="text-align:center;">
        <h1 style="font-size:3rem;">🔆 SolarGuard</h1>
        <p style="font-size:1.3rem;">Stop reacting to angry solar customer calls.<br>
        Start protecting them — proactively.</p>
    </div>""", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("### 🔍 Always Watching")
        st.write("Automated daily monitoring of every system you install. Catch drops before they become complaints.")
    with c2:
        st.markdown("### 📬 Instant Alerts")
        st.write("You and your homeowner get an email the moment production dips below healthy levels.")
    with c3:
        st.markdown("### 💼 Retain Customers")
        st.write("Turn service calls into trust-building moments. Position yourself as the proactive expert.")
    st.divider()
    f1, f2, f3, f4 = st.columns(4)
    f1.metric("Starting at", "$99/mo")
    f2.metric("Setup time", "< 5 min")
    f3.metric("Plan options", "3 tiers")
    f4.metric("Demo systems", "5 preloaded")
    st.info("👈  Use the sidebar to log in with demo credentials:  \n"
            "**Email:** `demo@solarguard.app`  \n"
            "**Password:** `demo1234`")
else:
    page = {
        "📊 Dashboard": page_dashboard,
        "👥 Customers": page_customers,
        "🔔 Alerts": page_alerts,
        "📈 Production Data": page_production,
        "⚙️ Settings": page_settings,
    }[nav]
    page()


# ── Footer ───────────────────────────────────────────────────────────
st.markdown("---")
st.caption("🔆 SolarGuard v0.3 — Proactive Solar Monitoring for Installers")
