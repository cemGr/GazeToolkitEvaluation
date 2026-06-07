#!/usr/bin/env python3
"""Compare GazeToolkit EyeMovement CSV output with Tobii TSV movement labels.

The comparison is sample-based: each Tobii sample timestamp is matched to the
GazeToolkit movement interval that contains it, then Tobii and toolkit movement
labels are compared.
"""

from __future__ import annotations

import argparse
import csv
from bisect import bisect_right
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

TIMESTAMP_COLUMNS: Sequence[Tuple[str, str]] = (
    ("Eyetracker timestamp [μs]", "us"),
    ("Eyetracker timestamp [us]", "us"),
    ("Recording timestamp [μs]", "us"),
    ("Recording timestamp [us]", "us"),
    ("Recording timestamp [ms]", "ms"),
)

TOBII_TO_TOOLKIT_LABELS = {
    "fixation": "Fixation",
    "saccade": "Saccade",
    "eyesnotfound": "Unknown",
    "unclassified": "Unknown",
    "unknown": "Unknown",
    "": "Unknown",
}

LABELS: Sequence[str] = ("Fixation", "Saccade", "Unknown")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate GazeToolkit EyeMovement CSV output against Tobii TSV "
            "sample-level movement labels. Use the same timestamp source as for conversion."
        )
    )
    parser.add_argument("tobii_tsv", type=Path, help="Original Tobii TSV export with Eye movement type labels.")
    parser.add_argument("movements_csv", type=Path, help="GazeToolkit EyeMovement CSV output.")
    parser.add_argument(
        "--timestamp-column",
        default=None,
        help="Explicit Tobii timestamp column. Defaults to Eyetracker [μs], then Recording [μs]/[ms].",
    )
    parser.add_argument(
        "--tobii-label-column",
        default="Eye movement type",
        help="Tobii movement label column (default: Eye movement type).",
    )
    parser.add_argument(
        "--movement-timestamp-column",
        default="Timestamp",
        help="GazeToolkit movement timestamp column (default: Timestamp).",
    )
    parser.add_argument(
        "--movement-type-column",
        default="MovementType",
        help="GazeToolkit movement type column (default: MovementType).",
    )
    parser.add_argument(
        "--duration-column",
        default="Duration",
        help="GazeToolkit movement duration column in milliseconds (default: Duration).",
    )
    return parser.parse_args()


