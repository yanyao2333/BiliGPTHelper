"""监听bilibili平台的私信、at消息"""

import time
from copy import deepcopy
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bilibili_api import session
from injector import inject

from src.bilibili.bili_credential import BiliCredential
from src.utils.logging import LOGGER
from src.utils.models import Config
from src.utils.queue_manager import QueueManager
from src.utils.types import *

_LOGGER = LOGGER.bind(name="bilibili-listener")


class Listen:
    @inject
    def __init__(
        self,
        credential: BiliCredential,
        queue_manager: QueueManager,
        # value_manager: GlobalVariablesManager,
        config: Config,
        sched: AsyncIOScheduler = AsyncIOScheduler(timezone="Asia/Shanghai"),
    ):
        self.sess = None
        self.credential = credential
        self.summarize_queue = queue_manager.get_queue("summarize")
        self.evaluate_queue = queue_manager.get_queue("evaluate")
        self.last_at_time = int(time.time())  # 当前时间作为初始时间戳
        self.sched = sched
        # self.value_manager = value_manager
        self.user_sessions = {}  # 存储用户状态和视频信息
        self.config = config

    async def listen_at(self):
        # global run_time
        data: AtAPIResponse = await session.get_at(self.credential)
        _LOGGER.debug(f"获取at消息成功，内容为：{data}")

        # # TODO remove this
        # if len(data["items"]) != 0:
        #     if run_time > 2:
        #         return
        #     _LOGGER.warning(f"目前处于debug状态，将直接处理第一条at消息")
        #     await self.dispatch_task(data["items"][0])
        #     run_time += 1
        #     return

        # 判断是否有新消息
        if len(data["items"]) == 0:
            _LOGGER.debug(f"没有新消息，返回")
            return
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
        _LOGGER.info(f"开始处理消息，内容为：{content}")
        summarize_keyword = self.config.chain_keywords.summarize_keywords
        evaluate_keyword = self.config.chain_keywords.evaluate_keywords
        for keyword in summarize_keyword:
            if keyword in content:
                _LOGGER.info(f"检测到关键字 {keyword} ，放入【总结】队列")
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
            seconds=20,  # 有新任务都会一次性提交，时间无所谓
            id="listen_at",
            max_instances=3,
            next_run_time=datetime.now(),
        )
        # self.sched.start()
        _LOGGER.info("[定时任务]侦听at消息定时任务注册成功， 每20秒检查一次")

    def build_private_msg_to_at_items(self, msg: PrivateMsgSession) -> AtItems:
        event = deepcopy(msg)
        video: Video = event["video_event"]["content"]
        uri = "https://bilibili.com/video/" + video.get_bvid()
        new_items: AtItems = {
            "at_time": int(time.time()),
            "id": 0,
            "user": {},
            "item": {
                "type": "private_msg",
                "source_content": event["text_event"]["content"],
                "at_time": int(time.time()),
                "uri": uri,
                "private_msg_event": event,
                "business": "私信",
                "business_id": 114,
                "title": "私信",
                "image": "",
                "source_id": 0,
                "target_id": 0,
                "root_id": 0,
                "native_url": "",
                "at_details": [],
            },
        }
        new_items["item"]["private_msg_event"] = event
        return new_items

    async def handle_video(self, user_id, event):
        _session: PrivateMsgSession = self.user_sessions.get(
            user_id, {"status": "idle", "text_event": {}, "video_event": {}}
        )
        match _session["status"]:
            case "idle" | "waiting_for_keyword":
                _session["status"] = "waiting_for_keyword"
                _session["video_event"] = event

            case "waiting_for_video":
                _session["video_event"] = event
                at_items = self.build_private_msg_to_at_items(_session)
                await self.dispatch_task(at_items)
                _session["status"] = "idle"
                _session["text_event"] = {}
                _session["video_event"] = {}
            case _:
                pass
        self.user_sessions[user_id] = _session

    async def handle_text(self, user_id, event):
        _session: PrivateMsgSession = self.user_sessions.get(
            user_id, {"status": "idle", "text_event": {}, "video_event": {}}
        )

        match "BV" in event["content"]:
            case True:
                _LOGGER.debug(f"检测到消息中包含BV号，开始解析")
                try:
                    p1, p2 = event["content"].split(" ")  # 简单分离一下关键词与链接
                except Exception as e:
                    _LOGGER.error(f"分离关键词与链接失败：{e}，返回")
                    return

                if "BV" in p1:
                    bvid = p1
                    keyword = p2
                else:
                    bvid = p2
                    keyword = p1
                video = Video(bvid)
                if (
                    _session["status"] == "waiting_for_keyword"
                    or _session["status"] == "idle"
                    or _session["status"] == "waiting_for_video"
                ):
                    _session["video_event"] = deepcopy(event)
                    _session["video_event"]["content"] = video
                    _session["text_event"] = deepcopy(event)
                    _session["text_event"]["content"] = keyword
                    at_items = self.build_private_msg_to_at_items(_session)
                    await self.dispatch_task(at_items)
                    _session["status"] = "idle"
                    _session["text_event"] = {}
                    _session["video_event"] = {}
                self.user_sessions[user_id] = _session
                return

        match _session["status"]:
            case "waiting_for_keyword":
                _session["text_event"] = event
                at_items = self.build_private_msg_to_at_items(_session)
                # at_items = self.build_private_msg_to_at_items(_session["event"])  # type: ignore
                # at_items["item"]["source_content"] = text  # 将文本消息填入at内容
                await self.dispatch_task(at_items)
                _session["status"] = "idle"
                _session["text_event"] = {}
                _session["video_event"] = {}

            case "idle":
                _session["text_event"] = event
                _session["status"] = "waiting_for_video"

            case "waiting_for_video":
                _session["text_event"] = event

            case _:
                pass
        self.user_sessions[user_id] = _session

    async def on_receive(self, event: session.Event):
        """接收到视频分享消息时的回调函数"""
        _LOGGER.debug(f"接收到私聊消息，内容为：{event}")
        data: PrivateMsg = event.__dict__
        if data["msg_type"] == 7:
            await self.handle_video(data["sender_uid"], data)
        elif data["msg_type"] == 1:
            await self.handle_text(data["sender_uid"], data)
        else:
            _LOGGER.debug(f"未知的消息类型{data['msg_type']}")

    async def listen_private(self):
        # TODO 将轮询功能从bilibili_api库分离，重写
        self.sess = session.Session(self.credential)
        self.sess.logger = _LOGGER
        await self.sess.run()
        self.sess.add_event_listener(session.Event.SHARE_VIDEO, self.on_receive)  # type: ignore
        self.sess.add_event_listener(session.Event.TEXT, self.on_receive)  # type: ignore

    def close_private_listen(self):
        self.sess.close()
        _LOGGER.info("私聊侦听已关闭")
