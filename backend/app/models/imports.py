import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Identity, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ImportBatchMode(str, enum.Enum):
    create_plan = "create_plan"
    append_to_plan = "append_to_plan"
    replace_draft_from_same_source = "replace_draft_from_same_source"


class ImportBatchStatus(str, enum.Enum):
    parsed = "parsed"
    failed = "failed"
    applied = "applied"
    cancelled = "cancelled"


class ImportFile(Base):
    __tablename__ = "import_files"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_extension: Mapped[str] = mapped_column(String(20), nullable=False)
    detected_format: Mapped[str] = mapped_column(String(50), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("import_files.id"), nullable=False)
    production_plan_id: Mapped[int] = mapped_column(ForeignKey("production_plans.id"), nullable=False)
    mode: Mapped[ImportBatchMode] = mapped_column(Enum(ImportBatchMode, name="import_batch_mode"), nullable=False)
    status: Mapped[ImportBatchStatus] = mapped_column(
        Enum(ImportBatchStatus, name="import_batch_status"),
        nullable=False,
        server_default=text("'parsed'"),
        default=ImportBatchStatus.parsed,
    )
    source_system: Mapped[str] = mapped_column(String(100), nullable=False, server_default=text("'excel'"), default="excel")
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    header_row_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_rows: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parsed_rows: Mapped[int] = mapped_column(BigInteger, nullable=False)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
