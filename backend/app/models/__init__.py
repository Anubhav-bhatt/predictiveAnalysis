"""SQLAlchemy models.

Importing this package registers every table on ``Base.metadata``, which is what
Alembic autogenerate and the test-suite's ``create_all`` both rely on.
"""

from __future__ import annotations

from backend.app.db.base import Base
from backend.app.models.charger import Charger
from backend.app.models.charger_day_coverage import ChargerDayCoverage
from backend.app.models.data_quality_issue import DataQualityIssue
from backend.app.models.field_definition import (
    FieldAllowedValue,
    FieldDefinition,
    FieldPredictionDomain,
    FieldSentinelValue,
)
from backend.app.models.field_profile import FieldProfile
from backend.app.models.ingestion_run import IngestionRun
from backend.app.models.schema_version import SchemaVersion
from backend.app.models.telemetry_file import (
    IdentifierType,
    TelemetryFile,
    TelemetryFileIdentifier,
)
from backend.app.models.telemetry_file_day import TelemetryFileDay
from backend.app.models.telemetry_frame import (
    TelemetryFrameRow,
    TelemetryFrameSource,
    TelemetrySourceFrame,
)
from backend.app.models.telemetry_gap import TelemetryGap
from backend.app.models.upload_batch import UploadBatch, UploadBatchFile

__all__ = [
    "Base",
    "Charger",
    "ChargerDayCoverage",
    "DataQualityIssue",
    "FieldAllowedValue",
    "FieldDefinition",
    "FieldPredictionDomain",
    "FieldProfile",
    "FieldSentinelValue",
    "IdentifierType",
    "IngestionRun",
    "SchemaVersion",
    "TelemetryFile",
    "TelemetryFileDay",
    "TelemetryFileIdentifier",
    "TelemetryFrameRow",
    "TelemetryFrameSource",
    "TelemetryGap",
    "TelemetrySourceFrame",
    "UploadBatch",
    "UploadBatchFile",
]
