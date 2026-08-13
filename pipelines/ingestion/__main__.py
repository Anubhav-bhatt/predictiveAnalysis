"""Scheduler-friendly ingestion CLI (Phase 1C sections 23, 24).

Two commands, both safe to re-run:

``run-daily``
    The full daily cycle: create a run, discover and register files, execute the
    Phase 1A/1B profiling, schema and quality stages, then reconcile every
    business date the arriving telemetry actually touched.

``reconcile``
    Recompute charger-day coverage for a date without ingesting anything. This is
    what turns a MISSING charger-day into LATE/COMPLETE once a late file has been
    registered (section 24), and it is idempotent by construction.

No scheduler is embedded. The commands exit with a meaningful status code so cron,
systemd timers or any orchestrator can drive them; Kafka and Airflow are
explicitly out of scope for this phase.

Exit codes:

    0  completed cleanly
    1  completed with warnings (some files failed or were quarantined)
    2  the run itself failed
    3  invalid invocation
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
from collections.abc import Sequence
from uuid import UUID

from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging, get_logger, log_context
from backend.app.db.session import dispose_engine, session_scope
from backend.app.models.enums import (
    IngestionRunStatus,
    IngestionTrigger,
    UploadBatchStatus,
)
from backend.app.repositories.uploads import UploadRepository
from backend.app.services.coverage_service import ReconciliationSummary
from backend.app.services.factory import (
    build_coverage_service,
    build_filesystem_source,
    build_frame_service,
    build_ingestion_service,
    build_upload_service,
)
from backend.app.services.ingestion_service import RunSummary
from backend.app.services.upload_service import BatchProcessingResult, UploadRejected

logger = get_logger(__name__)

EXIT_OK = 0
EXIT_WARNINGS = 1
EXIT_FAILED = 2
EXIT_USAGE = 3


def _parse_date(raw: str) -> dt.date:
    try:
        return dt.date.fromisoformat(raw)
    except ValueError as exc:  # pragma: no cover - argparse surfaces the message
        raise argparse.ArgumentTypeError(
            f"{raw!r} is not an ISO date (expected YYYY-MM-DD)"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipelines.ingestion",
        description="Daily fleet telemetry ingestion and charger-day reconciliation.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    daily = sub.add_parser(
        "run-daily",
        help="Discover, register, analyse and reconcile a daily fleet collection cycle.",
    )
    daily.add_argument(
        "--date",
        type=_parse_date,
        default=None,
        help=(
            "Business date to reconcile (YYYY-MM-DD). Omit to reconcile whichever "
            "dates the ingested telemetry actually contains."
        ),
    )
    daily.add_argument(
        "--no-reconcile",
        action="store_true",
        help="Ingest only; skip charger-day reconciliation.",
    )

    batch = sub.add_parser(
        "process-uploads",
        help=(
            "Process staged manual-upload batches through the common pipeline "
            "(ingest, coverage, frame reconstruction)."
        ),
    )
    batch.add_argument(
        "--batch",
        dest="batch_id",
        default=None,
        help="A specific upload_batch id. Omit to process every queued batch.",
    )
    batch.add_argument(
        "--no-reconstruct",
        action="store_true",
        help="Skip Phase 1D frame reconstruction (ingest and coverage only).",
    )

    reconcile = sub.add_parser(
        "reconcile",
        help="Recompute charger-day coverage for a date. Idempotent; ingests nothing.",
    )
    reconcile.add_argument("--date", type=_parse_date, required=True)

    return parser


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


async def run_daily(business_date: dt.date | None, *, reconcile: bool = True) -> int:
    """Ingest everything available, then reconcile the dates it touched."""
    settings = get_settings()
    source = build_filesystem_source(settings)

    async with session_scope() as session:
        service = build_ingestion_service(session, settings=settings)
        summary = await service.run(
            source,
            trigger=IngestionTrigger.CLI,
            business_date=business_date,
        )

        ready_ids = [
            outcome.telemetry_file_id
            for outcome in summary.outcomes
            if outcome.telemetry_file_id is not None
        ]

        # Reconcile the dates the telemetry *actually* contains rather than the
        # nominal run date: a cross-midnight file legitimately affects two days
        # (section 8), and the filename is never trusted for this.
        dates: list[dt.date] = []
        if reconcile:
            file_repo_dates = await service.files.dates_touched_by_files(ready_ids)
            dates = list(file_repo_dates)
            if business_date is not None and business_date not in dates:
                dates.append(business_date)

        reconciliations: list[ReconciliationSummary] = []
        if dates:
            coverage = build_coverage_service(session, settings=settings)
            reconciliations = await coverage.reconcile_dates(
                dates, ingestion_run_id=summary.ingestion_run_id
            )

    _print_run_report(summary, reconciliations)
    return _exit_code(summary.status)


async def process_uploads(batch_id: str | None, *, reconstruct: bool = True) -> int:
    """Run staged upload batches through the standard pipeline.

    This is the worker half of manual upload. It deliberately calls the same
    ingestion service the filesystem source uses - manual upload is an acquisition
    path, not a second pipeline.
    """
    settings = get_settings()
    results: list[BatchProcessingResult] = []

    async with session_scope() as session:
        uploads = build_upload_service(session, settings=settings)
        repo = UploadRepository(session)

        if batch_id is not None:
            try:
                targets = [UUID(batch_id)]
            except ValueError:
                print(f"{batch_id!r} is not a valid UUID.", file=sys.stderr)
                return EXIT_USAGE
        else:
            queued = await repo.queued_batches()
            targets = [item.id for item in queued]

        if not targets:
            print("\nNo upload batches are queued for processing.")
            return EXIT_OK

        ingestion = build_ingestion_service(session, settings=settings)
        coverage = build_coverage_service(session, settings=settings)
        frames = build_frame_service(session, settings=settings) if reconstruct else None

        for target in targets:
            try:
                results.append(
                    await uploads.process_batch(
                        target, ingestion=ingestion, coverage=coverage, frames=frames
                    )
                )
            except UploadRejected as exc:
                print(f"\nBatch {target}: {exc}", file=sys.stderr)
                return EXIT_USAGE

    for result in results:
        _print_batch_result(result)

    if any(r.status is UploadBatchStatus.FAILED for r in results):
        return EXIT_FAILED
    if any(r.status is UploadBatchStatus.COMPLETED_WITH_WARNINGS for r in results):
        return EXIT_WARNINGS
    return EXIT_OK


def _print_batch_result(result: BatchProcessingResult) -> None:
    print(
        "\n".join(
            [
                "",
                f"UPLOAD BATCH {result.batch_id}",
                "---------------------------------------------",
                f"Status:                {result.status.value}",
                f"Files registered:      {result.files_registered:>8}",
                f"Files ready:           {result.files_ready:>8}",
                # Without this line a batch of nothing but already-held telemetry
                # printed zeros across the board and looked like it had lost the
                # files, when in fact it had correctly recognised them.
                f"Files already present: {result.files_already_present:>8}",
                f"Files duplicate:       {result.files_duplicate:>8}",
                f"Files failed:          {result.files_failed:>8}",
                f"Files quarantined:     {result.files_quarantined:>8}",
                f"Frames reconstructed:  {result.frames_reconstructed:>8}",
                f"Dates reconciled:      "
                f"{', '.join(d.isoformat() for d in result.dates_reconciled) or '-'}",
            ]
        )
    )


async def reconcile_only(business_date: dt.date) -> int:
    """Recompute one date's charger-day coverage."""
    settings = get_settings()
    async with session_scope() as session:
        coverage = build_coverage_service(session, settings=settings)
        summary = await coverage.reconcile(business_date)
    _print_reconciliation(summary)
    return EXIT_OK


