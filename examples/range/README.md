# Range timeline CSV examples

Sample files for exercising the range timeline CSV importer. Use them with
the GUI's *Timelines → Import Range Timeline → from CSV file* (or the
backend `tilia.parsers.csv.range.import_by_time` /
`import_by_measure`).

| File | Mode | Purpose |
| --- | --- | --- |
| `by_time_minimal.csv` | by-time | Smallest valid input (just `start,end,row`). Verifies row auto-creation by name. |
| `by_time_basic.csv` | by-time | Realistic by-time CSV with all optional columns (label, color, comments) and two rows. Time range: 0–120s. |
| `by_time_overlapping.csv` | by-time | Overlapping ranges within a row, plus a second row that fully contains the first. Use this to verify the overlap-allowed invariant. |
| `by_time_joined_basic.csv` | by-time | Two adjacent ranges with `joined_with_next=true` on the first; verifies the simplest join case. |
| `by_time_joined_chain.csv` | by-time | Five-range chain on a single row, four joined together. Renders as a single connected band. |
| `by_time_joined_multi_row.csv` | by-time | Joins on two rows simultaneously, with the CSV interleaving rows. Verifies that joins are scoped per row regardless of CSV order. |
| `by_time_joined_bool_variants.csv` | by-time | Exercises every accepted boolean spelling: `true`, `yes`, `1`, `Y`, `TRUE`. |
| `by_time_joined_invalid.csv` | by-time | **(Item 4 preview.)** Demonstrates invalid join configurations: a gap between two flagged-and-joined ranges (row A), an overlap (row B), and a flag on the temporally last range of a row (row C). Today these silently fail to join — once import-side validation lands, the importer will report each as an error. |
| `by_measure_basic.csv` | by-measure | All optional columns, multiple rows. Requires a beat timeline with at least 36 measures. |
| `by_measure_with_fractions.csv` | by-measure | Exercises `start_fraction` / `end_fraction`. Requires a beat timeline with 20 measures. |
| `by_measure_joined.csv` | by-measure | `joined_with_next` in measure mode. Requires a beat timeline with ≥24 measures. |
| `errors_demo.csv` | by-time | Mixes valid rows with bad start/end values and an empty row name. Useful for verifying that errors are surfaced and bad rows are skipped without aborting the import. |

## Required columns

- `start`, `end`, `row` are required.
- `label`, `color`, `comments` are optional. Empty `color` falls back to the
  row's color (or, in turn, to the global default).
- `joined_with_next` is optional. `true`/`yes`/`1`/`y`/`t` (case-insensitive)
  link the current range to the temporally-next range on the same row;
  empty / `false`/`no`/`0`/`n`/`f` leave it independent. Joining only fires
  when the two ranges abut (`r1.end == r2.start`); a gap will be reported
  by the importer once join validation lands.
- For `import_by_measure`, `start_fraction` and `end_fraction` (0–1) are
  also optional and default to 0.

## Tips for testing

- For the by-measure CSVs, create a beat timeline first (e.g. 1 beat per
  measure with a beat at every second) so the importer can resolve
  measures to times. The basic file expects ≥36 measures; the fractions
  file expects ≥20.
- After import, the importer **auto-creates rows by name** in the order
  they first appear in the CSV. Existing rows with matching names are
  reused.
