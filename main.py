import asyncio
import os
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from injector import Injector

from src.bilibili.bili_comment import BiliComment
from src.bilibili.bili_credential import BiliCredential
from src.bilibili.bili_session import BiliSession
from src.chain.summarize import Summarize
from src.core.app import BiliGPT
from src.listener.bili_listen import Listen
from src.models.config import Config
from src.models.task import Chains
from src.utils.logging import LOGGER
from src.utils.merge_config import is_have_diff, merge_config, load_config, save_config
from src.utils.queue_manager import QueueManager
from src.utils.task_status_record import TaskStatusRecorder


class BiliGPTPipeline:
    stop_event: asyncio.Event

    def __init__(self):
        _LOGGER.info("正在启动BiliGPTHelper")
        signal.signal(signal.SIGINT, BiliGPTPipeline.stop_handler)
        signal.signal(signal.SIGTERM, BiliGPTPipeline.stop_handler)

        # 检查环境变量，预设置docker环境
        if os.getenv("RUNNING_IN_DOCKER") == "yes":
            if not os.listdir("/data"):
                os.system("cp -r /clone-data/* /data")

        config_path = "./config.yml"

        if os.getenv("RUNNING_IN_DOCKER") == "yes":
            temp = "./config/docker_config.yml"
            conf = load_config(config_path)
            template = load_config(temp)
            if is_have_diff(conf, template):
                _LOGGER.info("检测到config模板发生更新，正在更新用户的config，请记得及时填写新的字段")
                merge_config(conf, template)
                save_config(conf, config_path)
        else:
            temp = "./config/example_config.yml"
            conf = load_config(config_path)
            template = load_config(temp)
            if is_have_diff(conf, template):
                _LOGGER.info("检测到config模板发生更新，正在更新用户的config，请记得及时填写新的字段")
                merge_config(conf, template)
                save_config(conf, config_path)

        # 初始化注入器
        _LOGGER.info("正在初始化注入器")
        self.injector = Injector(BiliGPT)

        BiliGPTPipeline.stop_event = self.injector.get(asyncio.Event)
        config = self.injector.get(Config)

        if config.debug_mode is False:
            LOGGER.remove()
            LOGGER.add(sys.stdout, level="INFO")

    @staticmethod
    def stop_handler(_, __):
        BiliGPTPipeline.stop_event.set()

    async def start(self):
        injector = self.injector

        # 初始化at侦听器
        _LOGGER.info("正在初始化at侦听器")
        listen = injector.get(Listen)

        # 初始化摘要处理链
        _LOGGER.info("正在初始化摘要处理链")
        summarize_chain = injector.get(Summarize)

        # 启动侦听器
        _LOGGER.info("正在启动at侦听器")
        listen.start_listen_at()
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
            injector.get(BiliCredential),
            injector.get(QueueManager).get_queue("private"),
        )
        private_task = asyncio.create_task(private.start_private_reply())

        _LOGGER.info("摘要处理链、评论处理链、私信处理链启动完成")

        _LOGGER.info("🎉启动完成 enjoy it")

        while True:
            if BiliGPTPipeline.stop_event.is_set():
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
                    queue_name="summarize",
                    chain=Chains.SUMMARIZE,
                )
                _LOGGER.info("正在关闭所有的处理链")
                summarize_task.cancel()
                comment_task.cancel()
                private_task.cancel()
                # _LOGGER.info("正在生成本次运行的统计报告")
                # statistics_dir = injector.get(Config).model_dump()["storage_settings"][
                #     "statistics_dir"
                # ]
                # run_statistic(
                #     statistics_dir if statistics_dir else "./statistics",
                #     injector.get(TaskStatusRecorder).tasks,
                # )
                break
            await asyncio.sleep(1)


if __name__ == "__main__":
    _LOGGER = LOGGER.bind(name="main")
    biligpt = BiliGPTPipeline()
    asyncio.run(biligpt.start())
