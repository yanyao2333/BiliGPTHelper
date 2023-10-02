import asyncio
import os
import signal
from enum import Enum

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from injector import Injector

from src.bilibili.bili_comment import BiliComment
from src.bilibili.bili_credential import BiliCredential
from src.bilibili.bili_session import BiliSession
from src.bilibili.listen import Listen
from src.chain.summarize import SummarizeChain
from src.core.app import BiliGPT
from src.utils.logging import LOGGER
from src.utils.models import Config
from src.utils.queue_manager import QueueManager
from src.utils.statistic import run_statistic
from src.utils.task_status_record import TaskStatusRecorder
from src.utils.types import TaskProcessEvent


class Status(Enum):
    """状态枚举"""

    RUNNING = "running"
    STOPPED = "stopped"


async def start_pipeline():
    _LOGGER.info("正在启动BiliGPTHelper")

    # 检查环境变量，预设置docker环境
    if os.getenv("RUNNING_IN_DOCKER") == "yes":
        if not os.listdir("/data"):
            os.system("cp -r /clone-data/* /data")

    # 注册BiliGPT超级应用
    _LOGGER.info("正在注册BiliGPT应用")
    injector = Injector([BiliGPT()])

    # 初始化at侦听器
    _LOGGER.info("正在初始化at侦听器")
    listen = injector.get(Listen)

    # 初始化摘要处理链
    _LOGGER.info("正在初始化摘要处理链")
    summarize_chain = injector.get(SummarizeChain)

    # 启动侦听器
    _LOGGER.info("正在启动at侦听器")
    listen.start_listening()
    _LOGGER.info("启动私信侦听器")
    await listen.listen_private()

    _LOGGER.info("正在启动cookie过期检查和刷新")
    injector.get(BiliCredential).start_check()

    # 启动定时任务调度器
    _LOGGER.info("正在启动定时任务调度器")
    injector.get(AsyncIOScheduler).start()

    # 启动摘要处理链
    _LOGGER.info("正在启动摘要处理链")
    summarize_task = asyncio.create_task(summarize_chain.main())

    # 启动评论
    _LOGGER.info("正在启动评论处理链")
    comment = BiliComment(
        injector.get(QueueManager).get_queue("reply"), injector.get(BiliCredential)
    )
    comment_task = asyncio.create_task(comment.start_comment())

    # 启动私信
    _LOGGER.info("正在启动私信处理链")
    private = BiliSession(
        injector.get(BiliCredential), injector.get(QueueManager).get_queue("private")
    )
    private_task = asyncio.create_task(private.start_private_reply())

    _LOGGER.info("摘要处理链、评论处理链、私信处理链启动完成")

    _LOGGER.info("🎉启动完成 enjoy it")

    while True:
        if flag == Status.STOPPED:
            _LOGGER.info("正在关闭BiliGPTHelper，记得下次再来玩喵！")
            _LOGGER.info("正在关闭定时任务调度器")
            sched = injector.get(AsyncIOScheduler)
            for job in sched.get_jobs():
                sched.remove_job(job.id)
            sched.shutdown()
            listen.close_private_listen()
            _LOGGER.info("正在保存队列任务信息")
            # NOTICE: 需要保存其他queue时，需要在这里添加
            injector.get(TaskStatusRecorder).save_queue(
                injector.get(QueueManager).get_queue("summarize"),
                event=TaskProcessEvent.SUMMARIZE,
                queue_name="summarize",
            )
            _LOGGER.info("正在关闭所有的处理链")
            summarize_task.cancel()
            comment_task.cancel()
            private_task.cancel()
            _LOGGER.info("正在生成本次运行的统计报告")
            statistics_dir = injector.get(Config).model_dump()["statistics_dir"]
            run_statistic(
                statistics_dir if statistics_dir else "./statistics",
                injector.get(TaskStatusRecorder).tasks,
            )
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
