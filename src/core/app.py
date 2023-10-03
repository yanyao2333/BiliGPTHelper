import asyncio
import os

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from injector import Module, singleton, provider

from src.asr.asr_router import ASRouter
from src.bilibili.bili_credential import BiliCredential
from src.utils.cache import Cache
from src.utils.global_variables_manager import GlobalVariablesManager
from src.utils.logging import LOGGER
from src.utils.models import Config
from src.utils.queue_manager import QueueManager
from src.utils.task_status_record import TaskStatusRecorder

_LOGGER = LOGGER.bind(name="app")


class ConfigError(Exception):
    def __init__(self, message):
        super().__init__(message)


def flatten_dict(d):
    items = {}
    for k, v in d.items():
        k = k.replace("-", "_")
        if isinstance(v, dict):
            items.update(flatten_dict(v))
        else:
            items[k] = v
    return items


class BiliGPT(Module):
    """BiliGPTHelper应用，储存所有的单例对象"""

    @singleton
    @provider
    def provide_config_obj(self) -> Config:
        with open(os.getenv("CONFIG_FILE", "config.yml"), "r", encoding="utf-8") as f:
            config = flatten_dict(yaml.load(f, Loader=yaml.FullLoader))
        try:
            config = Config(**config)
        except Exception as e:
            raise ConfigError(f"配置文件格式错误：{e}")
        return config

    @singleton
    @provider
    def provide_global_variables_manager(
        self, config: Config
    ) -> GlobalVariablesManager:
        _LOGGER.info("正在初始化全局变量管理器")
        return GlobalVariablesManager().set_from_dict(config.model_dump())

    @singleton
    @provider
    def provide_queue_manager(self) -> QueueManager:
        _LOGGER.info("正在初始化队列管理器")
        return QueueManager()

    @singleton
    @provider
    def provide_task_status_recorder(self, config: Config) -> TaskStatusRecorder:
        _LOGGER.info(f"正在初始化任务状态管理器，位置：{config.model_dump()['task_status_records']}")
        return TaskStatusRecorder(config.model_dump()["task_status_records"])

    @singleton
    @provider
    def provide_cache(self, config: Config) -> Cache:
        _LOGGER.info(f"正在初始化缓存，缓存路径为：{config.model_dump()['cache_path']}")
        return Cache(config.model_dump()["cache_path"])

    @singleton
    @provider
    def provide_credential(
        self, config: Config, scheduler: AsyncIOScheduler
    ) -> BiliCredential:
        _LOGGER.info("正在初始化cookie")
        _config = config.model_dump()
        return BiliCredential(
            SESSDATA=_config["SESSDATA"],
            bili_jct=_config["bili_jct"],
            buvid3=_config["buvid3"],
            dedeuserid=_config["dedeuserid"],
            ac_time_value=_config["ac_time_value"],
            sched=scheduler,
        )

    @singleton
    @provider
    def provide_whisper_model(self) -> ASRouter:
        _LOGGER.info("正在初始化ASR路由器")
        if os.getenv("ENABLE_WHISPER", "yes") == "yes":
            return ASRouter().load_from_dir()  # FIXME 现在只有whisper一个asr，所以直接返回
        else:
            _LOGGER.warning("未启用whisper，跳过初始化")
            return None

    @singleton
    @provider
    def provide_scheduler(self) -> AsyncIOScheduler:
        _LOGGER.info("正在初始化定时器")
        return AsyncIOScheduler(timezone="Asia/Shanghai")

    @provider
    def provide_queue(
        self, queue_manager: QueueManager, queue_name: str
    ) -> asyncio.Queue:
        _LOGGER.info(f"正在初始化队列 {queue_name}")
        return queue_manager.get_queue(queue_name)
