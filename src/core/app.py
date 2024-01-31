import asyncio
import os

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from injector import Module, provider, singleton

from src.bilibili.bili_credential import BiliCredential
from src.core.schedulers.asr_scheduler import ASRouter
from src.core.schedulers.llm_scheduler import LLMRouter
from src.models.config import Config
from src.utils.cache import Cache
from src.utils.exceptions import ConfigError
from src.utils.logging import LOGGER
from src.utils.queue_manager import QueueManager
from src.utils.task_status_record import TaskStatusRecorder

_LOGGER = LOGGER.bind(name="app")


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
        with open(os.getenv("CONFIG_FILE", "config.yml"), encoding="utf-8") as f:
            config = yaml.load(f, Loader=yaml.FullLoader)
        try:
            # _LOGGER.debug(config)
            config = Config(**config)
        except Exception as e:
            raise ConfigError(f"配置文件格式错误：{e}") from e
        return config

    @singleton
    @provider
    def provide_queue_manager(self) -> QueueManager:
        _LOGGER.info("正在初始化队列管理器")
        return QueueManager()

    @singleton
    @provider
    def provide_task_status_recorder(self, config: Config) -> TaskStatusRecorder:
        _LOGGER.info(f"正在初始化任务状态管理器，位置：{config.storage_settings.task_status_records}")
        return TaskStatusRecorder(config.storage_settings.task_status_records)

    @singleton
    @provider
    def provide_cache(self, config: Config) -> Cache:
        _LOGGER.info(f"正在初始化缓存，缓存路径为：{config.storage_settings.cache_path}")
        return Cache(config.storage_settings.cache_path)

    @singleton
    @provider
    def provide_credential(self, config: Config, scheduler: AsyncIOScheduler) -> BiliCredential:
        _LOGGER.info("正在初始化cookie")
        return BiliCredential(
            SESSDATA=config.bilibili_cookie.SESSDATA,
            bili_jct=config.bilibili_cookie.bili_jct,
            dedeuserid=config.bilibili_cookie.dedeuserid,
            buvid3=config.bilibili_cookie.buvid3,
            ac_time_value=config.bilibili_cookie.ac_time_value,
            sched=scheduler,
        )

    @singleton
    @provider
    def provide_asr_router(self, config: Config, llm_router: LLMRouter) -> ASRouter:
        _LOGGER.info("正在初始化ASR路由器")
        router = ASRouter(config, llm_router)
        router.load_from_dir()
        return router

    @singleton
    @provider
    def provide_llm_router(self, config: Config) -> LLMRouter:
        _LOGGER.info("正在初始化LLM路由器")
        router = LLMRouter(config)
        router.load_from_dir()
        return router

    @singleton
    @provider
    def provide_scheduler(self) -> AsyncIOScheduler:
        _LOGGER.info("正在初始化定时器")
        return AsyncIOScheduler(timezone="Asia/Shanghai")

    @provider
    def provide_queue(self, queue_manager: QueueManager, queue_name: str) -> asyncio.Queue:
        _LOGGER.info(f"正在初始化队列 {queue_name}")
        return queue_manager.get_queue(queue_name)

    @singleton
    @provider
    def provide_stop_event(self) -> asyncio.Event:
        return asyncio.Event()