def _exit_code(status: IngestionRunStatus) -> int:
    match status:
        case IngestionRunStatus.COMPLETED:
            return EXIT_OK
        case IngestionRunStatus.COMPLETED_WITH_WARNINGS:
            return EXIT_WARNINGS
        case _:
            return EXIT_FAILED


# ---------------------------------------------------------------------------
# Reporting - stdout is the operator-facing surface; logs go to stderr
# ---------------------------------------------------------------------------


def _print_run_report(
    summary: RunSummary, reconciliations: Sequence[ReconciliationSummary]
) -> None:
    lines = [
        "",
        "DAILY INGESTION RUN",
        "-------------------",
        f"Run id:            {summary.ingestion_run_id}",
        f"Status:            {summary.status.value}",
        f"Files discovered:  {summary.files_discovered}",
        f"Files registered:  {summary.files_registered}",
        f"Files ready:       {summary.files_ready}",
        f"Files skipped:     {summary.files_skipped} (already registered)",
        f"Files partial:     {summary.files_partial}",
        f"Files duplicate:   {summary.files_duplicate}",
        f"Files quarantined: {summary.files_quarantined}",
        f"Files failed:      {summary.files_failed}",
    ]
    if summary.files_failed or summary.files_quarantined:
        lines.append("")
        lines.append("Problem files:")
        for outcome in summary.outcomes:
            if outcome.status.value in {"FAILED", "QUARANTINED"}:
                lines.append(f"  [{outcome.status.value}] {outcome.filename}: {outcome.message}")
    print("\n".join(lines))

    for item in reconciliations:
        _print_reconciliation(item)


