# app.py — WasteWise: A role-based Streamlit app for municipal waste management
# --------------------------------------------------------------
# Roles: Ministry, Citizen, Employee
# Auth: Username/password (stored hashed in SQLite)
# DB: SQLite (wastewise.db)
# Deploy: Push to GitHub and deploy on Streamlit Community Cloud
# --------------------------------------------------------------
# SECURITY NOTE: This demo uses in-app user management + SQLite.
# For production, enable HTTPS, use stronger password policies, and
# consider an external auth provider (e.g., OAuth) and a managed DB.

import os
import sqlite3
from contextlib import closing
from datetime import datetime, date
from typing import Optional, Tuple, Dict

import pandas as pd
import streamlit as st
from passlib.hash import bcrypt

DB_PATH = os.getenv("WASTEWISE_DB", "wastewise.db")
APP_TITLE = "WasteWise — Waste Management Mediator"

# ------------------------- DB LAYER -------------------------

DDL = {
    "users": """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('ministry','citizen','employee')),
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """,
    "waste_requests": """
        CREATE TABLE IF NOT EXISTS waste_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            citizen_id INTEGER NOT NULL,
            address TEXT NOT NULL,
            category TEXT NOT NULL CHECK(category IN ('mixed','organic','recyclable','hazardous')),
            quantity_kg REAL NOT NULL,
            preferred_date DATE,
            status TEXT NOT NULL DEFAULT 'requested' CHECK(status IN (
                'requested','assigned','collected','segregated','recycled','cancelled'
            )),
            assigned_employee_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY(citizen_id) REFERENCES users(id),
            FOREIGN KEY(assigned_employee_id) REFERENCES users(id)
        );
    """,
    "segregation_records": """
        CREATE TABLE IF NOT EXISTS segregation_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER UNIQUE NOT NULL,
            organic_kg REAL DEFAULT 0,
            recyclable_kg REAL DEFAULT 0,
            hazardous_kg REAL DEFAULT 0,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(request_id) REFERENCES waste_requests(id)
        );
    """,
    "recycling_batches": """
        CREATE TABLE IF NOT EXISTS recycling_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            material TEXT NOT NULL,
            output_product TEXT NOT NULL,
            output_weight_kg REAL NOT NULL,
            processed_by INTEGER NOT NULL,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(request_id) REFERENCES waste_requests(id),
            FOREIGN KEY(processed_by) REFERENCES users(id)
        );
    """,
    "rewards": """
        CREATE TABLE IF NOT EXISTS rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            points INTEGER NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
            approved_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(approved_by) REFERENCES users(id)
        );
    """
}


def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    with closing(get_conn()) as conn:
        cur = conn.cursor()
        for sql in DDL.values():
            cur.execute(sql)
        conn.commit()

        # Seed a default ministry admin if none exists
        cur.execute("SELECT COUNT(*) FROM users WHERE role='ministry'")
        if cur.fetchone()[0] == 0:
            pwd_hash = bcrypt.hash("admin123")
            cur.execute(
                "INSERT INTO users (username, full_name, role, password_hash) VALUES (?,?,?,?)",
                ("admin@ministry.gov", "Ministry Admin", "ministry", pwd_hash)
            )
            conn.commit()


# ------------------------- AUTH -------------------------

def authenticate(username: str, password: str) -> Optional[Tuple[int, str, str]]:
    with closing(get_conn()) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, full_name, role, password_hash FROM users WHERE username=?", (username,))
        row = cur.fetchone()
        if not row:
            return None
        uid, full_name, role, pwh = row
        if bcrypt.verify(password, pwh):
            return uid, full_name, role
        return None


def user_by_id(user_id: int) -> Optional[Dict]:
    with closing(get_conn()) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, username, full_name, role FROM users WHERE id=?", (user_id,))
        row = cur.fetchone()
        if row:
            return {"id": row[0], "username": row[1], "full_name": row[2], "role": row[3]}
        return None


# ------------------------- UI HELPERS -------------------------

st.set_page_config(page_title=APP_TITLE, page_icon="♻️", layout="wide")

@st.cache_data(show_spinner=False)
def cached_users_df():
    with closing(get_conn()) as conn:
        return pd.read_sql_query("SELECT id, username, full_name, role, created_at FROM users", conn)


