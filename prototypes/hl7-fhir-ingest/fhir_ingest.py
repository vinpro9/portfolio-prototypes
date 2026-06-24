"""
fhir_ingest.py
Minimal FHIR ingestion prototype for learning purposes.

What it demonstrates:
  - Fetching Patient and Observation resources from a public FHIR server
    - Fetching Condition resources linked to each patient
    - Fetching MedicationRequest resources linked to each patient
    - Fetching Encounter resources linked to each patient
  - Flattening nested FHIR JSON into tabular rows
  - Incremental load via _lastUpdated watermark (watermark.json)
  - Basic data quality checks (missing IDs, bad dates, duplicates)

Run:
    python3 fhir_ingest.py

Output:
    patients.csv, observations.csv, conditions.csv, medication_requests.csv, encounters.csv, watermark.json
"""

import json
import csv
import os
import sys
from datetime import datetime, timezone
from typing import Optional

try:
    import requests
except ImportError:
    sys.exit("Install requests: pip3 install requests")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = "https://hapi.fhir.org/baseR4"
WATERMARK_FILE = "watermark.json"
PAGE_SIZE = 20
MAX_PATIENTS = 20   # Keep small for demo; increase as needed


# ---------------------------------------------------------------------------
# Watermark helpers (track incremental progress)
# ---------------------------------------------------------------------------
def load_watermark() -> dict:
    if os.path.exists(WATERMARK_FILE):
        with open(WATERMARK_FILE) as f:
            return json.load(f)
    return {}


def save_watermark(wm: dict) -> None:
    with open(WATERMARK_FILE, "w") as f:
        json.dump(wm, f, indent=2)
    print(f"  [watermark] Saved to {WATERMARK_FILE}: {wm}")


