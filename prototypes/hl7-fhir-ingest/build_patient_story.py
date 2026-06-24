#!/usr/bin/env python3
"""
Build a patient-centric summary and visual dashboard from FHIR CSV extracts.

Inputs (expected in current directory):
- patients.csv
- observations.csv
- conditions.csv
- medication_requests.csv
- encounters.csv

Outputs:
- patient_activity_summary.csv
- patient_story.html
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
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def choose_latest(values: list[str]) -> str:
    parsed = [(parse_iso(v), v) for v in values if v]
    parsed = [p for p in parsed if p[0] is not None]
    if not parsed:
        return ""
    parsed.sort(key=lambda x: x[0])
    return parsed[-1][1]


def safe_name(family: str, given: str) -> str:
    full = f"{given} {family}".strip()
    return full if full else "Unknown Name"


def build_summary(base: Path) -> tuple[list[dict], dict]:
    patients = read_csv(base / DATA_FILES["patients"])
    observations = read_csv(base / DATA_FILES["observations"])
    conditions = read_csv(base / DATA_FILES["conditions"])
    medreqs = read_csv(base / DATA_FILES["medication_requests"])
    encounters = read_csv(base / DATA_FILES["encounters"])

    by_patient = {}
    for p in patients:
        pid = p.get("id", "")
        if not pid:
            continue
        by_patient[pid] = {
            "patient_id": pid,
            "name": safe_name(p.get("family_name", ""), p.get("given_name", "")),
            "gender": p.get("gender", ""),
            "birth_date": p.get("birth_date", ""),
            "observation_count": 0,
            "condition_count": 0,
            "medreq_count": 0,
            "encounter_count": 0,
            "last_event_at": "",
            "dq_patient": p.get("dq_issues", ""),
            "risk_note": "",
        }

    # Include orphan events as pseudo-patients so data quality becomes visible.
    def ensure_patient(pid: str):
        if pid and pid not in by_patient:
            by_patient[pid] = {
                "patient_id": pid,
                "name": "Orphan Patient Ref",
                "gender": "",
                "birth_date": "",
                "observation_count": 0,
                "condition_count": 0,
                "medreq_count": 0,
                "encounter_count": 0,
                "last_event_at": "",
                "dq_patient": "MISSING_PATIENT_ROW",
                "risk_note": "",
            }

    for row in observations:
        pid = row.get("patient_id", "")
        ensure_patient(pid)
        if pid:
            by_patient[pid]["observation_count"] += 1

    for row in conditions:
        pid = row.get("patient_id", "")
        ensure_patient(pid)
        if pid:
            by_patient[pid]["condition_count"] += 1

    for row in medreqs:
        pid = row.get("patient_id", "")
        ensure_patient(pid)
        if pid:
            by_patient[pid]["medreq_count"] += 1

    for row in encounters:
        pid = row.get("patient_id", "")
        ensure_patient(pid)
        if pid:
            by_patient[pid]["encounter_count"] += 1

    # Compute last_event_at from all event streams.
    event_times = {}
    for pid in by_patient:
        event_times[pid] = []

    for row in observations:
        pid = row.get("patient_id", "")
        ts = row.get("last_updated", "")
        if pid in event_times and ts:
            event_times[pid].append(ts)

    for row in conditions:
        pid = row.get("patient_id", "")
        ts = row.get("last_updated", "")
        if pid in event_times and ts:
            event_times[pid].append(ts)

    for row in medreqs:
        pid = row.get("patient_id", "")
        ts = row.get("last_updated", "")
        if pid in event_times and ts:
            event_times[pid].append(ts)

    for row in encounters:
        pid = row.get("patient_id", "")
        ts = row.get("last_updated", "")
        if pid in event_times and ts:
            event_times[pid].append(ts)

    for pid, summary in by_patient.items():
        summary["last_event_at"] = choose_latest(event_times.get(pid, []))
        total = (
            summary["observation_count"]
            + summary["condition_count"]
            + summary["medreq_count"]
            + summary["encounter_count"]
        )
        summary["total_events"] = total

        risk_flags = []
        if not summary["birth_date"]:
            risk_flags.append("Missing DOB")
        if total == 0:
            risk_flags.append("No clinical events")
        if summary["encounter_count"] >= 3 and summary["condition_count"] == 0:
            risk_flags.append("Encounter-heavy, low diagnosis capture")
        summary["risk_note"] = "; ".join(risk_flags)

    summary_rows = sorted(
        by_patient.values(), key=lambda r: (r["total_events"], r["last_event_at"]), reverse=True
    )

    totals = {
        "patients": len(patients),
        "observations": len(observations),
        "conditions": len(conditions),
        "medication_requests": len(medreqs),
        "encounters": len(encounters),
        "summary_rows": len(summary_rows),
    }

    return summary_rows, totals


def write_summary_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = [
        "patient_id",
        "name",
        "gender",
        "birth_date",
        "encounter_count",
        "observation_count",
        "condition_count",
        "medreq_count",
        "total_events",
        "last_event_at",
        "risk_note",
        "dq_patient",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_dashboard_html(path: Path, rows: list[dict], totals: dict) -> None:
    top = rows[:12]
    labels = [r["patient_id"] for r in top]
    enc = [r["encounter_count"] for r in top]
    obs = [r["observation_count"] for r in top]
    cond = [r["condition_count"] for r in top]
    med = [r["medreq_count"] for r in top]

    bubbles = [
        {
            "x": int(r["encounter_count"]),
            "y": int(r["medreq_count"]),
            "r": max(4, min(20, int(r["total_events"]) + 3)),
            "patient": r["patient_id"],
        }
        for r in top
    ]

    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>FHIR Patient Story Dashboard</title>
  <script src=\"https://cdn.jsdelivr.net/npm/chart.js\"></script>
  <script type=\"module\">
    import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
    mermaid.initialize({{ startOnLoad: true, theme: 'base' }});
  </script>
  <style>
    :root {{
      --bg: #f3efe7;
      --panel: #fffaf2;
      --ink: #1b1b1b;
      --muted: #5f5a52;
      --accent-a: #0d7c66;
      --accent-b: #e76f51;
      --accent-c: #264653;
      --accent-d: #e9c46a;
      --line: #e5d8c4;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Trebuchet MS", sans-serif;
      background: radial-gradient(circle at 20% 10%, #fff5e6 0, var(--bg) 40%),
                  linear-gradient(130deg, #f5eee4 0%, #f0e7d8 100%);
      color: var(--ink);
    }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 28px 18px 40px; }}
    .hero {{
      padding: 24px;
      background: linear-gradient(135deg, #fff9ee, #f8efdd);
      border: 1px solid var(--line);
      border-radius: 20px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.06);
    }}
    h1 {{ margin: 0; font-size: 30px; letter-spacing: 0.2px; }}
    .sub {{ margin-top: 8px; color: var(--muted); }}
    .grid {{ display: grid; gap: 16px; margin-top: 16px; grid-template-columns: repeat(12,1fr); }}
    .card {{
      grid-column: span 3;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
    }}
    .k {{ font-size: 12px; color: var(--muted); text-transform: uppercase; }}
    .v {{ font-size: 28px; margin-top: 4px; font-weight: 700; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
      margin-top: 16px;
    }}
    .charts {{ display: grid; grid-template-columns: 2fr 1fr; gap: 16px; }}
    .panel h2 {{ margin: 4px 0 12px; font-size: 18px; }}
    canvas {{ width: 100%; min-height: 280px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
    th, td {{ text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--line); font-size: 13px; }}
    th {{ color: var(--muted); font-weight: 600; }}
    .risk {{ color: #9d2b00; font-weight: 600; }}
    .mer {{ margin-top: 18px; }}
    @media (max-width: 900px) {{
      .card {{ grid-column: span 6; }}
      .charts {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <section class=\"hero\">
      <h1>FHIR Patient Story Dashboard</h1>
      <div class=\"sub\">Patient-anchored view of Observation, Condition, MedicationRequest, and Encounter resources.</div>
      <div class=\"grid\">
        <div class=\"card\"><div class=\"k\">Patients</div><div class=\"v\">{totals['patients']}</div></div>
        <div class=\"card\"><div class=\"k\">Observations</div><div class=\"v\">{totals['observations']}</div></div>
        <div class=\"card\"><div class=\"k\">Conditions</div><div class=\"v\">{totals['conditions']}</div></div>
        <div class=\"card\"><div class=\"k\">Med Requests</div><div class=\"v\">{totals['medication_requests']}</div></div>
        <div class=\"card\"><div class=\"k\">Encounters</div><div class=\"v\">{totals['encounters']}</div></div>
        <div class=\"card\"><div class=\"k\">Patient Story Rows</div><div class=\"v\">{totals['summary_rows']}</div></div>
      </div>
    </section>

    <section class=\"panel charts\">
      <div>
        <h2>Top Patients by Activity Mix</h2>
        <canvas id=\"mix\"></canvas>
      </div>
      <div>
        <h2>Resource Volume Mix</h2>
        <canvas id=\"donut\"></canvas>
      </div>
    </section>

    <section class=\"panel\">
      <h2>Care Pattern Lens: Encounter vs Medication Request</h2>
      <canvas id=\"bubble\"></canvas>
    </section>

    <section class=\"panel\">
      <h2>Highest Activity Patient Rows</h2>
      <table>
        <thead>
          <tr>
            <th>Patient</th><th>Total</th><th>Enc</th><th>Obs</th><th>Cond</th><th>MedReq</th><th>Last Event</th><th>Risk Note</th>
          </tr>
        </thead>
        <tbody>
          {''.join([f"<tr><td>{r['patient_id']}</td><td>{r['total_events']}</td><td>{r['encounter_count']}</td><td>{r['observation_count']}</td><td>{r['condition_count']}</td><td>{r['medreq_count']}</td><td>{r['last_event_at']}</td><td class='risk'>{r['risk_note']}</td></tr>" for r in top])}
        </tbody>
      </table>
    </section>

    <section class=\"panel mer\">
      <h2>Resource Model (Patient-Anchored)</h2>
      <pre class=\"mermaid\">
flowchart LR
  P[Patient]
  E[Encounter]
  O[Observation]
  C[Condition]
  M[MedicationRequest]
  P --> E
  P --> O
  P --> C
  P --> M
  E -. timeline context .-> O
  E -. diagnosis context .-> C
  E -. treatment context .-> M
      </pre>
    </section>
  </div>

  <script>
    const labels = {json.dumps(labels)};
    const enc = {json.dumps(enc)};
    const obs = {json.dumps(obs)};
    const cond = {json.dumps(cond)};
    const med = {json.dumps(med)};

    new Chart(document.getElementById('mix'), {{
      type: 'bar',
      data: {{
        labels,
        datasets: [
          {{ label: 'Encounter', data: enc, backgroundColor: '#0d7c66' }},
          {{ label: 'Observation', data: obs, backgroundColor: '#264653' }},
          {{ label: 'Condition', data: cond, backgroundColor: '#e9c46a' }},
          {{ label: 'MedRequest', data: med, backgroundColor: '#e76f51' }}
        ]
      }},
      options: {{
        responsive: true,
        plugins: {{ legend: {{ position: 'bottom' }} }},
        scales: {{ x: {{ stacked: true }}, y: {{ stacked: true, beginAtZero: true }} }}
      }}
    }});

    new Chart(document.getElementById('donut'), {{
      type: 'doughnut',
      data: {{
        labels: ['Observations', 'Conditions', 'MedRequests', 'Encounters'],
        datasets: [{{
          data: [{totals['observations']}, {totals['conditions']}, {totals['medication_requests']}, {totals['encounters']}],
          backgroundColor: ['#264653', '#e9c46a', '#e76f51', '#0d7c66']
        }}]
      }},
      options: {{ plugins: {{ legend: {{ position: 'bottom' }} }} }}
    }});

    const bubbles = {json.dumps(bubbles)};
    new Chart(document.getElementById('bubble'), {{
      type: 'bubble',
      data: {{
        datasets: [{{
          label: 'Patient activity bubble',
          data: bubbles,
          backgroundColor: 'rgba(231,111,81,0.35)',
          borderColor: '#b84a31'
        }}]
      }},
      options: {{
        parsing: false,
        plugins: {{
          tooltip: {{
            callbacks: {{
              label: (ctx) => `Patient ${{ctx.raw.patient}} | Enc:${{ctx.raw.x}} MedReq:${{ctx.raw.y}} TotalRadius:${{ctx.raw.r}}`
            }}
          }}
        }},
        scales: {{
          x: {{ title: {{ display: true, text: 'Encounter Count' }}, beginAtZero: true }},
          y: {{ title: {{ display: true, text: 'MedicationRequest Count' }}, beginAtZero: true }}
        }}
      }}
    }});
  </script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> None:
    base = Path(__file__).resolve().parent
    summary_rows, totals = build_summary(base)

    summary_csv = base / "patient_activity_summary.csv"
    dashboard_html = base / "patient_story.html"

    write_summary_csv(summary_csv, summary_rows)
    build_dashboard_html(dashboard_html, summary_rows, totals)

    print(f"Wrote {summary_csv.name} with {len(summary_rows)} rows")
    print(f"Wrote {dashboard_html.name}")


if __name__ == "__main__":
    main()
