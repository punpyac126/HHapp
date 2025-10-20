# HHapp2 Auth Patch Bundle (20250902_045920)

This bundle includes:
- `auth_persist.py` — helpers to create/verify token, write `?auth=`, JS fallback, clear, ensure.
- `app_login_persist_patch.py` — a safe patcher that **adds** auth persistence to your existing `app.py` without overwriting your forms.

## How to use
1) Put both files next to your `app.py`.
2) Patch your app once:
   ```bash
   python3 app_login_persist_patch.py
   ```
   You should see: `✅ Applied robust auth patch...`
3) Set secret for signing tokens:
   ```bash
   export HH_APP_SECRET='super-secret-change-me'
   ```
4) Run your app:
   ```bash
   streamlit run app.py
   ```
5) After you log in successfully, your URL should contain `?auth=...` and refresh should keep you logged in.
