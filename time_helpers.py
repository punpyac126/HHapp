# time_helpers.py (v2) — configurable time step
import os
from datetime import datetime, time, timedelta

def _get_step_minutes(step_minutes):
    if step_minutes is None:
        # Environment override; default 15
        step_minutes = os.getenv("VITALS_STEP_MINUTES", "15")
    try:
        step = max(1, int(step_minutes))
    except Exception:
        step = 15
    return step

def vitals_time_input(st, label='เวลา', default=time(7,0), key='vitals_time', step_minutes=None):
    """Native time picker with configurable minute step (default 15).
    Example: vitals_time_input(st, step_minutes=5)
    Or set env VITALS_STEP_MINUTES=5
    """
    step = _get_step_minutes(step_minutes)
    return st.time_input(label, value=default, step=timedelta(minutes=step), key=key)

def day_options(step_minutes=15, fmt='%H:%M'):
    """Return a list of times across the day using the given step (minutes).
    Example: day_options(10) -> ['00:00','00:10',...,'23:50']
    """
    step = _get_step_minutes(step_minutes)
    out = []
    cur = datetime(2000,1,1,0,0)
    end = datetime(2000,1,2,0,0)
    delta = timedelta(minutes=step)
    while cur < end:
        out.append(cur.strftime(fmt))
        cur += delta
    return out