def _print_reconciliation(summary: ReconciliationSummary) -> None:
    print(
        "\n".join(
            [
                "",
                f"CHARGER-DAY RECONCILIATION - {summary.business_date.isoformat()}",
                "---------------------------------------------",
                f"Expected chargers:     {summary.expected_charger_count:>8}",
                f"Received chargers:     {summary.received_charger_count:>8}",
                f"Complete:              {summary.complete_count:>8}",
                f"Partial:               {summary.partial_count:>8}",
                f"Severely incomplete:   {summary.severely_incomplete_count:>8}",
                f"Missing:               {summary.missing_charger_count:>8}",
                f"Late:                  {summary.late_charger_count:>8}",
                f"Unexpected:            {summary.unexpected_charger_count:>8}",
                "",
                f"Unique event stamps:   {summary.total_unique_timestamps:>8}",
                f"Raw rows (context):    {summary.total_raw_rows:>8}",
                f"Telemetry gaps:        {summary.gap_count:>8}",
                f"Daily findings:        {summary.daily_finding_count:>8}",
                "",
                f"Fleet coverage:        {summary.fleet_coverage_percentage:>7.2f}%",
                f"Delivery rate:         {summary.delivery_rate:>7.2f}%",
            ]
        )
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _dispatch(args: argparse.Namespace) -> int:
    try:
        if args.command == "run-daily":
            return await run_daily(args.date, reconcile=not args.no_reconcile)
        if args.command == "reconcile":
            return await reconcile_only(args.date)
        if args.command == "process-uploads":
            return await process_uploads(
                args.batch_id, reconstruct=not args.no_reconstruct
            )
    finally:
        await dispose_engine()
    return EXIT_USAGE


def main(argv: Sequence[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_format.value == "json")

    args = build_parser().parse_args(argv)
    with log_context(trigger=IngestionTrigger.CLI.value, command=args.command):
        try:
            return asyncio.run(_dispatch(args))
        except KeyboardInterrupt:  # pragma: no cover - operator interrupt
            logger.warning("ingestion.cli.interrupted")
            return EXIT_FAILED
        except Exception as exc:  # noqa: BLE001 - the CLI boundary reports, never traces
            logger.exception("ingestion.cli.failed", error=str(exc))
            print(f"\nRun failed: {exc}", file=sys.stderr)
            return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
