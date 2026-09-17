"""Frame reconstruction CLI (Phase 1D sections 41, 42).

```bash
python -m pipelines.frame_reconstruction reconstruct <telemetry-file-id>
python -m pipelines.frame_reconstruction reconstruct --filename HYD12_28-07-2026.csv
python -m pipelines.frame_reconstruction reconstruct-day --charger <id> --date 2026-07-27
```

``--charger`` takes the **charger_id as it appears in telemetry**, not the OCPP id
and not a database primary key. ``--ocpp`` is offered separately and resolved
through the registry, because assuming OCPP id equals charger id is exactly the
kind of shortcut that silently reconstructs the wrong charger.

Every number printed is measured. Exit codes match the ingestion CLI's convention:
0 clean, 1 completed with warnings, 2 failed, 3 bad invocation.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging, get_logger
from backend.app.db.session import dispose_engine, session_scope
from backend.app.models.charger import Charger
from backend.app.models.telemetry_file import TelemetryFile
from backend.app.services.factory import build_frame_service
from backend.app.services.frame_service import FrameReconstructionResult

logger = get_logger(__name__)

EXIT_OK = 0
EXIT_WARNINGS = 1
EXIT_FAILED = 2
EXIT_USAGE = 3


def _parse_date(raw: str) -> dt.date:
    try:
        return dt.date.fromisoformat(raw)
    except ValueError as exc:  # pragma: no cover - argparse surfaces this
        raise argparse.ArgumentTypeError(
            f"{raw!r} is not an ISO date (expected YYYY-MM-DD)"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipelines.frame_reconstruction",
        description=(
            "Reconstruct logical source frames from registered telemetry files. "
            "Repeated observations are classified, never deleted."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    one = sub.add_parser("reconstruct", help="Reconstruct a single telemetry file.")
    target = one.add_mutually_exclusive_group(required=True)
    target.add_argument("file_id", nargs="?", help="telemetry_file UUID.")
    target.add_argument("--filename", help="Original filename, when the UUID is not to hand.")

    day = sub.add_parser(
        "reconstruct-day",
        help="Reconstruct every usable file contributing to one charger-day.",
    )
    identity = day.add_mutually_exclusive_group(required=True)
    identity.add_argument(
        "--charger", help="charger_id exactly as it appears inside the telemetry."
    )
    identity.add_argument("--ocpp", help="OCPP id; resolved to a charger_id through the registry.")
    day.add_argument("--date", type=_parse_date, required=True)

    return parser


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


async def reconstruct_one(*, file_id: str | None, filename: str | None) -> int:
    settings = get_settings()
    async with session_scope() as session:
        telemetry_file = await _resolve_file(session, file_id=file_id, filename=filename)
        if telemetry_file is None:
            print("No registered telemetry file matches that identifier.", file=sys.stderr)
            return EXIT_USAGE

        service = build_frame_service(session, settings=settings)
        result = await service.reconstruct_file(telemetry_file)

    _print_file_result(telemetry_file.original_filename, result)
    return EXIT_OK if result.succeeded else EXIT_FAILED


async def reconstruct_day(*, charger: str | None, ocpp: str | None, business_date: dt.date) -> int:
    settings = get_settings()
    async with session_scope() as session:
        charger_id = charger
        if charger_id is None and ocpp is not None:
            resolved = await session.execute(
                sa.select(Charger.charger_id).where(Charger.ocpp_id == ocpp)
            )
            charger_id = resolved.scalars().first()
            if charger_id is None:
                print(f"No registered charger has OCPP id {ocpp!r}.", file=sys.stderr)
                return EXIT_USAGE

        assert charger_id is not None
        service = build_frame_service(session, settings=settings)
        results = await service.reconstruct_charger_day(charger_id, business_date)

    if not results:
        print(f"\nNo usable telemetry files for {charger_id} on {business_date.isoformat()}.")
        return EXIT_OK

    print(f"\nCHARGER-DAY RECONSTRUCTION - {charger_id} {business_date.isoformat()}")
    print("=" * 62)
    for result in results:
        _print_file_result(str(result.telemetry_file_id), result)

    failures = sum(1 for result in results if not result.succeeded)
    if failures == len(results):
        return EXIT_FAILED
    return EXIT_WARNINGS if failures else EXIT_OK


async def _resolve_file(
    session: AsyncSession, *, file_id: str | None, filename: str | None
) -> TelemetryFile | None:
    if file_id:
        try:
            parsed = UUID(file_id)
        except ValueError:
            print(f"{file_id!r} is not a valid UUID.", file=sys.stderr)
            return None
        return await session.get(TelemetryFile, parsed)

    result = await session.execute(
        sa.select(TelemetryFile)
        .where(TelemetryFile.original_filename == filename)
        .order_by(TelemetryFile.received_at.desc())
    )
    return result.scalars().first()


def _print_file_result(label: str, result: FrameReconstructionResult) -> None:
    print(f"\nFILE: {label}")
    print("-" * 62)
    if result.skipped_reason is not None:
        print(f"  skipped: {result.skipped_reason}")
        return
    if result.outcome is None:  # pragma: no cover - guarded above
        print("  no reconstruction outcome")
        return

    print(f"  charger: {result.charger_id or '<unresolved>'}")
    print(f"  topology: {result.outcome.topology.describe()}")
    if result.outcome.topology.note:
        print(f"    note: {result.outcome.topology.note}")
    print()
    print(result.outcome.metrics.render())
    print()
    print(f"  Frames persisted               {result.frames_persisted:>10,}")
    print(f"  Reused from other files        {result.frames_reused_from_other_files:>10,}")
    print(f"  Findings persisted             {result.findings_persisted:>10,}")

    collisions = result.outcome.collision_timestamps
    if collisions:
        shown = ", ".join(stamp.isoformat() for stamp in collisions[:5])
        suffix = " ..." if len(collisions) > 5 else ""
        print(f"  Collision timestamps: {shown}{suffix}")
    if result.outcome.failed_groups:
        print(f"  Failed timestamp groups: {len(result.outcome.failed_groups)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _dispatch(args: argparse.Namespace) -> int:
    try:
        if args.command == "reconstruct":
            return await reconstruct_one(file_id=args.file_id, filename=args.filename)
        if args.command == "reconstruct-day":
            return await reconstruct_day(
                charger=args.charger, ocpp=args.ocpp, business_date=args.date
            )
    finally:
        await dispose_engine()
    return EXIT_USAGE


def main(argv: Sequence[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_format.value == "json")

    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_dispatch(args))
    except KeyboardInterrupt:  # pragma: no cover - operator interrupt
        logger.warning("frames.cli.interrupted")
        return EXIT_FAILED
    except Exception as exc:  # noqa: BLE001 - the CLI boundary reports, never traces
        logger.exception("frames.cli.failed", error=str(exc))
        print(f"\nReconstruction failed: {exc}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
