import asyncio
import os
import signal
from enum import Enum

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.bilibili.bili_comment import BiliComment
from src.bilibili.bili_credential import BiliCredential
from src.bilibili.bili_session import BiliSession
from src.bilibili.listen import Listen
from src.chain.summarize import SummarizeChain
from src.utils.cache import Cache
from src.utils.global_variables_manager import GlobalVariablesManager
from src.utils.logging import LOGGER
from src.utils.queue_manager import QueueManager
from src.utils.task_status_record import TaskStatusRecorder
from src.utils.types import TaskProcessEvent


class ConfigError(Exception):
    def __init__(self, message):
        super().__init__(message)


class Status(Enum):
    """状态枚举"""

    RUNNING = "running"
    STOPPED = "stopped"


def flatten_dict(d):
    items = {}
    for k, v in d.items():
        if isinstance(v, dict):
            items.update(flatten_dict(v))
        else:
            items[k] = v
    return items


def config_reader():
    with open(os.getenv('CONFIG_FILE', 'config.yml'), "r", encoding="utf-8") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    return flatten_dict(config)


def check_config(config: dict):
    key_list = ["SESSDATA", "bili_jct", "buvid3", "dedeuserid", "ac_time_value", "cache-path", "api-key", "model",
                "summarize-keywords", "evaluate-keywords", "temp-dir", "task-status-records"]
    for key in key_list:
        if key not in config:
            raise ConfigError(f"配置文件中缺少{key}字段，请检查配置文件")
        if not config[key]:
            raise ConfigError(f"配置文件中{key}字段为空，请检查配置文件")
    if config["whisper-enable"]:
        if not config.get("whisper-model-size", None):
            raise ConfigError("配置文件中whisper-model-size字段为空，请检查配置文件")
        if not config.get("whisper-device", None):
            raise ConfigError("配置文件中whisper-device字段为空，请检查配置文件")
        if not config.get("whisper-model-dir", None):
            raise ConfigError("配置文件中whisper-model-dir字段为空，请检查配置文件")
    if len(config["summarize-keywords"]) == 0:
        raise ConfigError("配置文件中summarize-keywords字段为空，请检查配置文件")


def docker_prepare(config):
    if config["whisper-enable"]:
        config["whisper-device"] = "cpu"
    config["cache-path"] = os.getenv('CACHE_FILE', '/data/cache.json')
    config["temp-dir"] = os.getenv('TEMP_DIR', '/data/temp')
    config["whisper-model-dir"] = os.getenv('WHISPER_MODELS_DIR', '/data/whisper-models')



