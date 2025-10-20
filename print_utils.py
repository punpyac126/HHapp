
import base64
from datetime import datetime, date
from pathlib import Path

def _logo_base64(get_logo_path):
    lp = get_logo_path()
    if not lp or not Path(lp).exists(): 
        return ""
    try:
        with open(lp, "rb") as f:
            import base64 as b64
            return b64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return ""

def _patient_banner_rows(run_query, calc_age_ymd, pid:int):
    row = run_query(
        "SELECT hn,first_name,last_name,photo_path,blood_group,ward,underlying_disease,weight,drug_allergy,hospital,feeding,foley,dob,relative_name,relative_phone FROM patients WHERE id=?",
        (pid,), fetch=True
    )
    if not row: 
        return {}, ""
    r = row[0]
    age_txt = calc_age_ymd(r.get("dob")) or "-"
    banner_html = f"""
    <table class='banner'>
      <tr>
        <td><strong>ชื่อ–นามสกุล:</strong> คุณ {r.get('first_name','') or '-'} {r.get('last_name','') or '-'}</td>
        <td><strong>HN:</strong> {r.get('hn') or '-'}</td>
      </tr>
      <tr>
        <td><strong>อายุ:</strong> {age_txt}</td>
        <td><strong>กรุ๊ปเลือด:</strong> {r.get('blood_group') or '-'}</td>
      </tr>
      <tr>
        <td><strong>วอร์ด:</strong> {r.get('ward') or '-'}</td>
        <td><strong>โรงพยาบาล:</strong> {r.get('hospital') or '-'}</td>
      </tr>
      <tr>
        <td><strong>โรคประจำตัว:</strong> {r.get('underlying_disease') or '-'}</td>
        <td><strong>น้ำหนัก:</strong> {r.get('weight') if r.get('weight') not in (None, '') else '-'}</td>
      </tr>
      <tr>
        <td><strong>แพ้ยา:</strong> {r.get('drug_allergy') or '-'}</td>
        <td><strong>การให้อาหาร:</strong> {r.get('feeding') or '-'}  •  <strong>Foley's:</strong> {'Yes' if r.get('foley') else 'No'}</td>
      </tr>
      <tr>
        <td colspan='2'><strong>ญาติผู้ป่วย:</strong> {r.get('relative_name') or '-'}  •  <strong>เบอร์ติดต่อ:</strong> {r.get('relative_phone') or '-'}</td>
      </tr>
    </table>
    """
    return r, banner_html

def _base_css():
    return '''
    <style>
    @page { size: A4; margin: 14mm; }
    body { font-family: "Tahoma", Arial, sans-serif; font-size: 12pt; color:#222; }
    h1,h2,h3 { margin: 4px 0; }
    .header { text-align:center; margin-bottom: 8px; }
    .header img { height: 48px; }
    .sub { font-size: 11pt; color:#444; }
    .title { font-size: 14pt; font-weight: 700; margin-top: 6px; }
    .banner { width:100%; border-collapse: collapse; margin: 8px 0 10px; }
    .banner td { border:1px solid #ccc; padding:6px 8px; vertical-align: top;}
    .section { margin-top: 10px; }
    .tbl { width:100%; border-collapse: collapse; }
    .tbl th, .tbl td { border:1px solid #ccc; padding:6px; }
    .sign { margin-top:14px; display:grid; grid-template-columns:1fr 1fr; gap:16px; }
    .sigbox { height:64px; border:1px dashed #999; padding:6px; }
    .muted { color:#666; font-size: 10pt; }
    </style>
    '''

def _header_html(get_logo_path, doc_title:str):
    b64 = _logo_base64(get_logo_path)
    img_html = f"<img src='data:image/png;base64,{b64}'/>" if b64 else "<div style='font-size:24px'>🏥</div>"
    lines = "".join([f"<div class='sub'>{ln}</div>" for ln in [
        "ศูนย์ฟื้นฟูเฮลท์ตี้แฮบบิแทท",
        "59 ซอยเฉลิมพระเกียรติ28 แยก14 แขววงดอกไม้ เขตประเวศ 10250 กรุงเทพ",
        "ติดต่อสอบถามเพิ่มเติมได้ที่ Line: HealthyHabitat.th หรือโทร 02-853-9562, 096-415-1982",
    ]])
    return f"<div class='header'>{img_html}{lines}<div class='title'>{doc_title}</div></div>"

