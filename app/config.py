from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    razorpay_key_id: str
    razorpay_key_secret: str
    razorpay_webhook_secret: str

    database_url: str = "sqlite:///./recoverai.db"

    human_review_timeout_hours: int = 24
    max_recovery_window_days: int = 14
    max_retry_attempts: int = 3
    retry_cooling_off_hours: int = 4

    # Cost per action (business policy - ₹ cost of attempting this action)
    action_cost_retry: float = 5.0
    action_cost_payment_link: float = 15.0
    action_cost_alt_method: float = 10.0

    # Decision thresholds (Section 10)
    score_floor: float = 0.0
    confidence_band_low: float = 0.40
    confidence_band_high: float = 0.60
    human_review_amount_threshold: float = 50000.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()