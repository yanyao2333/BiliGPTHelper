import abc
import asyncio
import copy
import os
import time
from typing import Optional

import ffmpeg
import httpx
from bilibili_api import HEADERS
from bilibili_api.video import Video
from injector import inject

from src.asr.asr_router import ASRouter
from src.bilibili.bili_comment import BiliComment
from src.bilibili.bili_credential import BiliCredential
from src.bilibili.bili_video import BiliVideo
from src.llm.llm_router import LLMRouter
from src.utils.cache import Cache
from src.utils.logging import LOGGER
from src.utils.models import Config
from src.utils.queue_manager import QueueManager
from src.utils.task_status_record import TaskStatusRecorder
from src.utils.types import (
    TaskProcessStage,
    TaskProcessEndReason,
    AtItems,
    TaskProcessEvent,
)


class BaseChain:
    """处理链基类
    对于b站来说，处理链需要接管的内容基本都要包含对视频基本信息的处理和字幕的提取，这个基类全部帮你做了
    """

    @inject
    def __init__(
        self,
        queue_manager: QueueManager,
        config: Config,
        credential: BiliCredential,
        cache: Cache,
        asr_router: ASRouter,
        task_status_recorder: TaskStatusRecorder,
        stop_event: asyncio.Event,
        llm_router: LLMRouter,
    ):
        self.llm_router = llm_router
        self.queue_manager = queue_manager
        self.config = config
        self.cache = cache
        self.asr_router = asr_router
        self.now_tokens = 0
        self.credential = credential
        self.task_status_recorder = task_status_recorder
        self._get_variables()
        self._get_queues()
        self.asr = asr_router.get_one()
        self._LOGGER = LOGGER.bind(name=self.__class__.__name__)
        self.stop_event = stop_event

    def _get_variables(self):
        """从Config获取配置信息"""
        self.temp_dir = self.config.storage_settings.temp_dir
        self.api_key = self.config.LLMs.openai.api_key
        self.api_base = self.config.LLMs.openai.api_base

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

    def _set_normal_end(self, _uuid: str, if_retry: bool = False):
        """当一个视频正常结束时，调用此方法"""
        self.task_status_recorder.update_record(
            _uuid,
            stage=TaskProcessStage.END,
            end_reason=TaskProcessEndReason.NORMAL,
            gmt_end=int(time.time()),
            if_retry=if_retry,
        )

    def _set_noneed_end(self, _uuid: str):
        """当一个视频不需要处理时，调用此方法"""
        self.task_status_recorder.update_record(
            _uuid,
            stage=TaskProcessStage.END,
            end_reason=TaskProcessEndReason.NONEED,
            gmt_end=int(time.time()),
        )

    @abc.abstractmethod
    def _precheck(self, at_item: AtItems, _uuid: str) -> bool:
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

    async def finish(
        self,
        at_items: AtItems,
        resp: dict,
        bvid: str,
        _uuid: str,
        is_retry: bool = False,
    ) -> bool:
        """
        结束一项任务，将消息放入队列、设置缓存、更新任务状态
        :param is_retry:
        :param resp: ai的回复
        :param at_items:
        :param _uuid: 任务uuid
        :param bvid: 视频bvid
        :return:
        """
        _LOGGER = self._LOGGER
        reply_data = copy.deepcopy(at_items)
        reply_data["item"]["ai_response"] = resp
        if (
            at_items["item"]["type"] == "private_msg"
            and at_items["item"]["business_id"] == 114
        ):
            _LOGGER.debug(f"该消息是私信消息，将结果放入私信处理队列")
            await self.private_queue.put(reply_data)
        else:
            _LOGGER.debug(f"正在将结果加入发送队列，等待回复")
            await self.reply_queue.put(reply_data)
        _LOGGER.debug("处理结束，开始清理并提交记录")
        self.task_status_recorder.update_record(
            _uuid, stage=TaskProcessStage.WAITING_PUSH_TO_CACHE
        )
        self.cache.set_cache(key=bvid, value=BaseChain.cut_items_leaves(reply_data))
        self._set_normal_end(_uuid, if_retry=is_retry)
        return True

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
                await self.finish(at_items, cache, video_info["bvid"], _uuid)
            else:
                cache = self.cache.get_cache(key=video_info["bvid"])
                at_items["item"]["ai_response"] = cache
                await self.finish(at_items, cache, video_info["bvid"], _uuid)
            return True
        return False

    async def _get_video_info(
        self, at_items: AtItems, _uuid: str
    ) -> Optional[tuple[BiliVideo, dict, str, str, str]]:
        """获取视频的一些信息

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
        video_info = await video.get_video_info
        _LOGGER.debug(f"视频信息获取成功，正在获取视频标签")
        format_video_name = f"『{video_info['title']}』"
        # TODO 不清楚b站回复和at时分P的展现机制，暂时遇到分P视频就跳过
        if len(video_info["pages"]) > 1:
            _LOGGER.info(f"视频{format_video_name}分P，跳过处理")
            self._set_err_end(_uuid, "视频分P，跳过处理")
            return None
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

    async def _get_subtitle_from_bilibili(self, video: BiliVideo, _uuid: str) -> str:
        """从bilibili获取字幕(返回的是纯字幕，不包含时间轴)"""
        _LOGGER = self._LOGGER
        subtitle_url = await video.get_video_subtitle(page_index=0)
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

    async def _get_subtitle_from_asr(
        self, video: BiliVideo, _uuid: str, is_retry: bool = False
    ) -> Optional[str]:
        _LOGGER = self._LOGGER
        if self.asr is None:
            _LOGGER.warning(f"没有可用的asr，跳过处理")
            self._set_err_end(_uuid, "没有可用的asr，跳过处理")
        if is_retry:
            # 如果是重试，就默认已下载音频文件，直接开始转写
            bvid = await video.bvid
            audio_path = f"{self.temp_dir}/{bvid} temp.mp3"
            self.asr = self.asr_router.get_one()  # 重新获取一个，防止因为错误而被禁用，但调用端没及时更新
            if self.asr is None:
                _LOGGER.warning(f"没有可用的asr，跳过处理")
                self._set_err_end(_uuid, "没有可用的asr，跳过处理")
            text = await self.asr.transcribe(audio_path)
            if text is None:
                _LOGGER.warning(f"音频转写失败，报告并重试")
                self.asr_router.report_error(self.asr.alias)
                await self._get_subtitle_from_asr(
                    video, _uuid, is_retry=True
                )  # 递归，应该不会爆栈
            return text
        _LOGGER.debug(f"正在获取视频音频流")
        video_download_url = await video.get_video_download_url()
        audio_url = video_download_url["dash"]["audio"][0]["baseUrl"]
        _LOGGER.debug(f"视频下载链接获取成功，正在下载视频中的音频流")
        bvid = await video.bvid
        # 下载视频中的音频流
        async with httpx.AsyncClient() as client:
            resp = await client.get(audio_url, headers=HEADERS)
            temp_dir = self.temp_dir
            if not os.path.exists(temp_dir):
                os.mkdir(temp_dir)
            with open(f"{temp_dir}/{bvid} temp.m4s", "wb") as f:
                f.write(resp.content)
        _LOGGER.debug(f"视频中的音频流下载成功，正在转换音频格式")
        # 转换音频格式
        (
            ffmpeg.input(f"{temp_dir}/{bvid} temp.m4s")
            .output(f"{temp_dir}/{bvid} temp.mp3")
            .run(overwrite_output=True)
        )
        _LOGGER.debug(f"音频格式转换成功，正在使用whisper转写音频")
        # 使用whisper转写音频
        audio_path = f"{temp_dir}/{bvid} temp.mp3"
        text = await self.asr.transcribe(audio_path)
        if text is None:
            _LOGGER.warning(f"音频转写失败，报告并重试")
            self.asr_router.report_error(self.asr.alias)
            await self._get_subtitle_from_asr(video, _uuid, is_retry=True)  # 递归，应该不会爆栈
        _LOGGER.debug(f"音频转写成功，正在删除临时文件")
        # 删除临时文件
        os.remove(f"{temp_dir}/{bvid} temp.m4s")
        os.remove(f"{temp_dir}/{bvid} temp.mp3")
        _LOGGER.debug(f"临时文件删除成功")
        return text

    async def _smart_get_subtitle(
        self, video: BiliVideo, _uuid: str, format_video_name: str, at_items: AtItems
    ) -> Optional[str]:
        """根据用户配置智能获取字幕"""
        _LOGGER = self._LOGGER
        subtitle_url = await video.get_video_subtitle(page_index=0)
        if subtitle_url is None:
            if self.asr is None:
                _LOGGER.warning(f"视频{format_video_name}没有字幕，你没有可用的asr，跳过处理")
                self._set_err_end(_uuid, "视频没有字幕，你没有可用的asr，跳过处理")
                return None
            _LOGGER.warning(f"视频{format_video_name}没有字幕，开始使用asr转写，这可能会导致字幕质量下降")
            text = await self._get_subtitle_from_asr(video, _uuid)
            temp = at_items
            temp["item"]["whisper_subtitle"] = text
            self.task_status_recorder.update_record(_uuid, data=temp, use_whisper=True)
            return text
        else:
            _LOGGER.debug(f"视频{format_video_name}有字幕，开始处理")
            text = await self._get_subtitle_from_bilibili(video, _uuid)
            return text

    def _create_record(self, at_items: AtItems) -> str:
        """创建一条任务记录，返回uuid"""
        if isinstance(
            at_items.get("item")
            .get("private_msg_event", {"video_event": {"content": "None"}})
            .get("video_event", {})
            .get("content", None),
            Video,
        ):
            temp = at_items
            temp["item"]["private_msg_event"]["video_event"]["content"] = temp["item"][
                "private_msg_event"
            ]["video_event"]["content"].get_bvid()
        else:
            temp = at_items
        _item_uuid = self.task_status_recorder.create_record(
            temp,
            TaskProcessStage.PREPROCESS,
            TaskProcessEvent.SUMMARIZE,
            int(time.time()),
        )
        return _item_uuid

    @abc.abstractmethod
    async def main(self):
        """
        处理链主函数
        捕获错误的最佳实践是使用tenacity.retry装饰器，callback也已经写好了，就在utils.callback中
        如果实现_on_start的话别忘了在循环代码前调用

        eg：
        @tenacity.retry(
        retry=tenacity.retry_if_exception_type(Exception),
        wait=tenacity.wait_fixed(10),
        before_sleep=chain_callback
        )
        :return:
        """
        pass

    @abc.abstractmethod
    async def _on_start(self):
        """
        在这里完成一些初始化任务，比如将已保存的未处理任务恢复到队列中
        记得在main中调用啊！
        """
        pass

    @abc.abstractmethod
    async def retry(self, *args, **kwargs):
        """
        重试函数，你可以在这里写重试逻辑
        这要求你必须在main函数中捕捉错误并进行调用该函数
        因为llm的返回内容具有不稳定性，所以我强烈建议你实现这个函数。
        """
        pass