def build_vitals_print_html(run_query, get_logo_path, calc_age_ymd, pid:int, selected_date:str):
    _, banner_html = _patient_banner_rows(run_query, calc_age_ymd, pid)
    rows = run_query(
        "SELECT ts,shift,temperature,bp,heart_rate,resp_rate,spo2,dtx,intake_ml,output_times,stool,note,caregiver_name,head_nurse_name,created_by FROM vitals WHERE patient_id=? AND date(ts)=? ORDER BY ts ASC",
        (pid, selected_date), fetch=True
    ) or []
    night = []; day = []
    for r in rows:
        try: h = int(r['ts'][11:13])
        except Exception: h = 0
        if 7 <= h < 19: day.append(r)
        else: night.append(r)
    def _rows_to_table(rs):
        if not rs: return "<div class='muted'>ไม่มีข้อมูล</div>"
        th = "<tr><th>เวลา</th><th>Temp</th><th>BP</th><th>HR</th><th>RR</th><th>SpO₂</th><th>DTX</th><th>น้ำเข้า (ml)</th><th>ปัสสาวะ (ครั้ง)</th><th>อุจจาระ</th><th>บันทึก</th></tr>"
        trs = []
        for r in rs:
            trs.append(f"<tr><td>{r['ts'][11:16]}</td><td>{r.get('temperature') or ''}</td><td>{r.get('bp') or ''}</td><td>{r.get('heart_rate') or ''}</td><td>{r.get('resp_rate') or ''}</td><td>{r.get('spo2') or ''}</td><td>{r.get('dtx') or ''}</td><td>{r.get('intake_ml') or ''}</td><td>{r.get('output_times') or ''}</td><td>{r.get('stool') or ''}</td><td>{r.get('note') or ''}</td></tr>")
        return f"<table class='tbl'>{th}{''.join(trs)}</table>"
    def _cg(rs, key): 
        vals=[(r.get(key) or '').strip() for r in rs if (r.get(key) or '').strip()]
        return vals[-1] if vals else ""
    day_cg = _cg(day, 'caregiver_name'); day_hd = _cg(day, 'head_nurse_name')
    night_cg = _cg(night, 'caregiver_name'); night_hd = _cg(night, 'head_nurse_name')
    sign_html = f"""
    <div class='sign'>
      <div><div class='sigbox'></div><div class='muted'>ผู้ดูแลช่วงกลางวัน: {day_cg or '__________'}  •  หัวหน้าเวรช่วงกลางวัน: {day_hd or '__________'}</div></div>
      <div><div class='sigbox'></div><div class='muted'>ผู้ดูแลช่วงกลางคืน: {night_cg or '__________'}  •  หัวหน้าเวรช่วงกลางคืน: {night_hd or '__________'}</div></div>
    </div>
    """
    html = "<html><head>"+_base_css()+"</head><body>"
    html += _header_html(get_logo_path, "บันทึกรายงานสุขภาพประจำวัน")
    html += f"<div class='muted'>วันที่: {selected_date}</div>"
    html += banner_html
    html += "<div class='section'><h3>ช่วงกลางคืน (19:00–07:00)</h3>"+_rows_to_table(night)+"</div>"
    html += "<div class='section'><h3>ช่วงกลางวัน (07:00–19:00)</h3>"+_rows_to_table(day)+"</div>"
    html += sign_html
    html += "</body></html>"
    return html

def build_physio_print_html(run_query, get_logo_path, calc_age_ymd, pid:int, selected_date:str):
    _, banner_html = _patient_banner_rows(run_query, calc_age_ymd, pid)
    rows = run_query(
        "SELECT * FROM physio_sessions WHERE patient_id=? AND date(session_date)=? ORDER BY created_at ASC",
        (pid, selected_date), fetch=True
    ) or []
    def _block_from_row(r):
        items=[]
        for k,v in r.items():
            if k in ('id','patient_id','created_by','created_at'): 
                continue
            if v in (None,""):
                continue
            kk = k.replace('_',' ')
            items.append(f"<tr><td style='width:30%'><strong>{kk}</strong></td><td>{v}</td></tr>")
        if not items:
            return ""
        return "<table class='tbl'>" + "".join(items) + "</table>"
    blocks = [ _block_from_row(r) for r in rows ]
    html = "<html><head>"+_base_css()+"</head><body>"
    html += _header_html(get_logo_path, "บันทึกรายงานกายภาพประจำวัน")
    html += f"<div class='muted'>วันที่: {selected_date}</div>"
    html += banner_html
    if blocks:
        html += "<div class='section'>" + "<hr/>".join(blocks) + "</div>"
    else:
        html += "<div class='muted'>ไม่มีข้อมูล</div>"
    html += "</body></html>"
    return html

