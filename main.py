import json

from src.bilibili.bili_credential import BiliCredential
from src.utils.logging import LOGGER
from src.utils.global_variables_manager import GlobalVariablesManager
from src.utils.queue_manager import QueueManager
from src.bilibili.listen import Listen
from src.chain.summarize import SummarizeChain


_LOGGER = LOGGER.bind(name="main")


def config_reader():
    """读取配置文件，现在只是个示例"""
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    return config


async def main():
    # 初始化全局变量管理器
    value_manager = GlobalVariablesManager()
    # 读取配置文件
    config = config_reader()
    value_manager.set_from_dict(config)
    # 初始化队列管理器
    queue_manager = QueueManager()
    # 初始化日志
    _LOGGER.info("初始化日志成功")
    # 初始化cookie
    credential = BiliCredential(
        SESSDATA=config["SESSDATA"],
        bili_jct=config["bili_jct"],
        buvid3=config["buvid3"],
        dedeuserid=config["dedeuserid"],
        ac_time_value=config["ac_time_value"]
    )
    # 启动cookie过期检查和刷新
    credential.start_check()
    # 初始化at侦听器
    listen = Listen(credential, queue_manager)
    # 初始化摘要处理链
    summarize_chain = SummarizeChain(queue_manager, value_manager)
    # 启动侦听器
    await listen.start_listening()
    # 启动摘要处理链
    await summarize_chain.start()