def refresh_users_cache():
    cached_users_df.clear()


# ------------------------- PAGES -------------------------

def page_login():
    st.title("♻️ " + APP_TITLE)
    st.caption("Mediator between Ministry, Citizens, and Employees — from collection to recycling and rewards")

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Username (email)")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")

    if submitted:
        user = authenticate(username, password)
        if user:
            uid, full_name, role = user
            st.session_state.user = {"id": uid, "full_name": full_name, "role": role}
            st.success(f"Welcome, {full_name} ({role.title()})")
            st.experimental_rerun()
        else:
            st.error("Invalid credentials. Hint: default ministry admin is admin@ministry.gov / admin123 (please change).")


def navbar():
    user = st.session_state.get("user")
    if not user:
        return

    left, right = st.columns([3,1])
    with left:
        st.subheader(f"Hello, {user['full_name']} — {user['role'].title()} portal")
    with right:
        if st.button("Log out"):
            st.session_state.clear()
            st.experimental_rerun()


# -------- Citizen Pages --------

def citizen_create_request():
    st.markdown("### 🗑️ Schedule a Pickup")
    with st.form("req_form"):
        address = st.text_area("Pickup Address")
        category = st.selectbox("Waste Category", ["mixed","organic","recyclable","hazardous"])
        quantity = st.number_input("Estimated Quantity (kg)", min_value=0.1, step=0.1)
        pref_date = st.date_input("Preferred Date", value=date.today())
        submit = st.form_submit_button("Create Request")
    if submit:
        with closing(get_conn()) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO waste_requests (citizen_id, address, category, quantity_kg, preferred_date, status) VALUES (?,?,?,?,?,?)",
                (st.session_state.user['id'], address, category, float(quantity), pref_date.isoformat(), 'requested')
            )
            conn.commit()
        st.success("Pickup request created.")


def citizen_track_requests():
    st.markdown("### 📦 My Requests")
    with closing(get_conn()) as conn:
        df = pd.read_sql_query(
            f"""
            SELECT r.id, r.status, r.category, r.quantity_kg, r.preferred_date, r.created_at,
                   u.full_name AS assigned_employee
            FROM waste_requests r
            LEFT JOIN users u ON r.assigned_employee_id = u.id
            WHERE r.citizen_id = {st.session_state.user['id']}
            ORDER BY r.created_at DESC
            """, conn
        )
    st.dataframe(df, use_container_width=True)


def citizen_rewards():
    st.markdown("### 🎁 My Rewards")
    with closing(get_conn()) as conn:
        df = pd.read_sql_query(
            f"SELECT id, points, reason, status, created_at FROM rewards WHERE user_id={st.session_state.user['id']} ORDER BY created_at DESC",
            conn
        )
        total = df[df['status']=="approved"]["points"].sum() if not df.empty else 0
    st.metric("Approved Points", total)
    st.dataframe(df, use_container_width=True)


# -------- Employee Pages --------

def employee_assigned_jobs():
    st.markdown("### 📋 Assigned Pickups")
    with closing(get_conn()) as conn:
        df = pd.read_sql_query(
            f"""
            SELECT r.id, r.status, r.address, r.category, r.quantity_kg, r.preferred_date,
                   c.full_name as citizen
            FROM waste_requests r
            JOIN users c ON r.citizen_id = c.id
            WHERE r.assigned_employee_id = {st.session_state.user['id']} AND r.status IN ('assigned','collected','segregated')
            ORDER BY r.preferred_date
            """, conn
        )
    st.dataframe(df, use_container_width=True)

    rid = st.number_input("Request ID to update", min_value=0, step=1)
    action = st.selectbox("Update Status", ["-- select --","collected","segregated"])
    if st.button("Update Status") and rid > 0 and action != "-- select --":
        with closing(get_conn()) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE waste_requests SET status=?, updated_at=? WHERE id=?", (action, datetime.utcnow().isoformat(), int(rid)))
            conn.commit()
        st.success("Status updated.")