def build_meds_print_html(run_query, get_logo_path, calc_age_ymd, pid:int, selected_date:str):
    _, banner_html = _patient_banner_rows(run_query, calc_age_ymd, pid)
    rows = run_query(
        "SELECT meal_times,timing_radio,timing_other,image_path,drug_name,drug_type,how_to,responsible,created_by,created_at FROM medications WHERE patient_id=? AND date(created_at)=? ORDER BY created_at ASC",
        (pid, selected_date), fetch=True
    ) or []
    buckets = {
        "เช้า-ก่อนอาหาร": [],
        "เช้า-หลังอาหาร": [],
        "เที่ยง-ก่อนอาหาร": [],
        "เที่ยง-หลังอาหาร": [],
        "เย็น-ก่อนอาหาร": [],
        "เย็น-หลังอาหาร": [],
        "ก่อนนอน": [],
        "อื่นๆ": [],
    }
    def _label(meal, timing):
        mmap = {"morning":"เช้า","noon":"เที่ยง","evening":"เย็น","bedtime":"ก่อนนอน","other":"อื่นๆ","เช้า":"เช้า","เที่ยง":"เที่ยง","เย็น":"เย็น"}
        tmap = {"before":"ก่อนอาหาร","after":"หลังอาหาร","":""}
        M = mmap.get((meal or "").lower(), None)
        T = tmap.get((timing or "").lower(), None)
        if M in ("เช้า","เที่ยง","เย็น") and T:
            return f"{M}-{T}"
        if M == "ก่อนนอน":
            return "ก่อนนอน"
        return "อื่นๆ"
    for r in rows:
        label = _label(r.get("meal_times"), r.get("timing_radio"))
        buckets.setdefault(label, [])
        buckets[label].append(r)
    def _rows_tbl(rs):
        if not rs: return "<div class='muted'>—</div>"
        th = "<tr><th>ชื่อยา</th><th>ประเภท</th><th>วิธีรับประทาน</th><th>ผู้ลงรายการ</th></tr>"
        trs=[]
        for r in rs:
            who = r.get('responsible') or r.get('created_by') or ''
            trs.append(f"<tr><td>{r.get('drug_name') or ''}</td><td>{r.get('drug_type') or ''}</td><td>{r.get('how_to') or ''}</td><td>{who}</td></tr>")
        return f"<table class='tbl'>{th}{''.join(trs)}</table>"
    html = "<html><head>"+_base_css()+"</head><body>"
    html += _header_html(get_logo_path, "บันทึกรายการยา")
    html += f"<div class='muted'>วันที่: {selected_date}</div>"
    html += banner_html
    order = ["เช้า-ก่อนอาหาร","เช้า-หลังอาหาร","เที่ยง-ก่อนอาหาร","เที่ยง-หลังอาหาร","เย็น-ก่อนอาหาร","เย็น-หลังอาหาร","ก่อนนอน","อื่นๆ"]
    for sec in order:
        html += f"<div class='section'><h3>{sec}</h3>{_rows_tbl(buckets.get(sec, []))}</div>"
    html += "</body></html>"
    return html

def download_print_button(st, label, html_str, filename):
    b = html_str.encode('utf-8')
    st.download_button(label, data=b, file_name=filename, mime="text/html")


