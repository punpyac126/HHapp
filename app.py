
# app.py — HHapp2 (patched to match HHapp2_Project_Summary.md)
# Run: streamlit run app.py

import os
from pathlib import Path
import sqlite3
from contextlib import closing
from datetime import datetime, date, time, timedelta
import hashlib, secrets, json
import re

import pandas as pd
import streamlit as st

# Local helpers
from shift_helpers import shift_picker
from time_helpers import vitals_time_input
from print_utils import (
    build_patient_inputlike_print_html,
    build_vitals_inputlike_print_html,
    build_physio_inputlike_print_html,
    download_print_button,
)

# remember_login helpers (URL token persistence)
import remember_login as rlogin

# ---------------- Page config (first Streamlit call) ----------------
ASSETS_DIR = Path("assets"); ASSETS_DIR.mkdir(exist_ok=True)
UPLOAD_DIR = Path("uploads"); UPLOAD_DIR.mkdir(exist_ok=True)
FAV_PATH = ASSETS_DIR / "logo.png"
if FAV_PATH.exists():
    st.set_page_config(page_title="Healthy Habitat", page_icon=str(FAV_PATH), layout="wide")
else:
    st.set_page_config(page_title="Healthy Habitat", page_icon="🏥", layout="wide")

APP_TITLE = "Healthy Habitat"
DB_PATH = "clinic.db"

# ---------------- DB helpers ----------------
def run_query(sql, params=(), fetch=False, many=False):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if many:
            cur.executemany(sql, params)
        else:
            cur.execute(sql, params)
        if fetch:
            return [dict(r) for r in cur.fetchall()]
        conn.commit()