def employee_segregation_record():
    st.markdown("### ♻️ Add Segregation Details")
    with st.form("seg_form"):
        req_id = st.number_input("Request ID", min_value=1, step=1)
        organic = st.number_input("Organic (kg)", min_value=0.0, step=0.1)
        recyclable = st.number_input("Recyclable (kg)", min_value=0.0, step=0.1)
        hazardous = st.number_input("Hazardous (kg)", min_value=0.0, step=0.1)
        notes = st.text_area("Notes")
        submit = st.form_submit_button("Save Segregation")
    if submit:
        with closing(get_conn()) as conn:
            cur = conn.cursor()
            cur.execute("SELECT status FROM waste_requests WHERE id=?", (int(req_id),))
            r = cur.fetchone()
            if not r:
                st.error("Request not found")
                return
            cur.execute(
                "INSERT OR REPLACE INTO segregation_records (request_id, organic_kg, recyclable_kg, hazardous_kg, notes) VALUES (?,?,?,?,?)",
                (int(req_id), float(organic), float(recyclable), float(hazardous), notes)
            )
            cur.execute("UPDATE waste_requests SET status='segregated', updated_at=? WHERE id=?", (datetime.utcnow().isoformat(), int(req_id)))
            conn.commit()
        st.success("Segregation saved.")


def employee_recycling_entry():
    st.markdown("### 🔄 Log Recycling Output")
    with st.form("recyc_form"):
        req_id = st.number_input("Request ID", min_value=1, step=1)
        material = st.selectbox("Material", ["biogas_feedstock","compost","plastic_pellets","paper_pulp","metal_ingots","e-waste_parts"]) 
        output_product = st.text_input("Output Product")
        out_wt = st.number_input("Output Weight (kg)", min_value=0.0, step=0.1)
        submit = st.form_submit_button("Log Batch")
    if submit:
        with closing(get_conn()) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO recycling_batches (request_id, material, output_product, output_weight_kg, processed_by) VALUES (?,?,?,?,?)",
                (int(req_id), material, output_product, float(out_wt), st.session_state.user['id'])
            )
            cur.execute("UPDATE waste_requests SET status='recycled', updated_at=? WHERE id=?", (datetime.utcnow().isoformat(), int(req_id)))
            conn.commit()
        st.success("Recycling batch logged.")


# -------- Ministry Pages --------

def ministry_assign_requests():
    st.markdown("### 🧭 Assign Requests to Employees")
    with closing(get_conn()) as conn:
        pending = pd.read_sql_query(
            """
            SELECT r.id, c.full_name AS citizen, r.address, r.category, r.quantity_kg, r.preferred_date, r.status
            FROM waste_requests r
            JOIN users c ON r.citizen_id = c.id
            WHERE r.status='requested'
            ORDER BY r.created_at ASC
            """, conn
        )
        employees = pd.read_sql_query(
            "SELECT id, full_name FROM users WHERE role='employee' ORDER BY full_name", conn
        )
    st.dataframe(pending, use_container_width=True)

    if not employees.empty:
        rid = st.number_input("Request ID", min_value=0, step=1)
        emp_name_to_id = {f"{row.full_name} (#{row.id})": int(row.id) for _, row in employees.iterrows()}
        assignee = st.selectbox("Assign to", list(emp_name_to_id.keys()))
        if st.button("Assign") and rid > 0:
            with closing(get_conn()) as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE waste_requests SET status='assigned', assigned_employee_id=?, updated_at=? WHERE id=?",
                    (emp_name_to_id[assignee], datetime.utcnow().isoformat(), int(rid))
                )
                conn.commit()
            st.success("Request assigned.")
    else:
        st.info("No employees available to assign.")


def ministry_rewards():
    st.markdown("### 🏅 Approve Rewards")
    with closing(get_conn()) as conn:
        pending = pd.read_sql_query(
            """
            SELECT rw.id, u.full_name AS user, u.role, rw.points, rw.reason, rw.status, rw.created_at
            FROM rewards rw JOIN users u ON rw.user_id = u.id
            WHERE rw.status='pending' ORDER BY rw.created_at ASC
            """, conn
        )
    st.dataframe(pending, use_container_width=True)

    rid = st.number_input("Reward ID", min_value=0, step=1)
    decision = st.selectbox("Decision", ["approve","reject"])
    if st.button("Apply") and rid > 0:
        with closing(get_conn()) as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE rewards SET status=?, approved_by=?, updated_at=? WHERE id=?",
                ("approved" if decision=="approve" else "rejected", st.session_state.user['id'], datetime.utcnow().isoformat(), int(rid))
            )
            conn.commit()
        st.success("Decision recorded.")


