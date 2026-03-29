Session-pipeline JSON Schemas live here.

These schemas cover the structured artifacts currently produced by the session code and skills:

- `session-manifest.schema.json`: `session.yaml` from `prepare-source`
- `speaker-stats.schema.json`: `speaker-stats.json` from `prepare-source`
- `normalized-transcript.schema.json`: `*.normalized.json` from `taelgar_utils.session.normalize`
- `cleanup-report.schema.json`: `<prefix>-cleanup-report.json` from `report_cleanup_diff.py`
- `session-corrections.schema.json`: `<prefix>-session-corrections.yaml` from `report_cleanup_diff.py`
- `beats.schema.json`: `<prefix>-beats.json` from `manage_beats.py`
- `beat-contexts.schema.json`: `<prefix>-beat-contexts.json` from `extract_beat_context.py`
- `beat-facts.schema.json`: `<prefix>-beat-facts.json` from the beat-annotator skill

The YAML artifacts are listed here because JSON Schema can validate YAML data models too.
