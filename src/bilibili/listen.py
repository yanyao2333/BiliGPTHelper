"""侦听at消息和私聊转发视频消息"""

import asyncio
import sys
import time
from datetime import datetime, timedelta

from bilibili_api import session, Credential
from src.utils.logging import LOGGER, custom_format
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.utils.types import *
from src.constants import summarize_keyword, evaluate_keyword

from src.utils.queue_manager import QueueManager


_LOGGER = LOGGER.bind(name="bilibili-listener")
_LOGGER.add(sys.stdout, format=custom_format)


class Listen:
    def __init__(self, credential, queue_manager: QueueManager):
        self.credential = credential
        self.summarize_queue = queue_manager.get_queue("summarize")
        self.evaluate_queue = queue_manager.get_queue("evaluate")
        self.last_at_time = int(time.time())  # 当前时间作为初始时间戳
        self.sched = AsyncIOScheduler(timezone="Asia/Shanghai")

    async def listen_at(self):
        data: AtAPIResponse = await session.get_at(self.credential)

        # 判断是否有新消息
        if self.last_at_time >= data["items"][0]["at_time"]:
            _LOGGER.debug(
                f"last_at_time{self.last_at_time}大于或等于当前最新消息的at_time{data['items'][0]['at_time']}，返回"
            )
            return

        new_items = []
        for item in reversed(data["items"]):
            if item["at_time"] > self.last_at_time:
                _LOGGER.debug(
                    f"at_time{item['at_time']}大于last_at_time{self.last_at_time}，放入新消息队列"
                )
                new_items.append(item)
        if len(new_items) == 0:
            _LOGGER.debug(f"没有新消息，返回")
            return
        _LOGGER.info(f"检测到{len(new_items)}条新消息，开始处理")
        for item in new_items:
            await self.dispatch_task(item)

        self.last_at_time = data["items"][0]["at_time"]

    async def dispatch_task(self, data: AtItems):
        content = data["item"]["source_content"]
        _LOGGER.info(f"检测到at消息，内容为：{content}")
        for keyword in summarize_keyword:
            if keyword in content:
                _LOGGER.info(f"检测到关键字{keyword}，放入【总结】队列")
                await self.summarize_queue.put(data)
                return
        for keyword in evaluate_keyword:
            if keyword in content:
                _LOGGER.info(f"检测到关键字{keyword}，放入【锐评】队列")
                await self.evaluate_queue.put(data)
                return
        _LOGGER.debug(f"没有检测到关键字，跳过")

    def start_listening(self):
        self.sched.add_job(
            self.listen_at,
            trigger="interval",
            seconds=20,
            id="listen_at",
            max_instances=3,
            next_run_time=datetime.now(),
        )
        self.sched.start()
        _LOGGER.info("侦听at消息定时任务注册成功， 每20秒检查一次")

    @staticmethod
    def build_credential(sessdata, bili_jct, buvid3, dedeuserid, ac_time_value):
        """构建credential（并没有什么卵用）
        :param sessdata: sessdata
        :param bili_jct: bili_jct
        :param buvid3: buvid3
        :param dedeuserid: dedeuserid
        :param ac_time_value: ac_time_value（刷新cookie用，反正获取又不难，配置完省心）
        :return: credential
        """
        return Credential(sessdata, bili_jct, buvid3, dedeuserid, ac_time_value)