def ministry_analytics():
    st.markdown("### 📊 Operational Analytics")
    with closing(get_conn()) as conn:
        reqs = pd.read_sql_query("SELECT status, COUNT(*) as n FROM waste_requests GROUP BY status", conn)
        seg = pd.read_sql_query("SELECT SUM(organic_kg) as organic, SUM(recyclable_kg) as recyclable, SUM(hazardous_kg) as hazardous FROM segregation_records", conn)
        recy = pd.read_sql_query("SELECT material, SUM(output_weight_kg) as kg FROM recycling_batches GROUP BY material", conn)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Requests by Status**")
        st.dataframe(reqs)
        if not reqs.empty:
            st.bar_chart(reqs.set_index('status'))
    with col2:
        st.markdown("**Recycling Output (kg) by Material**")
        st.dataframe(recy)
        if not recy.empty:
            st.bar_chart(recy.set_index('material'))

    st.markdown("**Total Segregated (kg)**")
    st.dataframe(seg)


def ministry_user_mgmt():
    st.markdown("### 👥 User Management")
    st.write("Create Citizens/Employees; change passwords.")

    tab1, tab2 = st.tabs(["Create User", "Reset Password"])

    with tab1:
        with st.form("create_user"):
            uname = st.text_input("Username (email)")
            fname = st.text_input("Full Name")
            role = st.selectbox("Role", ["citizen","employee","ministry"])
            pwd = st.text_input("Temp Password", type="password")
            submit = st.form_submit_button("Create")
        if submit:
            try:
                with closing(get_conn()) as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO users (username, full_name, role, password_hash) VALUES (?,?,?,?)",
                        (uname, fname, role, bcrypt.hash(pwd))
                    )
                    conn.commit()
                refresh_users_cache()
                st.success("User created.")
            except sqlite3.IntegrityError:
                st.error("Username already exists.")

    with tab2:
        users_df = cached_users_df()
        st.dataframe(users_df, use_container_width=True)
        target_id = st.number_input("User ID", min_value=1, step=1)
        new_pwd = st.text_input("New Password", type="password")
        if st.button("Reset Password") and new_pwd:
            with closing(get_conn()) as conn:
                cur = conn.cursor()
                cur.execute("UPDATE users SET password_hash=? WHERE id=?", (bcrypt.hash(new_pwd), int(target_id)))
                conn.commit()
            st.success("Password updated.")


# -------- Shared --------

def request_rewards_proposal():
    st.markdown("### 🙌 Propose a Reward")
    with st.form("rw_form"):
        points = st.number_input("Points", min_value=1, step=1)
        reason = st.text_area("Reason (e.g., timely pickup, clean segregation, recycling milestone)")
        submit = st.form_submit_button("Submit Proposal")
    if submit:
        with closing(get_conn()) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO rewards (user_id, points, reason) VALUES (?,?,?)",
                (st.session_state.user['id'], int(points), reason)
            )
            conn.commit()
        st.success("Reward proposal submitted for ministry approval.")


# ------------------------- ROUTER -------------------------

def route_role():
    role = st.session_state.user["role"]
    navbar()

    if role == "citizen":
        t1, t2, t3 = st.tabs(["Schedule Pickup", "My Requests", "My Rewards"])
        with t1:
            citizen_create_request()
            request_rewards_proposal()
        with t2:
            citizen_track_requests()
        with t3:
            citizen_rewards()

    elif role == "employee":
        t1, t2, t3 = st.tabs(["Assigned Jobs", "Segregation", "Recycling & Rewards"]) 
        with t1:
            employee_assigned_jobs()
        with t2:
            employee_segregation_record()
        with t3:
            employee_recycling_entry()
            request_rewards_proposal()

    elif role == "ministry":
        t1, t2, t3, t4 = st.tabs(["Assign Requests", "Rewards", "Analytics", "User Mgmt"]) 
        with t1:
            ministry_assign_requests()
        with t2:
            ministry_rewards()
        with t3:
            ministry_analytics()
        with t4:
            ministry_user_mgmt()


# ------------------------- MAIN -------------------------

def main():
    init_db()
    if "user" not in st.session_state:
        page_login()
    else:
        route_role()


if __name__ == "__main__":
    main()
