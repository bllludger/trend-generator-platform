from pydantic import BaseModel


class JobOut(BaseModel):
    job_id: str
    user_id: str
    trend_id: str
    status: str
    reserved_tokens: int
    error_code: str | None
