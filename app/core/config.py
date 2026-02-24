"""
Application configuration.
All settings are loaded from environment variables.
Use env.example as a reference for required variables.
"""
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    IMPORTANT: Credentials have no defaults - they MUST be set in .env file.
    """
    
    # ===========================================
    # APPLICATION
    # ===========================================
    app_env: str = "local"
    # CORS: через запятую (например http://localhost:3000,http://admin-ui:80). Пусто = дефолтный список в коде.
    cors_origins: str = ""
    # Trusted proxy IPs (comma-separated). Used for X-Forwarded-For in production.
    trusted_proxy_ips: str = ""
    
    # ===========================================
    # DATABASE (PostgreSQL)
    # ===========================================
    database_url: str  # Required, no default
    
    # Docker-compose variables (not used by app directly)
    postgres_db: str | None = None
    postgres_user: str | None = None
    postgres_password: str | None = None
    
    # ===========================================
    # REDIS & CELERY
    # ===========================================
    redis_url: str  # Required, no default
    celery_broker_url: str  # Required, no default
    celery_result_backend: str  # Required, no default
    
    # ===========================================
    # TELEGRAM BOT
    # ===========================================
    telegram_bot_token: str  # Required, no default
    # Username бота без @ (для deep link «Попробовать этот тренд»). Пример: NanoBananaBot
    telegram_bot_username: str = ""
    # Ссылка на канал с идеями (кнопка «Подписаться» после генерации/ошибки). Пример: https://t.me/nanobanan_channel
    telegram_channel_url: str = ""
    # Обязательная подписка для новых пользователей: @username канала (без @). Пример: nanobanana_al. Пусто = не требовать.
    subscription_channel_username: str = ""
    
    # ===========================================
    # IMAGE GENERATION - PROVIDER SELECTION
    # ===========================================
    image_provider: str = "openai"  # openai, huggingface, replicate, google_vertex, gemini
    
    # ===========================================
    # OPENAI API (Provider: openai)
    # ===========================================
    openai_api_key: str  # Required, no default
    openai_image_model: str = "dall-e-2"  # dall-e-2, dall-e-3
    # Модель для анализа референса ("Сделать такую же"): должна точно считать и описывать акторов (людей/животных) 1:1. Рекомендуется gpt-4o.
    openai_vision_model: str = "gpt-4o"
    openai_rate_limit_qps: int = 2
    openai_request_timeout: float = 120.0
    
    # ===========================================
    # HUGGING FACE API (Provider: huggingface)
    # ===========================================
    huggingface_api_key: str = ""  # Optional
    huggingface_api_url: str = "https://api-inference.huggingface.co"
    huggingface_image_model: str = "black-forest-labs/FLUX.1-schnell"  # FLUX, Stable Diffusion
    huggingface_timeout: float = 120.0
    
    # ===========================================
    # REPLICATE API (Provider: replicate)
    # ===========================================
    replicate_api_token: str = ""  # Optional
    replicate_api_url: str = "https://api.replicate.com/v1"
    replicate_image_model: str = "black-forest-labs/flux-schnell"
    replicate_timeout: float = 120.0
    replicate_poll_interval: float = 2.0
    
    # ===========================================
    # GOOGLE VERTEX AI (Provider: google_vertex)
    # ===========================================
    google_vertex_project_id: str = ""  # Optional
    google_vertex_location: str = "us-central1"
    google_vertex_access_token: str = ""  # OAuth2 token
    google_vertex_image_model: str = "imagen-3.0-fast-generate-001"
    google_vertex_timeout: float = 120.0
    
    # ===========================================
    # GOOGLE GEMINI NANO BANANA (Provider: gemini)
    # ===========================================
    gemini_api_key: str = ""  # Optional - Get from https://aistudio.google.com/apikey
    gemini_project_id: str = ""  # Optional
    gemini_location: str = "us-central1"
    gemini_api_endpoint: str = "https://generativelanguage.googleapis.com"
    gemini_image_model: str = "gemini-2.5-flash-image"  # or gemini-3-pro-image-preview
    gemini_timeout: float = 180.0  # генерация + загрузка тела ответа (изображение)
    # SafetySettings для generateContent (JSON-массив или пусто). Управляется только через конфиг/админку.
    gemini_safety_settings: str = ""

    # ===========================================
    # IMAGE GENERATION - COMMON SETTINGS
    # ===========================================
    # Runner retry budget (plan §3.3): max attempts total, backoff seconds, respect Retry-After on 429
    image_generation_retry_max_attempts: int = 2
    image_generation_retry_backoff_seconds: float = 2.0
    image_generation_retry_respect_retry_after: bool = True
    # При False референс стиля тренда не отправляется в API (только фото пользователя + текст сцены). Снижает IMAGE_SAFETY и путаницу с лицом.
    send_style_reference_to_api: bool = True
    image_size: str = "1024x1024"
    image_format: str = "png"
    generation_cost_tokens: int = 1
    max_file_size_mb: int = 10
    allowed_image_extensions: str = ".jpg,.jpeg,.png,.webp"
    
    # ===========================================
    # MONETIZATION (Telegram Stars)
    # ===========================================
    watermark_text: str = "NanoBanan Preview"
    unlock_cost_stars: int = 2  # стоимость разблокировки одного фото (Stars) — дешевле пакета, чтобы был смысл
    unlock_cost_tokens: int = 1  # стоимость разблокировки одного фото в токенах (кнопка «За N токен»)
    # Курс 1 Star → рубли (для отображения в скобках). Пример: 1.3 при ~100 ₽/$
    star_to_rub: float = 1.3
    
    # ===========================================
    # REFERRAL PROGRAM
    # ===========================================
    referral_min_pack_stars: int = 249
    referral_hold_hours: int = 24
    referral_attribution_window_days: int = 7
    referral_daily_limit: int = 2
    referral_monthly_limit: int = 10
    referral_bonus_ladder: str = '{"249": 2, "499": 4, "999": 8}'

    # ===========================================
    # BANK TRANSFER (альтернативная оплата переводом на карту)
    # ===========================================
    # Номер карты Озон Банка для приёма оплаты переводом. Если пусто — способ отключён.
    bank_transfer_card: str = ""
    # Комментарий к переводу (опционально, отображается пользователю)
    bank_transfer_comment: str = ""
    
    # ===========================================
    # STORAGE
    # ===========================================
    storage_base_path: str = "/data/generated_images"
    prompts_base_path: str = "prompts"
    # Директория для примеров и референсов трендов (относительно рабочей директории или абсолютный путь)
    trend_examples_dir: str = "data/trend_examples"
    
    # ===========================================
    # WORKERS & PERFORMANCE
    # ===========================================
    uvicorn_workers: int = 2
    max_worker_concurrency: int = 2
    celery_task_retry_delay: int = 5
    celery_task_max_retries: int = 3
    
    # ===========================================
    # ADMIN API
    # ===========================================
    admin_api_key: str | None = None  # Optional, but recommended
    
    # ===========================================
    # ADMIN UI (REQUIRED - CHANGE DEFAULTS!)
    # ===========================================
    admin_ui_username: str  # Required, no default
    admin_ui_password: str  # Required, no default  
    admin_ui_password_hash: str | None = None  # Optional, more secure than plain password
    admin_ui_password_hash_bcrypt: str | None = None  # Optional, for JWT admin panel
    admin_ui_password_hash_sha256: str | None = None  # Optional, for legacy Jinja admin UI
    admin_ui_session_secret: str  # Required, no default
    admin_ui_session_ttl: int = 3600  # 1 hour
    admin_ui_cookie_secure: bool = False  # Set True in production (HTTPS)
    admin_ui_cookie_samesite: str = "strict"
    admin_ui_api_base: str = "http://localhost:8000"
    
    # JWT for new admin panel
    jwt_secret_key: str | None = None

    # Login rate limit (brute-force protection)
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 900  # 15 min
    
    # ===========================================
    # INTERNAL SERVICES
    # ===========================================
    cleanup_api_base: str = "http://cleanup:8001"
    cleanup_temp_ttl_hours: int = 24
    http_client_timeout: float = 10.0
    http_client_timeout_long: float = 30.0
    
    # ===========================================
    # CIRCUIT BREAKER
    # ===========================================
    cb_failure_threshold: int = 5
    cb_open_seconds: int = 30
    
    # ===========================================
    # LOGGING
    # ===========================================
    request_id_header: str = "X-Request-Id"
    log_file: str | None = None
    log_max_bytes: int = 10_000_000
    log_backup_count: int = 5
    
    # ===========================================
    # STATE MANAGEMENT
    # ===========================================
    user_state_ttl: int = 3600  # 1 hour
    idempotency_ttl: int = 300  # 5 minutes
    
    @field_validator("allowed_image_extensions")
    @classmethod
    def parse_extensions(cls, v: str) -> str:
        """Validate extensions format."""
        # Store as comma-separated string, parse when needed
        return v.lower().strip()
    
    @property
    def allowed_extensions_set(self) -> set[str]:
        """Get allowed extensions as a set."""
        return {ext.strip() for ext in self.allowed_image_extensions.split(",") if ext.strip()}

    @property
    def trusted_proxy_ips_set(self) -> set[str]:
        """Get trusted proxy IPs as a set."""
        return {ip.strip() for ip in self.trusted_proxy_ips.split(",") if ip.strip()}
    
    @field_validator("admin_ui_session_secret")
    @classmethod
    def validate_session_secret(cls, v: str) -> str:
        """Ensure session secret is reasonably secure."""
        if len(v) < 16:
            raise ValueError("admin_ui_session_secret must be at least 16 characters")
        if v in ("changeme", "secret", "password", "admin"):
            raise ValueError("admin_ui_session_secret is too weak, please change it")
        return v
    
    @field_validator("admin_ui_password")
    @classmethod
    def validate_admin_password(cls, v: str) -> str:
        """Warn if password is weak."""
        if v in ("admin", "password", "123456", "changeme"):
            raise ValueError("admin_ui_password is too weak, please change it")
        return v

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Игнорировать неизвестные поля из .env


settings = Settings()
