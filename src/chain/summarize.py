import asyncio
import httpx
from bilibili_api import Credential, HEADERS

from src.utils.queue_manager import QueueManager
from src.utils.logging import LOGGER
from src.llm.openai_gpt import OpenAIGPTClient
from src.llm.templates import Templates
from src.asr.local_whisper import Whisper
from src.utils.types import *
from src.utils.global_variables_manager import GlobalVariablesManager
from src.bilibili.bili_video import BiliVideo
from src.bilibili.bili_comment import BiliComment
import ffmpeg
import time
import os
import json

_LOGGER = LOGGER.bind(name="summarize")


class SummarizeChain:
    """摘要处理链"""

    def __init__(
        self,
        queue_manager: QueueManager,
        value_manager: GlobalVariablesManager,
        credential: Credential,
    ):
        self.queue = queue_manager.get_queue("summarize")
        self.value_manager = value_manager
        self.api_key = self.value_manager.get_variable("api-key")
        self.api_base = self.value_manager.get_variable("api-base")
        self.temp_dir = (
            self.value_manager.get_variable("temp-dir")
            if self.value_manager.get_variable("temp-dir")
            else os.path.join(os.getcwd(), "temp")
        )
        self.whisper_model = (
            self.value_manager.get_variable("whisper-model")
            if self.value_manager.get_variable("whisper-model")
            else ("medium")
        )
        self.model = (
            self.value_manager.get_variable("model")
            if self.value_manager.get_variable("model")
            else ("gpt-3.5-torbo")
        )
        self.whisper_device = (
            self.value_manager.get_variable("whisper-device")
            if self.value_manager.get_variable("whisper-device")
            else ("cpu")
        )
        self.credential = credential
        self.whisper_after_process = (
            self.value_manager.get_variable("whisper-after-process")
            if self.value_manager.get_variable("whisper-after-process")
            else False
        )

    async def start(self):
        while True:
            try:
                await self._start_chain()
            except asyncio.CancelledError:
                _LOGGER.info("收到取消信号，摘要处理链关闭")
                break
            except Exception as e:
                _LOGGER.trace(f"摘要处理链出现错误：{e}，正在重启并处理剩余任务")

    async def _start_chain(self):
        try:
            while True:
                # 从队列中获取摘要
                summarize: AtItems = await self.queue.get()
                _LOGGER.info(f"摘要处理链获取到新任务了：{summarize['item']['url']}")
                # 获取视频相关信息
                begin_time = time.perf_counter()
                _LOGGER.info(f"开始处理该视频音频流和字幕")
                video = BiliVideo(self.credential, url=summarize["item"]["url"])
                _LOGGER.debug(f"视频对象创建成功，正在获取视频信息")
                video_info = await video.get_video_info()
                _LOGGER.debug(f"视频信息获取成功，正在获取视频标签")
                format_video_name = f"『{video_info['title']}』"
                # video_pages = await video.get_video_pages() # TODO 不清楚b站回复和at时分P的展现机制，暂时遇到分P视频就跳过
                if len(video_info["pages"]) > 1:
                    _LOGGER.info(f"视频{format_video_name}分P，跳过处理")
                    continue
                # 获取视频标签
                video_tags = (
                    await video.get_video_tags()
                )  # 增加tag有概率导致输出内容变差，后期通过prompt engineering解决
                video_tags_string = ""
                for tag in video_tags:
                    video_tags_string += f"#{tag['tag_name']} "
                _LOGGER.debug(f"视频标签获取成功，开始获取视频评论")
                # 获取视频评论
                video_comments = await BiliComment.get_random_comment(
                    video_info["aid"], self.credential
                )
                _LOGGER.debug(f"视频评论获取成功，开始获取视频字幕")
                if len(video_info["subtitle"]["list"]) == 0:
                    _LOGGER.warning(
                        f"视频{format_video_name}没有字幕，开始使用whisper转写并处理，时间会更长（长了不是一点点）"
                    )
                    video_download_url = await video.get_video_download_url()
                    audio_url = video_download_url["dash"]["audio"][0]["baseUrl"]
                    _LOGGER.debug(f"视频下载链接获取成功，正在下载视频中的音频流")
                    # 下载视频中的音频流
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(audio_url, headers=HEADERS)
                        temp_dir = self.temp_dir
                        if not os.path.exists(temp_dir):
                            os.mkdir(temp_dir)
                        with open(
                            f"{temp_dir}/{video_info['aid']} temp.m4s", "wb"
                        ) as f:
                            f.write(resp.content)
                    _LOGGER.debug(f"视频中的音频流下载成功，正在转换音频格式")
                    # 转换音频格式
                    (
                        ffmpeg.input(f"{temp_dir}/{video_info['aid']} temp.m4s")
                        .output(f"{temp_dir}/{video_info['aid']} temp.mp3")
                        .run()
                    )
                    _LOGGER.debug(f"音频格式转换成功，正在使用whisper转写音频")
                    # 使用whisper转写音频
                    audio_path = f"{temp_dir}/{video_info['aid']} temp.mp3"
                    text = Whisper.whisper_audio(
                        audio_path,
                        model_size=self.whisper_model,
                        device=self.whisper_device,
                        after_process=self.whisper_after_process,
                        openai_api_key=self.api_key,
                        openai_endpoint=self.api_base,
                    )
                    _LOGGER.debug(f"音频转写成功，正在删除临时文件")
                    # 删除临时文件
                    os.remove(f"{temp_dir}/{video_info['aid']} temp.m4s")
                    os.remove(f"{temp_dir}/{video_info['aid']} temp.mp3")
                    _LOGGER.debug(f"临时文件删除成功，开始使用模板生成prompt")
                    # 使用模板生成prompt
                    prompt = OpenAIGPTClient.use_template(
                        Templates.SUMMARIZE_USER,
                        Templates.SUMMARIZE_SYSTEM,
                        title=video_info["title"],
                        tags=video_tags_string,
                        comments=video_comments,
                        subtitle=text,
                        description=video_info["desc"],
                    )
                    _LOGGER.debug(f"prompt生成成功，开始调用openai的Completion API")
                    # 调用openai的Completion API
                    answer, _ = OpenAIGPTClient.completion(prompt, model=self.model)
                    _LOGGER.debug(f"调用openai的Completion API成功，开始处理结果")
                    # 处理结果
                    if answer:
                        try:
                            resp = json.loads(answer)
                            if "noneed" is True:
                                _LOGGER.warning(
                                    f"视频{format_video_name}被ai判定为不需要摘要，跳过处理"
                                )
                                continue
                            elif "summary" "score" "thinking" in resp.keys():
                                _LOGGER.info(
                                    f"ai返回内容解析正确，视频{format_video_name}摘要处理完成，共用时{time.perf_counter() - begin_time}s"
                                )
                                _LOGGER.debug(f"正在将结果加入发送队列，等待回复")
                                summarize["item"]["summary"] = resp["summary"]
                                summarize["item"]["score"] = resp["score"]
                                summarize["item"]["thinking"] = resp["thinking"]
                                summarize["item"]["noneed"] = False
                                self.queue.put(summarize)
                        except Exception as e:
                            _LOGGER.trace(f"处理结果失败：{e}")

        except asyncio.CancelledError:
            _LOGGER.info("摘要处理链关闭")
            raise asyncio.CancelledError
