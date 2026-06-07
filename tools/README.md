# Tobii TSV conversion and filter evaluation

## Does the conversion make sense?

Yes, for running the GazeToolkit I-VT pipeline on Tobii exports, with one important assumption:
Tobii's 2D gaze point in DACS pixels is written to `GazePoint2D`, while Tobii's DACS millimetre
coordinates are written to `GazePoint3D` and used together with `EyePosition3D` for visual-angle
velocity calculation.

The converter writes:

- `Timestamp` from `Eyetracker timestamp [μs]` when available, otherwise `Recording timestamp [μs]`
  or `Recording timestamp [ms]`. Millisecond timestamps are converted to microseconds, so use
  `--timestamp-format ticks:us` with the GazeToolkit tools.
- `LeftValidity`/`RightValidity` from Tobii validity fields.
- `GazePoint2D` from `Gaze point <eye> X/Y [DACS px]`.
- `GazePoint3D` from `Gaze point <eye> X/Y [DACS mm]` with `Z = 0`, because the gaze point lies on
  the display plane in DACS coordinates.
- `EyePosition3D` from `Eye position <eye> X/Y/Z [DACS mm]`.
- `PupilDiameter` from `Pupil diameter <eye> [mm]`.

Rows with missing timestamps are skipped. If an eye is not `Valid`, or any required value for that eye
is empty/unparseable, that eye is emitted as `Invalid` with `NaN` values, as required by the README input
structure.

This conversion is not expected to reproduce Tobii's fixation output bit-for-bit. Differences can come from
Tobii's proprietary preprocessing, slightly different timestamps/frequency, interpolation/noise settings, and
whether Tobii or GazeToolkit classifies edge samples at movement boundaries.

## Convert the evaluation data

```bash
python3 tools/convert_tobii_tsv_to_gazedata_csv.py evaluationdata -o /tmp/gazedata-converted
```

The output CSV files can be consumed by the filters as `GazeData` CSV with microsecond ticks:

```bash
i-vt.exe /tmp/gazedata-converted/IVT-Interpolation75ms-Eyeboth-NoNoise-VelocityWindow20-VelocityTreshold30.gazedata.csv \
  --format CSV \
  --timestamp-format ticks:us \
  --frequency 120 \
  --fillin --fillin-max-gap 75 \
  --select Average \
  --window-side 20 \
  --threshold 30 \
  --output-format CSV \
  --output /tmp/gazedata-converted/toolkit-movements.csv
```

Use the settings from the Tobii export name/metadata as closely as possible. For example, the supplied
`IVT-Interpolation75ms-Eyeboth-NoNoise-VelocityWindow20-VelocityTreshold30.tsv` corresponds to fill-in up
to 75 ms, both-eye average selection, no denoising, a 20 ms velocity-window side, and a 30 deg/s threshold.
The sample files are approximately 120 Hz, so `--frequency 120` is the appropriate starting point.

## Evaluate against Tobii's movement labels

After running `i-vt.exe`, compare GazeToolkit movement intervals with Tobii's sample-level
`Eye movement type` labels:

```bash
python3 tools/evaluate_eye_movements_against_tobii.py \
  evaluationdata/IVT-Interpolation75ms-Eyeboth-NoNoise-VelocityWindow20-VelocityTreshold30.tsv \
  /tmp/gazedata-converted/toolkit-movements.csv
```

The evaluator matches each Tobii sample timestamp to the GazeToolkit `EyeMovement` interval containing that
timestamp and reports overall matched-sample accuracy, fixation precision/recall/F1, unmatched samples, and a
confusion matrix for `Fixation`, `Saccade`, and `Unknown`.

For a fair interpretation, inspect boundary mismatches separately: a one-sample shift around fixation/saccade
edges can reduce sample-level accuracy even when detected fixation intervals are practically equivalent.
