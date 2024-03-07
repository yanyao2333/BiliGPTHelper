"""监听bilibili平台的私信、at消息"""
import asyncio
import json
import os
import re
import time
import traceback
from copy import deepcopy
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bilibili_api import session, user
from injector import inject
from src.bilibili.bili_credential import BiliCredential
from src.bilibili.bili_video import BiliVideo
from src.core.routers.chain_router import ChainRouter
from src.models.config import Config
from src.models.task import BiliAtSpecialAttributes, BiliGPTTask
from src.utils.logging import LOGGER
from src.utils.queue_manager import QueueManager
from src.utils.up_video_cache import load_cache, set_cache, get_up_file
_LOGGER = LOGGER.bind(name="bilibili-listener")


class Listen:
    @inject
    def __init__(
        self,
        credential: BiliCredential,
        queue_manager: QueueManager,
        # value_manager: GlobalVariablesManager,
        config: Config,
        schedule: AsyncIOScheduler,
        chain_router: ChainRouter,
    ):
        self.sess = None
        self.credential = credential
        self.summarize_queue = queue_manager.get_queue("summarize")
        self.evaluate_queue = queue_manager.get_queue("evaluate")
        self.last_at_time = int(time.time())  # 当前时间作为初始时间戳
        self.sched = schedule
        self.user_sessions = {}  # 存储用户状态和视频信息
        self.config = config
        self.chain_router = chain_router
        # 以下是自动查询视频更新的参数
        # self.cache_path = './data/video_cache.json'
        # self.up_file_path = './data/up.json'
        self.chain_router = chain_router
        self.uids = {}
        self.video_cache = {}

    async def listen_at(self):
        # global run_time
        data: dict = await session.get_at(self.credential)
        _LOGGER.debug(f"获取at消息成功，内容为：{data}")

        # if len(data["items"]) != 0:
        #     if run_time > 2:
        #         return
        #     _LOGGER.warning(f"目前处于debug状态，将直接处理第一条at消息")
        #     await self.dispatch_task(data["items"][0])
        #     run_time += 1
        #     return

        # 判断是否有新消息
        if len(data["items"]) == 0:
            _LOGGER.debug("没有新消息，返回")
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
                # item["user"] = data["items"]["user"]
                new_items.append(item)
        if len(new_items) == 0:
            _LOGGER.debug("没有新消息，返回")
            return
        _LOGGER.info(f"检测到{len(new_items)}条新消息，开始处理")
        for item in new_items:
            task_metadata = await self.build_task_from_at_msg(item)
            if task_metadata is None:
                continue
            await self.chain_router.dispatch_a_task(task_metadata)

        self.last_at_time = data["items"][0]["at_time"]

    async def build_task_from_at_msg(self, msg: dict) -> BiliGPTTask | None:
        # print(msg)
        try:
            event = deepcopy(msg)
            if msg["item"]["type"] != "reply" or msg["item"]["business_id"] != 1:
                _LOGGER.warning("不是回复消息，跳过")
                return None
            elif msg["item"]["root_id"] != 0 or msg["item"]["target_id"] != 0:
                _LOGGER.warning("该消息是楼中楼消息，暂时不受支持，跳过处理")
                return None
            event["source_type"] = "bili_comment"
            event["raw_task_data"] = deepcopy(msg)
            event["source_extra_attr"] = BiliAtSpecialAttributes.model_validate(
                event["item"]
            )
            event["sender_id"] = str(event["user"]["mid"])
            event["video_url"] = event["item"]["uri"]
            event["source_command"] = event["item"]["source_content"]
            # event["mission"] = False
            event["video_id"] = await BiliVideo(
                credential=self.credential, url=event["item"]["uri"]
            ).bvid
            task_metadata = BiliGPTTask.model_validate(event)
        except Exception:
            traceback.print_exc()
            _LOGGER.error("在验证任务数据结构时出现错误，跳过处理！")
            return None

        return task_metadata

    def start_listen_at(self):
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

    def start_video_mission(self):
        self.sched.add_job(
            self.async_video_list_mission,
            trigger="interval",
            minutes=60,   # minutes=60,
            id="video_list_mission",
            max_instances=3,
            next_run_time=datetime.now(),
        )
        _LOGGER.info("[定时任务]侦听up视频更新任务注册成功， 每60分钟检查一次")

    async def async_video_list_mission(self):
        _LOGGER.info(f"开始执行获取UP的最新视频")
        self.video_cache = load_cache(self.config.storage_settings.up_video_cache)
        self.uids = get_up_file(self.config.storage_settings.up_file)
        for item in self.uids:
            u = user.User(uid=item['uid'])
            try:
                media_list = await u.get_media_list(ps=1, desc=True)
            except Exception:
                traceback.print_exc()
                _LOGGER.error(f"在获取 uid{item} 的视频列表时出错！")
                return None
            media = media_list['media_list'][0]
            bv_id = media['bv_id']
            _LOGGER.info(f"当前视频的bvid：{bv_id}")
            oid = media['id']
            _LOGGER.info(f"当前视频的oid：{oid}")
            if str(item['uid']) in self.video_cache:
                cache_bvid = self.video_cache[str(item['uid'])]['bv_id']
                _LOGGER.info(f"缓存文件中的bvid：{cache_bvid}")
                if cache_bvid != bv_id:
                    _LOGGER.info(
                        f"up有视频更新，视频信息为：\n 作者：{item['username']} 标题：{media['title']}")
                    # 将视频信息传递给消息队列
                    task_metadata = await self.build_task_from_at_mission(media)
                    if task_metadata is None:
                        continue
                    await self.chain_router.dispatch_a_task(task_metadata)
                    set_cache(self.config.storage_settings.up_video_cache, self.video_cache,
                              {'bv_id': bv_id, 'oid': oid}, str(item['uid']))

                else:
                    _LOGGER.info(f"up没有视频更新")

            else:
                _LOGGER.info(f"缓存文件为空，第一次写入数据")
                # self.set_cache({'bv_id': media, 'oid': oid}, str(item['uid']))
            _LOGGER.info(f"休息20秒")
            await asyncio.sleep(20)

    async def build_task_from_at_mission(self, msg: dict) -> BiliGPTTask | None:
        # print(msg)
        try:
            # event = deepcopy(msg)
            event: dict = {}
            event["source_type"] = "bili_up"
            event["raw_task_data"] = {
                "user": {
                    "mid": self.config.bilibili_cookie.dedeuserid,
                    "nickname": self.config.bilibili_self.nickname,
                }
            }
            event["source_extra_attr"] = BiliAtSpecialAttributes.model_validate(
                {"source_id": msg['id'], "target_id": 0, "root_id": 0, "native_uri": msg['link'],"at_details": [
                {
                    "mid": self.config.bilibili_cookie.dedeuserid,
                    "fans": 0,
                    "nickname": self.config.bilibili_self.nickname,
                    "avatar": "http://i1.hdslb.com/bfs/face/d21cf99c96dfdca5e38106c00eb338dd150b4b65.jpg",
                    "mid_link": "",
                    "follow": False
                }
            ]}
            )
            event["sender_id"] = self.config.bilibili_cookie.dedeuserid
            event["video_url"] = msg['short_link']
            event["source_command"] = f"@{self.config.bilibili_self.nickname} 总结一下"
            event["video_id"] = msg['bv_id']
            # event["mission"] = True
            task_metadata = BiliGPTTask.model_validate(event)
        except Exception:
            traceback.print_exc()
            _LOGGER.error("在验证任务数据结构时出现错误，跳过处理！")
            return None

        return task_metadata

    async def build_task_from_private_msg(self, msg: dict) -> BiliGPTTask | None:
        try:
            event = deepcopy(msg)
            bvid = event["video_event"]["content"]
            uri = "https://bilibili.com/video/" + bvid
            event["source_type"] = "bili_private"
            event["raw_task_data"] = deepcopy(msg)
            event["raw_task_data"]["video_event"]["content"] = bvid
            event["sender_id"] = event["text_event"]["sender_uid"]
            event["video_url"] = uri
            event["source_command"] = event["text_event"]["content"][12:]  # 去除掉bv号
            event["video_id"] = bvid
            # event["mission"] = False
            del event["video_event"]
            del event["text_event"]
            del event["status"]
            task_metadata = BiliGPTTask.model_validate(event)
        except Exception:
            traceback.print_exc()
            _LOGGER.error("在验证任务数据结构时出现错误，跳过处理！")
            return None

        return task_metadata

    async def handle_video(self, user_id, event):
        _session = self.user_sessions.get(
            user_id, {"status": "idle", "text_event": {}, "video_event": {}}
        )
        match _session["status"]:
            case "idle" | "waiting_for_keyword":
                _session["status"] = "waiting_for_keyword"
                _session["video_event"] = event
                _session["video_event"]["content"] = _session["video_event"][
                    "content"
                ].get_bvid()

            case "waiting_for_video":
                _session["video_event"] = event
                _session["video_event"]["content"] = _session["video_event"][
                    "content"
                ].get_bvid()
                at_items = await self.build_task_from_private_msg(_session)
                if at_items is None:
                    return
                await self.chain_router.dispatch_a_task(at_items)
                _session["status"] = "idle"
                _session["text_event"] = {}
                _session["video_event"] = {}
            case _:
                pass
        self.user_sessions[user_id] = _session

    async def handle_text(self, user_id, event):
        # _session = PrivateMsgSession(self.user_sessions.get(
        #     user_id, {"status": "idle", "text_event": {}, "video_event": {}}
        # ))
        _session = (
            self.user_sessions[user_id]
            if self.user_sessions.get(user_id, None)
            else {"status": "idle", "video_event": {}, "text_event": {}}
        )

        match "BV" in event["content"]:
            case True:
                _LOGGER.debug("检测到消息中包含BV号，开始提取")
                # try:
                #     p1, p2 = event["content"].split(" ")  # 简单分离一下关键词与链接
                # except Exception as e:
                #     _LOGGER.error(f"分离关键词与链接失败：{e}，返回")
                #     return
                #
                # if "BV" in p1:
                #     bvid = p1
                #     keyword = p2
                # else:
                #     bvid = p2
                #     keyword = p1
                bvid = event["content"][:12]
                if not re.search("^BV[a-zA-Z0-9]{10}$", bvid):
                    _LOGGER.warning(
                        f"从消息‘{event['content']}’中提取bv号失败！你是不是没把bv号放在消息最前面？！"
                    )
                    return
                if _session["status"] in (
                    "waiting_for_keyword",
                    "idle",
                    "waiting_for_video",
                ):
                    _session["video_event"] = {}
                    _session["video_event"]["content"] = bvid
                    _session["text_event"] = deepcopy(event)
                    task_metadata = await self.build_task_from_private_msg(_session)
                    if task_metadata is None:
                        return
                    await self.chain_router.dispatch_a_task(task_metadata)
                    _session["status"] = "idle"
                    _session["text_event"] = {}
                    _session["video_event"] = {}
                self.user_sessions[user_id] = _session
                return

        match _session["status"]:
            case "waiting_for_keyword":
                _session["text_event"] = event
                task_metadata = await self.build_task_from_private_msg(_session)
                if task_metadata is None:
                    return
                # task_metadata = self.build_private_msg_to_at_items(_session["event"])  # type: ignore
                # task_metadata["item"]["source_content"] = text  # 将文本消息填入at内容
                await self.chain_router.dispatch_a_task(task_metadata)
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
        data = event.__dict__
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
        if os.getenv("DEBUG_MODE") == "true":  # debug模式下不排除自己发的消息
            await self.sess.run(exclude_self=False)
        else:
            await self.sess.run(exclude_self=True)
        self.sess.add_event_listener(str(session.EventType.SHARE_VIDEO.value), self.on_receive)  # type: ignore
        self.sess.add_event_listener(str(session.EventType.TEXT.value), self.on_receive)  # type: ignore

    def close_private_listen(self):
        self.sess.close()
        _LOGGER.info("私聊侦听已关闭")

    # def get_cache(self):
    #     with open(self.cache_path, 'r', encoding="utf-8") as f:
    #         cache = json.loads(f.read())
    #     return cache
    #
    # def set_cache(self, data: dict, key: str):
    #     if key not in self.video_cache:
    #         self.video_cache[key] = {}
    #     self.video_cache[key] = data
    #     with open(self.cache_path, "w") as file:
    #         file.write(json.dumps(self.video_cache, ensure_ascii=False, indent=4))

    # def get_up_file(self):
    #     with open(self.up_file_path, 'r', encoding="utf-8") as f:
    #         up_list = json.loads(f.read())
    #     return up_list['all_area']
