"""Clean messy CSV files with pandas.

Usage:
    python clean_csv.py input.csv -o cleaned.csv --report
    python clean_csv.py input.csv --report --date-columns joined signup_date

Cleaning steps:
  1. Strip whitespace from column names and string cells.
  2. Convert empty / whitespace-only strings to NaN.
  3. Drop rows that are entirely empty.
  4. Remove duplicate rows.
  5. Parse date columns (auto-detected + user-specified), normalize to YYYY-MM-DD.
  6. Fill missing values: numeric -> median, categorical -> mode, all-empty -> 'Unknown'/0.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd


def detect_date_columns(df: pd.DataFrame, user_cols: list[str] | None = None) -> list[str]:
    """Return date columns: user-specified plus auto-detected (*date*, *time*, *dob*, *joined*, etc.)."""
    cols = []
    if user_cols:
        cols.extend([c for c in user_cols if c in df.columns])
    keywords = ("date", "time", "dob", "birth", "joined", "created", "updated", "signup", "sign_up")
    for c in df.columns:
        if c in cols:
            continue
        name = c.lower()
        if any(k in name for k in keywords):
            cols.append(c)
            continue
        # Heuristic: if a string/object column has at least one parseable date, treat as date.
        if pd.api.types.is_string_dtype(df[c].dtype) or df[c].dtype == object:
            sample = df[c].dropna().head(20)
            if sample.empty:
                continue
            try:
                parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
                if parsed.notna().sum() >= max(1, len(sample) // 2):
                    cols.append(c)
            except Exception:
                pass
    return cols


def clean_dataframe(df: pd.DataFrame, date_columns: list[str] | None = None) -> tuple[pd.DataFrame, dict]:
    report: dict = {}
    report["rows_before"] = len(df)
    report["columns"] = list(df.columns)

    # 1. Clean column names (strip).
    original_cols = list(df.columns)
    df = df.rename(columns=lambda x: x.strip() if isinstance(x, str) else x)
    renamed = {o: n for o, n in zip(original_cols, df.columns) if o != n}
    report["renamed_columns"] = renamed

    # 2. Strip string cells, convert empty/whitespace-only to NA.
    for col in df.select_dtypes(include=["object", "str"]).columns:
        df[col] = df[col].apply(lambda v: v.strip() if isinstance(v, str) else v)
    df = df.replace(r"^\s*$", pd.NA, regex=True)

    report["missing_before"] = {c: int(df[c].isna().sum()) for c in df.columns}

    # 3. Drop fully-empty rows.
    empty_rows = int(df.isna().all(axis=1).sum())
    df = df.dropna(how="all")
    report["empty_rows_dropped"] = empty_rows

    # 4. Duplicates.
    dupes = int(df.duplicated().sum())
    df = df.drop_duplicates().reset_index(drop=True)
    report["duplicates_removed"] = dupes

    # 5. Dates: parse + normalize to ISO YYYY-MM-DD.
    date_cols = detect_date_columns(df, date_columns)
    date_info = {}
    for col in date_cols:
        before_nat = int(pd.to_datetime(df[col], errors="coerce", format="mixed").isna().sum())
        parsed = pd.to_datetime(df[col], errors="coerce", format="mixed")
        unparseable = int(parsed.isna().sum() - df[col].isna().sum())
        # Only keep conversion if at least one value parsed.
        if parsed.notna().any():
            df[col] = parsed.dt.strftime("%Y-%m-%d")
            # strftime turns NaT into NaN; restore as NA for consistent missing-value handling.
            df[col] = df[col].where(parsed.notna(), pd.NA)
        date_info[col] = {"unparseable_values": max(0, unparseable), "missing_after_parse": before_nat}
    report["date_columns"] = date_info

    # 6. Missing values.
    filled = {}
    for col in df.columns:
        n_missing = int(df[col].isna().sum())
        if n_missing == 0:
            continue
        # Try numeric conversion for object columns that look numeric.
        series = df[col]
        numeric = pd.to_numeric(series, errors="coerce")
        is_numeric = pd.api.types.is_numeric_dtype(df[col]) or (
            series.dtype == object and numeric.notna().sum() > 0 and numeric.notna().sum() >= n_missing * 0.5
        )
        if col in date_info:
            # Leave dates as-is (NaN = missing/unparseable); just report.
            filled[col] = {"strategy": "left as empty (date)", "filled": 0, "remaining": n_missing}
        elif is_numeric:
            if pd.api.types.is_numeric_dtype(df[col]):
                median = df[col].median()
            else:
                median = numeric.median()
                # Commit numeric conversion if it looks numeric.
                if numeric.notna().sum() >= series.notna().sum() * 0.8:
                    df[col] = numeric
            if pd.isna(median):
                df[col] = df[col].fillna(0)
                filled[col] = {"strategy": "all-empty -> 0", "filled": n_missing, "remaining": 0}
            else:
                df[col] = df[col].fillna(median)
                filled[col] = {"strategy": f"median ({median})", "filled": n_missing, "remaining": 0}
        else:
            mode_vals = df[col].mode(dropna=True)
            if len(mode_vals) == 0:
                df[col] = df[col].fillna("Unknown")
                filled[col] = {"strategy": "all-empty -> 'Unknown'", "filled": n_missing, "remaining": 0}
            else:
                df[col] = df[col].fillna(mode_vals.iloc[0])
                filled[col] = {"strategy": f"mode ('{mode_vals.iloc[0]}')", "filled": n_missing, "remaining": 0}
    report["missing_filled"] = filled
    report["rows_after"] = len(df)
    report["rows_removed"] = report["rows_before"] - len(df)
    return df, report


def format_report(report: dict) -> str:
    lines = [
        "=== CSV Clean Report ===",
        f"Rows before: {report['rows_before']}",
        f"Rows after:  {report['rows_after']}",
        f"Rows removed (dupes + fully-empty): {report['rows_removed']}",
        f"  - Duplicates removed: {report['duplicates_removed']}",
        f"  - Fully-empty rows dropped: {report['empty_rows_dropped']}",
    ]
    if report["renamed_columns"]:
        lines.append("Renamed columns (whitespace stripped):")
        for o, n in report["renamed_columns"].items():
            lines.append(f"  - '{o}' -> '{n}'")
    lines.append("Missing values before cleaning:")
    for col, n in report["missing_before"].items():
        lines.append(f"  - {col}: {n}")
    if report["date_columns"]:
        lines.append("Date columns:")
        for col, info in report["date_columns"].items():
            lines.append(f"  - {col}: unparseable={info['unparseable_values']}")
    else:
        lines.append("Date columns: none detected")
    if report["missing_filled"]:
        lines.append("Missing values filled:")
        for col, info in report["missing_filled"].items():
            lines.append(f"  - {col}: {info['strategy']}, filled={info['filled']}")
    else:
        lines.append("Missing values filled: none needed")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Clean a messy CSV (missing values, inconsistent dates, duplicates).")
    p.add_argument("input", help="Input CSV path")
    p.add_argument("-o", "--output", default=None, help="Output CSV path (default: <input_stem>_cleaned.csv)")
    p.add_argument("--report", action="store_true", help="Print a summary of what was cleaned")
    p.add_argument("--date-columns", nargs="*", default=None, help="Extra columns to force-parse as dates")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    in_path = Path(args.input)
    if not in_path.is_file():
        print(f"Error: input file not found: {in_path}", file=sys.stderr)
        return 2
    out_path = Path(args.output) if args.output else in_path.with_name(f"{in_path.stem}_cleaned.csv")

    try:
        df = pd.read_csv(in_path, dtype=str, keep_default_na=True)
        # Let pandas infer numerics where possible after initial string read.
        for col in df.columns:
            converted = pd.to_numeric(df[col], errors="coerce")
            if converted.notna().sum() >= df[col].notna().sum() * 0.8 and converted.notna().any():
                df[col] = converted
    except Exception as e:
        print(f"Error reading CSV: {e}", file=sys.stderr)
        return 1

    cleaned, report = clean_dataframe(df, date_columns=args.date_columns)

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cleaned.to_csv(out_path, index=False)
    except Exception as e:
        print(f"Error writing CSV: {e}", file=sys.stderr)
        return 1

    print(f"Cleaned CSV written to {out_path} ({len(cleaned)} rows)")
    if args.report:
        print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())