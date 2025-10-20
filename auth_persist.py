# auth_persist.py
import os, time, hmac, hashlib, base64, json

SECRET = os.getenv("HH_APP_SECRET", "PLEASE_CHANGE_ME")
DEBUG = os.getenv("HH_DEBUG", "").strip().lower() in ("1","true","yes","on")

def _b64u(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def _unb64u(s: str) -> bytes:
    import base64
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))

def _sign(msg: bytes) -> str:
    sig = hmac.new(SECRET.encode("utf-8"), msg, hashlib.sha256).digest()
    return _b64u(sig)

def create_token(claims: dict, exp_seconds: int = 7*24*3600) -> str:
    now = int(time.time())
    payload = dict(claims)
    payload.setdefault("iat", now)
    payload.setdefault("exp", now + exp_seconds)
    body = _b64u(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _sign(body.encode("ascii"))
    return f"{body}.{sig}"

def verify_token(token: str) -> dict | None:
    if not token or "." not in token:
        return None
    body, sig = token.split(".", 1)
    if _sign(body.encode("ascii")) != sig:
        return None
    try:
        payload = json.loads(_unb64u(body).decode("utf-8"))
    except Exception:
        return None
    now = int(time.time())
    if int(payload.get("exp", 0)) < now:
        return None
    return payload

def _get_qs_token(st) -> str | None:
    token = None
    try:
        q = st.query_params
        if isinstance(q, dict):
            token = q.get("auth")
            if isinstance(token, list):
                token = token[0] if token else None
    except Exception:
        pass
    if not token:
        try:
            q = st.experimental_get_query_params()
            token = q.get("auth", [None])[0]
        except Exception:
            pass
    return token

def _set_qs_token(st, token: str | None):
    try:
        if token is not None:
            st.query_params.update({"auth": token})
        else:
            qp = dict(st.query_params)
            qp.pop("auth", None)
            st.query_params.clear()
            if qp:
                st.query_params.update(qp)
        return True
    except Exception:
        pass
    try:
        if token is not None:
            st.experimental_set_query_params(auth=token)
        else:
            st.experimental_set_query_params()
        return True
    except Exception:
        return False

def persist_login(st, user_dict: dict) -> str:
    token = create_token({
        "uid": user_dict.get("id"),
        "un": user_dict.get("username") or user_dict.get("name") or "",
        "role": user_dict.get("role") or ""
    })
    _set_qs_token(st, token)
    if DEBUG:
        st.sidebar.caption("persist_login(): token set via _set_qs_token (best effort).")
    return token

def force_auth_in_url(st, token: str, reload: bool = True):
    import streamlit.components.v1 as components
    js = "<script>(function(){try{var u=new URL(window.location.href);var t='%s';if(u.searchParams.get('auth')!==t){u.searchParams.set('auth',t);window.history.replaceState(null,'',u.toString());}%s}catch(e){console.error('force_auth_in_url',e);}})();</script>" % (token, "location.reload();" if reload else "")
    components.html(js, height=0)
    if DEBUG:
        st.sidebar.caption("force_auth_in_url(): injected JS to set ?auth=.")

def clear_persisted_login(st, reload: bool = False):
    ok = _set_qs_token(st, None)
    if DEBUG:
        st.sidebar.caption("clear_persisted_login(): clear via _set_qs_token -> " + ("OK" if ok else "fallback JS"))
    if ok:
        return
    import streamlit.components.v1 as components
    js = "<script>(function(){try{var u=new URL(window.location.href);if(u.searchParams.has('auth')){u.searchParams.delete('auth');window.history.replaceState(null,'',u.toString());}%s}catch(e){console.error('clear_persisted_login',e);}})();</script>" % ("location.reload();" if reload else "")
    components.html(js, height=0)

def auto_login_from_qs(st, lookup_user_by_id):
    if st.session_state.get("user"):
        return st.session_state["user"]
    token = _get_qs_token(st)
    if not token:
        return None
    payload = verify_token(token)
    if not payload:
        return None
    uid = payload.get("uid")
    if not uid:
        return None
    u = lookup_user_by_id(uid)
    if not u:
        return None
    user_dict = {
        "id": u.get("id"),
        "name": u.get("name") or "",
        "role": u.get("role") or "",
        "username": u.get("username") or u.get("email") or "",
    }
    st.session_state["user"] = user_dict
    return user_dict

def ensure_auth_param(st, user_dict: dict, reload: bool = False):
    if not user_dict:
        return
    try:
        existing = _get_qs_token(st)
    except Exception:
        existing = None
    if existing:
        return
    token = create_token({
        "uid": user_dict.get("id"),
        "un": user_dict.get("username") or user_dict.get("name") or "",
        "role": user_dict.get("role") or ""
    })
    ok = _set_qs_token(st, token)
    if DEBUG:
        st.sidebar.caption("ensure_auth_param(): set via _set_qs_token -> " + ("OK" if ok else "fallback JS"))
    if not ok:
        force_auth_in_url(st, token, reload=reload)
