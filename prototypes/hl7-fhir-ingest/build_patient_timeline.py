#!/usr/bin/env python3
"""
Build an interactive, scrollable patient clinical timeline for the highest-activity patient.

Inputs (expected in current directory):
  encounters.csv, observations.csv, conditions.csv, medication_requests.csv, patients.csv

Output:
  patient_timeline.html
"""

import csv
import json
from datetime import datetime
from pathlib import Path


DATA_FILES = {
    "patients": "patients.csv",
    "observations": "observations.csv",
    "conditions": "conditions.csv",
    "medication_requests": "medication_requests.csv",
    "encounters": "encounters.csv",
}


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_iso(value: str):
    if not value:
        return None
    for suffix in ("Z", "+00:00"):
        value = value.replace(suffix, "+00:00") if suffix in value else value
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def pick_date(row: dict, *keys: str) -> str:
    for k in keys:
        v = row.get(k, "")
        if v and parse_iso(v):
            return v
    return ""


def collect_events(base: Path, pid: str) -> list[dict]:
    events = []

    # Encounters
    for r in read_csv(base / DATA_FILES["encounters"]):
        if r.get("patient_id") != pid:
            continue
        ts = pick_date(r, "period_start", "last_updated")
        end = r.get("period_end", "")
        label = r.get("type_display") or r.get("class_code") or "Encounter"
        events.append({
            "type": "encounter",
            "ts": ts,
            "end": end,
            "label": label,
            "detail": f"Class: {r.get('class_code','')}  Status: {r.get('status','')}",
            "id": r.get("id", ""),
            "icon": "🏥",
            "color": "#0d7c66",
        })

    # Conditions
    for r in read_csv(base / DATA_FILES["conditions"]):
        if r.get("patient_id") != pid:
            continue
        ts = pick_date(r, "onset_datetime", "recorded_date", "last_updated")
        events.append({
            "type": "condition",
            "ts": ts,
            "end": "",
            "label": r.get("display") or r.get("code") or "Condition",
            "detail": f"Status: {r.get('clinical_status','')}  Verified: {r.get('verification_status','')}",
            "id": r.get("id", ""),
            "icon": "🩺",
            "color": "#e9c46a",
        })

    # Observations
    for r in read_csv(base / DATA_FILES["observations"]):
        if r.get("patient_id") != pid:
            continue
        ts = pick_date(r, "effective_date", "issued", "last_updated")
        val_str = f"{r.get('value','')} {r.get('unit','')}".strip() if r.get("value") else ""
        events.append({
            "type": "observation",
            "ts": ts,
            "end": "",
            "label": r.get("display") or r.get("code") or "Observation",
            "detail": val_str or "No value recorded",
            "id": r.get("id", ""),
            "icon": "📋",
            "color": "#264653",
        })

    # MedicationRequests
    for r in read_csv(base / DATA_FILES["medication_requests"]):
        if r.get("patient_id") != pid:
            continue
        ts = pick_date(r, "authored_on", "last_updated")
        events.append({
            "type": "medication",
            "ts": ts,
            "end": "",
            "label": r.get("medication_display") or r.get("medication_code") or "Medication",
            "detail": f"Status: {r.get('status','')}  Intent: {r.get('intent','')}",
            "id": r.get("id", ""),
            "icon": "💊",
            "color": "#e76f51",
        })

    # Sort chronologically; events with no date go to end
    events.sort(key=lambda e: (parse_iso(e["ts"]) or datetime.max, e["type"]))
    return events


def format_dt(iso: str) -> str:
    d = parse_iso(iso)
    if not d:
        return ""
    return d.strftime("%b %d, %Y  %H:%M")


