# shift_helpers.py
from datetime import time

def shift_picker(st, label='เวร', key='vitals_shift'):
    """Return (shift_code, shift_time).
    shift_code: 'day' or 'night'
    shift_time: time(7,0) for day, time(19,0) for night
    """
    choices = ['กลางวัน (07:00-19:00)', 'กลางคืน (19:00-07:00)']
    sel = st.radio(label, choices, horizontal=True, key=key)
    is_day = sel.startswith('กลางวัน')
    return ('day' if is_day else 'night'), (time(7,0) if is_day else time(19,0))