def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        c = conn.cursor()
        c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hn TEXT UNIQUE,
            first_name TEXT,
            last_name TEXT,
            dob TEXT,
            ward TEXT,
            weight REAL,
            height REAL,
            hospital TEXT,
            blood_group TEXT,
            relative_name TEXT,
            relative_phone TEXT,
            underlying_disease TEXT,
            drug_allergy TEXT,
            admission_date TEXT,
            feeding TEXT,
            foley INTEGER DEFAULT 0,
            detail TEXT,
            photo_path TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS nurse_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            hn TEXT,
            ts TEXT,
            shift TEXT,
            section TEXT,
            field TEXT,
            value TEXT,
            created_by TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        -- physio_logs append-only (per spec)
        CREATE TABLE IF NOT EXISTS physio_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            log_date TEXT NOT NULL,         -- YYYY-MM-DD
            physio_type TEXT NOT NULL,      -- 'basic' | 'rehab'
            section TEXT NOT NULL,          -- e.g. 'Vital (pre)', 'Exercise', 'Functional'
            field TEXT NOT NULL,            -- label
            value TEXT,                     -- value
            created_by TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS medications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            meal_times TEXT,
            meal_times_other TEXT,
            timing_radio TEXT,
            timing_other TEXT,
            image_path TEXT,
            drug_name TEXT,
            drug_type TEXT,
            how_to TEXT,
            responsible TEXT,
            created_by TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT CHECK(role IN ('nurse','physio','pharmacy','admin')) NOT NULL,
            phone TEXT,
            email TEXT,
            username TEXT UNIQUE,
            password_hash TEXT,
            last_login TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS patient_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            action TEXT,
            changed_at TEXT DEFAULT (datetime('now')),
            changed_by TEXT,
            before_data TEXT,
            after_data TEXT
        );
        """)
        conn.commit()

init_db()



# ---------------- Responsive CSS ----------------
def inject_responsive_css():
    st.markdown(
        """
        <style>
        /* Make the main container wider on large screens and padded on small screens */
        .block-container {padding-left: 1rem !important; padding-right: 1rem !important;}
        @media (min-width: 1600px) {
          .block-container {max-width: 1400px;}
        }
        /* Make Streamlit tabs scrollable horizontally on small screens */
        .stTabs [role="tablist"] { overflow-x: auto; white-space: nowrap; }
        .stTabs [role="tab"] { flex: 0 0 auto; }
        /* Buttons full-width on narrow screens */
        @media (max-width: 768px) {
          .stButton > button { width: 100% !important; }
          .stDownloadButton > button { width: 100% !important; }
          .st-emotion-cache-1erivf3 { width: 100% !important; } /* some buttons */
        }
        /* Make images scale with container */
        .stImage img { max-width: 100% !important; height: auto !important; }
        /* Dataframes and editors: allow horizontal scroll on mobile */
        .stDataFrame, .stTable, .st-emotion-cache-1y4p8pa { overflow-x: auto; }
        /* Tighten markdown H2/H3 on mobile */
        @media (max-width: 768px) {
          h2 { font-size: 1.25rem; }
          h3 { font-size: 1.1rem; }
        }
        /* Sidebar tweaks */
        @media (max-width: 768px) {
          section[data-testid="stSidebar"] { width: 18rem !important; }
        }
        </style>
        """,
        unsafe_allow_html=True
    )


# ---------------- Auth utils ----------------
def hash_password(password: str, iterations: int = 120_000) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations)
    return f"pbkdf2${iterations}${salt}${dk.hex()}"

def verify_password(stored: str, provided: str) -> bool:
    try:
        algo, iters, salt, hexd = stored.split("$")
        if algo != "pbkdf2": return False
        iters = int(iters)
        dk = hashlib.pbkdf2_hmac("sha256", provided.encode(), bytes.fromhex(salt), iters)
        return dk.hex() == hexd
    except Exception:
        return False

def current_user():
    return st.session_state.get("user")

def lookup_user_by_id(uid:int):
    row = run_query("SELECT id, name, role, username FROM staff WHERE id=? AND is_active=1", (uid,), fetch=True)
    return row[0] if row else None

def can_edit_page(page: str) -> bool:
    u = current_user()
    if not u: return False
    role = u.get("role")
    if role == "admin": return True
    return (page == "vitals" and role == "nurse") or (page == "physio" and role == "physio") or (page == "meds" and role == "pharmacy")

# ---------------- Helpers ----------------
def normalize_date_str(s: str):
    if not s: return None
    s = s.strip()
    if len(s) == 8 and s.isdigit():
        first2 = int(s[:2]); mid2 = int(s[2:4])
        if first2 > 31: y,m,d = s[:4], s[4:6], s[6:8]
        else:
            if 1 <= mid2 <= 12: d,m,y = s[:2], s[2:4], s[4:8]
            else: return None
        try: return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
        except Exception: return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except Exception:
        return None

def calc_age_ymd(dob_str):
    if not dob_str:
        return "-"
    try:
        dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
        today = date.today()
        y = today.year - dob.year
        m = today.month - dob.month
        d = today.day - dob.day
        if d < 0:
            import calendar
            prev_month = (today.month - 1) or 12
            prev_year = today.year - 1 if today.month == 1 else today.year
            d += calendar.monthrange(prev_year, prev_month)[1]
            m -= 1
        if m < 0:
            m += 12; y -= 1
        return f"{max(y,0)} ปี {max(m,0)} เดือน {max(d,0)} วัน"
    except Exception:
        return "-"

def log_patient_change(pid, action, before, after):
    run_query(
        "INSERT INTO patient_audit (patient_id, action, changed_by, before_data, after_data) VALUES (?,?,?,?,?)",
        (pid, action, (current_user() or {}).get("name"), json.dumps(before or {}, ensure_ascii=False), json.dumps(after or {}, ensure_ascii=False))
    )

# ---------------- Header ----------------
def get_logo_path():
    for pth in [
        ASSETS_DIR / "logo.png", ASSETS_DIR / "logo.jpg", ASSETS_DIR / "logo.jpeg",
        UPLOAD_DIR / "logo.png", UPLOAD_DIR / "logo.jpg", UPLOAD_DIR / "logo.jpeg",
        UPLOAD_DIR / "logo" / "logo.png", UPLOAD_DIR / "logo" / "logo.jpg", UPLOAD_DIR / "logo" / "logo.jpeg",
    ]:
        if Path(pth).exists():
            return str(pth)
    return None

def render_top_header():
    c1, c2 = st.columns([1,6])
    with c1:
        lp = get_logo_path()
        if lp:
            try:
                st.image(lp, use_container_width=True)
            except TypeError:
                # สำหรับสภาพแวดล้อมที่ยังใช้ Streamlit เวอร์ชันเก่า
                st.image(lp, use_column_width=True)

    with c2:
        st.markdown(f"## {APP_TITLE}")

def render_patient_banner(pid: int):
    if not pid:
        return
    row = run_query(
        "SELECT hn,first_name,last_name,photo_path,blood_group,ward,underlying_disease,weight,drug_allergy,hospital,feeding,foley,dob,relative_name,relative_phone "
        "FROM patients WHERE id=?", (pid,), fetch=True
    )
    if not row:
        return
    r = row[0]
    full_name = f"คุณ {r.get('first_name','')} {r.get('last_name','')}"
    ward = r.get("ward") or "-"
    hospital = r.get("hospital") or "-"
    bg = r.get("blood_group") or "-"
    age_txt = calc_age_ymd(r.get("dob")) or "-"
    photo_path = r.get("photo_path")

    colA, colB = st.columns([1,6])
    with colA:
        try:
            if photo_path and Path(photo_path).exists():
                st.image(photo_path, width=120)
            else:
                st.markdown(
                    "<div style='width:120px;height:120px;border-radius:8px;background:#EEE;display:flex;align-items:center;justify-content:center;color:#888;'>No Photo</div>",
                    unsafe_allow_html=True
                )
        except Exception:
            st.markdown(
                "<div style='width:120px;height:120px;border-radius:8px;background:#EEE;display:flex;align-items:center;justify-content:center;color:#888;'>No Photo</div>",
                unsafe_allow_html=True
            )

    with colB:
        st.markdown(f"### {full_name}")
        st.markdown(
            f"**HN:** `{r.get('hn') or '-'}`  •  **วอร์ด:** {ward}  •  **อายุ:** {age_txt}  •  **กรุ๊ปเลือด:** {bg}"
        )
        st.markdown(
            f"**โรคประจำตัว:** {r.get('underlying_disease') or '-'}  •  **น้ำหนัก:** "
            f"{(r.get('weight') if r.get('weight') not in (None, '') else '-')}  •  **แพ้ยา:** {r.get('drug_allergy') or '-'}"
        )
        st.markdown(
            f"**การรับประทานอาหาร:** {r.get('feeding') or '-'}  •  **Foley's:** {'Yes' if r.get('foley') else 'No'}"
        )
        st.markdown(
            f"**โรงพยาบาล:** {hospital}"
        )
        st.markdown(
            f"**ญาติผู้ป่วย:** {r.get('relative_name') or '-'}  •  **เบอร์ติดต่อ:** {r.get('relative_phone') or '-'}"
        )
    st.divider()


# ---- Bootstrap: ensure at least one active admin exists ----
try:
    _admin_exist = run_query("SELECT id FROM staff WHERE role='admin' AND is_active=1 LIMIT 1", fetch=True)
    if not _admin_exist:
        run_query(
            "INSERT INTO staff (name, role, username, password_hash, is_active) VALUES (?,?,?,?,1)",
            ("Administrator", "admin", "admin", hash_password("admin123"))
        )
except Exception as _e:
    pass


def render_auth_sidebar():
    st.sidebar.header("🔐 เข้าสู่ระบบ")

    # ถ้ามี session user แล้ว
    if st.session_state.get("user"):
        u = st.session_state["user"]
        st.sidebar.success(f"สวัสดี {u.get('name','')} ({u.get('role')})")
        if st.sidebar.button("ออกจากระบบ"):
            st.session_state.pop("user", None)
            st.rerun()
        return

    # ----- Login -----
    with st.sidebar.form("login_form"):
        username = st.text_input("ชื่อผู้ใช้")
        password = st.text_input("รหัสผ่าน", type="password")
        do_login = st.form_submit_button("เข้าสู่ระบบ")

    if do_login:
        row = run_query(
            "SELECT id,name,role,username,password_hash FROM staff WHERE is_active=1 AND username=?",
            (username,),
            fetch=True,
        )
        if not row or not verify_password(row[0].get("password_hash") or "", password):
            st.sidebar.error("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
        else:
            u = row[0]
            st.session_state["user"] = {
                "id": u["id"],
                "name": u["name"],
                "role": u["role"],
                "username": u["username"],
            }
            st.rerun()
    # ----- Forgot password disabled: contact admin -----
    with st.sidebar.expander("🔁 ลืมรหัสผ่าน?"):
        st.caption("โปรดติดต่อผู้ดูแลระบบเพื่อรีเซ็ตรหัสผ่าน")

# ----- Self-registration disabled by policy -----
# Sidebar: patient search
def render_patient_search_sidebar():
    st.sidebar.header("🧑‍⚕️ ค้นหา/เลือกคนไข้")
    with st.sidebar.form("patient_search_form"):
        q = st.text_input("พิมพ์ชื่อ/นามสกุล/HN/วอร์ด", key="patient_search")
        search = st.form_submit_button("ค้นหา")
    if search:
        if q.strip():
            qn = q.replace(" ", "").replace("-", "").replace("/", "").lower()
            like = f"%{qn}%"
            rows = run_query(
                """
                SELECT id, hn, first_name, last_name, hospital, ward, photo_path
                FROM patients
                WHERE is_active=1 AND (
                    LOWER(REPLACE(REPLACE(REPLACE(hn, ' ', ''), '-', ''), '/', '')) LIKE ? OR
                    LOWER(REPLACE(first_name, ' ', '')) LIKE ? OR
                    LOWER(REPLACE(last_name, ' ', '')) LIKE ? OR
                    LOWER(REPLACE(ward, ' ', '')) LIKE ?
                )
                ORDER BY updated_at DESC
                LIMIT 50
                """,
                (like, like, like, like), fetch=True
            )
        else:
            rows = []
        st.session_state["search_results"] = rows

    results = st.session_state.get("search_results", [])
    if results:
        st.sidebar.caption(f"พบ {len(results)} รายการ")
        for r in results:
            label = f"{r.get('hn') or '-'} | คุณ {r['first_name']} {r['last_name']} | Ward: {r.get('ward') or '-'}"
            if st.sidebar.button(label, key=f"pick_{r['id']}"):
                st.session_state["patient_id"] = r["id"]
                st.rerun()
    else:
        st.sidebar.info("พิมพ์คำค้นแล้วกด 'ค้นหา'")

# ---------------- Main ----------------
def main():
    inject_responsive_css()
    # --- editable guard (avoid UnboundLocalError) ---
    editable_guard_applied = True
    try:
        _u = current_user() or {}
        _role = (_u.get("role") or "").lower()
        editable = _role in ("nurse", "admin")
    except Exception:
        editable = True

    # --- Global selected date safe default ---
    from datetime import date as _date
    if 'sel_date' not in st.session_state:
        st.session_state['sel_date'] = _date.today()
    sel_date = st.session_state['sel_date']

    render_top_header()
    render_auth_sidebar()
    if not current_user():
        st.info("โปรดเข้าสู่ระบบก่อนใช้งาน"); st.stop()

    render_patient_search_sidebar()
    pid = st.session_state.get("patient_id")

    st.markdown("### เลือกคนไข้")
    if pid:
        _pat = run_query("SELECT id, hn, first_name, last_name FROM patients WHERE id=?", (pid,), fetch=True) or []
        options = [f"{r['hn']} - {r['first_name']} {r['last_name']}" for r in _pat]
        ids = [r['id'] for r in _pat]
        if options:
            sel = st.selectbox("คนไข้", options, index=0)
            if sel:
                st.session_state['patient_id'] = ids[options.index(sel)]

    tabs = st.tabs(["ข้อมูลคนไข้", "ทีมพยาบาล (Vitals)", "ทีมกายภาพ", "เวชระเบียนยา"] + (["จัดการพนักงาน (Admin)"] if (current_user() and current_user().get("role")=="admin") else []))

    # ===== Admin: จัดการพนักงาน (เฉพาะ admin) =====
    if current_user() and current_user().get("role") == "admin":
        with tabs[-1]:
            st.subheader("👥 จัดการพนักงาน (Admin)")
            st.caption("แก้ไขบทบาท (role) และสถานะการใช้งานได้ที่นี่")
            staff_rows = run_query("SELECT id, name, username, role, phone, email, is_active FROM staff ORDER BY id", fetch=True)
            import pandas as pd
            df = pd.DataFrame(staff_rows)
            if df.empty:
                st.info("ยังไม่มีพนักงานในระบบ")
            else:
                role_options = ["nurse", "physio", "pharmacy", "admin"]
                edited = st.data_editor(
                    df,
                    hide_index=True,
                    column_config={
                        "id": st.column_config.NumberColumn("ID", disabled=True),
                        "username": st.column_config.TextColumn("Username", disabled=True),
                        "role": st.column_config.SelectboxColumn("Role", options=role_options, required=True),
                        "is_active": st.column_config.CheckboxColumn("ใช้งาน"),
                    },
                )
                if st.button("บันทึกการเปลี่ยนแปลง", type="primary", ):
                    changed = 0
                    for i in range(len(df)):
                        before = df.iloc[i]
                        after = edited.iloc[i]
                        if before["role"] != after["role"] or int(bool(before["is_active"])) != int(bool(after["is_active"])):
                            run_query(
                                "UPDATE staff SET role=?, is_active=? WHERE id=?",
                                (after["role"], int(bool(after["is_active"])), int(after["id"]))
                            )
                            changed += 1
                    if changed:
                        st.success(f"อัปเดตสำเร็จ {changed} รายการ")
                        st.rerun()
                    else:
                        st.info("ไม่มีการเปลี่ยนแปลง")

                st.divider()
                st.markdown("#### ➕ เพิ่มผู้ใช้งานใหม่")
                with st.form("admin_create_user"):
                    cu_name = st.text_input("ชื่อ - นามสกุล *")
                    cu_role = st.selectbox("บทบาท *", ["nurse","physio","pharmacy","admin"])
                    cu_username = st.text_input("Username (ไม่ซ้ำ) *")
                    cu_pw1 = st.text_input("รหัสผ่าน *", type="password")
                    cu_pw2 = st.text_input("ยืนยันรหัสผ่าน *", type="password")
                    cu_phone = st.text_input("เบอร์โทร (ถ้ามี)")
                    cu_email = st.text_input("อีเมล (ถ้ามี)")
                    do_create = st.form_submit_button("สร้างผู้ใช้ใหม่", type="primary")

                if do_create:
                    errs = []
                    if not cu_name.strip() or not cu_username.strip() or not cu_pw1 or not cu_pw2:
                        errs.append("กรอกข้อมูลที่มี * ให้ครบ")
                    if cu_pw1 != cu_pw2:
                        errs.append("ยืนยันรหัสผ่านไม่ตรงกัน")
                    if errs:
                        for e in errs: st.error(e)
                    else:
                        dup = run_query("SELECT id FROM staff WHERE username=?", (cu_username,), fetch=True)
                        if dup:
                            st.error("ชื่อผู้ใช้ซ้ำ")
                        else:
                            run_query(
                                "INSERT INTO staff (name, role, phone, email, username, password_hash, is_active) VALUES (?,?,?,?,?,?,1)",
                                (cu_name.strip(), cu_role, cu_phone or None, cu_email or None, cu_username.strip(), hash_password(cu_pw1))
                            )
                            st.success("เพิ่มผู้ใช้ใหม่สำเร็จ")
                            st.rerun()

                    st.markdown("#### 🔐 รีเซ็ตรหัสผ่านผู้ใช้")
                    _staff_all = run_query("SELECT id, name, username, is_active FROM staff ORDER BY name", fetch=True) or []
                    _opts = [f"{r['name']} ({r['username']}){' [inactive]' if not r['is_active'] else ''}" for r in _staff_all]
                    _ids = [r["id"] for r in _staff_all]
                    with st.form("admin_reset_pw"):
                        if _opts:
                            sel = st.selectbox("เลือกผู้ใช้", _opts, index=0)
                            new_pw1 = st.text_input("รหัสผ่านใหม่ *", type="password")
                            new_pw2 = st.text_input("ยืนยันรหัสผ่านใหม่ *", type="password")
                            do_reset = st.form_submit_button("รีเซ็ตรหัสผ่าน")
                        else:
                            st.info("ยังไม่มีผู้ใช้ในระบบ")
                            sel = None
                            do_reset = False
                            new_pw1 = new_pw2 = ""

                    if _opts and do_reset:
                        if not new_pw1 or not new_pw2:
                            st.error("กรุณากรอกรหัสผ่านใหม่ให้ครบ")
                        elif new_pw1 != new_pw2:
                            st.error("ยืนยันรหัสผ่านไม่ตรงกัน")
                        else:
                            target_id = _ids[_opts.index(sel)]
                            run_query("UPDATE staff SET password_hash=? WHERE id=?", (hash_password(new_pw1), target_id))
                            st.success("รีเซ็ตรหัสผ่านสำเร็จ")
                            st.rerun()
    
    # ---------------- Tab 0: Patient Info (admin editable) ----------------
    with tabs[0]:
        st.subheader("🧾 ข้อมูลคนไข้")
        render_patient_banner(pid)
        p = None
        if pid:
            row = run_query("SELECT * FROM patients WHERE id=?", (pid,), fetch=True)
            p = row[0] if row else None

        if current_user().get("role") != "admin":
            st.caption("**หมายเหตุ:** หน้านี้แก้ไขได้เฉพาะผู้ดูแลระบบ (admin)")
        else:
            st.markdown("**เพิ่ม/แก้ไขคนไข้**")
            with st.form("patient_form"):
                hn = st.text_input("HN", value=(p.get("hn") if p else ""))
                first_name = st.text_input("ชื่อ", value=(p.get('first_name') if p else ""))
                last_name = st.text_input("นามสกุล", value=(p.get('last_name') if p else ""))
                dob = st.text_input("วันเกิด (YYYY-MM-DD/yyyymmdd/ddmmyyyy)", value=(p.get('dob') if p else ""))
                underlying_disease = st.text_area("โรคประจำตัว", value=(p.get('underlying_disease') if p else ""))

                c_w, c_h = st.columns(2)
                with c_w:
                    weight = st.number_input("น้ำหนัก (กก.)", min_value=0.0, max_value=500.0, step=0.1, value=(float(p.get("weight")) if (p and p.get("weight")) else 0.0))
                with c_h:
                    height = st.number_input("ส่วนสูง (ซม.)", min_value=0.0, max_value=250.0, step=0.5, value=(float(p.get("height")) if (p and p.get("height")) else 0.0))

                drug_allergy = st.text_area("ประวัติแพ้ยา", value=(p.get('drug_allergy') if p else ""))
                feeding = st.radio("การรับประทานอาหาร", ["oral","NG"], index=(0 if ((p.get("feeding") if p else "oral")=="oral") else 1), horizontal=True)
                ward = st.text_input("วอร์ด", value=(p.get('ward') if p else ""))
                hospital = st.text_input("โรงพยาบาล", value=(p.get('hospital') if p else ""))

                opts_bg = ["N/A","A Rh+","A Rh-","AB Rh+","AB Rh-","B Rh+","B Rh-","O Rh+","O Rh-"]
                _bg_val = (p.get("blood_group") if p else None)
                _bg_idx = opts_bg.index(_bg_val) if (_bg_val in opts_bg) else 0
                blood_group = st.selectbox("กรุ๊ปเลือด", opts_bg, index=_bg_idx)

                foley = st.radio("Foley's", ["No","Yes"], index=1 if (p and p.get("foley")) else 0, horizontal=True)
                admission_date = st.text_input("วันที่เข้ารักษา (YYYY-MM-DD/yyyymmdd/ddmmyyyy)", value=(p.get('admission_date') if p else ""))
                detail = st.text_area("รายละเอียดเพิ่มเติม", value=(p.get('detail') if p else ""))
                relative_name = st.text_input("ชื่อญาติผู้ป่วย", value=(p.get('relative_name') if p else ""))
                relative_phone = st.text_input("เบอร์ติดต่อ", value=(p.get('relative_phone') if p else ""))
                pat_photo = st.file_uploader("อัปโหลดรูปคนไข้ (PNG/JPG)", type=["png","jpg","jpeg"], key="pat_photo_admin")
                save = st.form_submit_button("บันทึก")
            if save:
                dob_norm = normalize_date_str(dob)
                admit_norm = normalize_date_str(admission_date)
                existing = p or {}
                admit_norm_final = existing.get("admission_date") or admit_norm
                photo_path = existing.get("photo_path")
                if pat_photo is not None:
                    save_dir = Path("patient_photos")
                    # sanitize HN and create per-HN subfolder to avoid slashes in file name
                    safe_hn = re.sub(r"[^A-Za-z0-9_-]+", "_", (hn or 'patient'))
                    subdir = save_dir / safe_hn
                    subdir.mkdir(parents=True, exist_ok=True)
                    ext = (pat_photo.name.split(".")[-1] or "jpg").lower()
                    fname = f"{int(datetime.now().timestamp())}.{ext}"
                    fpath = subdir / fname
                    with open(fpath, "wb") as f: f.write(pat_photo.getbuffer())
                    photo_path = str(fpath)
                try:
                    if p:
                        before = p.copy()
                        run_query("""UPDATE patients SET hn=?, first_name=?, last_name=?, dob=?, underlying_disease=?, weight=?, height=?, drug_allergy=?, feeding=?, ward=?, hospital=?, blood_group=?, foley=?, admission_date=?, detail=?, relative_name=?, relative_phone=?, photo_path=?, updated_at=datetime('now') WHERE id=?""",
                                  (hn or None, first_name or None, last_name or None, dob_norm, underlying_disease or None, (weight or None), (height or None), drug_allergy or None, feeding or None, ward or None, hospital or None, blood_group or None, 1 if foley=="Yes" else 0, admit_norm_final, detail or None, relative_name or None, relative_phone or None, photo_path, pid))
                        after = run_query("SELECT * FROM patients WHERE id=?", (pid,), fetch=True)[0]
                        log_patient_change(pid, "update_patient", before, after)
                        st.success("อัปเดตแล้ว")
                        # --- Clear form fields & prepare for new entry ---
                        for _k in ["pat_photo_admin"]:
                            st.session_state.pop(_k, None)
                        st.session_state.pop("patient_id", None)
                        st.session_state.pop("search_results", None)
                        st.rerun()
                    else:
                        run_query("""INSERT INTO patients (hn, first_name, last_name, dob, underlying_disease, weight, height, drug_allergy, feeding, ward, hospital, blood_group, foley, admission_date, detail, relative_name, relative_phone, photo_path) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                  (hn or None, first_name or None, last_name or None, dob_norm, underlying_disease or None, (weight or None), (height or None), drug_allergy or None, feeding or None, ward or None, hospital or None, blood_group or None, 1 if foley=="Yes" else 0, admit_norm, detail or None, relative_name or None, relative_phone or None, photo_path))
                        # Re-select newly inserted row (แทนการใช้ last_insert_rowid)
                        new_row = []
                        if hn:
                            new_row = run_query("SELECT * FROM patients WHERE hn=?", (hn,), fetch=True) or []
                        if not new_row:
                            new_row = run_query("SELECT * FROM patients ORDER BY id DESC LIMIT 1", fetch=True) or []

                        if new_row:
                            new_id = new_row[0]["id"]
                            log_patient_change(new_id, "create_patient", None, new_row[0])
                        else:
                            new_id = None
                            log_patient_change(None, "create_patient", None, {"hn": hn, "first_name": first_name, "last_name": last_name})

                        st.toast("เพิ่มคนไข้ใหม่สำเร็จ")
                        st.session_state.pop("pat_photo_admin", None)
                        st.session_state.pop("patient_id", None)
                        st.session_state.pop("search_results", None)
                        st.rerun()
                except sqlite3.IntegrityError:
                    st.error("HN นี้มีอยู่แล้วในระบบ ห้ามซ้ำ ❌")

        # Print button (A4) for patient info
        if pid:
            html = build_patient_inputlike_print_html(run_query, get_logo_path, calc_age_ymd, pid)
            download_print_button(st, "🖨️ พิมพ์/ดาวน์โหลด (A4)", html, f"patient_{pid}.html")

    # ---------------- Tab 1: Nurse Logs ----------------
    
    with tabs[1]:
        # Patient selection guard
        pid = st.session_state.get('patient_id')
        if not pid:
            st.info('กรุณาเลือกคนไข้ก่อนใช้งานแท็บพยาบาล')
            st.stop()

        # Use the same banner renderer as other tabs
        render_patient_banner(pid)

        st.subheader("ทีมพยาบาล (Vitals)")
        st.caption("บันทึกกลางคืนและกลางวันในหน้าเดียวกัน • ไม่มีช่องเวลา ระบบจะใช้เวลาปัจจุบันเมื่อกดบันทึก")

        # ---- Prevent selecting future dates ----
        _today = date.today()
        _default_date = st.session_state.get("vitals_date") or _today
        if _default_date > _today:
            _default_date = _today
        sel_date_v = st.date_input("วันที่บันทึก", value=_default_date, max_value=_today, key="vitals_date")

        # ---- If date changed, clear widget states so the form reflects the new date ----
        prev_date = st.session_state.get("vitals_date_prev")
        if prev_date != sel_date_v:
            _keys = [
                # night
                "T_n","BP_n","HR_n","RR_n","SpO2_n","DTX_n","Intake_n","Output_n","Stool_n",
                "Cough_n","Sputum_n","Suction_n","Lines_n","PostSuction_n","sleep_n","night_food_n",
                "detail_n","note_night","caregiver_n","head_night",
                # day
                "T_d","BP_d","HR_d","RR_d","SpO2_d","DTX_d","Intake_d","Output_d","Stool_d",
                "Cough_d","Sputum_d","Suction_d","Lines_d","PostSuction_d","eat_normal_d","eat_ng_d",
                "eat_abn_d","activity_d","detail_d","note_day","caregiver_d","head_day",
            ]
            for k in _keys:
                if k in st.session_state:
                    del st.session_state[k]
            st.session_state["vitals_date_prev"] = sel_date_v

        def _fetch_latest(patient_id, daydate, shift, section, field):
            ds = daydate.strftime("%Y-%m-%d")
            rows = run_query(
                """
                SELECT value FROM nurse_logs
                WHERE patient_id=? AND substr(ts,1,10)=? AND shift=? AND section=? AND field=?
                ORDER BY ts DESC
                LIMIT 1
                """,
                (patient_id, ds, shift, section, field),
                fetch=True
            )
            if rows and isinstance(rows, list):
                row0 = rows[0]
                return row0.get("value") if isinstance(row0, dict) else (row0[0] if row0 else "")
            return ""

        # ---- Prefill from DB for selected date ----
        defvals = {}
        # night
        defvals["T_n"] = _fetch_latest(pid, sel_date_v, "night", "สัญญาณชีพ", "T/อุณหภูมิ")
        defvals["BP_n"] = _fetch_latest(pid, sel_date_v, "night", "สัญญาณชีพ", "BP/ความดัน")
        defvals["HR_n"] = _fetch_latest(pid, sel_date_v, "night", "สัญญาณชีพ", "HR/อัตราการเต้นหัวใจ")
        defvals["RR_n"] = _fetch_latest(pid, sel_date_v, "night", "สัญญาณชีพ", "RR/อัตราการหายใจ")
        defvals["SpO2_n"] = _fetch_latest(pid, sel_date_v, "night", "สัญญาณชีพ", "SpO2/ค่าออกซิเจน")
        defvals["DTX_n"] = _fetch_latest(pid, sel_date_v, "night", "สัญญาณชีพ", "DTX/ระดับน้ำตาลในเลือด")
        defvals["Intake_n"] = _fetch_latest(pid, sel_date_v, "night", "สัญญาณชีพ", "Intake/น้ำเข้าร่างกาย")
        defvals["Output_n"] = _fetch_latest(pid, sel_date_v, "night", "สัญญาณชีพ", "Output/ปัสสาวะ")
        defvals["Stool_n"] = _fetch_latest(pid, sel_date_v, "night", "สัญญาณชีพ", "Stool/อุจจาระ")

        defvals["Cough_n"] = _fetch_latest(pid, sel_date_v, "night", "ทางเดินหายใจ", "อาการไอ/มีเสมหะ")
        defvals["Sputum_n"] = _fetch_latest(pid, sel_date_v, "night", "ทางเดินหายใจ", "ลักษณะ")
        defvals["Suction_n"] = _fetch_latest(pid, sel_date_v, "night", "ทางเดินหายใจ", "Suction/การดูดเสมหะ")
        defvals["Lines_n"] = _fetch_latest(pid, sel_date_v, "night", "ทางเดินหายใจ", "จำนวนสายSuction")
        defvals["PostSuction_n"] = _fetch_latest(pid, sel_date_v, "night", "ทางเดินหายใจ", "อาการหลังSuction")

        defvals["sleep_n"] = _fetch_latest(pid, sel_date_v, "night", "กลางคืน", "การนอนหลับ")
        defvals["night_food_n"] = _fetch_latest(pid, sel_date_v, "night", "กลางคืน", "การรับประทานอาหาร")
        defvals["detail_n"] = _fetch_latest(pid, sel_date_v, "night", "กลางคืน", "รายละเอียดเพิ่มเติม")
        defvals["note_night"] = _fetch_latest(pid, sel_date_v, "night", "กลางคืน", "หมายเหตุ")
        defvals["caregiver_n"] = _fetch_latest(pid, sel_date_v, "night", "กลางคืน", "ผู้ดูแล")
        defvals["head_night"] = _fetch_latest(pid, sel_date_v, "night", "กลางคืน", "หัวหน้าเวร")

        # day
        defvals["T_d"] = _fetch_latest(pid, sel_date_v, "day", "สัญญาณชีพ", "T/อุณหภูมิ")
        defvals["BP_d"] = _fetch_latest(pid, sel_date_v, "day", "สัญญาณชีพ", "BP/ความดัน")
        defvals["HR_d"] = _fetch_latest(pid, sel_date_v, "day", "สัญญาณชีพ", "HR/อัตราการเต้นหัวใจ")
        defvals["RR_d"] = _fetch_latest(pid, sel_date_v, "day", "สัญญาณชีพ", "RR/อัตราการหายใจ")
        defvals["SpO2_d"] = _fetch_latest(pid, sel_date_v, "day", "สัญญาณชีพ", "SpO2/ค่าออกซิเจน")
        defvals["DTX_d"] = _fetch_latest(pid, sel_date_v, "day", "สัญญาณชีพ", "DTX/ระดับน้ำตาลในเลือด")
        defvals["Intake_d"] = _fetch_latest(pid, sel_date_v, "day", "สัญญาณชีพ", "Intake/น้ำเข้าร่างกาย")
        defvals["Output_d"] = _fetch_latest(pid, sel_date_v, "day", "สัญญาณชีพ", "Output/ปัสสาวะ")
        defvals["Stool_d"] = _fetch_latest(pid, sel_date_v, "day", "สัญญาณชีพ", "Stool/อุจจาระ")

        defvals["Cough_d"] = _fetch_latest(pid, sel_date_v, "day", "ทางเดินหายใจ", "อาการไอ/มีเสมหะ")
        defvals["Sputum_d"] = _fetch_latest(pid, sel_date_v, "day", "ทางเดินหายใจ", "ลักษณะ")
        defvals["Suction_d"] = _fetch_latest(pid, sel_date_v, "day", "ทางเดินหายใจ", "Suction/การดูดเสมหะ")
        defvals["Lines_d"] = _fetch_latest(pid, sel_date_v, "day", "ทางเดินหายใจ", "จำนวนสายSuction")
        defvals["PostSuction_d"] = _fetch_latest(pid, sel_date_v, "day", "ทางเดินหายใจ", "อาการหลังSuction")

        defvals["eat_normal_d"] = _fetch_latest(pid, sel_date_v, "day", "กลางวัน", "การรับประทานอาหาร")
        defvals["eat_ng_d"] = _fetch_latest(pid, sel_date_v, "day", "กลางวัน", "รับอาหารทางสายยาง")
        defvals["eat_abn_d"] = _fetch_latest(pid, sel_date_v, "day", "กลางวัน", "อาการผิดปกติหลังให้อาหาร")
        defvals["activity_d"] = _fetch_latest(pid, sel_date_v, "day", "กลางวัน", "การออกกำลังกายและกิจกรรมระหว่างวัน")
        defvals["detail_d"] = _fetch_latest(pid, sel_date_v, "day", "กลางวัน", "รายละเอียดเพิ่มเติม")
        defvals["note_day"] = _fetch_latest(pid, sel_date_v, "day", "กลางวัน", "หมายเหตุ")
        defvals["caregiver_d"] = _fetch_latest(pid, sel_date_v, "day", "กลางวัน", "ผู้ดูแล")
        defvals["head_day"] = _fetch_latest(pid, sel_date_v, "day", "กลางวัน", "หัวหน้าเวร")

        with st.form("nurse_form_all_in_one"):
            # ===== กลางคืน =====
            st.markdown("## กลางคืน (19:00-07:00 เมื่อคืน)")
            c1,c2,c3,c4,c5 = st.columns(5)
            with c1: T_n = st.text_input("T/อุณหภูมิ (กลางคืน)", key="T_n", value=defvals.get("T_n",""))
            with c2: BP_n = st.text_input("BP/ความดัน (กลางคืน)", key="BP_n", value=defvals.get("BP_n",""))
            with c3: HR_n = st.text_input("HR/อัตราการเต้นหัวใจ (กลางคืน)", key="HR_n", value=defvals.get("HR_n",""))
            with c4: RR_n = st.text_input("RR/อัตราการหายใจ (กลางคืน)", key="RR_n", value=defvals.get("RR_n",""))
            with c5: SpO2_n = st.text_input("SpO2/ค่าออกซิเจน (กลางคืน)", key="SpO2_n", value=defvals.get("SpO2_n",""))
            c6,c7,c8,c9 = st.columns(4)
            with c6: DTX_n = st.text_input("DTX/ระดับน้ำตาลในเลือด (กลางคืน)", key="DTX_n", value=defvals.get("DTX_n",""))
            with c7: Intake_n = st.text_input("Intake/น้ำเข้าร่างกาย (กลางคืน)", key="Intake_n", value=defvals.get("Intake_n",""))
            with c8: Output_n = st.text_input("Output/ปัสสาวะ (กลางคืน)", key="Output_n", value=defvals.get("Output_n",""))
            with c9: Stool_n = st.text_input("Stool/อุจจาระ (กลางคืน)", key="Stool_n", value=defvals.get("Stool_n",""))
            c10,c11,c12,c13 = st.columns(4)
            with c10: Cough_n = st.text_input("อาการไอ/มีเสมหะ (กลางคืน)", key="Cough_n", value=defvals.get("Cough_n",""))
            with c11: Sputum_n = st.text_input("ลักษณะ (กลางคืน)", key="Sputum_n", value=defvals.get("Sputum_n",""))
            with c12: Suction_n = st.text_input("Suction/การดูดเสมหะ (กลางคืน)", key="Suction_n", value=defvals.get("Suction_n",""))
            with c13: Lines_n = st.text_input("จำนวนสายSuction (กลางคืน)", key="Lines_n", value=defvals.get("Lines_n",""))
            
            cn1,cn2,cn3 = st.columns(3)
            with cn1:
                PostSuction_n = st.text_input("อาการหลังSuction (กลางคืน)", key="PostSuction_n", value=defvals.get("PostSuction_n",""))
            with cn2:
                sleep_n = st.text_input("การนอนหลับ (กลางคืน)", key="sleep_n", value=defvals.get("sleep_n",""))
            with cn3:
                night_food_n = st.text_input("การรับประทานอาหาร (กลางคืน)", key="night_food_n", value=defvals.get("night_food_n",""))
            detail_n = st.text_area("รายละเอียดเพิ่มเติม (กลางคืน)", key="detail_n", value=defvals.get("detail_n",""))
            note_night = st.text_input("หมายเหตุ (กลางคืน)", key="note_night", value=defvals.get("note_night",""))
            cgn, hnn = st.columns(2)
            with cgn: caregiver_n = st.text_input("ชื่อผู้ดูแล (กลางคืน)", key="caregiver_n", value=defvals.get("caregiver_n",""))
            with hnn: head_night = st.text_input("หัวหน้าเวร (กลางคืน)", key="head_night", value=defvals.get("head_night",""))

            st.divider()

            # ===== กลางวัน =====
            st.markdown("## กลางวัน (07:00-19:00)")
            c1d,c2d,c3d,c4d,c5d = st.columns(5)
            with c1d: T_d = st.text_input("T/อุณหภูมิ (กลางวัน)", key="T_d", value=defvals.get("T_d",""))
            with c2d: BP_d = st.text_input("BP/ความดัน (กลางวัน)", key="BP_d", value=defvals.get("BP_d",""))
            with c3d: HR_d = st.text_input("HR/อัตราการเต้นหัวใจ (กลางวัน)", key="HR_d", value=defvals.get("HR_d",""))
            with c4d: RR_d = st.text_input("RR/อัตราการหายใจ (กลางวัน)", key="RR_d", value=defvals.get("RR_d",""))
            with c5d: SpO2_d = st.text_input("SpO2/ค่าออกซิเจน (กลางวัน)", key="SpO2_d", value=defvals.get("SpO2_d",""))
            d6,d7,d8,d9 = st.columns(4)
            with d6: DTX_d = st.text_input("DTX/ระดับน้ำตาลในเลือด (กลางวัน)", key="DTX_d", value=defvals.get("DTX_d",""))
            with d7: Intake_d = st.text_input("Intake/น้ำเข้าร่างกาย (กลางวัน)", key="Intake_d", value=defvals.get("Intake_d",""))
            with d8: Output_d = st.text_input("Output/ปัสสาวะ (กลางวัน)", key="Output_d", value=defvals.get("Output_d",""))
            with d9: Stool_d = st.text_input("Stool/อุจจาระ (กลางวัน)", key="Stool_d", value=defvals.get("Stool_d",""))
            d10,d11,d12,d13 = st.columns(4)
            with d10: Cough_d = st.text_input("อาการไอ/มีเสมหะ (กลางวัน)", key="Cough_d", value=defvals.get("Cough_d",""))
            with d11: Sputum_d = st.text_input("ลักษณะ (กลางวัน)", key="Sputum_d", value=defvals.get("Sputum_d",""))
            with d12: Suction_d = st.text_input("Suction/การดูดเสมหะ (กลางวัน)", key="Suction_d", value=defvals.get("Suction_d",""))
            with d13: Lines_d = st.text_input("จำนวนสายSuction (กลางวัน)", key="Lines_d", value=defvals.get("Lines_d",""))
            
            dd1,dd2,dd3,dd4 = st.columns(4)
            with dd1:
                PostSuction_d = st.text_input("อาการหลังSuction (กลางวัน)", key="PostSuction_d", value=defvals.get("PostSuction_d",""))
            with dd2:
                eat_normal_d = st.text_input("การรับประทานอาหาร (กลางวัน)", key="eat_normal_d", value=defvals.get("eat_normal_d",""))
            with dd3:
                eat_ng_d = st.text_input("รับอาหารทางสายยาง (กลางวัน)", key="eat_ng_d", value=defvals.get("eat_ng_d",""))
            with dd4:
                eat_abn_d = st.text_input("อาการผิดปกติหลังให้อาหาร (กลางวัน)", key="eat_abn_d", value=defvals.get("eat_abn_d",""))
            activity_d = st.text_input("การออกกำลังกายและกิจกรรมระหว่างวัน (กลางวัน)", key="activity_d", value=defvals.get("activity_d",""))
            detail_d = st.text_area("รายละเอียดเพิ่มเติม (กลางวัน)", key="detail_d", value=defvals.get("detail_d",""))
            note_day = st.text_input("หมายเหตุ (กลางวัน)", key="note_day", value=defvals.get("note_day",""))
            cgd, hnd = st.columns(2)
            with cgd: caregiver_d = st.text_input("ชื่อผู้ดูแล (กลางวัน)", key="caregiver_d", value=defvals.get("caregiver_d",""))
            with hnd: head_day = st.text_input("หัวหน้าเวร (กลางวัน)", key="head_day", value=defvals.get("head_day",""))

            submit_all = st.form_submit_button('บันทึก (กลางคืน/กลางวัน)', )

        if submit_all:
            from datetime import datetime as _dt
            ts_now = _dt.combine(sel_date_v, _dt.now().time()).strftime("%Y-%m-%d %H:%M")

            def _ins(patient_id, ts_str, section, field, value, shift):
                if value in (None, ""):
                    return
                hn_row = run_query("SELECT hn FROM patients WHERE id=?", (patient_id,), fetch=True) or [{}]
                hn = (hn_row[0] or {}).get("hn")
                run_query(
                    "INSERT INTO nurse_logs (patient_id, hn, ts, shift, section, field, value, created_by) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        patient_id,
                        hn,
                        ts_str,
                        shift,
                        section,
                        field,
                        str(value),
                        (current_user() or {}).get("name"),
                    ),
                )

            def _any_filled(vals):
                return any([(str(v).strip() if isinstance(v, str) else v) for v in vals])

            # บันทึกกลางคืน
            if _any_filled([T_n,BP_n,HR_n,RR_n,SpO2_n,DTX_n,Intake_n,Output_n,Stool_n,Cough_n,Sputum_n,Suction_n,Lines_n,PostSuction_n,sleep_n,night_food_n,detail_n,note_night,caregiver_n,head_night]):
                _ins(pid, ts_now, "สัญญาณชีพ", "T/อุณหภูมิ", T_n, "night")
                _ins(pid, ts_now, "สัญญาณชีพ", "BP/ความดัน", BP_n, "night")
                _ins(pid, ts_now, "สัญญาณชีพ", "HR/อัตราการเต้นหัวใจ", HR_n, "night")
                _ins(pid, ts_now, "สัญญาณชีพ", "RR/อัตราการหายใจ", RR_n, "night")
                _ins(pid, ts_now, "สัญญาณชีพ", "SpO2/ค่าออกซิเจน", SpO2_n, "night")
                _ins(pid, ts_now, "สัญญาณชีพ", "DTX/ระดับน้ำตาลในเลือด", DTX_n, "night")
                _ins(pid, ts_now, "สัญญาณชีพ", "Intake/น้ำเข้าร่างกาย", Intake_n, "night")
                _ins(pid, ts_now, "สัญญาณชีพ", "Output/ปัสสาวะ", Output_n, "night")
                _ins(pid, ts_now, "สัญญาณชีพ", "Stool/อุจจาระ", Stool_n, "night")

                _ins(pid, ts_now, "ทางเดินหายใจ", "อาการไอ/มีเสมหะ", Cough_n, "night")
                _ins(pid, ts_now, "ทางเดินหายใจ", "ลักษณะ", Sputum_n, "night")
                _ins(pid, ts_now, "ทางเดินหายใจ", "Suction/การดูดเสมหะ", Suction_n, "night")
                _ins(pid, ts_now, "ทางเดินหายใจ", "จำนวนสายSuction", Lines_n, "night")
                _ins(pid, ts_now, "ทางเดินหายใจ", "อาการหลังSuction", PostSuction_n, "night")

                _ins(pid, ts_now, "กลางคืน", "การนอนหลับ", sleep_n, "night")
                _ins(pid, ts_now, "กลางคืน", "การรับประทานอาหาร", night_food_n, "night")
                _ins(pid, ts_now, "กลางคืน", "รายละเอียดเพิ่มเติม", detail_n, "night")
                _ins(pid, ts_now, "กลางคืน", "หมายเหตุ", note_night, "night")
                _ins(pid, ts_now, "กลางคืน", "ผู้ดูแล", caregiver_n, "night")
                _ins(pid, ts_now, "กลางคืน", "หัวหน้าเวร", head_night, "night")
                st.success("บันทึก (กลางคืน) สำเร็จ")

            # บันทึกกลางวัน
            if _any_filled([T_d,BP_d,HR_d,RR_d,SpO2_d,DTX_d,Intake_d,Output_d,Stool_d,Cough_d,Sputum_d,Suction_d,Lines_d,PostSuction_d,eat_normal_d,eat_ng_d,eat_abn_d,activity_d,detail_d,note_day,caregiver_d,head_day]):
                _ins(pid, ts_now, "สัญญาณชีพ", "T/อุณหภูมิ", T_d, "day")
                _ins(pid, ts_now, "สัญญาณชีพ", "BP/ความดัน", BP_d, "day")
                _ins(pid, ts_now, "สัญญาณชีพ", "HR/อัตราการเต้นหัวใจ", HR_d, "day")
                _ins(pid, ts_now, "สัญญาณชีพ", "RR/อัตราการหายใจ", RR_d, "day")
                _ins(pid, ts_now, "สัญญาณชีพ", "SpO2/ค่าออกซิเจน", SpO2_d, "day")
                _ins(pid, ts_now, "สัญญาณชีพ", "DTX/ระดับน้ำตาลในเลือด", DTX_d, "day")
                _ins(pid, ts_now, "สัญญาณชีพ", "Intake/น้ำเข้าร่างกาย", Intake_d, "day")
                _ins(pid, ts_now, "สัญญาณชีพ", "Output/ปัสสาวะ", Output_d, "day")
                _ins(pid, ts_now, "สัญญาณชีพ", "Stool/อุจจาระ", Stool_d, "day")

                _ins(pid, ts_now, "ทางเดินหายใจ", "อาการไอ/มีเสมหะ", Cough_d, "day")
                _ins(pid, ts_now, "ทางเดินหายใจ", "ลักษณะ", Sputum_d, "day")
                _ins(pid, ts_now, "ทางเดินหายใจ", "Suction/การดูดเสมหะ", Suction_d, "day")
                _ins(pid, ts_now, "ทางเดินหายใจ", "จำนวนสายSuction", Lines_d, "day")
                _ins(pid, ts_now, "ทางเดินหายใจ", "อาการหลังSuction", PostSuction_d, "day")

                _ins(pid, ts_now, "กลางวัน", "การรับประทานอาหาร", eat_normal_d, "day")
                _ins(pid, ts_now, "กลางวัน", "รับอาหารทางสายยาง", eat_ng_d, "day")
                _ins(pid, ts_now, "กลางวัน", "อาการผิดปกติหลังให้อาหาร", eat_abn_d, "day")
                _ins(pid, ts_now, "กลางวัน", "การออกกำลังกายและกิจกรรมระหว่างวัน", activity_d, "day")
                _ins(pid, ts_now, "กลางวัน", "รายละเอียดเพิ่มเติม", detail_d, "day")
                _ins(pid, ts_now, "กลางวัน", "หมายเหตุ", note_day, "day")
                _ins(pid, ts_now, "กลางวัน", "ผู้ดูแล", caregiver_d, "day")
                _ins(pid, ts_now, "กลางวัน", "หัวหน้าเวร", head_day, "day")
                st.success("บันทึก (กลางวัน) สำเร็จ")
    with tabs[2]:
        st.subheader("ทีมกายภาพ")

        # Guard + Banner
        pid = st.session_state.get("patient_id")
        if not pid:
            st.info("เลือกคนไข้ก่อน")
            st.stop()
        render_patient_banner(pid)

        editable = can_edit_page("physio")
        if not editable:
            st.caption("**โหมดอ่านอย่างเดียว**: คุณไม่มีสิทธิ์แก้ไขหน้านี้")

        # Type + Date (no future)
        physio_type = st.radio("ประเภทกายภาพ", ["กายภาพพื้นฐาน","กายภาพฟื้นฟู"], horizontal=True, key="physio_type_sel")
        ptype_code = "basic" if physio_type == "กายภาพพื้นฐาน" else "rehab"

        from datetime import date as _date, datetime as _dt
        _today = _date.today()
        default_date = st.session_state.get("physio_date") or _today
        if default_date > _today:
            default_date = _today
        sel_date_p = st.date_input("วันที่ทำกายภาพ", value=default_date, max_value=_today, key="physio_date")

        # React to date/type change: clear widget states for physio form
        prev_date = st.session_state.get("physio_date_prev")
        prev_type = st.session_state.get("physio_type_prev")
        if prev_date != sel_date_p or prev_type != ptype_code:
            for k in [
                "pre_bp","pre_hr","pre_rr","pre_spo2","pre_sym",
                "post_bp","post_hr","post_rr","post_spo2","post_sym",
                "activity","result","remark","assistant","physio_name","note",
                "e_min","e_act","e_res",
                "f_min","f_act","f_res",
                "g_dist","g_act","g_res",
                "el_min","el_act","el_res",
                "sp_min","sp_act1","sp_res1","sp_act2","sp_res2",
                "cg_min","cg_act","cg_res"
            ]:
                st.session_state.pop(k, None)
            st.session_state["physio_date_prev"] = sel_date_p
            st.session_state["physio_type_prev"] = ptype_code

        # Prefill helper (use physio_type column)
        def _fetch_physio(patient_id, log_date_iso, physio_type, section, field):
            rows = run_query("""
                SELECT value FROM physio_logs
                WHERE patient_id=? AND log_date=? AND physio_type=? AND section=? AND field=?
                ORDER BY id DESC LIMIT 1
                """,
                (patient_id, log_date_iso, physio_type, section, field),
                fetch=True
            )
            if rows:
                r0 = rows[0]
                return r0.get("value") if isinstance(r0, dict) else (r0[0] if r0 else "")
            return ""

        # Build defvals
        defvals = {}
        # Vital pre
        for fld, key in [("BP","pre_bp"),("HR","pre_hr"),("RR","pre_rr"),("SpO2","pre_spo2"),("Symptoms","pre_sym")]:
            defvals[key] = _fetch_physio(pid, sel_date_p.isoformat(), ptype_code, "Vital (pre)", fld)
        # Vital post
        for fld, key in [("BP","post_bp"),("HR","post_hr"),("RR","post_rr"),("SpO2","post_spo2"),("Symptoms","post_sym")]:
            defvals[key] = _fetch_physio(pid, sel_date_p.isoformat(), ptype_code, "Vital (post)", fld)

        # Basic
        for fld, key in [("Activity","activity"),("Result","result"),("Remark","remark"),("Assistant","assistant")]:
            defvals[key] = _fetch_physio(pid, sel_date_p.isoformat(), ptype_code, "Basic", fld)

        # Rehab groups
        key_map = {
            ("Exercise","Minutes"): "e_min", ("Exercise","Activity"): "e_act", ("Exercise","Result"): "e_res",
            ("Functional","Minutes"): "f_min", ("Functional","Activity"): "f_act", ("Functional","Result"): "f_res",
            ("Gait","Distance (m)"): "g_dist", ("Gait","Activity"): "g_act", ("Gait","Result"): "g_res",
            ("Electrical","Minutes"): "el_min", ("Electrical","Activity"): "el_act", ("Electrical","Result"): "el_res",
            ("Speech","Minutes"): "sp_min", ("Speech","Activity1"): "sp_act1", ("Speech","Result1"): "sp_res1",
            ("Speech","Activity2"): "sp_act2", ("Speech","Result2"): "sp_res2",
            ("Cognitive","Minutes"): "cg_min", ("Cognitive","Activity"): "cg_act", ("Cognitive","Result"): "cg_res",
        }
        for (sec, fld), key in key_map.items():
            defvals[key] = _fetch_physio(pid, sel_date_p.isoformat(), ptype_code, sec, fld)

        # Meta
        defvals["physio_name"] = _fetch_physio(pid, sel_date_p.isoformat(), ptype_code, "Meta", "Physio")
        defvals["note"] = _fetch_physio(pid, sel_date_p.isoformat(), ptype_code, "Meta", "Note")

        with st.form("physio_form"):
            # Vital signs (pre)
            st.markdown("### Vital signs ก่อนทำ")
            c1,c2,c3,c4,c5 = st.columns(5)
            with c1: pre_bp = st.text_input("BP ก่อน", key="pre_bp", value=defvals.get("pre_bp",""))
            with c2: pre_hr = st.text_input("HR ก่อน", key="pre_hr", value=defvals.get("pre_hr",""))
            with c3: pre_rr = st.text_input("RR ก่อน", key="pre_rr", value=defvals.get("pre_rr",""))
            with c4: pre_spo2 = st.text_input("SpO2 ก่อน", key="pre_spo2", value=defvals.get("pre_spo2",""))
            with c5: pre_sym = st.text_input("Symptoms ก่อน", key="pre_sym", value=defvals.get("pre_sym",""))

            # Vital signs (post)
            st.markdown("### Vital signs หลังทำ")
            c6,c7,c8,c9,c10 = st.columns(5)
            with c6: post_bp = st.text_input("BP หลัง", key="post_bp", value=defvals.get("post_bp",""))
            with c7: post_hr = st.text_input("HR หลัง", key="post_hr", value=defvals.get("post_hr",""))
            with c8: post_rr = st.text_input("RR หลัง", key="post_rr", value=defvals.get("post_rr",""))
            with c9: post_spo2 = st.text_input("SpO2 หลัง", key="post_spo2", value=defvals.get("post_spo2",""))
            with c10: post_sym = st.text_input("Symptoms หลัง", key="post_sym", value=defvals.get("post_sym",""))

            if ptype_code == "basic":
                st.markdown("### กายภาพพื้นฐาน (Basic)")
                activity = st.text_input("กิจกรรม — Basic", key="activity", value=defvals.get("activity",""))
                result = st.text_input("ผลลัพธ์ — Basic", key="result", value=defvals.get("result",""))
                remark = st.text_input("หมายเหตุ — Basic", key="remark", value=defvals.get("remark",""))
                assistant = st.text_input("ผู้ช่วย (ถ้ามี)", key="assistant", value=defvals.get("assistant",""))
            else:
                st.markdown("### กายภาพฟื้นฟู (Rehab)")
                st.markdown("#### Exercise")
                e_min = st.text_input("เวลา (นาที) — Exercise", key="e_min", value=defvals.get("e_min",""))
                e_act = st.text_input("กิจกรรม — Exercise", key="e_act", value=defvals.get("e_act",""))
                e_res = st.text_input("ผลลัพธ์ — Exercise", key="e_res", value=defvals.get("e_res",""))

                st.markdown("#### Functional movement")
                f_min = st.text_input("เวลา (นาที) — Functional", key="f_min", value=defvals.get("f_min",""))
                f_act = st.text_input("กิจกรรม — Functional", key="f_act", value=defvals.get("f_act",""))
                f_res = st.text_input("ผลลัพธ์ — Functional", key="f_res", value=defvals.get("f_res",""))

                st.markdown("#### Gait analysis")
                g_dist = st.text_input("ระยะทาง (เมตร)", key="g_dist", value=defvals.get("g_dist",""))
                g_act = st.text_input("กิจกรรม — Gait", key="g_act", value=defvals.get("g_act",""))
                g_res = st.text_input("ผลลัพธ์ — Gait", key="g_res", value=defvals.get("g_res",""))

                st.markdown("#### Electrical")
                el_min = st.text_input("เวลา (นาที) — Electrical", key="el_min", value=defvals.get("el_min",""))
                el_act = st.text_input("กิจกรรม — Electrical", key="el_act", value=defvals.get("el_act",""))
                el_res = st.text_input("ผลลัพธ์ — Electrical", key="el_res", value=defvals.get("el_res",""))

                st.markdown("#### Speech therapy")
                sp_min = st.text_input("เวลา (นาที) — Speech", key="sp_min", value=defvals.get("sp_min",""))
                sp_act1 = st.text_input("กิจกรรม1 — Speech", key="sp_act1", value=defvals.get("sp_act1",""))
                sp_res1 = st.text_input("ผลลัพธ์1 — Speech", key="sp_res1", value=defvals.get("sp_res1",""))
                sp_act2 = st.text_input("กิจกรรม2 — Speech", key="sp_act2", value=defvals.get("sp_act2",""))
                sp_res2 = st.text_input("ผลลัพธ์2 — Speech", key="sp_res2", value=defvals.get("sp_res2",""))

                st.markdown("#### Cognitive training")
                cg_min = st.text_input("เวลา (นาที) — Cognitive", key="cg_min", value=defvals.get("cg_min",""))
                cg_act = st.text_input("กิจกรรม — Cognitive", key="cg_act", value=defvals.get("cg_act",""))
                cg_res = st.text_input("ผลลัพธ์ — Cognitive", key="cg_res", value=defvals.get("cg_res",""))

            st.markdown("### ข้อมูลผู้ปฏิบัติ/หมายเหตุ")
            physio_name = st.text_input("ชื่อนักกายภาพ", key="physio_name", value=defvals.get("physio_name", (current_user().get("name") if current_user() else "")))
            note = st.text_area("หมายเหตุ (กายภาพ)", key="note", value=defvals.get("note",""))

            submit_physio = st.form_submit_button("บันทึกกายภาพ", disabled=not editable)

        # Handle submit
        if submit_physio and editable:
            entries = []
            # Vital pre
            entries += [("Vital (pre)","BP", pre_bp), ("Vital (pre)","HR", pre_hr), ("Vital (pre)","RR", pre_rr), ("Vital (pre)","SpO2", pre_spo2), ("Vital (pre)","Symptoms", pre_sym)]
            # Vital post
            entries += [("Vital (post)","BP", post_bp), ("Vital (post)","HR", post_hr), ("Vital (post)","RR", post_rr), ("Vital (post)","SpO2", post_spo2), ("Vital (post)","Symptoms", post_sym)]

            if ptype_code == "basic":
                entries += [("Basic","Activity", activity), ("Basic","Result", result), ("Basic","Remark", remark), ("Basic","Assistant", assistant)]
            else:
                entries += [("Exercise","Minutes", e_min), ("Exercise","Activity", e_act), ("Exercise","Result", e_res)]
                entries += [("Functional","Minutes", f_min), ("Functional","Activity", f_act), ("Functional","Result", f_res)]
                entries += [("Gait","Distance (m)", g_dist), ("Gait","Activity", g_act), ("Gait","Result", g_res)]
                entries += [("Electrical","Minutes", el_min), ("Electrical","Activity", el_act), ("Electrical","Result", el_res)]
                entries += [("Speech","Minutes", sp_min), ("Speech","Activity1", sp_act1), ("Speech","Result1", sp_res1), ("Speech","Activity2", sp_act2), ("Speech","Result2", sp_res2)]
                entries += [("Cognitive","Minutes", cg_min), ("Cognitive","Activity", cg_act), ("Cognitive","Result", cg_res)]

            for sec, fld, val in entries:
                if val not in (None, ""):
                    run_query(
                        "INSERT INTO physio_logs (patient_id, log_date, physio_type, section, field, value, created_by) VALUES (?,?,?,?,?,?,?)",
                        (pid, sel_date_p.isoformat(), ptype_code, sec, fld, str(val), (current_user() or {}).get("name"))
                    )
            st.success("บันทึกแล้ว")

        # Print A4
        if pid:
            html = build_physio_inputlike_print_html(run_query, get_logo_path, calc_age_ymd, pid, sel_date_p.isoformat())
            download_print_button(st, "🖨️ พิมพ์/ดาวน์โหลด (A4) — ทีมกายภาพ", html, f"physio_{pid}_{sel_date_p.isoformat()}.html")

    # ---- Tabs fallback (safety) ----
    if 'tabs' not in locals():
        tabs = st.tabs([
            'ข้อมูลคนไข้', 'ทีมพยาบาล (Vitals)', 'ทีมกายภาพ', 'เวชระเบียนยา'
        ])
    with tabs[3]:
        from pathlib import Path
        from datetime import date as _date
        st.subheader("เวชระเบียนยา")

        # --- Ensure medications columns exist ---
        try:
            cols = run_query("PRAGMA table_info(medications)", fetch=True) or []
            def _colname(c): 
                try: return c.get("name")
                except: return c[1]
            colnames = [ _colname(c) for c in cols ]
            if "start_date" not in colnames:
                run_query("ALTER TABLE medications ADD COLUMN start_date TEXT")
            if "note" not in colnames:
                run_query("ALTER TABLE medications ADD COLUMN note TEXT")
            if "active" not in colnames:
                run_query("ALTER TABLE medications ADD COLUMN active INTEGER DEFAULT 1")
            if "inactive_date" not in colnames:
                run_query("ALTER TABLE medications ADD COLUMN inactive_date TEXT")
        except Exception as _e:
            pass
    
        render_patient_banner(pid)
        if not pid:
            st.info("เลือกคนไข้ก่อน")
        else:
            editable = can_edit_page("meds")

        # === Summary table (Active meds) ===
        st.markdown("### สรุปยา (Active)")
        timing_rank = {"ก่อนอาหาร": 0, "หลังอาหาร": 1}
        meal_rank = {"เช้า": 0, "กลางวัน": 2, "เย็น": 4, "ก่อนนอน": 6}
        rows = run_query(
            "SELECT id, meal_times, meal_times_other, timing_radio, timing_other, drug_name, drug_type, how_to, start_date, note, image_path, COALESCE(active,1) as active FROM medications WHERE patient_id=? AND COALESCE(active,1)=1 ORDER BY created_at DESC",
            (pid,), fetch=True
        ) or []

        expanded = []
        for r in rows:
            is_dict = isinstance(r, dict)
            mt = (r.get("meal_times") if is_dict else r[1]) or ""
            mt = [m.strip() for m in mt.split(",") if m and m.strip()]
            timing = (r.get("timing_radio") if is_dict else r[3]) or ""
            drug_name = (r.get("drug_name") if is_dict else r[5]) or ""
            drug_type = (r.get("drug_type") if is_dict else r[6]) or ""
            how_to = (r.get("how_to") if is_dict else r[7]) or ""
            start_date = (r.get("start_date") if is_dict else (None if len(r) < 9 else r[8])) or ""
            note = (r.get("note") if is_dict else (None if len(r) < 10 else r[9])) or ""
            image_path = (r.get("image_path") if is_dict else (None if len(r) < 11 else r[10]))
            rid = r.get("id") if is_dict else r[0]

            def classify(mt_list, timing_val):
                if timing_val not in ("ก่อนอาหาร","หลังอาหาร"):
                    return [("ยาเพิ่มเติม", 99)]
                out = []
                any_other = False
                for m in mt_list:
                    if m == "อื่นๆ":
                        any_other = True
                        continue
                    if m in ("เช้า","กลางวัน","เย็น"):
                        rank = timing_rank.get(timing_val, 10) + meal_rank.get(m, 10)
                        out.append((f"{timing_val}{m}", rank))
                    elif m == "ก่อนนอน":
                        out.append(("ยาเพิ่มเติม", 99))
                    else:
                        any_other = True
                if any_other or not out:
                    out.append(("ยาเพิ่มเติม", 99))
                return out

            for label, rank in classify(mt, timing):
                expanded.append({
                    "rid": rid, "rank": rank, "label": label,
                    "image_path": image_path, "drug_name": drug_name, "drug_type": drug_type,
                    "how_to": how_to, "start_date": start_date, "note": note
                })

        expanded.sort(key=lambda x: (x["rank"], x["drug_name"]))

        if expanded:
            
            # ตารางหัวคอลัมน์ 8 ช่อง (เพิ่ม "การกระทำ")
            c_cols = st.columns([2,2,3,2,3,2,2,2])
            headers = ["มื้อ/เวลา","รูปภาพ","ชื่อยา","ประเภทยา","วิธีรับประทาน","วันที่เริ่มรับประทานยา","หมายเหตุ","การกระทำ"]
            for c,h in zip(c_cols, headers):
                with c: st.markdown(f"**{h}**")

            for idx, row in enumerate(expanded):
                rid = row["rid"]
                c1,c2,c3,c4,c5,c6,c7,c8 = st.columns([2,2,3,2,3,2,2,2])
                with c1: st.write(row["label"])
                with c2:
                    if row.get("image_path"):
                        try: st.image(row["image_path"], width=80)
                        except Exception: st.write("-")
                    else:
                        st.write("-")
                with c3: st.write(row.get("drug_name") or "-")
                with c4: st.write(row.get("drug_type") or "-")
                with c5: st.write(row.get("how_to") or "-")
                with c6: st.write(row.get("start_date") or "-")
                with c7: st.write(row.get("note") or "-")
                with c8:
                    import hashlib
                    label_str = str(row.get("label",""))
                    label_hash = hashlib.md5(label_str.encode("utf-8")).hexdigest()[:8]
                    key_suffix = f"{rid}_{label_hash}_{idx}"
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("แก้ไข", key=f"med_edit_{key_suffix}", use_container_width=False):
                            st.session_state["med_edit_id"] = rid
                            st.rerun()
                    with b2:
                        if st.button("Inactive", key=f"med_inact_{key_suffix}", use_container_width=False, disabled=not editable):
                            # Per-meal inactive: remove only the clicked meal from meal_times; if none left -> inactive the med
                            _rows = run_query("SELECT meal_times FROM medications WHERE id=?", (rid,), fetch=True) or []
                            _mt = []
                            if _rows:
                                r0 = _rows[0]
                                if isinstance(r0, dict):
                                    _raw = r0.get("meal_times")
                                else:
                                    # sqlite3.Row or tuple-like
                                    try:
                                        _raw = r0["meal_times"]
                                    except Exception:
                                        _raw = r0[0] if r0 else ""
                                _raw = _raw or ""
                                _mt = [m.strip() for m in str(_raw).split(",") if m and m.strip()]

                            # Determine which meal to remove based on the label shown
                            _rm = None
                            if "เช้า" in label_str:
                                _rm = "เช้า"
                            elif "กลางวัน" in label_str:
                                _rm = "กลางวัน"
                            elif "เย็น" in label_str:
                                _rm = "เย็น"
                            elif "ก่อนนอน" in label_str:
                                _rm = "ก่อนนอน"
                            elif "อื่นๆ" in label_str:
                                _rm = "อื่นๆ"

                            # build new meal_times list
                            if _rm is not None:
                                try:
                                    _mt.remove(_rm)
                                except ValueError:
                                    pass

                            _new_mt_str = (",".join(_mt) if _mt else None)
                            if _new_mt_str:
                                run_query("UPDATE medications SET meal_times=? WHERE id=?", (_new_mt_str, rid))
                            else:
                                run_query("UPDATE medications SET active=0, inactive_date=date('now') WHERE id=?", (rid,))
                            st.rerun()
        # History & Print sections
        if st.button("🕓 ดูประวัติยา (History)"):
            st.session_state["show_meds_history"] = True

        if st.session_state.get("show_meds_history"):
            st.markdown("### ประวัติยา (Inactive) — ล่าสุดอยู่บนสุด")
            hist = run_query(
                "SELECT id, drug_name, drug_type, how_to, start_date, inactive_date, note FROM medications WHERE patient_id=? AND COALESCE(active,1)=0 ORDER BY COALESCE(inactive_date, date('now')) DESC, id DESC",
                (pid,), fetch=True
            ) or []
            if hist:
                hc = st.columns([3,2,3,2,3,3])
                for c,h in zip(hc, ["ชื่อยา","ประเภทยา","วิธีรับประทาน","วันที่เริ่ม","วันที่หยุด","หมายเหตุ"]):
                    with c: st.markdown(f"**{h}**")
                for r in hist:
                    isd = isinstance(r, dict)
                    vals = [
                        (r.get("drug_name") if isd else r[1]) or "-",
                        (r.get("drug_type") if isd else r[2]) or "-",
                        (r.get("how_to") if isd else r[3]) or "-",
                        (r.get("start_date") if isd else r[4]) or "-",
                        (r.get("inactive_date") if isd else r[5]) or "-",
                        (r.get("note") if isd else r[6]) or "-",
                    ]
                    ncols = st.columns([3,2,3,2,3,3])
                    for c,v in zip(ncols, vals):
                        with c: st.write(v)
            else:
                st.info("ยังไม่มีประวัติการหยุดยา")
            st.divider()

        # Print A4 for meds (by selected date)
        if pid:
            from datetime import date as _date
            sel_date_m = st.date_input("วันที่พิมพ์รายการยา", value=_date.today(), key="meds_date")
            from print_utils import build_meds_print_html
            html = build_meds_print_html(run_query, get_logo_path, calc_age_ymd, pid, sel_date_m.isoformat())
            download_print_button(st, "🖨️ พิมพ์/ดาวน์โหลด (A4) — ห้องยา", html, f"meds_{pid}_{sel_date_m.isoformat()}.html")
        # ==== Prefill for edit mode ====
        edit_id = st.session_state.get("med_edit_id")
        pre = {}
        if edit_id:
            _rows = run_query("SELECT * FROM medications WHERE id=?", (edit_id,), fetch=True) or []
            pre = _rows[0] if _rows else {}

        from datetime import date as __date, datetime as _dt

        def _split_meals(s):
            return [m.strip() for m in str(s or "").split(",") if m and m.strip()]

        _def_meals = _split_meals(pre.get("meal_times"))
        _t_opts = ["ก่อนอาหาร","หลังอาหาร","อื่นๆ"]
        _t_def = pre.get("timing_radio") if pre.get("timing_radio") in _t_opts else "อื่นๆ"
        try:
            _def_sd = __date.fromisoformat(pre.get("start_date")) if pre.get("start_date") else __date.today()
        except Exception:
            _def_sd = __date.today()

        with st.form("med_form"):
            meal_times = st.multiselect("มื้อ", ["เช้า","กลางวัน","เย็น","ก่อนนอน","อื่นๆ"], default=_def_meals, key="f_meal_times")
            meal_times_other = st.text_input("อื่นๆ (ถ้ามี)", value=pre.get("meal_times_other") or "", key="f_meal_times_other")
            timing = st.radio("การทานยา", _t_opts, index=_t_opts.index(_t_def), horizontal=True, key="f_timing")
            timing_other = st.text_input("อื่นๆ (เวลาทาน)", value=pre.get("timing_other") or "", key="f_timing_other")
            drug_name = st.text_input("ชื่อยา", value=pre.get("drug_name") or "", key="f_drug_name")
            drug_type = st.text_input("ประเภทยา", value=pre.get("drug_type") or "", key="f_drug_type")
            how_to = st.text_input("วิธีทานยา", value=pre.get("how_to") or "", key="f_how_to")
            note_val = st.text_input("หมายเหตุ", value=pre.get("note") or "", key="f_note")
            start_date_val = st.date_input("วันที่เริ่มรับประทานยา", value=_def_sd, key="f_start_date")

            if pre.get("image_path"):
                try:
                    st.image(pre.get("image_path"), width=120, caption="รูปเดิม")
                except Exception:
                    pass
            up_img = st.file_uploader("รูปยา (PNG/JPG)", type=["png","jpg","jpeg"], key="f_img")

            resp_default = pre.get("responsible") if pre.get("responsible") else (current_user().get("name") if current_user() else "")
            responsible = st.text_input("ผู้รับผิดชอบ", value=resp_default, key="f_responsible")

            submit_med = st.form_submit_button("บันทึกยา", disabled=not editable, )


        # ----- Minimal validation (ตามที่ร้องขอ) -----
        errors = []
        if not (meal_times and len(meal_times) > 0):
            errors.append("กรุณาเลือก **มื้อยา**")
        if not (drug_name or "").strip():
            errors.append("กรุณากรอก **ชื่อยา**")
        if not (drug_type or "").strip():
            errors.append("กรุณากรอก **ประเภทยา**")
        if submit_med and errors:
            st.error("โปรดแก้ไขข้อมูลก่อนบันทึก:\n- " + "\n- ".join(errors))

        if submit_med and editable and not errors:
            from pathlib import Path as _Path
            img_path = pre.get("image_path") if pre else None

            # Save new image if uploaded
            up = st.session_state.get("f_img")
            if up is not None:
                save_dir = _Path("uploads/meds") / str(pid)
                save_dir.mkdir(parents=True, exist_ok=True)
                ext = (up.name.split(".")[-1] or "jpg").lower()
                fname = f"med_{int(_dt.now().timestamp())}.{ext}"
                fpath = save_dir / fname
                with open(fpath, "wb") as f:
                    f.write(up.getbuffer())
                img_path = str(fpath)

            if edit_id:
                # UPDATE existing medication
                run_query(
                    """UPDATE medications SET
                    meal_times=?, meal_times_other=?, timing_radio=?, timing_other=?,
                    drug_name=?, drug_type=?, how_to=?, responsible=?,
                    start_date=?, note=?, image_path=?
                    WHERE id=?""",
                    (
                        ",".join(meal_times) if meal_times else None,
                        meal_times_other or None,
                        timing or None,
                        timing_other or None,
                        drug_name or None,
                        drug_type or None,
                        how_to or None,
                        responsible or None,
                        start_date_val.isoformat(),
                        note_val or None,
                        img_path,
                        edit_id
                    )
                )
                st.success("อัปเดตยาสำเร็จ")
            else:
                # INSERT new medication
                run_query(
                    """INSERT INTO medications (
                    patient_id, meal_times, meal_times_other, timing_radio, timing_other,
                    image_path, drug_name, drug_type, how_to, responsible, created_by,
                    start_date, note, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (
                        pid,
                        ",".join(meal_times) if meal_times else None,
                        meal_times_other or None,
                        timing or None,
                        timing_other or None,
                        img_path,
                        drug_name or None,
                        drug_type or None,
                        how_to or None,
                        responsible or None,
                        (current_user().get("name") if current_user() else None),
                        start_date_val.isoformat(),
                        note_val or None
                    )
                )
                st.success("บันทึกแล้ว")

            # Clear form state + exit edit mode
            for k in ["f_meal_times","f_meal_times_other","f_timing","f_timing_other","f_drug_name","f_drug_type","f_how_to","f_note","f_start_date","f_img","f_responsible"]:
                st.session_state.pop(k, None)
            st.session_state.pop("med_edit_id", None)
            st.rerun()

if __name__ == "__main__":
    main()