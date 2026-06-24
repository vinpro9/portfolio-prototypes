# hl7-fhir-ingest

A minimal, working FHIR R4 incremental ingestion pipeline built against the public HAPI FHIR test server.

## What it demonstrates

- FHIR R4 resource model: Patient → Encounter, Observation, Condition, MedicationRequest
- Incremental loads using `_lastUpdated` watermark (reruns fetch only new/changed records)
- Idempotency via `resource.id` deduplication
- Flattening nested FHIR JSON into normalized tabular output (CSV)
- Per-resource data quality checks: missing IDs, invalid dates, missing references, duplicates
- Patient-centric joined summary with risk scoring
- Visual HTML dashboards (Chart.js + Mermaid) — no framework needed, just open in browser

## Files

| File | Purpose |
|---|---|
| `fhir_ingest.py` | Core ingestion pipeline. Fetches all 5 resource types per patient, writes CSVs, updates watermark. |
| `build_patient_story.py` | Joins CSVs into a patient activity summary + generates `patient_story.html` dashboard. |
| `build_patient_timeline.py` | Builds a chronological per-patient care timeline → `patient_timeline.html`. |
| `patient_story.html` | Activity dashboard: KPI cards, stacked bar, donut, bubble chart, risk table, Mermaid model diagram. |
| `patient_timeline.html` | Scrollable care timeline for the highest-activity patient. Filterable by resource type. |
| `watermark.json` | Auto-generated. Tracks per-resource last-ingested timestamp for incremental runs. |
| `*.csv` | Auto-generated output: patients, encounters, observations, conditions, medication_requests, summary. |

## Setup

```bash
pip install requests
```

No other dependencies. Runs against the free public HAPI FHIR R4 server — no API key required.

## Usage

```bash
# Step 1: Run ingestion (incremental; safe to rerun)
python fhir_ingest.py

# Step 2: Build the activity dashboard
python build_patient_story.py

# Step 3: Build the patient timeline
python build_patient_timeline.py

# Step 4: Open visuals
open patient_story.html
open patient_timeline.html
```

On the second run, `fhir_ingest.py` only fetches records updated since the last run (watermark-based).

## Key FHIR concepts exercised

| Concept | Implementation |
|---|---|
| Resource model | Patient as anchor; Encounter/Observation/Condition/MedicationRequest linked via `subject.reference` |
| Search params | `patient=`, `_lastUpdated=gt{ts}`, `_sort=_lastUpdated`, `_count` |
| Pagination | Follows FHIR Bundle `next` links automatically |
| Incremental load | Per-resource watermark in `watermark.json`, advanced each run |
| Terminology | SNOMED codes surfaced in Condition/Encounter `type` fields |

## What the data looks like

Against the public HAPI server, a typical run yields:
- 20 patients
- 33+ encounters with real procedure codes and durations
- Conditions with clinical/verification status
- MedicationRequests with RxNorm codes and authoring dates
- Data quality signals: missing DOBs, encounter-heavy patients with no diagnosis capture

## Honest scope

Built in one focused session for domain learning. Not production-hardened — no auth, no PHI handling, no retry logic beyond timeout. The patterns (incremental watermark, DQ checks, resource normalization) apply directly to production FHIR integrations.
