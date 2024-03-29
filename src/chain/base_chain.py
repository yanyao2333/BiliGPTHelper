import abc
import asyncio
import os
import time
from typing import Optional

import ffmpeg
import httpx
from bilibili_api import HEADERS
from injector import inject

from src.bilibili.bili_comment import BiliComment
from src.bilibili.bili_credential import BiliCredential
from src.bilibili.bili_session import BiliSession
from src.bilibili.bili_video import BiliVideo
from src.core.routers.asr_router import ASRouter
from src.core.routers.llm_router import LLMRouter
from src.models.config import Config
from src.models.task import (
    AskAIResponse,
    BiliGPTTask,
    EndReasons,
    ProcessStages,
    SummarizeAiResponse,
)
from src.utils.cache import Cache
from src.utils.logging import LOGGER
from src.utils.queue_manager import QueueManager
from src.utils.task_status_record import TaskStatusRecorder


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
        self.ask_ai_queue = self.queue_manager.get_queue("ask_ai")

    async def _set_err_end(self, msg: str, _uuid: str = None, task: BiliGPTTask = None):
        """当一个视频因为错误而结束时，调用此方法

        :param msg: 错误信息
        :param _uuid: 任务uuid (跟task二选一)
        :param task: 任务对象
        """
        self.task_status_recorder.update_record(
            _uuid if _uuid else task.uuid,
            new_task_data=None,
            process_stage=ProcessStages.END,
            end_reason=EndReasons.ERROR,
            gmt_end=int(time.time()),
            error_msg=msg,
        )
        _task = self.task_status_recorder.get_data_by_uuid(_uuid) if _uuid else task
        match _task.source_type:
            case "bili_private":
                self._LOGGER.debug(f"任务{task.uuid}:私信消息，直接回复：{msg}")
                await BiliSession.quick_send(
                    self.credential,
                    task,
                    msg,
                )
            case "bili_comment":
                _task.process_result = msg
                self._LOGGER.debug(f"任务{task.uuid}:评论消息，将结果放入评论处理队列，内容：{msg}")
                await self.reply_queue.put(task)
            case "api":
                self._LOGGER.warning(f"任务{task.uuid}:api获取的消息，未实现处理逻辑")
            case "bili_up":
                _task.process_result = msg
                self._LOGGER.debug(f"任务{task.uuid}:评论消息，将结果放入评论处理队列，内容：{msg}")
                await self.reply_queue.put(task)

    async def _set_normal_end(self, task: BiliGPTTask = None, _uuid: str = None):
        """当一个视频正常结束时，调用此方法

        :param task: 任务对象
        :param _uuid: 任务uuid (跟task二选一)
        """
        self.task_status_recorder.update_record(
            _uuid if _uuid else task.uuid,
            new_task_data=None,
            process_stage=ProcessStages.END,
            end_reason=EndReasons.NORMAL,
            gmt_end=int(time.time()),
        )

    async def _set_noneed_end(self, task: BiliGPTTask = None, _uuid: str = None):
        """当一个视频不需要处理时，调用此方法

        :param task: 任务对象
        :param _uuid: 任务uuid (跟task二选一)
        """
        self.task_status_recorder.update_record(
            _uuid if _uuid else task.uuid,
            new_task_data=None,
            process_stage=ProcessStages.END,
            end_reason=EndReasons.NONEED,
            gmt_end=int(time.time()),
        )
        await BiliSession.quick_send(
            self.credential,
            task,
            "AI觉得你的视频不需要处理，换个更有意义的视频再试试看吧！",
        )

    @abc.abstractmethod
    async def _precheck(self, task: BiliGPTTask) -> bool:
        """检查是否符合调用条件
        :param task: AtItem

        如不符合，请务必调用self._set_err_end()方法后返回False
        """
        pass

    async def finish(self, task: BiliGPTTask, use_cache: bool = False) -> bool:
        """
        当一个任务 **正常** 结束时，调用这个，将消息放入队列、设置缓存、更新任务状态
        :param task:
        :param use_cache: 是否直接使用缓存而非正常处理
        :return:
        """
        _LOGGER = self._LOGGER
        reply_data = task
        # if reply_data.source_type == "bili_private":
        #     _LOGGER.debug("该消息是私信消息，将结果放入私信处理队列")
        #     await self.private_queue.put(reply_data)
        # elif reply_data.source_type == "bili_comment":
        #     _LOGGER.debug("正在将结果加入发送队列，等待回复")
        #     await self.reply_queue.put(reply_data)
        match reply_data.source_type:
            case "bili_private":
                _LOGGER.debug(f"任务{task.uuid}:私信消息，将结果放入私信处理队列")
                await self.private_queue.put(reply_data)
            case "bili_comment":
                _LOGGER.info(f"任务{task.uuid}:评论消息，将结果放入评论处理队列")
                await self.reply_queue.put(reply_data)
            case "api":
                _LOGGER.warning(f"任务{task.uuid}:api获取的消息，未实现处理逻辑")
            case "bili_up":
                _LOGGER.info(f"任务{task.uuid}:评论消息，将结果放入评论处理队列")
                await self.reply_queue.put(reply_data)
        _LOGGER.debug("处理结束，开始清理并提交记录")
        self.task_status_recorder.update_record(
            reply_data.uuid,
            new_task_data=task,
            process_stage=ProcessStages.WAITING_PUSH_TO_CACHE,
        )
        if use_cache:
            await self._set_normal_end(task)
            return True
        self.cache.set_cache(
            key=reply_data.video_id,
            value=reply_data.process_result.model_dump(),
            chain=str(task.chain.value),
        )
        await self._set_normal_end(task)
        return True

    async def _is_cached_video(self, task: BiliGPTTask, _uuid: str, video_info: dict) -> bool:
        """检查是否是缓存的视频
        如果是缓存的视频，直接从缓存中获取结果并发送
        """
        if self.cache.get_cache(key=video_info["bvid"], chain=str(task.chain.value)):
            LOGGER.debug(f"视频{video_info['title']}已经处理过，直接使用缓存")
            cache = self.cache.get_cache(key=video_info["bvid"], chain=str(task.chain.value))
            # if str(task.chain.value) == "summarize":
            #     cache = SummarizeAiResponse.model_validate(cache)
            # elif str(task.chain.value) == "ask_ai":
            #     cache = AskAIResponse.model_validate(cache)
            match str(task.chain.value):
                case "summarize":
                    cache = SummarizeAiResponse.model_validate(cache)
                case "ask_ai":
                    cache = AskAIResponse.model_validate(cache)
                case _:
                    self._LOGGER.error(
                        f"获取到了缓存，但无法匹配处理链{task.chain.value}，无法调取缓存，开始按正常流程处理"
                    )
                    return False
            match task.source_type:
                case "bili_private":
                    task.process_result = cache
                    await self.finish(task, True)
                case "bili_comment":
                    task.process_result = cache
                    await self.finish(task, True)
                case "bili_up":
                    task.process_result = cache
                    await self.finish(task, True)
            return True
        return False

    async def _get_video_info(
        self, task: BiliGPTTask, if_get_comments: bool = True
    ) -> Optional[tuple[BiliVideo, dict, str, str, Optional[str]]]:
        """获取视频的一些信息
        :param task: 任务对象
        :param if_get_comments: 是否获取评论，为假就返回空

        :return 视频正常返回元组(video, video_info, format_video_name, video_tags_string, video_comments)

        video: BiliVideo对象
        video_info: bilibili官方api返回的视频信息
        format_video_name: 格式化后的视频名，用于日志
        video_tags_string: 视频标签
        video_comments: 随机获取的几条视频评论拼接的字符串
        """
        _LOGGER = self._LOGGER
        _LOGGER.info("开始处理该视频音频流和字幕")
        video = BiliVideo(self.credential, url=task.video_url)
        _LOGGER.debug("视频对象创建成功，正在获取视频信息")
        video_info = await video.get_video_info
        _LOGGER.debug("视频信息获取成功，正在获取视频标签")
        format_video_name = f"『{video_info['title']}』"
        # TODO 不清楚b站回复和at时分P的展现机制，暂时遇到分P视频就跳过
        if len(video_info["pages"]) > 1:
            _LOGGER.warning(f"任务{task.uuid}: 视频{format_video_name}分P，跳过处理")
            await self._set_err_end(msg="视频分P，跳过处理", task=task)
            return None
        # 获取视频标签
        video_tags_string = " ".join(f"#{tag['tag_name']}" for tag in await video.get_video_tags())
        _LOGGER.debug("视频标签获取成功，开始获取视频评论")
        # 获取视频评论
        video_comments = (
            await BiliComment.get_random_comment(video_info["aid"], self.credential) if if_get_comments else None
        )
        return video, video_info, format_video_name, video_tags_string, video_comments

    async def _get_subtitle_from_bilibili(self, video: BiliVideo) -> str:
        """从bilibili获取字幕(返回的是纯字幕，不包含时间轴)"""
        _LOGGER = self._LOGGER
        subtitle_url = await video.get_video_subtitle(page_index=0)
        _LOGGER.debug("视频字幕获取成功，正在读取字幕")
        # 下载字幕
        async with httpx.AsyncClient() as client:
            resp = await client.get("https:" + subtitle_url, headers=HEADERS)
        _LOGGER.debug("字幕获取成功，正在转换为纯字幕")
        # 转换字幕格式
        text = ""
        for subtitle in resp.json()["body"]:
            text += f"{subtitle['content']}\n"
        return text

    async def _get_subtitle_from_asr(self, video: BiliVideo, _uuid: str, is_retry: bool = False) -> Optional[str]:
        _LOGGER = self._LOGGER
        if self.asr is None:
            _LOGGER.warning("没有可用的asr，跳过处理")
            await self._set_err_end(_uuid=_uuid, msg="没有可用的asr，跳过处理")
        if is_retry:
            # 如果是重试，就默认已下载音频文件，直接开始转写
            bvid = await video.bvid
            audio_path = f"{self.temp_dir}/{bvid} temp.mp3"
            self.asr = self.asr_router.get_one()  # 重新获取一个，防止因为错误而被禁用，但调用端没及时更新
            if self.asr is None:
                _LOGGER.warning("没有可用的asr，跳过处理")
                await self._set_err_end(_uuid, "没有可用的asr，跳过处理")
            text = await self.asr.transcribe(audio_path)
            if text is None:
                _LOGGER.warning("音频转写失败，报告并重试")
                self.asr_router.report_error(self.asr.alias)
                await self._get_subtitle_from_asr(video, _uuid, is_retry=True)  # 递归，应该不会爆栈
            return text
        _LOGGER.debug("正在获取视频音频流")
        video_download_url = await video.get_video_download_url()
        audio_url = video_download_url["dash"]["audio"][0]["baseUrl"]
        _LOGGER.debug("视频下载链接获取成功，正在下载视频中的音频流")
        bvid = await video.bvid
        # 下载视频中的音频流
        async with httpx.AsyncClient() as client:
            resp = await client.get(audio_url, headers=HEADERS)
            temp_dir = self.temp_dir
            if not os.path.exists(temp_dir):
                os.mkdir(temp_dir)
            with open(f"{temp_dir}/{bvid} temp.m4s", "wb") as f:
                f.write(resp.content)
        _LOGGER.debug("视频中的音频流下载成功，正在转换音频格式")
        # 转换音频格式
        (ffmpeg.input(f"{temp_dir}/{bvid} temp.m4s").output(f"{temp_dir}/{bvid} temp.mp3").run(overwrite_output=True))
        _LOGGER.debug("音频格式转换成功，正在使用whisper转写音频")
        # 使用whisper转写音频
        audio_path = f"{temp_dir}/{bvid} temp.mp3"
        text = await self.asr.transcribe(audio_path)
        if text is None:
            _LOGGER.warning("音频转写失败，报告并重试")
            self.asr_router.report_error(self.asr.alias)
            await self._get_subtitle_from_asr(video, _uuid, is_retry=True)  # 递归，应该不会爆栈
        _LOGGER.debug("音频转写成功，正在删除临时文件")
        # 删除临时文件
        os.remove(f"{temp_dir}/{bvid} temp.m4s")
        os.remove(f"{temp_dir}/{bvid} temp.mp3")
        _LOGGER.debug("临时文件删除成功")
        return text

    async def _smart_get_subtitle(
        self, video: BiliVideo, _uuid: str, format_video_name: str, task: BiliGPTTask
    ) -> Optional[str]:
        """根据用户配置智能获取字幕"""
        _LOGGER = self._LOGGER
        subtitle_url = await video.get_video_subtitle(page_index=0)
        if subtitle_url is None:
            if self.asr is None:
                _LOGGER.warning(f"视频{format_video_name}没有字幕，你没有可用的asr，跳过处理")
                await self._set_err_end(_uuid, "视频没有字幕，你没有可用的asr，跳过处理")
                return None
            _LOGGER.warning(f"视频{format_video_name}没有字幕，开始使用asr转写，这可能会导致字幕质量下降")
            text = await self._get_subtitle_from_asr(video, _uuid)
            task.subtitle = text
            self.task_status_recorder.update_record(_uuid, new_task_data=task, use_whisper=True)
            return text
        _LOGGER.debug(f"视频{format_video_name}有字幕，开始处理")
        text = await self._get_subtitle_from_bilibili(video)
        return text

    def _create_record(self, task: BiliGPTTask) -> str:
        """创建（或查询）一条任务记录，返回uuid"""
        task.gmt_start_process = int(time.time())
        _item_uuid = self.task_status_recorder.create_record(task)
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

    def __repr__(self):
        return self.__class__.__name__