def build_timeline_html(path: Path, pid: str, patient_row: dict, events: list[dict]) -> None:
    name = f"{patient_row.get('given_name','')} {patient_row.get('family_name','')}".strip() or pid
    gender = patient_row.get("gender", "").capitalize()
    dob = patient_row.get("birth_date", "")
    city = patient_row.get("city", "")
    state = patient_row.get("state", "")

    counts = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1

    events_js = json.dumps(events, default=str)

    # Build timeline items HTML
    timeline_items = []
    prev_year = None
    for i, e in enumerate(events):
        year = parse_iso(e["ts"]).year if parse_iso(e["ts"]) else None
        year_marker = ""
        if year and year != prev_year:
            prev_year = year
            year_marker = f'<div class="year-marker">{year}</div>'

        duration_html = ""
        if e["end"]:
            start_dt = parse_iso(e["ts"])
            end_dt = parse_iso(e["end"])
            if start_dt and end_dt:
                delta = end_dt - start_dt
                mins = int(delta.total_seconds() / 60)
                if mins < 60:
                    duration_html = f'<span class="dur">⏱ {mins} min</span>'
                else:
                    duration_html = f'<span class="dur">⏱ {mins // 60}h {mins % 60}m</span>'

        side = "left" if i % 2 == 0 else "right"
        timeline_items.append(f"""
{year_marker}
<div class="evt evt-{side}" data-type="{e['type']}">
  <div class="dot" style="background:{e['color']};">{e['icon']}</div>
  <div class="card" style="border-left:4px solid {e['color']};">
    <div class="card-type" style="color:{e['color']};">{e['type'].upper()}</div>
    <div class="card-label">{e['label']}</div>
    <div class="card-meta">{format_dt(e['ts'])} {duration_html}</div>
    <div class="card-detail">{e['detail']}</div>
  </div>
</div>""")

    items_html = "\n".join(timeline_items)

    filter_btns = ""
    types = [
        ("all", "#444", "All"),
        ("encounter", "#0d7c66", "🏥 Encounters"),
        ("condition", "#c49a0a", "🩺 Conditions"),
        ("observation", "#264653", "📋 Observations"),
        ("medication", "#e76f51", "💊 Medications"),
    ]
    for t, color, label in types:
        filter_btns += f'<button class="fbtn" data-filter="{t}" style="border-color:{color};color:{color};">{label}</button>'

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Patient Clinical Timeline — {name}</title>
  <style>
    :root {{
      --bg: #f5ede0;
      --panel: #fffaf2;
      --ink: #1b1b1b;
      --muted: #6b6359;
      --line: #e5d5c0;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: "Avenir Next","Trebuchet MS",sans-serif; background: var(--bg); color: var(--ink); }}

    /* ── Header ── */
    .hdr {{
      background: linear-gradient(135deg, #1b3a4b 0%, #0d7c66 100%);
      color: #fff;
      padding: 26px 32px 20px;
    }}
    .hdr h1 {{ font-size: 26px; letter-spacing: 0.3px; }}
    .hdr .meta {{ margin-top: 6px; opacity: 0.8; font-size: 14px; }}
    .kpis {{ display: flex; gap: 14px; margin-top: 18px; flex-wrap: wrap; }}
    .kpi {{
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.25);
      border-radius: 10px;
      padding: 8px 16px;
      text-align: center;
      min-width: 90px;
    }}
    .kpi .kn {{ font-size: 22px; font-weight: 700; }}
    .kpi .kl {{ font-size: 11px; opacity: 0.75; text-transform: uppercase; margin-top: 2px; }}

    /* ── Filters ── */
    .filters {{
      display: flex; gap: 8px; padding: 16px 24px; flex-wrap: wrap;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }}
    .fbtn {{
      border-radius: 20px;
      border: 1.5px solid;
      background: transparent;
      padding: 5px 14px;
      font-size: 13px;
      cursor: pointer;
      font-family: inherit;
      transition: background 0.15s, color 0.15s;
    }}
    .fbtn:hover, .fbtn.active {{ background: var(--ink); color: #fff !important; border-color: var(--ink) !important; }}

    /* ── Timeline ── */
    .tl-wrap {{
      max-width: 900px;
      margin: 0 auto;
      padding: 30px 16px 60px;
      position: relative;
    }}
    .tl-wrap::before {{
      content: '';
      position: absolute;
      left: 50%;
      top: 0; bottom: 0;
      width: 2px;
      background: var(--line);
      transform: translateX(-50%);
    }}

    .year-marker {{
      text-align: center;
      position: relative;
      z-index: 2;
      margin: 22px 0 6px;
    }}
    .year-marker span, .year-marker {{
      display: inline-block;
      background: #1b3a4b;
      color: #fff;
      border-radius: 20px;
      padding: 3px 16px;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 1px;
    }}

    .evt {{
      display: flex;
      align-items: flex-start;
      margin: 14px 0;
      position: relative;
      width: 50%;
      opacity: 1;
      transition: opacity 0.2s;
    }}
    .evt.hidden {{ opacity: 0; max-height: 0; overflow: hidden; margin: 0; pointer-events: none; }}

    .evt-left {{
      padding-right: 36px;
      flex-direction: row-reverse;
      align-self: flex-start;
    }}
    .evt-right {{
      padding-left: 36px;
      margin-left: 50%;
    }}

    .dot {{
      position: absolute;
      width: 34px; height: 34px;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 16px;
      border: 3px solid var(--bg);
      z-index: 3;
      flex-shrink: 0;
    }}
    .evt-left .dot  {{ right: -17px; }}
    .evt-right .dot {{ left: -17px; }}

    .card {{
      background: var(--panel);
      border-radius: 12px;
      border-left: 4px solid #999;
      padding: 12px 14px;
      box-shadow: 0 3px 12px rgba(0,0,0,0.07);
      flex: 1;
      min-width: 0;
    }}
    .evt-left .card {{ text-align: right; border-left: none !important; border-right: 4px solid #999; }}
    .evt-left .card {{ border-right-color: inherit; }}
    .card-type {{ font-size: 10px; font-weight: 700; letter-spacing: 1.2px; margin-bottom: 4px; }}
    .card-label {{ font-size: 15px; font-weight: 600; line-height: 1.3; }}
    .card-meta {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
    .card-detail {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
    .dur {{ background: #f0e8d8; border-radius: 8px; padding: 2px 7px; font-size: 11px; margin-left: 6px; }}
    .no-events {{ text-align: center; color: var(--muted); padding: 40px; font-size: 16px; display: none; }}

    @media (max-width: 680px) {{
      .tl-wrap::before {{ left: 20px; }}
      .evt {{ width: 100%; margin-left: 0 !important; padding-left: 54px !important; padding-right: 0 !important; flex-direction: row !important; }}
      .evt .dot {{ left: 3px !important; right: auto !important; }}
      .card {{ text-align: left !important; border-left: 4px solid !important; border-right: none !important; }}
    }}
  </style>
</head>
<body>
  <div class="hdr">
    <h1>Patient Clinical Timeline</h1>
    <div class="meta">{name} &nbsp;·&nbsp; {gender} &nbsp;·&nbsp; DOB: {dob or "Unknown"} &nbsp;·&nbsp; {city}{", " + state if state else ""}</div>
    <div class="kpis">
      <div class="kpi"><div class="kn">{counts.get("encounter",0)}</div><div class="kl">Encounters</div></div>
      <div class="kpi"><div class="kn">{counts.get("observation",0)}</div><div class="kl">Observations</div></div>
      <div class="kpi"><div class="kn">{counts.get("condition",0)}</div><div class="kl">Conditions</div></div>
      <div class="kpi"><div class="kn">{counts.get("medication",0)}</div><div class="kl">Medications</div></div>
      <div class="kpi"><div class="kn">{len(events)}</div><div class="kl">Total Events</div></div>
    </div>
  </div>

  <div class="filters">
    {filter_btns}
  </div>

  <div class="tl-wrap" id="tl">
    {items_html}
    <div class="no-events" id="noevt">No events match this filter.</div>
  </div>

  <script>
    const btns = document.querySelectorAll('.fbtn');
    const evts = document.querySelectorAll('.evt');
    const noEvt = document.getElementById('noevt');

    btns.forEach(btn => {{
      btn.addEventListener('click', () => {{
        btns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const f = btn.dataset.filter;
        let visible = 0;
        evts.forEach(e => {{
          const match = f === 'all' || e.dataset.type === f;
          e.classList.toggle('hidden', !match);
          if (match) visible++;
        }});
        noEvt.style.display = visible === 0 ? 'block' : 'none';
      }});
    }});

    // Activate "All" by default
    document.querySelector('.fbtn[data-filter="all"]').click();
  </script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> None:
    base = Path(__file__).resolve().parent
    encounters = read_csv(base / DATA_FILES["encounters"])
    patients = {r["id"]: r for r in read_csv(base / DATA_FILES["patients"])}

    if not encounters:
        print("No encounter data found. Run fhir_ingest.py first.")
        return

    # Pick patient with most encounters that also has a patient record
    from collections import Counter
    counts = Counter(r["patient_id"] for r in encounters if r["patient_id"])
    pid = None
    for candidate, _ in counts.most_common():
        if candidate in patients:
            pid = candidate
            break

    if not pid:
        pid = counts.most_common(1)[0][0]

    patient_row = patients.get(pid, {})
    name = f"{patient_row.get('given_name','')} {patient_row.get('family_name','')}".strip() or pid
    print(f"Building timeline for patient {pid} — {name}")

    events = collect_events(base, pid)
    print(f"  {len(events)} total events across all resource types")

    out = base / "patient_timeline.html"
    build_timeline_html(out, pid, patient_row, events)
    print(f"  Wrote {out.name}")


if __name__ == "__main__":
    main()
