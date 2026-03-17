# IONM-Label
## v2.0 — 03/17/2026

### New Features
- **D-wave stacked view**: D-wave files now display all electrode pairs (e.g. 1_2, 1_3, 2_3)
  as vertically stacked subplots per stimulus group, grouped by channel block structure
- **Per-channel Exclude button**: each D-wave subplot has an [Excl] button that marks
  that channel as NO waveform and clears its markers independently
- **Per-channel drag**: start/end marker lines can be dragged independently per subplot,
  allowing fine-tuned latency adjustment per electrode pair after global placement
- **Zoom and pan sliders**: X/Y zoom (right = zoom in, 1–10×) and X/Y pan sliders
  with hard clamping — cannot scroll past data edges
- **Channel status in info bar**: per-channel annotation status shown as symbols
  (e.g. 1_2:✓  1_3:?  2_3:✗) in the top info bar

### Bug Fixes
- **Correct X-axis units**: time axis now derived from `Analysis time` and
  `Display length` metadata fields (ms_per_unit = analysis_time × display_len / 1000),
  fixing D-wave display which previously showed ~15ms data on a 100ms axis
- **Correct Y-axis units**: amplitude now scaled by sensitivity factor
  (sens_value_µV × 1.5e-4 µV/unit) parsed from the `Sens` metadata field
- **Annotation markers now plot at correct positions**: previously markers were
  double-corrected, placing them at wrong x positions
- **Marking mode no longer locks up**: navigating away mid-annotation (e.g. after
  placing start but before end) no longer freezes the marking workflow
- **D-wave load crash fixed**: `ValueError: Width and height specified must be
  non-negative` on loading D-wave files resolved by rebuilding groups before
  figure setup, and always creating a fresh figure on file load

### Performance
- **Async background saves**: file I/O now runs in a daemon thread — UI never
  blocks on disk writes, eliminating the freeze on every annotation change
- **Deferred writes**: file is written on navigation or Ctrl+S rather than on
  every single click, reducing total write operations significantly
- **[unsaved] indicator**: info bar shows pending changes not yet written to disk

### Pipeline Compatibility
- Annotations stored in original raw axis unit convention (compatible with
  existing `data.py` pipeline — `annotation_start_ms` / `annotation_end_ms`
  are in raw units, corrected to true ms by `ms_correction_factor` on read)

### Code Quality
- Removed duplicate class definitions (three versions of MEPAnnotator collapsed
  into one unified class)
- File → Exit now flushes save before closing; use instead of window X button
  to ensure last annotations are written