async def start_pipeline():
    _LOGGER.info("正在启动BiliGPTHelper")
    if os.getenv('RUNNING_IN_DOCKER') == "yes":
        if not os.listdir("/data"):
            os.system("cp -r /clone-data/* /data")


    # 初始化全局变量管理器
    _LOGGER.info("正在初始化全局变量管理器")
    value_manager = GlobalVariablesManager()

    # 读取配置文件
    _LOGGER.info("正在读取配置文件")
    config = config_reader()
    _LOGGER.info(f"读取配置文件成功，配置项：{config}")

    # docker环境准备
    if os.getenv('RUNNING_IN_DOCKER') == "yes":
        _LOGGER.info("正在准备docker环境")
        docker_prepare(config)
        _LOGGER.info("docker环境准备完成")

    # 检查配置文件
    _LOGGER.info("正在检查配置文件")
    check_config(config)
    _LOGGER.info("检查配置文件成功")

    # 设置全局变量
    _LOGGER.info("正在设置全局变量")
    value_manager.set_from_dict(config)

    # 初始化队列管理器
    _LOGGER.info("正在初始化队列管理器")
    queue_manager = QueueManager()

    # 初始化任务状态管理器
    _LOGGER.info(f"正在初始化任务状态管理器，位置：{config['task-status-records']}")
    task_status_recorder = TaskStatusRecorder(config["task-status-records"])

    # 初始化缓存
    _LOGGER.info(f"正在初始化缓存，缓存路径为：{config['cache-path']}")
    cache = Cache(config["cache-path"])

    # 初始化定时器
    _LOGGER.info("正在初始化定时器")
    sched = AsyncIOScheduler(timezone="Asia/Shanghai")

    # 初始化cookie
    _LOGGER.info("正在初始化cookie")
    credential = BiliCredential(
        SESSDATA=config["SESSDATA"],
        bili_jct=config["bili_jct"],
        buvid3=config["buvid3"],
        dedeuserid=config["dedeuserid"],
        ac_time_value=config["ac_time_value"],
        sched=sched,
    )

    # 初始化at侦听器
    _LOGGER.info("正在初始化at侦听器")
    listen = Listen(credential, queue_manager, value_manager, sched=sched)

    # 预加载whisper模型
    _LOGGER.info("正在预加载whisper模型")
    if config["whisper-enable"]:
        from src.asr.local_whisper import Whisper
        whisper_obj = Whisper()
        whisper_model_obj = whisper_obj.load_model(
            config["whisper-model-size"],
            config["whisper-device"],
            config["whisper-model-dir"],
        )
    else:
        _LOGGER.info("whisper未启用")
        whisper_model_obj = None
        whisper_obj = None

    # 初始化摘要处理链
    _LOGGER.info("正在初始化摘要处理链")
    summarize_chain = SummarizeChain(queue_manager, value_manager, credential, cache, whisper_model_obj, whisper_obj,
                                     task_status_recorder)

    # 启动侦听器
    _LOGGER.info("正在启动at侦听器")
    listen.start_listening()
    _LOGGER.info("启动私信侦听器")
    await listen.listen_private()
    # 启动cookie过期检查和刷新
    _LOGGER.info("正在启动cookie过期检查和刷新")
    credential.start_check()

    # 启动定时任务调度器
    _LOGGER.info("正在启动定时任务调度器")
    sched.start()

    # 启动摘要处理链
    _LOGGER.info("正在启动摘要处理链")
    summarize_task = asyncio.create_task(summarize_chain.start_chain())

    # 启动评论
    _LOGGER.info("正在启动评论处理链")
    comment = BiliComment(queue_manager.get_queue("reply"), credential)
    comment_task = asyncio.create_task(comment.start_comment())

    # 启动私信
    _LOGGER.info("正在启动私信处理链")
    private = BiliSession(credential, queue_manager.get_queue("private"))
    private_task = asyncio.create_task(private.start_private_reply())

    # await asyncio.gather(summarize_task, comment_task)
    _LOGGER.info("摘要处理链、评论处理链、私信处理链启动完成")

    # _LOGGER.info("正在启动摘要处理链和评论处理链")
    # await summarize_chain.start_chain()
    # _LOGGER.info("摘要处理链启动完成")
    # await BiliComment(queue_manager.get_queue("reply"), credential).start_comment()
    # _LOGGER.info("评论处理链启动完成")

    _LOGGER.info("🎉启动完成 enjoy it")

    while True:
        if flag == Status.STOPPED:
            _LOGGER.info("正在关闭BiliGPTHelper，记得下次再来玩喵！")
            _LOGGER.info("正在关闭定时任务调度器")
            for job in sched.get_jobs():
                sched.remove_job(job.id)
            sched.shutdown()
            task_status_recorder.save_queue(queue_manager.get_queue("summarize"), event=TaskProcessEvent.SUMMARIZE)
            _LOGGER.info("正在关闭所有的处理链")
            summarize_task.cancel()
            comment_task.cancel()
            private_task.cancel()
            _LOGGER.info("正在保存队列")
            _LOGGER.info("再见了喵！")
            break
        await asyncio.sleep(1)


if __name__ == "__main__":
    flag = Status.RUNNING
    _LOGGER = LOGGER.bind(name="main")


    def stop_handler(sig, frame):
        global flag
        flag = Status.STOPPED


    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    asyncio.run(start_pipeline())
