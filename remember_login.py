
# remember_login.py — simple persistent login via signed token in URL (?authtoken=<token>)
# - Requires: streamlit>=1.25 (uses st.query_params), your app must provide run_query(sql, params, fetch)
# - Set HH_SECRET in environment for stronger signing, else fallback to a default (change it!)
import os, hashlib, secrets
from datetime import datetime, timedelta
import streamlit as st

def _secret() -> str:
    s = os.getenv("HH_SECRET", "").strip()
    return s if s else "change-this-secret"

def _hash_token(token: str) -> str:
    m = hashlib.sha256()
    m.update((token + _secret()).encode("utf-8"))
    return m.hexdigest()

def ensure_tables(run_query):
    run_query(
        """
        CREATE TABLE IF NOT EXISTS auth_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT,
            is_revoked INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_auth_token_hash ON auth_tokens(token_hash);
        """
    )

def _set_query_param_token(token: str):
    try:
        qp = dict(st.query_params)
        qp["authtoken"] = token
        st.query_params = qp
    except Exception:
        # Fallback old API
        st.experimental_set_query_params(authtoken=token)

def _clear_query_param_token():
    try:
        qp = dict(st.query_params)
        if "authtoken" in qp:
            del qp["authtoken"]
        st.query_params = qp
    except Exception:
        st.experimental_set_query_params()

def create_persistent_login(user_id: int, run_query, days_valid: int = 30) -> str:
    """Create a new token for the user, store hashed in DB, set to URL query params, and return the raw token."""
    ensure_tables(run_query)
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    exp = (datetime.utcnow() + timedelta(days=days_valid)).strftime("%Y-%m-%d %H:%M:%S")
    run_query("INSERT INTO auth_tokens (user_id, token_hash, expires_at) VALUES (?,?,?)", (user_id, token_hash, exp))
    _set_query_param_token(token)
    return token

def get_user_from_token(run_query):
    """If ?authtoken=... exists and valid, fetch and return a user dict (id, name, role, username)."""
    try:
        token = st.query_params.get("authtoken", None)
        if isinstance(token, list): token = token[0] if token else None
    except Exception:
        # Fallback
        token = None
    if not token:
        return None
    token_hash = _hash_token(token)
    rows = run_query(
        """
        SELECT s.id, s.name, s.role, COALESCE(s.username, s.email) AS username
        FROM auth_tokens t
        JOIN staff s ON s.id = t.user_id
        WHERE t.token_hash=? AND t.is_revoked=0 AND (t.expires_at IS NULL OR t.expires_at >= datetime('now')) AND s.is_active=1
        ORDER BY t.id DESC LIMIT 1
        """,
        (token_hash,), fetch=True
    )
    if not rows: 
        return None
    u = rows[0]
    # Optional: extend expiry (sliding window)
    try:
        run_query("UPDATE auth_tokens SET expires_at=datetime('now','+30 days') WHERE token_hash=? AND is_revoked=0", (token_hash,))
    except Exception:
        pass
    return {"id": u["id"], "name": u["name"], "role": u["role"], "username": u["username"]}

def revoke_current_token(run_query):
    """Revoke token present in URL and clear query param."""
    try:
        token = st.query_params.get("authtoken", None)
        if isinstance(token, list): token = token[0] if token else None
    except Exception:
        token = None
    if token:
        token_hash = _hash_token(token)
        run_query("UPDATE auth_tokens SET is_revoked=1 WHERE token_hash=?", (token_hash,))
    _clear_query_param_token()
