"""
CSV/TSV Converter for Gear Calendar Data

Convert tabular gear data (from spreadsheet) to JSON calendar format.

Expected input format (tab or comma separated):
    date    count   Chainring   Cog     Gear
    3/2/2025    1.00    57  13  118.4
    3/2/2025    2.00    57  13  118.4
    ...

Where:
    - date: Activity date (M/D/YYYY or YYYY-MM-DD)
    - count: Effort index/number (1-based, will be converted to 0-based)
    - Chainring: Chainring teeth
    - Cog: Cog teeth
    - Gear: Gear inches (optional, for display only)
"""

import csv
import json
from collections import defaultdict
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, Union


def parse_date(date_str: str) -> date:
    """Parse date from various formats."""
    date_str = date_str.strip()

    # Try ISO format first (YYYY-MM-DD)
    if '-' in date_str and len(date_str) == 10:
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            pass

    # Try M/D/YYYY format
    if '/' in date_str:
        parts = date_str.split('/')
        if len(parts) == 3:
            month, day, year = parts
            # Handle 2-digit year
            year = int(year)
            if year < 100:
                year += 2000
            return date(year, int(month), int(day))

    raise ValueError(f"Cannot parse date: {date_str}")


def convert_tsv_to_calendar_json(
    input_data: Union[str, Path],
    output_path: Optional[str] = None,
    delimiter: str = '\t',
    has_header: bool = True,
) -> Dict:
    """
    Convert TSV/CSV gear data to JSON calendar format.

    Args:
        input_data: File path or string containing the data
        output_path: Optional output JSON file path
        delimiter: Column delimiter (tab or comma)
        has_header: Whether first row is header

    Returns:
        Dict in calendar JSON format
    """
    # Read data
    if isinstance(input_data, Path) or (isinstance(input_data, str) and Path(input_data).exists()):
        with open(input_data, 'r') as f:
            content = f.read()
    else:
        content = input_data

    # Parse as CSV/TSV
    reader = csv.reader(StringIO(content), delimiter=delimiter)
    rows = list(reader)

    if has_header:
        header = [h.lower().strip() for h in rows[0]]
        rows = rows[1:]
    else:
        # Default column order
        header = ['date', 'count', 'chainring', 'cog', 'gear']

    # Find column indices
    def find_col(names: List[str]) -> int:
        for name in names:
            if name in header:
                return header.index(name)
        return -1

    date_col = find_col(['date', 'activity_date'])
    count_col = find_col(['count', 'effort_index', 'index', 'effort_num', '#'])
    chainring_col = find_col(['chainring', 'cr', 'front', 'big_ring'])
    cog_col = find_col(['cog', 'sprocket', 'rear', 'small_ring'])

    if date_col < 0 or chainring_col < 0 or cog_col < 0:
        raise ValueError(f"Required columns not found. Header: {header}")

    # Group by date
    efforts_by_date: Dict[date, List[Dict]] = defaultdict(list)

    for row in rows:
        if not row or not row[date_col].strip():
            continue

        try:
            d = parse_date(row[date_col])
            chainring = int(float(row[chainring_col]))
            cog = int(float(row[cog_col]))

            # Effort index (convert from 1-based to 0-based if present)
            if count_col >= 0 and row[count_col].strip():
                effort_index = int(float(row[count_col])) - 1  # Convert to 0-based
            else:
                effort_index = len(efforts_by_date[d])  # Auto-increment

            efforts_by_date[d].append({
                'chainring': chainring,
                'cog': cog,
                'effort_index': effort_index,
                'effort_type': 200,
            })

        except (ValueError, IndexError) as e:
            print(f"Warning: Skipping row {row}: {e}")
            continue

    # Build calendar JSON
    calendar = {}
    for d in sorted(efforts_by_date.keys()):
        efforts = efforts_by_date[d]

        # Sort by effort index
        efforts.sort(key=lambda e: e['effort_index'])

        calendar[d.isoformat()] = {
            'efforts': efforts
        }

    # Save if output path provided
    if output_path:
        with open(output_path, 'w') as f:
            json.dump(calendar, f, indent=2)
        print(f"Saved calendar to: {output_path}")

    return calendar


def convert_inline_data(data: str, output_path: str) -> Dict:
    """
    Convenience function for converting inline pasted data.

    Automatically detects delimiter (tab vs comma).
    """
    # Detect delimiter
    if '\t' in data:
        delimiter = '\t'
    elif ',' in data:
        delimiter = ','
    else:
        # Assume whitespace
        delimiter = None

    if delimiter:
        return convert_tsv_to_calendar_json(data, output_path, delimiter=delimiter)
    else:
        # Handle whitespace-delimited
        lines = data.strip().split('\n')
        processed = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 4:
                # Assume: date count chainring cog [gear]
                processed.append('\t'.join(parts[:5]))
        return convert_tsv_to_calendar_json('\n'.join(processed), output_path, delimiter='\t', has_header=False)


def print_calendar_summary(calendar: Dict) -> None:
    """Print a summary of the calendar data."""
    print("\n" + "=" * 60)
    print("Calendar Summary")
    print("=" * 60)

    total_efforts = 0
    gears = defaultdict(int)

    for date_str, entry in sorted(calendar.items()):
        efforts = entry.get('efforts', [])
        n_efforts = len(efforts)
        total_efforts += n_efforts

        gear_strs = [f"{e['chainring']}/{e['cog']}" for e in efforts]
        unique_gears = set(gear_strs)

        for g in gear_strs:
            gears[g] += 1

        if len(unique_gears) > 1:
            # Multiple gears on same date - highlight
            print(f"{date_str}: {n_efforts} efforts - MIXED GEARS: {', '.join(gear_strs)}")
        else:
            print(f"{date_str}: {n_efforts} efforts @ {gear_strs[0]}")

    print("-" * 60)
    print(f"Total: {len(calendar)} dates, {total_efforts} efforts")
    print("\nGear distribution:")
    for gear, count in sorted(gears.items(), key=lambda x: -x[1]):
        print(f"  {gear}: {count} efforts")


# CLI usage
if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python csv_converter.py <input_file> [output_json]")
        print("       Converts TSV/CSV gear data to calendar JSON format")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'gear_calendar.json'

    # Auto-detect delimiter from file extension
    if input_file.endswith('.csv'):
        delimiter = ','
    else:
        delimiter = '\t'

    calendar = convert_tsv_to_calendar_json(input_file, output_file, delimiter=delimiter)
    print_calendar_summary(calendar)
