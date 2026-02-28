import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class JobType(str, enum.Enum):
    gmail_sync = "gmail_sync"
    process_receipt = "process_receipt"
    reprocess_receipt = "reprocess_receipt"


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    job_type: Mapped[JobType] = mapped_column(String(50))
    status: Mapped[JobStatus] = mapped_column(String(20), default=JobStatus.pending)
    task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime] = mapped_column(default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
