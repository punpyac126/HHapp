# Fix: Vitals time picker shows only 00:00, 00:15, 00:30

**Cause**: In your Vitals form the time dropdown was built incorrectly (minutes list `[0,15,30]` only and/or hours loop limited to 0).

## Quick fix (recommended — 1 line)

Replace your existing time widget with Streamlit's native `time_input` (15‑minute step):

```python
from datetime import datetime, timedelta, time
from time_helpers import vitals_time_input

# inside Vitals form:
t = vitals_time_input(st, label='เวลา', default=time(7,0), key='vitals_time')
ts_str = datetime.combine(selected_date, t).strftime('%Y-%m-%d %H:%M')
```

This gives a proper picker for **00:00 → 23:45** in 15‑minute steps.

## Alternative (keep dropdown)

If you prefer `selectbox`, use the full 96 options:

```python
from time_helpers import full_day_quarter_options
times = full_day_quarter_options()  # ['00:00', '00:15', ..., '23:45']
time_str = st.selectbox('เวลา', times, index=times.index('07:00'), key='vitals_time')
ts_str = f"{selected_date.strftime('%Y-%m-%d')} {time_str}"
```

> Make sure you **include '00:45'** and **every hour**. The old list was truncated so you only saw 00:00/00:15/00:30.

## Notes
- Save to DB using `ts_str` (`YYYY-MM-DD HH:MM`) to keep it consistent.
- The widget keeps the last picked value via `key='vitals_time'`.
