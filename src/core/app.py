import asyncio
import os
import shutil

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from injector import Module, provider, singleton

from src.bilibili.bili_credential import BiliCredential
from src.core.routers.asr_router import ASRouter
from src.core.routers.chain_router import ChainRouter
from src.core.routers.llm_router import LLMRouter
from src.models.config import Config
from src.utils.cache import Cache
from src.utils.exceptions import ConfigError
from src.utils.logging import LOGGER
from src.utils.queue_manager import QueueManager
from src.utils.task_status_record import TaskStatusRecorder

_LOGGER = LOGGER.bind(name="app")


class BiliGPT(Module):
    """BiliGPTHelper应用，储存所有的单例对象"""

    @singleton
    @provider
    def provide_config_obj(self) -> Config:
        with open(os.getenv("DOCKER_CONFIG_FILE", "config.yml"), encoding="utf-8") as f:
            config = yaml.load(f, Loader=yaml.FullLoader)
        try:
            # _LOGGER.debug(config)
            config = Config.model_validate(config)
        except Exception as e:
            # shutil.copy(
            #     os.getenv("DOCKER_CONFIG_FILE", "config.yml"), os.getenv("DOCKER_CONFIG_FILE", "config.yml") + ".bak"
            # )
            if os.getenv("RUNNING_IN_DOCKER") == "yes":
                shutil.copy(
                    "./config/docker_config.yml",
                    os.getenv("DOCKER_CONFIG_FILE", "config_template.yml"),
                )
            else:
                shutil.copy(
                    "./config/example_config.yml",
                    os.getenv("DOCKER_CONFIG_FILE", "config_template.yml"),
                )
            # {
            #     field_name: (field.field_info.default if not field.required else "")
            #     for field_name, field in Config.model_fields.items()
            # }
            # yaml.dump(Config().model_dump(mode="python"))
            _LOGGER.error(
                "配置文件格式错误 可能是因为项目更新、配置文件添加了新字段，请自行检查配置文件格式并更新配置文件 已复制最新配置文件模板到 config_template.yml 下面将打印详细错误日志"
            )
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
    def provide_credential(
        self, config: Config, scheduler: AsyncIOScheduler
    ) -> BiliCredential:
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
    def provide_chain_router(
        self, config: Config, queue_manager: QueueManager
    ) -> ChainRouter:
        _LOGGER.info("正在初始化Chain路由器")
        router = ChainRouter(config, queue_manager)
        return router

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

    @singleton
    @provider
    def provide_stop_event(self) -> asyncio.Event:
        return asyncio.Event()

    # @singleton
    # @provider
    # def provide_chains(
    #     self,
    #     queue_manager: QueueManager,
    #     config: Config,
    #     credential: BiliCredential,
    #     cache: Cache,
    #     asr_router: ASRouter,
    #     task_status_recorder: TaskStatusRecorder,
    #     stop_event: asyncio.Event,
    #     llm_router: LLMRouter
    # ) -> dict[str, BaseChain]:
    #     """
    #     如果增加了处理链，要在这里导入
    #     :return:
    #     """
    #     _LOGGER.info("开始加载摘要处理链")
    #     _summarize_chain = Summarize(queue_manager=queue_manager, config=config, credential=credential, cache=cache, asr_router=asr_router, task_status_recorder=task_status_recorder, stop_event=stop_event, llm_router=llm_router)
    #     return {str(_summarize_chain): _summarize_chain}
