# CSV Cleaner

A command-line tool that cleans messy CSV files — handles missing values, 
duplicate rows, mixed date formats, and inconsistent data — and generates 
a data quality report.

## Features
- Removes duplicate and empty rows
- Normalizes date formats to `YYYY-MM-DD`
- Fills missing numeric values with median
- Fills missing categorical values with mode (most frequent value)
- Generates a summary report of changes made

## Usage
```bash
python clean_csv.py --input test.csv --output cleaned.csv --report
```

## Example
**Input (`test.csv`)** — messy data with duplicates, missing values, and inconsistent formats

**Output (`cleaned.csv`)** — cleaned and normalized data, ready for analysis

## Tech Stack
Python, pandas
