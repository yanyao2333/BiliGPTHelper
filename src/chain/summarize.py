import asyncio

from bilibili_api import Credential

from src.utils.queue_manager import QueueManager
from src.utils.logging import LOGGER
from src.llm.openai_gpt import OpenAIGPTClient
from src.llm.templates import Templates
from src.utils.types import *
from src.utils.global_variables_manager import GlobalVariablesManager
from src.bilibili.video import BiliVideo

_LOGGER = LOGGER.bind(name="summarize")


class SummarizeChain:
    """摘要处理链"""

    def __init__(self, queue_manager: QueueManager, value_manager: GlobalVariablesManager, credential: Credential):
        self.queue = queue_manager.get_queue('summarize')
        self.value_manager = value_manager
        self.api_key = self.value_manager.get_variable("api-key")
        self.api_base = self.value_manager.get_variable("api-base")
        self.model = self.value_manager.get_variable("model") if self.value_manager.get_variable("model") else (
            "gpt-3.5-torbo")
        self.credential = credential

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
                _LOGGER.info(f"摘要处理链获取到新任务了：{summarize}")
                # 获取视频相关信息
                video = BiliVideo(self.credential, url=summarize['item']["url"])
                _LOGGER.debug(f"视频对象创建成功，正在获取视频信息")
                video_info = await video.get_video_info()
                _LOGGER.debug(f"视频信息获取成功，正在获取视频标签")
                format_video_name = f"『{video_info['title']}』"
                # video_pages = await video.get_video_pages() # TODO 不清楚b站回复和at时分P的展现机制，暂时遇到分P视频就跳过
                if len(video_info["pages"]) > 1:
                    _LOGGER.info(f"视频{format_video_name}分P，跳过处理")
                    continue
                # 获取视频标签
                video_tags = await video.get_video_tags()  # 增加tag有概率导致输出内容变差，后期通过prompt engineering解决
                _LOGGER.debug(f"视频标签获取成功，正在获取视频下载链接")
                video_download_url = await video.get_video_download_url()




        except asyncio.CancelledError:
            _LOGGER.info("摘要处理链关闭")
            raise asyncio.CancelledError
