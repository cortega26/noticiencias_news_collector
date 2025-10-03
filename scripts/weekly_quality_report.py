"""Generate weekly quality monitoring report in the common output format."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from monitoring import QualityReportGenerator, default_quality_report_generator
from monitoring.io import load_monitoring_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Path to weekly stats JSON file")
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the monitoring payload (JSON)",
    )
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    dataset = load_monitoring_dataset(payload)

    generator: QualityReportGenerator = default_quality_report_generator()
    report = generator.generate(dataset)
    output = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
