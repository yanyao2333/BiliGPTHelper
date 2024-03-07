import asyncio
import os
import shutil
import signal
import sys
import traceback

from apscheduler.events import EVENT_JOB_ERROR
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from injector import Injector

from safe_update import merge_cache_to_new_version
from src.bilibili.bili_comment import BiliComment
from src.bilibili.bili_credential import BiliCredential
from src.bilibili.bili_session import BiliSession
from src.chain.ask_ai import AskAI
from src.chain.summarize import Summarize
from src.core.app import BiliGPT
from src.listener.bili_listen import Listen
from src.models.config import Config
from src.utils.callback import scheduler_error_callback
from src.utils.logging import LOGGER
from src.utils.queue_manager import QueueManager


class BiliGPTPipeline:
    stop_event: asyncio.Event

    def __init__(self):
        _LOGGER.info("正在启动BiliGPTHelper")
        with open("VERSION", encoding="utf-8") as ver:
            version = ver.read()
        _LOGGER.info(f"当前运行版本：V{version}")
        signal.signal(signal.SIGINT, BiliGPTPipeline.stop_handler)
        signal.signal(signal.SIGTERM, BiliGPTPipeline.stop_handler)

        # 检查环境变量，预设置docker环境
        if os.getenv("RUNNING_IN_DOCKER") == "yes":
            if not os.listdir("/data"):
                os.system("cp -r /clone-data/* /data")
        elif not os.path.isfile("config.yml"):
            _LOGGER.warning("没有发现配置文件，正在重新生成新的配置文件！")
            try:
                shutil.copyfile("./config/example_config.yml", "./config.yml")
            except Exception:
                _LOGGER.error("在复制过程中发生了未预期的错误，程序初始化停止")
                traceback.print_exc()
                exit(0)

        # config_path = "./config.yml"

        # if os.getenv("RUNNING_IN_DOCKER") == "yes":
        #     temp = "./config/docker_config.yml"
        #     conf = load_config(config_path)
        #     template = load_config(temp)
        #     if is_have_diff(conf, template):
        #         _LOGGER.info("检测到config模板发生更新，正在更新用户的config，请记得及时填写新的字段")
        #         merge_config(conf, template)
        #         save_config(conf, config_path)
        # else:
        #     temp = "./config/example_config.yml"
        #     conf = load_config(config_path)
        #     template = load_config(temp)
        #     if is_have_diff(conf, template):
        #         _LOGGER.info("检测到config模板发生更新，正在更新用户的config，请记得及时填写新的字段")
        #         merge_config(conf, template)
        #         save_config(conf, config_path)

        # 初始化注入器
        _LOGGER.info("正在初始化依赖注入器")
        self.injector = Injector(BiliGPT)

        BiliGPTPipeline.stop_event = self.injector.get(asyncio.Event)
        _LOGGER.debug("初始化配置文件")
        config = self.injector.get(Config)

        if config.debug_mode is False:
            LOGGER.remove()
            LOGGER.add(sys.stdout, level="INFO")

        _LOGGER.debug("尝试更新用户数据，符合新版本结构（这只是个提示，每次运行都会显示，其他地方不报错就别管了）")
        self.update_sth(config)

    def update_sth(self, config: Config):
        """升级后进行配置文件、运行数据的转换"""
        merge_cache_to_new_version(config.storage_settings.cache_path)

    @staticmethod
    def stop_handler(_, __):
        BiliGPTPipeline.stop_event.set()

    async def start(self):
        try:
            _injector = self.injector

            # 恢复队列任务
            _LOGGER.info("正在恢复队列信息")
            _injector.get(QueueManager).recover_queue(
                _injector.get(Config).storage_settings.queue_save_dir
            )

            # 初始化at侦听器
            _LOGGER.info("正在初始化at侦听器")
            listen = _injector.get(Listen)

            # 初始化摘要处理链
            _LOGGER.info("正在初始化摘要处理链")
            summarize_chain = _injector.get(Summarize)

            # 初始化ask_ai处理链
            _LOGGER.info("正在初始化ask_ai处理链")
            ask_ai_chain = _injector.get(AskAI)

            # 启动侦听器
            _LOGGER.info("正在启动at侦听器")
            listen.start_listen_at()
            _LOGGER.info("正在启动视频更新检测侦听器")
            listen.start_video_mission()

            # 默认关掉私信，私信太烧内存
            # _LOGGER.info("启动私信侦听器")
            # await listen.listen_private()

            _LOGGER.info("正在启动cookie过期检查和刷新")
            _injector.get(BiliCredential).start_check()

            # 启动定时任务调度器
            _LOGGER.info("正在启动定时任务调度器")
            _injector.get(AsyncIOScheduler).start()
            _injector.get(AsyncIOScheduler).add_listener(
                scheduler_error_callback, EVENT_JOB_ERROR
            )

            # 启动处理链
            _LOGGER.info("正在启动处理链")
            summarize_task = asyncio.create_task(summarize_chain.main())
            ask_ai_task = asyncio.create_task(ask_ai_chain.main())

            # 启动评论
            _LOGGER.info("正在启动评论处理链")
            comment = BiliComment(
                _injector.get(QueueManager).get_queue("reply"),
                _injector.get(BiliCredential),
            )
            comment_task = asyncio.create_task(comment.start_comment())

            # 启动私信
            _LOGGER.info("正在启动私信处理链")
            private = BiliSession(
                _injector.get(BiliCredential),
                _injector.get(QueueManager).get_queue("private"),
            )
            private_task = asyncio.create_task(private.start_private_reply())

            _LOGGER.info("摘要处理链、评论处理链、私信处理链启动完成")

            # 定时执行指定up是否有更新视频，如果有自动回复
            # mission = BiliMission(_injector.get(BiliCredential), _injector.get(AsyncIOScheduler))
            # await mission.start()
            # _LOGGER.info("创建刷新UP最新视频任务成功，刷新频率：60分钟")

            _LOGGER.success("🎉启动完成 enjoy it")

            while True:
                if BiliGPTPipeline.stop_event.is_set():
                    _LOGGER.info("正在关闭BiliGPTHelper，记得下次再来玩喵！")
                    _LOGGER.info("正在关闭定时任务调度器")
                    sched = _injector.get(AsyncIOScheduler)
                    for job in sched.get_jobs():
                        sched.remove_job(job.id)
                    sched.shutdown()
                    listen.close_private_listen()
                    _LOGGER.info("正在保存队列任务信息")
                    _injector.get(QueueManager).safe_close_all_queues(
                        _injector.get(Config).storage_settings.queue_save_dir
                    )
                    _LOGGER.info("正在关闭所有的处理链")
                    summarize_task.cancel()
                    ask_ai_task.cancel()
                    comment_task.cancel()
                    private_task.cancel()
                    # mission_task.cancel()
                    # _LOGGER.info("正在生成本次运行的统计报告")
                    # statistics_dir = _injector.get(Config).model_dump()["storage_settings"][
                    #     "statistics_dir"
                    # ]
                    # run_statistic(
                    #     statistics_dir if statistics_dir else "./statistics",
                    #     _injector.get(TaskStatusRecorder).tasks,
                    # )
                    break
                await asyncio.sleep(1)
        except Exception:
            _LOGGER.error("发生了未捕获的错误，停止运行！")
            traceback.print_exc()


if __name__ == "__main__":
    os.environ["DEBUG_MODE"] = "false"
    _LOGGER = LOGGER.bind(name="main")
    biligpt = BiliGPTPipeline()
    asyncio.run(biligpt.start())
