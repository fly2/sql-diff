# diff-sql

Compare Oracle PL/SQL package bodies with converted PostgreSQL or OceanBase SQL code.

The tool matches package files by filename, extracts `PACKAGE BODY` content, splits it into `FUNCTION` and `PROCEDURE` units, then reports word-level changes in CSV files.

## Features

- Batch compare two directories of SQL files.
- Match functions and procedures by name.
- Output summary and function/procedure-level detail CSV files.
- Generate normalized text files for manual review.
- Provide two comparison schemes:
  - Semantic normalization: ignores common equivalent Oracle to PostgreSQL/OceanBase syntax changes.
  - Whitespace normalization: removes comments and whitespace while preserving syntax changes.

## Requirements

- Python 3.8+
- No third-party Python dependencies

## Quick Start

```bash
python3 sql_diff.py --old ./examples/old --new ./examples/new --output ./output
```

Required arguments:

- `--old`: directory containing original Oracle PL/SQL files
- `--new`: directory containing converted SQL files

Optional arguments:

- `--output`: output directory, defaults to `output`

## Output

The output directory contains:

```text
output/
├── diff_summary.csv
├── diff_detail.csv
├── normalized/
├── old_body/
└── new_body/
```

`diff_summary.csv` contains file-level statistics for both schemes.

`diff_detail.csv` contains function/procedure-level statistics. The `方案` column identifies whether a row belongs to semantic normalization or whitespace normalization.

## Comparison Schemes

Semantic normalization currently treats these common conversions as equivalent:

- `NUMBER` to `NUMERIC`
- `DEFAULT` to `:=`
- `NVL` to `COALESCE`
- `SYSDATE` to `CURRENT_DATE`
- `ROWNUM` to `ROW_NUMBER`
- trailing `AS` to `IS`
- removes `DECLARE`, function names after `END`, and selected Oracle-only hints such as `DETERMINISTIC`

Whitespace normalization removes comments and blank lines, uppercases tokens, and keeps syntax differences.

## Limitations

This project uses rule-based parsing instead of a full SQL parser. It is intended for migration review metrics, not as proof of semantic equivalence. Complex PL/SQL formatting, nested blocks, dynamic SQL, or unusual package structures may require manual review.

## Development

Run the test suite:

```bash
python3 -m unittest discover -s tests
```

Run a syntax check:

```bash
python3 -m py_compile sql_diff.py
```
