# HHapp2 — Backup bundle (20250915_074835)

This bundle contains the latest files needed to run HHapp2 locally.

## Included
- app.py
- shift_helpers.py
- time_helpers.py
- app_before_nurse_shift_patch.py

- README_DEPLOY.md (this file)

## Quick start
```bash
# 1) (optional) create & activate venv
python3 -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\activate

# 2) install deps
pip install -r requirements.txt

# 3) (optional) envs
# URL-auth is optional (default OFF). Turn it on only if you want to persist login via ?auth=
export ENABLE_URL_AUTH=0
export HH_APP_SECRET='super-secret-change-me'   # required only when ENABLE_URL_AUTH=1

# Optional: change Vitals time step globally (minutes), default 15
export VITALS_STEP_MINUTES=15

# 4) run
streamlit run app.py
```

## Notes
- Nurse tab now uses **shift day/night** radio instead of a free time field.
- If you enable URL-auth, the app will try to keep login across refreshes using a signed token in the URL.
- Database file: `clinic.db` (included, if present here).
- Favicon expects `assets/logo.png` in project root; if missing the app falls back to 🏥.