# ---------------------------------------------------------------------------
# FHIR fetch helpers
# ---------------------------------------------------------------------------
def fhir_get(path: str, params: dict = None) -> dict:
    """GET a FHIR URL and return the parsed JSON."""
    url = f"{BASE_URL}/{path}"
    resp = requests.get(url, params=params or {}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def iter_bundle(path: str, params: dict = None):
    """Yield each resource entry from a paginated FHIR Bundle."""
    data = fhir_get(path, params)
    while True:
        for entry in data.get("entry", []):
            yield entry["resource"]
        # Follow 'next' link for pagination
        next_url = next(
            (l["url"] for l in data.get("link", []) if l["relation"] == "next"),
            None,
        )
        if not next_url:
            break
        resp = requests.get(next_url, timeout=15)
        resp.raise_for_status()
        data = resp.json()


# ---------------------------------------------------------------------------
# Flatten Patient resource
# ---------------------------------------------------------------------------
def flatten_patient(r: dict) -> dict:
    name = r.get("name", [{}])[0]
    family = name.get("family", "")
    given = " ".join(name.get("given", []))
    address = r.get("address", [{}])[0]
    return {
        "id": r.get("id", ""),
        "last_updated": r.get("meta", {}).get("lastUpdated", ""),
        "active": r.get("active", ""),
        "gender": r.get("gender", ""),
        "birth_date": r.get("birthDate", ""),
        "family_name": family,
        "given_name": given,
        "city": address.get("city", ""),
        "state": address.get("state", ""),
        "postal_code": address.get("postalCode", ""),
    }


# ---------------------------------------------------------------------------
# Flatten Observation resource
# ---------------------------------------------------------------------------
def flatten_observation(r: dict) -> dict:
    patient_ref = r.get("subject", {}).get("reference", "")
    # Extract numeric value if present
    value_quantity = r.get("valueQuantity", {})
    code = r.get("code", {}).get("coding", [{}])[0]
    return {
        "id": r.get("id", ""),
        "last_updated": r.get("meta", {}).get("lastUpdated", ""),
        "status": r.get("status", ""),
        "patient_id": patient_ref.replace("Patient/", ""),
        "code": code.get("code", ""),
        "display": code.get("display", ""),
        "value": value_quantity.get("value", ""),
        "unit": value_quantity.get("unit", ""),
        "effective_date": r.get("effectiveDateTime", ""),
        "issued": r.get("issued", ""),
    }


# ---------------------------------------------------------------------------
# Flatten Condition resource
# ---------------------------------------------------------------------------
def flatten_condition(r: dict) -> dict:
    patient_ref = r.get("subject", {}).get("reference", "")
    code = r.get("code", {}).get("coding", [{}])[0]
    category = r.get("category", [{}])[0].get("coding", [{}])[0]
    clinical_status = r.get("clinicalStatus", {}).get("coding", [{}])[0]
    verification_status = r.get("verificationStatus", {}).get("coding", [{}])[0]

    return {
        "id": r.get("id", ""),
        "last_updated": r.get("meta", {}).get("lastUpdated", ""),
        "patient_id": patient_ref.replace("Patient/", ""),
        "clinical_status": clinical_status.get("code", ""),
        "verification_status": verification_status.get("code", ""),
        "category": category.get("code", ""),
        "code": code.get("code", ""),
        "display": code.get("display", ""),
        "onset_datetime": r.get("onsetDateTime", ""),
        "recorded_date": r.get("recordedDate", ""),
    }


# ---------------------------------------------------------------------------
# Flatten MedicationRequest resource
# ---------------------------------------------------------------------------
def flatten_medication_request(r: dict) -> dict:
    patient_ref = r.get("subject", {}).get("reference", "")
    med_code = r.get("medicationCodeableConcept", {}).get("coding", [{}])[0]

    return {
        "id": r.get("id", ""),
        "last_updated": r.get("meta", {}).get("lastUpdated", ""),
        "patient_id": patient_ref.replace("Patient/", ""),
        "status": r.get("status", ""),
        "intent": r.get("intent", ""),
        "medication_code": med_code.get("code", ""),
        "medication_display": med_code.get("display", ""),
        "authored_on": r.get("authoredOn", ""),
    }


# ---------------------------------------------------------------------------
# Flatten Encounter resource
# ---------------------------------------------------------------------------
def flatten_encounter(r: dict) -> dict:
    subject_ref = r.get("subject", {}).get("reference", "")
    encounter_class = r.get("class", {})
    encounter_type = r.get("type", [{}])[0].get("coding", [{}])[0]

    return {
        "id": r.get("id", ""),
        "last_updated": r.get("meta", {}).get("lastUpdated", ""),
        "patient_id": subject_ref.replace("Patient/", ""),
        "status": r.get("status", ""),
        "class_code": encounter_class.get("code", ""),
        "class_display": encounter_class.get("display", ""),
        "type_code": encounter_type.get("code", ""),
        "type_display": encounter_type.get("display", ""),
        "period_start": r.get("period", {}).get("start", ""),
        "period_end": r.get("period", {}).get("end", ""),
    }


# ---------------------------------------------------------------------------
# Data quality checks
# ---------------------------------------------------------------------------
def check_patient(row: dict) -> list[str]:
    issues = []
    if not row["id"]:
        issues.append("MISSING_ID")
    if not row["birth_date"]:
        issues.append("MISSING_BIRTH_DATE")
    elif not _valid_date(row["birth_date"]):
        issues.append(f"INVALID_DATE:{row['birth_date']}")
    if row["gender"] not in ("male", "female", "other", "unknown", ""):
        issues.append(f"UNEXPECTED_GENDER:{row['gender']}")
    return issues


def check_observation(row: dict) -> list[str]:
    issues = []
    if not row["id"]:
        issues.append("MISSING_ID")
    if not row["patient_id"]:
        issues.append("MISSING_PATIENT_REF")
    if not row["code"]:
        issues.append("MISSING_CODE")
    if row["effective_date"] and not _valid_date(row["effective_date"]):
        issues.append(f"INVALID_EFFECTIVE_DATE:{row['effective_date']}")
    return issues


def check_condition(row: dict) -> list[str]:
    issues = []
    if not row["id"]:
        issues.append("MISSING_ID")
    if not row["patient_id"]:
        issues.append("MISSING_PATIENT_REF")
    if not row["code"]:
        issues.append("MISSING_CODE")
    if row["onset_datetime"] and not _valid_date(row["onset_datetime"]):
        issues.append(f"INVALID_ONSET_DATE:{row['onset_datetime']}")
    return issues


def check_medication_request(row: dict) -> list[str]:
    issues = []
    if not row["id"]:
        issues.append("MISSING_ID")
    if not row["patient_id"]:
        issues.append("MISSING_PATIENT_REF")
    if not row["status"]:
        issues.append("MISSING_STATUS")
    if not row["intent"]:
        issues.append("MISSING_INTENT")
    if not row["medication_code"]:
        issues.append("MISSING_MEDICATION_CODE")
    if row["authored_on"] and not _valid_date(row["authored_on"]):
        issues.append(f"INVALID_AUTHORED_ON:{row['authored_on']}")
    return issues


def check_encounter(row: dict) -> list[str]:
    issues = []
    if not row["id"]:
        issues.append("MISSING_ID")
    if not row["patient_id"]:
        issues.append("MISSING_PATIENT_REF")
    if not row["status"]:
        issues.append("MISSING_STATUS")
    if row["period_start"] and not _valid_date(row["period_start"]):
        issues.append(f"INVALID_PERIOD_START:{row['period_start']}")
    if row["period_end"] and not _valid_date(row["period_end"]):
        issues.append(f"INVALID_PERIOD_END:{row['period_end']}")
    return issues


def _valid_date(value: str) -> bool:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            datetime.strptime(value[:len(fmt) - 2], fmt[:len(value)])
            return True
        except ValueError:
            pass
    # Simplified: just check it starts with 4-digit year
    return len(value) >= 4 and value[:4].isdigit()


# ---------------------------------------------------------------------------
# Write CSV
# ---------------------------------------------------------------------------
def write_csv(filename: str, rows: list[dict], fieldnames: list[str]) -> None:
    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames + ["dq_issues"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"  [csv] Wrote {len(rows)} rows → {filename}")


# ---------------------------------------------------------------------------
# Main ingestion flow
# ---------------------------------------------------------------------------
def run():
    print("=" * 60)
    print("FHIR Ingestion Prototype")
    print(f"Server: {BASE_URL}")
    print("=" * 60)

    watermark = load_watermark()
    last_patient_ts = watermark.get("patients_last_updated", "1970-01-01T00:00:00Z")
    last_obs_ts = watermark.get("observations_last_updated", "1970-01-01T00:00:00Z")
    last_condition_ts = watermark.get("conditions_last_updated", "1970-01-01T00:00:00Z")
    last_medreq_ts = watermark.get("medication_requests_last_updated", "1970-01-01T00:00:00Z")
    last_encounter_ts = watermark.get("encounters_last_updated", "1970-01-01T00:00:00Z")

    # ---- Step 1: Fetch Patients ----
    print(f"\n[1] Fetching patients (incremental since {last_patient_ts})")
    params = {
        "_count": PAGE_SIZE,
        "_lastUpdated": f"gt{last_patient_ts}",
        "_sort": "_lastUpdated",
    }
    patient_rows = []
    seen_patient_ids = set()
    newest_patient_ts = last_patient_ts

    for resource in iter_bundle("Patient", params):
        if len(patient_rows) >= MAX_PATIENTS:
            break
        row = flatten_patient(resource)
        issues = check_patient(row)
        row["dq_issues"] = "|".join(issues) if issues else ""

        if row["id"] in seen_patient_ids:
            row["dq_issues"] += "|DUPLICATE_ID"
        seen_patient_ids.add(row["id"])

        patient_rows.append(row)
        if row["last_updated"] > newest_patient_ts:
            newest_patient_ts = row["last_updated"]

    print(f"  Fetched {len(patient_rows)} patients.")

    patient_fields = [
        "id", "last_updated", "active", "gender", "birth_date",
        "family_name", "given_name", "city", "state", "postal_code",
    ]
    write_csv("patients.csv", patient_rows, patient_fields)

    # ---- Step 2: Fetch Observations for each patient ----
    print(f"\n[2] Fetching observations (incremental since {last_obs_ts})")
    obs_rows = []
    seen_obs_ids = set()
    newest_obs_ts = last_obs_ts

    for patient in patient_rows:
        pid = patient["id"]
        if not pid:
            continue
        obs_params = {
            "_count": PAGE_SIZE,
            "patient": pid,
            "_lastUpdated": f"gt{last_obs_ts}",
            "_sort": "_lastUpdated",
        }
        try:
            for resource in iter_bundle("Observation", obs_params):
                row = flatten_observation(resource)
                issues = check_observation(row)
                row["dq_issues"] = "|".join(issues) if issues else ""

                if row["id"] in seen_obs_ids:
                    row["dq_issues"] += "|DUPLICATE_ID"
                seen_obs_ids.add(row["id"])

                obs_rows.append(row)
                if row["last_updated"] > newest_obs_ts:
                    newest_obs_ts = row["last_updated"]
        except Exception as e:
            print(f"  [warn] Could not fetch observations for patient {pid}: {e}")

    print(f"  Fetched {len(obs_rows)} observations.")

    obs_fields = [
        "id", "last_updated", "status", "patient_id",
        "code", "display", "value", "unit", "effective_date", "issued",
    ]
    write_csv("observations.csv", obs_rows, obs_fields)

    # ---- Step 3: Fetch Conditions for each patient ----
    print(f"\n[3] Fetching conditions (incremental since {last_condition_ts})")
    condition_rows = []
    seen_condition_ids = set()
    newest_condition_ts = last_condition_ts

    for patient in patient_rows:
        pid = patient["id"]
        if not pid:
            continue
        condition_params = {
            "_count": PAGE_SIZE,
            "patient": pid,
            "_lastUpdated": f"gt{last_condition_ts}",
            "_sort": "_lastUpdated",
        }
        try:
            for resource in iter_bundle("Condition", condition_params):
                row = flatten_condition(resource)
                issues = check_condition(row)
                row["dq_issues"] = "|".join(issues) if issues else ""

                if row["id"] in seen_condition_ids:
                    row["dq_issues"] += "|DUPLICATE_ID"
                seen_condition_ids.add(row["id"])

                condition_rows.append(row)
                if row["last_updated"] > newest_condition_ts:
                    newest_condition_ts = row["last_updated"]
        except Exception as e:
            print(f"  [warn] Could not fetch conditions for patient {pid}: {e}")

    print(f"  Fetched {len(condition_rows)} conditions.")

    condition_fields = [
        "id", "last_updated", "patient_id", "clinical_status", "verification_status",
        "category", "code", "display", "onset_datetime", "recorded_date",
    ]
    write_csv("conditions.csv", condition_rows, condition_fields)

    # ---- Step 4: Fetch MedicationRequests for each patient ----
    print(f"\n[4] Fetching medication requests (incremental since {last_medreq_ts})")
    medreq_rows = []
    seen_medreq_ids = set()
    newest_medreq_ts = last_medreq_ts

    for patient in patient_rows:
        pid = patient["id"]
        if not pid:
            continue
        medreq_params = {
            "_count": PAGE_SIZE,
            "patient": pid,
            "_lastUpdated": f"gt{last_medreq_ts}",
            "_sort": "_lastUpdated",
        }
        try:
            for resource in iter_bundle("MedicationRequest", medreq_params):
                row = flatten_medication_request(resource)
                issues = check_medication_request(row)
                row["dq_issues"] = "|".join(issues) if issues else ""

                if row["id"] in seen_medreq_ids:
                    row["dq_issues"] += "|DUPLICATE_ID"
                seen_medreq_ids.add(row["id"])

                medreq_rows.append(row)
                if row["last_updated"] > newest_medreq_ts:
                    newest_medreq_ts = row["last_updated"]
        except Exception as e:
            print(f"  [warn] Could not fetch medication requests for patient {pid}: {e}")

    print(f"  Fetched {len(medreq_rows)} medication requests.")

    medreq_fields = [
        "id", "last_updated", "patient_id", "status", "intent",
        "medication_code", "medication_display", "authored_on",
    ]
    write_csv("medication_requests.csv", medreq_rows, medreq_fields)

    # ---- Step 5: Fetch Encounters for each patient ----
    print(f"\n[5] Fetching encounters (incremental since {last_encounter_ts})")
    encounter_rows = []
    seen_encounter_ids = set()
    newest_encounter_ts = last_encounter_ts

    for patient in patient_rows:
        pid = patient["id"]
        if not pid:
            continue
        encounter_params = {
            "_count": PAGE_SIZE,
            "patient": pid,
            "_lastUpdated": f"gt{last_encounter_ts}",
            "_sort": "_lastUpdated",
        }
        try:
            for resource in iter_bundle("Encounter", encounter_params):
                row = flatten_encounter(resource)
                issues = check_encounter(row)
                row["dq_issues"] = "|".join(issues) if issues else ""

                if row["id"] in seen_encounter_ids:
                    row["dq_issues"] += "|DUPLICATE_ID"
                seen_encounter_ids.add(row["id"])

                encounter_rows.append(row)
                if row["last_updated"] > newest_encounter_ts:
                    newest_encounter_ts = row["last_updated"]
        except Exception as e:
            print(f"  [warn] Could not fetch encounters for patient {pid}: {e}")

    print(f"  Fetched {len(encounter_rows)} encounters.")

    encounter_fields = [
        "id", "last_updated", "patient_id", "status", "class_code", "class_display",
        "type_code", "type_display", "period_start", "period_end",
    ]
    write_csv("encounters.csv", encounter_rows, encounter_fields)

    # ---- Step 6: Save watermark ----
    save_watermark({
        "patients_last_updated": newest_patient_ts,
        "observations_last_updated": newest_obs_ts,
        "conditions_last_updated": newest_condition_ts,
        "medication_requests_last_updated": newest_medreq_ts,
        "encounters_last_updated": newest_encounter_ts,
        "run_at": datetime.now(timezone.utc).isoformat(),
    })

    # ---- Step 7: Summary ----
    bad_patients = [r for r in patient_rows if r["dq_issues"]]
    bad_obs = [r for r in obs_rows if r["dq_issues"]]
    bad_conditions = [r for r in condition_rows if r["dq_issues"]]
    bad_medreqs = [r for r in medreq_rows if r["dq_issues"]]
    bad_encounters = [r for r in encounter_rows if r["dq_issues"]]
    print("\n[Summary]")
    print(f"  Patients:     {len(patient_rows)} fetched, {len(bad_patients)} with DQ issues")
    print(f"  Observations: {len(obs_rows)} fetched, {len(bad_obs)} with DQ issues")
    print(f"  Conditions:   {len(condition_rows)} fetched, {len(bad_conditions)} with DQ issues")
    print(f"  MedRequests:  {len(medreq_rows)} fetched, {len(bad_medreqs)} with DQ issues")
    print(f"  Encounters:   {len(encounter_rows)} fetched, {len(bad_encounters)} with DQ issues")
    if bad_patients:
        print("\n  Patient DQ issues:")
        for r in bad_patients:
            print(f"    id={r['id']} issues={r['dq_issues']}")
    if bad_obs:
        print("\n  Observation DQ issues (first 5):")
        for r in bad_obs[:5]:
            print(f"    id={r['id']} issues={r['dq_issues']}")
    if bad_conditions:
        print("\n  Condition DQ issues (first 5):")
        for r in bad_conditions[:5]:
            print(f"    id={r['id']} issues={r['dq_issues']}")
    if bad_medreqs:
        print("\n  MedicationRequest DQ issues (first 5):")
        for r in bad_medreqs[:5]:
            print(f"    id={r['id']} issues={r['dq_issues']}")
    if bad_encounters:
        print("\n  Encounter DQ issues (first 5):")
        for r in bad_encounters[:5]:
            print(f"    id={r['id']} issues={r['dq_issues']}")
    print("\nDone.")


if __name__ == "__main__":
    run()