def parse_number(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    text = text.replace(" ", "").replace("\u00a0", "")
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def find_timestamp_column(fieldnames: Sequence[str], explicit: Optional[str]) -> Tuple[str, str]:
    if explicit:
        if explicit not in fieldnames:
            raise ValueError(f"Timestamp column not found: {explicit}")
        return explicit, "ms" if "[ms]" in explicit.lower() else "us"

    for column, unit in TIMESTAMP_COLUMNS:
        if column in fieldnames:
            return column, unit

    raise ValueError("No supported Tobii timestamp column found.")


def timestamp_to_microseconds(row: Mapping[str, str], column: str, unit: str) -> Optional[float]:
    timestamp = parse_number(row.get(column))
    if timestamp is None:
        return None
    return timestamp * 1000 if unit == "ms" else timestamp


def normalize_tobii_label(label: Optional[str]) -> str:
    key = (label or "").strip().replace(" ", "").lower()
    return TOBII_TO_TOOLKIT_LABELS.get(key, "Unknown")


def normalize_toolkit_label(label: Optional[str]) -> str:
    text = (label or "").strip()
    return text if text in LABELS else "Unknown"


def load_tobii_samples(
    path: Path, explicit_timestamp_column: Optional[str], label_column: str
) -> List[Tuple[float, str]]:
    samples: List[Tuple[float, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.DictReader(infile, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError(f"Input file has no header: {path}")
        timestamp_column, timestamp_unit = find_timestamp_column(reader.fieldnames, explicit_timestamp_column)
        if label_column not in reader.fieldnames:
            raise ValueError(f"Tobii label column not found: {label_column}")

        for row in reader:
            timestamp = timestamp_to_microseconds(row, timestamp_column, timestamp_unit)
            if timestamp is None:
                continue
            samples.append((timestamp, normalize_tobii_label(row.get(label_column))))

    return samples


def load_movements(
    path: Path, timestamp_column: str, movement_type_column: str, duration_column: str
) -> List[Tuple[float, float, str]]:
    movements: List[Tuple[float, float, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.DictReader(infile)
        if reader.fieldnames is None:
            raise ValueError(f"Input file has no header: {path}")
        for column in (timestamp_column, movement_type_column, duration_column):
            if column not in reader.fieldnames:
                raise ValueError(f"Movement CSV column not found: {column}")

        for row in reader:
            start = parse_number(row.get(timestamp_column))
            duration_ms = parse_number(row.get(duration_column))
            if start is None or duration_ms is None:
                continue
            end = start + duration_ms * 1000
            if end <= start:
                continue
            movements.append((start, end, normalize_toolkit_label(row.get(movement_type_column))))

    return sorted(movements, key=lambda movement: movement[0])


def find_movement_label(timestamp: float, movements: Sequence[Tuple[float, float, str]], starts: Sequence[float]) -> Optional[str]:
    index = bisect_right(starts, timestamp) - 1
    if index < 0:
        return None
    start, end, label = movements[index]
    if start <= timestamp < end:
        return label
    return None


def confusion_increment(confusion: Dict[str, Dict[str, int]], expected: str, actual: str) -> None:
    confusion.setdefault(expected, {label: 0 for label in LABELS})
    confusion[expected][actual] = confusion[expected].get(actual, 0) + 1


def safe_ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def print_results(confusion: Dict[str, Dict[str, int]], unmatched: int) -> None:
    total_matched = sum(sum(row.values()) for row in confusion.values())
    correct = sum(confusion.get(label, {}).get(label, 0) for label in LABELS)
    total = total_matched + unmatched

    print(f"Samples total: {total}")
    print(f"Samples matched to toolkit movements: {total_matched}")
    print(f"Samples without matching toolkit movement: {unmatched}")
    print(f"Overall matched-sample accuracy: {safe_ratio(correct, total_matched):.4f}")

    fixation_tp = confusion.get("Fixation", {}).get("Fixation", 0)
    fixation_fp = sum(confusion.get(label, {}).get("Fixation", 0) for label in LABELS if label != "Fixation")
    fixation_fn = sum(count for label, count in confusion.get("Fixation", {}).items() if label != "Fixation")
    precision = safe_ratio(fixation_tp, fixation_tp + fixation_fp)
    recall = safe_ratio(fixation_tp, fixation_tp + fixation_fn)
    f1 = safe_ratio(2 * precision * recall, precision + recall) if precision + recall else 0.0

    print(f"Fixation precision: {precision:.4f}")
    print(f"Fixation recall: {recall:.4f}")
    print(f"Fixation F1: {f1:.4f}")
    print("Confusion matrix (rows=Tobii, columns=GazeToolkit):")
    print(",".join(["Tobii\\GazeToolkit", *LABELS]))
    for expected in LABELS:
        row = confusion.get(expected, {})
        print(",".join([expected, *(str(row.get(actual, 0)) for actual in LABELS)]))


def evaluate(samples: Iterable[Tuple[float, str]], movements: Sequence[Tuple[float, float, str]]) -> Tuple[Dict[str, Dict[str, int]], int]:
    starts = [movement[0] for movement in movements]
    confusion: Dict[str, Dict[str, int]] = {label: {actual: 0 for actual in LABELS} for label in LABELS}
    unmatched = 0

    for timestamp, expected in samples:
        actual = find_movement_label(timestamp, movements, starts)
        if actual is None:
            unmatched += 1
            continue
        confusion_increment(confusion, expected, actual)

    return confusion, unmatched


def main() -> int:
    args = parse_args()
    samples = load_tobii_samples(args.tobii_tsv, args.timestamp_column, args.tobii_label_column)
    movements = load_movements(
        args.movements_csv,
        args.movement_timestamp_column,
        args.movement_type_column,
        args.duration_column,
    )
    confusion, unmatched = evaluate(samples, movements)
    print_results(confusion, unmatched)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
