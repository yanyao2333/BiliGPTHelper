import abc
import time

import httpx
from bilibili_api import HEADERS
from injector import inject

from src.asr.local_whisper import Whisper
from src.bilibili.bili_comment import BiliComment
from src.bilibili.bili_credential import BiliCredential
from src.bilibili.bili_video import BiliVideo
from src.utils.cache import Cache
from src.utils.global_variables_manager import GlobalVariablesManager
from src.utils.logging import LOGGER
from src.utils.queue_manager import QueueManager
from src.utils.task_status_record import TaskStatusRecorder
from src.utils.types import TaskProcessStage, TaskProcessEndReason, AtItems


class BaseChain:
    """处理链基类
    对于b站来说，处理链需要接管的内容基本都要包含对视频基本信息的处理和字幕的提取，这个基类全部帮你做了
    """

    @inject
    def __init__(
        self,
        queue_manager: QueueManager,
        value_manager: GlobalVariablesManager,
        credential: BiliCredential,
        cache: Cache,
        whisper_obj: Whisper,
        task_status_recorder: TaskStatusRecorder,
    ):
        self.queue_manager = queue_manager
        self.value_manager = value_manager
        self.cache = cache
        self.whisper_obj = whisper_obj
        self.whisper_model_obj = self.whisper_obj.get_model() if whisper_obj else None
        self.now_tokens = 0
        self.credential = credential
        self.task_status_recorder = task_status_recorder
        self._get_variables()
        self._get_queues()
        self._LOGGER = LOGGER.bind(name=self.__class__.__name__)

    def _get_variables(self):
        """从全局变量管理器获取配置信息"""
        self.api_key = self.value_manager.get_variable("api_key")
        self.api_base = self.value_manager.get_variable("api_base")
        self.temp_dir = self.value_manager.get_variable("temp_dir")
        self.whisper_model_size = self.value_manager.get_variable("whisper_model_size")
        self.model = self.value_manager.get_variable("model")
        self.whisper_device = self.value_manager.get_variable("whisper_device")
        self.whisper_after_process = self.value_manager.get_variable(
            "whisper_after_process"
        )
        self.max_tokens = self.value_manager.get_variable("max_total_tokens")

    def _get_queues(self):
        """从队列管理器获取队列"""
        self.summarize_queue = self.queue_manager.get_queue("summarize")
        self.reply_queue = self.queue_manager.get_queue("reply")
        self.private_queue = self.queue_manager.get_queue("private")

    def _set_err_end(self, _uuid: str, msg: str):
        """当一个视频因为错误而结束时，调用此方法"""
        self.task_status_recorder.update_record(
            _uuid,
            stage=TaskProcessStage.END,
            end_reason=TaskProcessEndReason.ERROR,
            gmt_end=int(time.time()),
            error_msg=msg,
        )

    def _set_normal_end(self, _uuid: str):
        """当一个视频正常结束时，调用此方法"""
        self.task_status_recorder.update_record(
            _uuid,
            stage=TaskProcessStage.END,
            end_reason=TaskProcessEndReason.NORMAL,
            gmt_end=int(time.time()),
        )

    @abc.abstractmethod
    def _check_require(self, at_item: AtItems, _uuid: str) -> bool:
        """检查是否符合调用条件
        :param at_item: AtItem
        :param _uuid: 这项任务的uuid

        如不符合，请务必调用self._set_err_end()方法后返回False
        """
        pass

    @staticmethod
    def cut_items_leaves(items: AtItems):
        """精简at items数据，只保存ai_response，准备存入cache"""
        return items["item"]["ai_response"]

    async def _finish(self, at_items: AtItems, mode: str, _uuid: str, bvid: str):
        """
        结束一项任务，将消息放入队列、设置缓存、更新任务状态
        :param at_items:
        :param mode: reply or private
        :param _uuid: 任务uuid
        :param bvid: 视频bvid
        :return:
        """
        if mode == "reply":
            await self.reply_queue.put(at_items)
        elif mode == "private":
            await self.private_queue.put(at_items)
        self._set_normal_end(_uuid)
        self.cache.set_cache(bvid, BaseChain.cut_items_leaves(at_items))

    async def _is_cached_video(
        self, at_items: AtItems, _uuid: str, video_info: dict
    ) -> bool:
        """检查是否是缓存的视频
        如果是缓存的视频，直接从缓存中获取结果并发送
        """
        if self.cache.get_cache(key=video_info["bvid"]):
            LOGGER.debug(f"视频{video_info['title']}已经处理过，直接使用缓存")
            if (
                at_items["item"]["type"] == "private_msg"
                and at_items["item"]["business_id"] == 114
            ):
                cache = self.cache.get_cache(key=video_info["bvid"])
                at_items["item"]["ai_response"] = cache
                await self._finish(at_items, "private", _uuid, video_info["bvid"])
            else:
                cache = self.cache.get_cache(key=video_info["bvid"])
                at_items["item"]["ai_response"] = cache
                await self._finish(at_items, "reply", _uuid, video_info["bvid"])
            return True
        return False

    async def _get_video_info(
        self, at_items: AtItems, _uuid: str
    ) -> bool | tuple[BiliVideo, dict, str, str, str]:
        """获取视频的一些信息

        :return 视频出错就返回False，命中缓存返回True
        :return 视频正常返回元组(video, video_info, format_video_name, video_tags_string, video_comments)

        video: BiliVideo对象
        video_info: bilibili官方api返回的视频信息
        format_video_name: 格式化后的视频名，用于日志
        video_tags_string: 视频标签
        video_comments: 随机获取的几条视频评论拼接的字符串
        """
        _LOGGER = self._LOGGER
        _LOGGER.info(f"开始处理该视频音频流和字幕")
        video = BiliVideo(self.credential, url=at_items["item"]["uri"])
        _LOGGER.debug(f"视频对象创建成功，正在获取视频信息")
        video_info = await video.get_video_info()
        if self._is_cached_video(at_items, _uuid, video_info):
            return True
        _LOGGER.debug(f"视频信息获取成功，正在获取视频标签")
        format_video_name = f"『{video_info['title']}』"
        # TODO 不清楚b站回复和at时分P的展现机制，暂时遇到分P视频就跳过
        if len(video_info["pages"]) > 1:
            _LOGGER.info(f"视频{format_video_name}分P，跳过处理")
            self._set_err_end(_uuid, "视频分P，跳过处理")
            return False
        # 获取视频标签
        video_tags_string = " ".join(
            f"#{tag['tag_name']}" for tag in await video.get_video_tags()
        )
        _LOGGER.debug(f"视频标签获取成功，开始获取视频评论")
        # 获取视频评论
        video_comments = await BiliComment.get_random_comment(
            video_info["aid"], self.credential
        )
        return video, video_info, format_video_name, video_tags_string, video_comments

    async def _get_subtitle_from_bilibili(
        self, video: BiliVideo, _uuid: str, format_video_name: str
    ) -> bool | str:
        """从bilibili获取字幕(返回的是纯字幕，不包含时间轴)"""
        _LOGGER = self._LOGGER
        subtitle_url = await video.get_video_subtitle(page_index=0)
        if subtitle_url is None:
            _LOGGER.warning(f"视频{format_video_name}因未知原因无法获取字幕，跳过处理")
            self._set_err_end(_uuid, "视频因未知原因无法获取字幕，跳过处理")
            return False
        _LOGGER.debug(f"视频字幕获取成功，正在读取字幕")
        # 下载字幕
        async with httpx.AsyncClient() as client:
            resp = await client.get("https:" + subtitle_url, headers=HEADERS)
        _LOGGER.debug(f"字幕获取成功，正在转换为纯字幕")
        # 转换字幕格式
        text = ""
        for subtitle in resp.json()["body"]:
            text += f"{subtitle['content']}\n"
        return text
