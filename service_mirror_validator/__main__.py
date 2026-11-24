"""Command line entry point: ``python -m service_mirror_validator snapshot.json``.

Runs entirely offline against a JSON snapshot file.
"""

import argparse
import sys

from .io import snapshot_kwargs
from .report import render_report
from .validator import validate_mirror


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate cross-cluster service mirroring from an offline JSON "
            "snapshot (no cluster connection)."
        )
    )
    parser.add_argument(
        "snapshot",
        help="path to a JSON snapshot of source/target cluster state",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    kwargs = snapshot_kwargs(args.snapshot)
    report = validate_mirror(**kwargs)
    print(render_report(report))
    # Exit non-zero whenever any service is not fully reachable or conflicts.
    has_issue = bool(report.global_conflicts) or any(
        item.conflicts
        or item.unreachable_endpoints
        or item.missing_from_target
        or item.stale_target_only
        for item in report.services
    )
    return 1 if has_issue else 0


if __name__ == "__main__":
    sys.exit(main())
