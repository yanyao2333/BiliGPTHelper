import os

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BilibiliCookie(BaseModel):
    # 防呆措施，避免有傻瓜把dedeuserid写成数字
    model_config = ConfigDict(coerce_numbers_to_str=True)  # type: ignore

    SESSDATA: str
    bili_jct: str
    buvid3: str
    dedeuserid: str
    ac_time_value: str

    # noinspection PyMethodParameters
    @field_validator("*", mode="after")
    def check_required_fields(cls, value):
        if value is None or (isinstance(value, (str, list)) and not value):
            raise ValueError(f"配置文件中{cls}字段为空，请检查配置文件")
        return value


class ChainKeywords(BaseModel):
    summarize_keywords: list[str]
    ask_ai_keywords: list[str]

    # noinspection PyMethodParameters
    @field_validator("*", mode="after")
    def check_keywords(cls, value):
        if not value or len(value) == 0:
            raise ValueError(f"配置文件中{cls}字段为空，请检查配置文件")
        return value


class Openai(BaseModel):
    enable: bool = True
    priority: int = 70
    api_key: str
    model: str = "gpt-3.5-turbo-16k"
    api_base: str = Field(default="https://api.openai.com/v1")

    # noinspection PyMethodParameters
    @field_validator("*", mode="after")
    def check_required_fields(cls, value, values):
        if values.data.get("enable") is False:
            return value
        if value is None or (isinstance(value, (str, list)) and not value):
            raise ValueError(f"配置文件中{cls}字段为空，请检查配置文件")
        return value


class AiproxyClaude(BaseModel):
    enable: bool = True
    priority: int = 90
    api_key: str
    model: str = "claude-instant-1"
    api_base: str = Field(default="https://api.aiproxy.io/")

    # noinspection PyMethodParameters
    @field_validator("*", mode="after")
    def check_required_fields(cls, value, values):
        if values.data.get("enable") is False:
            return value
        if value is None or (isinstance(value, (str, list)) and not value):
            raise ValueError(f"配置文件中{cls}字段为空，请检查配置文件")
        return value

    # noinspection PyMethodParameters
    @field_validator("model", mode="after")
    def check_model(cls, value, values):
        models = ["claude-instant-1", "claude-2"]
        if value not in models:
            raise ValueError(f"配置文件中{cls}字段为{value}，请检查配置文件，目前支持的模型有{models}")
        return value


class Spark(BaseModel):
    enable: bool = True
    priority: int = 80
    appid: str
    api_key: str
    api_secret: str
    spark_url: str = Field(default="wss://spark-api.xf-yun.com/v3.5/chat")  # 默认3.5版本
    domain: str = Field(default="generalv3.5")  # 默认3.5

    @field_validator("*", mode="after")
    def check_required_fields(cls, value, values):
        if values.data.get("enable") is False:
            return value
        if value is None or (isinstance(value, (str, list)) and not value):
            raise ValueError(f"配置文件中{cls}字段为空，请检查配置文件")
        return value


class LLMs(BaseModel):
    openai: Openai
    aiproxy_claude: AiproxyClaude
    spark: Spark


class OpenaiWhisper(BaseModel):
    BaseModel.model_config["protected_namespaces"] = ()
    enable: bool = False
    priority: int = 70
    api_key: str
    model: str = "whisper-1"
    api_base: str = Field(default="https://api.openai.com/v1")
    after_process: bool = False

    # noinspection PyMethodParameters
    @field_validator("api_key", mode="after")
    def check_required_fields(cls, value, values):
        if values.data.get("enable") is False:
            return value
        if value is None or (isinstance(value, (str, list)) and not value):
            raise ValueError(f"配置文件中{cls}字段为空，请检查配置文件")
        return value

    # noinspection PyMethodParameters
    @field_validator("model", mode="after")
    def check_model(cls, value, values):
        value = "whisper-1"
        return value


class LocalWhisper(BaseModel):
    BaseModel.model_config["protected_namespaces"] = ()
    enable: bool = False
    priority: int = 60
    model_size: str = "tiny"
    device: str = "cpu"
    model_dir: str = Field(
        default_factory=lambda: os.getenv("DOCKER_WHISPER_MODELS_DIR"),
        validate_default=True,
    )
    after_process: bool = False

    # noinspection PyMethodParameters
    @field_validator(
        "model_size",
        "device",
        "model_dir",
        mode="after",
    )
    def check_whisper_fields(cls, value, values):
        if values.data.get("whisper_enable"):
            if value is None or (isinstance(value, str) and not value):
                raise ValueError(f"配置文件中{cls}字段为空，请检查配置文件")
            if os.getenv("RUNNING_IN_DOCKER") == "yes":
                cls.device = "cpu"
            if os.getenv("ENABLE_WHISPER") == "yes":
                cls.enable = True
            else:
                cls.enable = False
        return value


class ASRs(BaseModel):
    local_whisper: LocalWhisper
    openai_whisper: OpenaiWhisper


class StorageSettings(BaseModel):
    cache_path: str = Field(default_factory=lambda: os.getenv("DOCKER_CACHE_FILE"), validate_default=True)
    temp_dir: str = Field(default_factory=lambda: os.getenv("DOCKER_TEMP_DIR"), validate_default=True)
    task_status_records: str = Field(default_factory=lambda: os.getenv("DOCKER_RECORDS_DIR"), validate_default=True)
    statistics_dir: str = Field(
        default_factory=lambda: os.getenv("DOCKER_STATISTICS_DIR"),
        validate_default=True,
    )
    queue_save_dir: str = Field(default_factory=lambda: os.getenv("DOCKER_QUEUE_DIR"), validate_default=True)
    up_video_cache: str = Field(default_factory=lambda: os.getenv("DOCKER_UP_VIDEO_CACHE"), validate_default=True)
    up_file: str = Field(default_factory=lambda: os.getenv("DOCKER_UP_FILE"), validate_default=True)

    # noinspection PyMethodParameters
    @field_validator("*", mode="after")
    def check_required_fields(cls, value):
        if value is None or (isinstance(value, (str, list)) and not value):
            raise ValueError(f"配置文件中{cls}字段为空，请检查配置文件")
        return value


class BilibiliNickName(BaseModel):
    nickname: str = "BiliBot"

    @field_validator("*", mode="after")
    def check_required_fields(cls, value):
        if value is None or (isinstance(value, (str, list)) and not value):
            raise ValueError(f"配置文件中{cls}字段为空，请检查配置文件")
        return value


class Config(BaseModel):
    """配置文件模型"""

    bilibili_cookie: BilibiliCookie
    bilibili_self: BilibiliNickName
    chain_keywords: ChainKeywords
    LLMs: LLMs
    ASRs: ASRs
    storage_settings: StorageSettings
    debug_mode: bool = True
