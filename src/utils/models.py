from pydantic import BaseModel, Field, field_validator


class Config(BaseModel):
    """配置文件模型"""

    # bilibili cookie
    SESSDATA: str
    bili_jct: str
    buvid3: str
    dedeuserid: str
    ac_time_value: str
    # keywords
    summarize_keywords: list[str]
    evaluate_keywords: list[str]

    # openai
    api_key: str
    model: str = "gpt-3.5-turbo"
    api_base: str = "https://api.openai.com/v1"

    # whisper
    whisper_enable: bool = False
    whisper_model_size: str = "tiny"
    whisper_device: str = "cpu"
    whisper_model_dir: str = Field(
        default_factory=lambda: os.getenv("WHISPER_MODELS_DIR", "/data/whisper-models")
    )
    whisper_after_process: bool = False

    # other
    cache_path: str = Field(
        default_factory=lambda: os.getenv("CACHE_FILE", "/data/cache.json")
    )
    temp_dir: str = Field(default_factory=lambda: os.getenv("TEMP_DIR", "/data/temp"))
    task_status_records: str = Field(default="/data/records.json")
    statistics_dir: str = Field(default="/data/statistics")

    @field_validator(
        "SESSDATA",
        "bili_jct",
        "buvid3",
        "dedeuserid",
        "ac_time_value",
        "cache_path",
        "api_key",
        "model",
        "summarize_keywords",
        "evaluate_keywords",
        "temp_dir",
        "task_status_records",
        mode="after",
    )
    def check_required_fields(cls, value):
        if value is None or (isinstance(value, (str, list)) and not value):
            raise ValueError(f"配置文件中{cls}字段为空，请检查配置文件")
        return value

    @field_validator("summarize_keywords", mode="after")
    def check_summarize_keywords(cls, value):
        if not value or len(value) == 0:
            raise ValueError("配置文件中summarize_keywords字段为空，请检查配置文件")
        return value

    @field_validator(
        "whisper_model_size",
        "whisper_device",
        "whisper_model_dir",
        mode="after",
    )
    def check_whisper_fields(cls, value, values):
        if values.data.get("whisper_enable"):
            if value is None or (isinstance(value, str) and not value):
                raise ValueError(f"配置文件中{cls}字段为空，请检查配置文件")
            if os.getenv("RUNNING_IN_DOCKER") == "yes":
                cls.whisper_device = "cpu"
        return value