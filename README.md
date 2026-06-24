# portfolio-prototypes

A collection of small, self-contained engineering prototypes built during interview preparation and domain exploration.
Each prototype is scoped to one problem area, runnable in an afternoon, and demonstrates a specific technical concept end-to-end.

## Structure

```
prototypes/
  hl7-fhir-ingest/   — FHIR R4 incremental patient data ingestion pipeline + visual dashboards
  project2/          — (next prototype)
  ...
```

## Philosophy

These are not production systems. They are deliberately minimal, runnable prototypes that demonstrate:
- Working knowledge of a domain or API
- Good engineering instincts: idempotency, incremental loads, data quality, observability
- The ability to ramp into unfamiliar territory and produce a concrete artifact quickly

Each prototype has its own README with setup, usage, and what it demonstrates.

## Prototypes

| Folder | Domain | What it builds |
|---|---|---|
| [hl7-fhir-ingest](prototypes/hl7-fhir-ingest/) | Healthcare / FHIR R4 | Incremental patient data ingestion pipeline across 5 resource types + HTML visual dashboard |