# ==== Input-like A4 builders ====
def build_patient_inputlike_print_html(run_query, get_logo_path, calc_age_ymd, pid:int):
    row, banner = _patient_banner_rows(run_query, calc_age_ymd, pid)
    html = "<html><head>"+_base_css()+"</head><body>" + _header_html(get_logo_path, "ข้อมูลคนไข้ (ตามแบบฟอร์ม)") + banner
    def _line(lbl, val): 
        v = val if val not in (None, "") else "—"
        return f"<div style='margin:6px 0'><strong>{lbl}</strong> : {v}</div>"
    if row:
        html += "".join([
            _line("HN", row.get("hn")),
            _line("ชื่อ", row.get("first_name")),
            _line("นามสกุล", row.get("last_name")),
            _line("วันเกิด", row.get("dob")),
            _line("โรคประจำตัว", row.get("underlying_disease")),
            _line("น้ำหนัก (กก.)", row.get("weight")),
            _line("ส่วนสูง (ซม.)", row.get("height")),
            _line("ประวัติแพ้ยา", row.get("drug_allergy")),
            _line("การรับประทานอาหาร", row.get("feeding")),
            _line("วอร์ด", row.get("ward")),
            _line("โรงพยาบาล", row.get("hospital")),
            _line("กรุ๊ปเลือด", row.get("blood_group")),
            _line("Foley's", "Yes" if row.get("foley") else "No"),
            _line("วันที่เข้ารักษา", row.get("admission_date")),
            _line("ญาติผู้ป่วย", row.get("relative_name")),
            _line("เบอร์ติดต่อ", row.get("relative_phone")),
            _line("รายละเอียดเพิ่มเติม", row.get("detail")),
        ])
    else:
        html += "<div class='muted'>ไม่มีข้อมูลผู้ป่วย</div>"
    return html + "</body></html>"

def build_vitals_inputlike_print_html(run_query, get_logo_path, calc_age_ymd, pid:int, selected_date:str):
    _, banner = _patient_banner_rows(run_query, calc_age_ymd, pid)
    html = "<html><head>"+_base_css()+"</head><body>" + _header_html(get_logo_path, "ทีมพยาบาล — ฟอร์มรวม Night+Day")
    html += f"<div class='muted'>วันที่: {selected_date}</div>" + banner
    rows = run_query(
        "SELECT ts,shift,section,field,value,created_by FROM nurse_logs WHERE patient_id=? AND date(ts)=? ORDER BY ts ASC, id ASC",
        (pid, selected_date), fetch=True
    ) or []
    if not rows:
        html += "<div class='muted'>ไม่มีข้อมูล</div></body></html>"
        return html
    def mk_tbl(rs):
        if not rs: return "<div class='muted'>—</div>"
        th = "<tr><th>เวลา</th><th>หัวข้อ</th><th>ฟิลด์</th><th>ค่า</th><th>ผู้บันทึก</th></tr>"
        trs = [f"<tr><td>{r['ts'][11:16]}</td><td>{r['section']}</td><td>{r['field']}</td><td>{r['value'] or ''}</td><td>{r.get('created_by') or ''}</td></tr>" for r in rs]
        return "<table class='tbl'>"+th+"".join(trs)+"</table>"
    night = [r for r in rows if r['shift']=='night']
    day = [r for r in rows if r['shift']=='day']
    html += "<div class='section'><h3>ช่วงกลางคืน (19:00–07:00)</h3>"+mk_tbl(night)+"</div>"
    html += "<div class='section'><h3>ช่วงกลางวัน (07:00–19:00)</h3>"+mk_tbl(day)+"</div>"
    return html + "</body></html>"

def build_physio_inputlike_print_html(run_query, get_logo_path, calc_age_ymd, pid:int, selected_date:str):
    _, banner = _patient_banner_rows(run_query, calc_age_ymd, pid)
    html = "<html><head>"+_base_css()+"</head><body>" + _header_html(get_logo_path, "ทีมกายภาพ — แบบฟอร์มตามที่บันทึก")
    html += f"<div class='muted'>วันที่: {selected_date}</div>" + banner
    rows = run_query(
        "SELECT physio_type, section, field, value, created_by FROM physio_logs WHERE patient_id=? AND log_date=? ORDER BY id ASC",
        (pid, selected_date), fetch=True
    ) or []
    if not rows:
        html += "<div class='muted'>ไม่มีข้อมูล</div></body></html>"
        return html
    from collections import defaultdict
    buf = defaultdict(list)
    for r in rows:
        buf[(r['physio_type'], r['section'])].append(r)
    for (ptype, sec), items in buf.items():
        t = "กายภาพพื้นฐาน" if ptype=='basic' else "กายภาพฟื้นฟู"
        html += f"<div class='section'><h3>{t} — {sec}</h3><table class='tbl'><tr><th>ฟิลด์</th><th>ค่า</th></tr>"
        for it in items:
            html += f"<tr><td>{it['field']}</td><td>{it['value'] or ''}</td></tr>"
        html += "</table></div>"
    return html + "</body></html>"
