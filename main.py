import asyncio

import yaml

from src.asr.local_whisper import Whisper
from src.bilibili.bili_comment import BiliComment
from src.bilibili.bili_credential import BiliCredential
from src.bilibili.bili_session import BiliSession
from src.bilibili.listen import Listen
from src.chain.summarize import SummarizeChain
from src.utils.cache import Cache
from src.utils.global_variables_manager import GlobalVariablesManager
from src.utils.logging import LOGGER
from src.utils.queue_manager import QueueManager


def flatten_dict(d):
    items = {}
    for k, v in d.items():
        if isinstance(v, dict):
            items.update(flatten_dict(v))
        else:
            items[k] = v
    return items


def config_reader():
    """读取配置文件，现在只是个示例"""
    with open("config.yml", "r", encoding="utf-8") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    return flatten_dict(config)


async def start_pipeline():
    # 初始化全局变量管理器
    _LOGGER.info("正在初始化全局变量管理器")
    value_manager = GlobalVariablesManager()

    # 读取配置文件
    _LOGGER.info("正在读取配置文件")
    config = config_reader()
    _LOGGER.info(f"读取配置文件成功，配置项：{config}")

    # 设置全局变量
    _LOGGER.info("正在设置全局变量")
    value_manager.set_from_dict(config)

    # 初始化队列管理器
    _LOGGER.info("正在初始化队列管理器")
    queue_manager = QueueManager()

    # 初始化缓存
    _LOGGER.info(f"正在初始化缓存，缓存路径为：{config['cache-path']}")
    cache = Cache(config["cache-path"])

    # 初始化cookie
    _LOGGER.info("正在初始化cookie")
    credential = BiliCredential(
        SESSDATA=config["SESSDATA"],
        bili_jct=config["bili_jct"],
        buvid3=config["buvid3"],
        dedeuserid=config["dedeuserid"],
        ac_time_value=config["ac_time_value"]
    )

    # 初始化at侦听器
    _LOGGER.info("正在初始化at侦听器")
    listen = Listen(credential, queue_manager, value_manager)

    # 预加载whisper模型
    _LOGGER.info("正在预加载whisper模型")
    if config["whisper-enable"]:
        whisper = Whisper().load_model(config["whisper-model-size"], config["whisper-device"],
                                       config["whisper-model-dir"])
    else:
        _LOGGER.info("whisper未启用")
        whisper = None

    # 初始化摘要处理链
    _LOGGER.info("正在初始化摘要处理链")
    summarize_chain = SummarizeChain(queue_manager, value_manager, credential, cache, whisper)

    # 启动侦听器
    _LOGGER.info("正在启动at侦听器")
    listen.start_listening()
    _LOGGER.info("启动私信侦听器")
    await listen.listen_private()
    # 启动cookie过期检查和刷新
    _LOGGER.info("正在启动cookie过期检查和刷新")
    credential.start_check()

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
        await asyncio.sleep(1)


if __name__ == "__main__":
    _LOGGER = LOGGER.bind(name="main")
    asyncio.run(start_pipeline())
