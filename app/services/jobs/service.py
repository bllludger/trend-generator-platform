from sqlalchemy.orm import Session

from app.models.job import Job


class JobService:
    def __init__(self, db: Session):
        self.db = db

    def create_job(
        self,
        user_id: str,
        trend_id: str,
        input_file_ids: list[str],
        input_local_paths: list[str],
        reserved_tokens: int,
        used_free_quota: bool = False,
        used_copy_quota: bool = False,
        job_id: str | None = None,
        custom_prompt: str | None = None,
        image_size: str | None = None,
    ) -> Job:
        job_kwargs: dict = {
            "user_id": user_id,
            "trend_id": trend_id,
            "status": "CREATED",
            "input_file_ids": input_file_ids,
            "input_local_paths": input_local_paths,
            "reserved_tokens": reserved_tokens,
            "used_free_quota": used_free_quota,
            "used_copy_quota": used_copy_quota,
        }
        if job_id is not None:
            job_kwargs["job_id"] = job_id
        if custom_prompt is not None:
            job_kwargs["custom_prompt"] = custom_prompt
        if image_size is not None:
            job_kwargs["image_size"] = image_size
        job = Job(**job_kwargs)
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def set_status(self, job: Job, status: str, error_code: str | None = None) -> Job:
        job.status = status
        job.error_code = error_code
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def set_output(self, job: Job, output_path: str) -> Job:
        job.output_path = output_path
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def set_output_with_paywall(
        self, job: Job, preview_path: str, original_path: str
    ) -> Job:
        """Выставить пути превью и оригинала, is_preview=True (для paywall)."""
        job.output_path = preview_path
        job.output_path_original = original_path
        job.is_preview = True
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def clear_inputs(self, job: Job) -> Job:
        job.input_local_paths = []
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.db.query(Job).filter(Job.job_id == job_id).one_or_none()
