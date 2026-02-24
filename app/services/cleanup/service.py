from datetime import datetime, timedelta, timezone
from typing import Any
import os

from sqlalchemy.orm import Session

from app.models.job import Job


class CleanupService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def preview_temp_cleanup(self, older_than_hours: int) -> dict[str, Any]:
        """Dry-run: return count of jobs and files that would be cleaned."""
        threshold = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        jobs = (
            self.db.query(Job)
            .filter(Job.updated_at <= threshold, Job.status.in_(["SUCCEEDED", "FAILED"]))
            .all()
        )
        jobs_with_inputs = [j for j in jobs if j.input_local_paths]
        files_count = sum(len(j.input_local_paths) for j in jobs_with_inputs)
        return {
            "jobs_count": len(jobs_with_inputs),
            "files_count": files_count,
            "older_than_hours": older_than_hours,
        }

    def cleanup_temp_files(self, older_than_hours: int) -> dict[str, Any]:
        threshold = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        jobs = (
            self.db.query(Job)
            .filter(Job.updated_at <= threshold, Job.status.in_(["SUCCEEDED", "FAILED"]))
            .all()
        )
        cleaned = 0
        for job in jobs:
            if job.input_local_paths:
                for path in job.input_local_paths:
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                    except OSError:
                        continue
                job.input_local_paths = []
                self.db.add(job)
                cleaned += 1
        self.db.commit()
        return {"cleaned_jobs": cleaned, "older_than_hours": older_than_hours}
