from prometheus_client import Counter, Histogram


face_id_jobs_total = Counter(
    "face_id_jobs_total",
    "Face-ID jobs by final status",
    ["status"],
)

face_id_job_duration_seconds = Histogram(
    "face_id_job_duration_seconds",
    "Face-ID job duration in seconds",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 40),
)

face_id_detected_faces_histogram = Histogram(
    "face_id_detected_faces_histogram",
    "Detected faces per image",
    buckets=(0, 1, 2, 3, 4, 5, 8, 12),
)
