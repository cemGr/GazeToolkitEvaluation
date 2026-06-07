#!/usr/bin/env python3
"""Convert Tobii TSV exports to UXI.GazeToolkit GazeData CSV files.

The generated CSV header matches the flattened field names written by
GazeDataCsvConverter and the nested EyeData/EyeSample/Point converters.
Invalid or incomplete eye samples are emitted as Invalid with NaN values.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

NAN = "NaN"

TIMESTAMP_COLUMNS: Sequence[Tuple[str, str]] = (
    ("Eyetracker timestamp [μs]", "us"),
    ("Eyetracker timestamp [us]", "us"),
    ("Recording timestamp [μs]", "us"),
    ("Recording timestamp [us]", "us"),
    ("Recording timestamp [ms]", "ms"),
)

OUTPUT_HEADER: Sequence[str] = (
    "Timestamp",
    "LeftValidity",
    "LeftGazePoint2DX",
    "LeftGazePoint2DY",
    "LeftGazePoint3DX",
    "LeftGazePoint3DY",
    "LeftGazePoint3DZ",
    "LeftEyePosition3DX",
    "LeftEyePosition3DY",
    "LeftEyePosition3DZ",
    "LeftPupilDiameter",
    "RightValidity",
    "RightGazePoint2DX",
    "RightGazePoint2DY",
    "RightGazePoint3DX",
    "RightGazePoint3DY",
    "RightGazePoint3DZ",
    "RightEyePosition3DX",
    "RightEyePosition3DY",
    "RightEyePosition3DZ",
    "RightPupilDiameter",
)

EYE_FIELD_TEMPLATES = {
    "gaze_px_x": "Gaze point {eye} X [DACS px]",
    "gaze_px_y": "Gaze point {eye} Y [DACS px]",
    "gaze_mm_x": "Gaze point {eye} X [DACS mm]",
    "gaze_mm_y": "Gaze point {eye} Y [DACS mm]",
    "eye_pos_x": "Eye position {eye} X [DACS mm]",
    "eye_pos_y": "Eye position {eye} Y [DACS mm]",
    "eye_pos_z": "Eye position {eye} Z [DACS mm]",
    "pupil": "Pupil diameter {eye} [mm]",
    "validity": "Validity {eye}",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert Tobii TSV files to CSV files consumable as UXI.GazeToolkit "
            "GazeData (--timestamp-format ticks:us)."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        default=[Path("evaluationdata")],
        help="TSV file(s) or directories with *.tsv files (default: evaluationdata).",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for converted CSV files. Defaults to each input file's directory.",
    )
    parser.add_argument(
        "--suffix",
        default=".gazedata.csv",
        help="Output filename suffix replacing .tsv (default: .gazedata.csv).",
    )
    parser.add_argument(
        "--timestamp-column",
        default=None,
        help=(
            "Explicit Tobii timestamp column to use. By default the first available "
            "column is selected in this order: Eyetracker [μs], Recording [μs], Recording [ms]."
        ),
    )
    return parser.parse_args()


def iter_input_files(paths: Iterable[Path]) -> List[Path]:
    files: List[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.glob("*.tsv")))
        else:
            files.append(path)
    return files


def find_timestamp_column(fieldnames: Sequence[str], explicit: Optional[str]) -> Tuple[str, str]:
    if explicit:
        if explicit not in fieldnames:
            raise ValueError(f"Timestamp column not found: {explicit}")
        return explicit, unit_from_column(explicit)

    for column, unit in TIMESTAMP_COLUMNS:
        if column in fieldnames:
            return column, unit

    raise ValueError(
        "No supported timestamp column found. Expected one of: "
        + ", ".join(column for column, _ in TIMESTAMP_COLUMNS)
    )


def unit_from_column(column: str) -> str:
    lower = column.lower()
    if "[ms]" in lower:
        return "ms"
    return "us"


def parse_number(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None

    text = value.strip()
    if not text:
        return None

    # Tobii exports in some locales use decimal commas. Remove spaces used as
    # group separators while keeping decimal points/commas parseable.
    text = text.replace(" ", "").replace("\u00a0", "")
    if "," in text and "." not in text:
        text = text.replace(",", ".")

    try:
        number = float(text)
    except ValueError:
        return None

    if math.isnan(number):
        return None
    return number


def format_number(number: Optional[float]) -> str:
    if number is None:
        return NAN
    return format(number, ".15g")


def timestamp_to_microseconds(row: Mapping[str, str], column: str, unit: str) -> Optional[str]:
    number = parse_number(row.get(column))
    if number is None:
        return None

    if unit == "ms":
        number *= 1000

    if number.is_integer():
        return str(int(number))
    return format_number(number)


def convert_eye(row: Mapping[str, str], eye: str) -> List[str]:
    columns = {key: template.format(eye=eye) for key, template in EYE_FIELD_TEMPLATES.items()}
    validity = (row.get(columns["validity"]) or "").strip().lower()

    values = {
        "gaze_px_x": parse_number(row.get(columns["gaze_px_x"])),
        "gaze_px_y": parse_number(row.get(columns["gaze_px_y"])),
        "gaze_mm_x": parse_number(row.get(columns["gaze_mm_x"])),
        "gaze_mm_y": parse_number(row.get(columns["gaze_mm_y"])),
        "eye_pos_x": parse_number(row.get(columns["eye_pos_x"])),
        "eye_pos_y": parse_number(row.get(columns["eye_pos_y"])),
        "eye_pos_z": parse_number(row.get(columns["eye_pos_z"])),
        "pupil": parse_number(row.get(columns["pupil"])),
    }

    if validity != "valid" or any(value is None for value in values.values()):
        return ["Invalid", NAN, NAN, NAN, NAN, NAN, NAN, NAN, NAN, NAN]

    return [
        "Valid",
        format_number(values["gaze_px_x"]),
        format_number(values["gaze_px_y"]),
        format_number(values["gaze_mm_x"]),
        format_number(values["gaze_mm_y"]),
        "0",
        format_number(values["eye_pos_x"]),
        format_number(values["eye_pos_y"]),
        format_number(values["eye_pos_z"]),
        format_number(values["pupil"]),
    ]


def output_path_for(input_path: Path, output_dir: Optional[Path], suffix: str) -> Path:
    directory = output_dir if output_dir is not None else input_path.parent
    return directory / f"{input_path.stem}{suffix}"


def convert_file(input_path: Path, output_path: Path, explicit_timestamp_column: Optional[str]) -> Tuple[int, int]:
    with input_path.open("r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.DictReader(infile, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError(f"Input file has no header: {input_path}")

        timestamp_column, timestamp_unit = find_timestamp_column(reader.fieldnames, explicit_timestamp_column)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        written = 0
        skipped = 0
        with output_path.open("w", encoding="utf-8", newline="") as outfile:
            writer = csv.writer(outfile)
            writer.writerow(OUTPUT_HEADER)

            for row in reader:
                timestamp = timestamp_to_microseconds(row, timestamp_column, timestamp_unit)
                if timestamp is None:
                    skipped += 1
                    continue

                writer.writerow([timestamp, *convert_eye(row, "left"), *convert_eye(row, "right")])
                written += 1

    return written, skipped


def main() -> int:
    args = parse_args()
    input_files = iter_input_files(args.inputs)
    if not input_files:
        raise SystemExit("No TSV input files found.")

    for input_file in input_files:
        output_file = output_path_for(input_file, args.output_dir, args.suffix)
        written, skipped = convert_file(input_file, output_file, args.timestamp_column)
        print(f"{input_file} -> {output_file} ({written} rows written, {skipped} skipped)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
