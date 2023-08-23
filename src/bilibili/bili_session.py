import asyncio
import traceback

import tenacity
from bilibili_api import Credential, session, ResourceType, video

from src.bilibili.bili_video import BiliVideo
from src.utils.logging import LOGGER
from src.utils.types import AtItems, AiResponse

_LOGGER = LOGGER.bind(name="bilibili-session")


class BiliSession:
    def __init__(self, credential: Credential, private_queue: asyncio.Queue):
        self.credential = credential
        self.private_queue = private_queue

    @staticmethod
    def build_reply_content(response: AiResponse) -> list:
        """构建回复内容（由于有私信消息过长被截断的先例，所以返回是一个list，分消息发）"""
        msg_list = []
        msg_list.append(f"就你这b召唤我出来的啊\n\n【视频摘要】{response['summary']}")
        msg_list.append(
            f"【咱对本次生成内容的自我评分】{response['score']}分\n\n【咱的思考】{response['thinking']}\n\n欢迎在github上给本项目点个star！ https://github.com/yanyao2333/BiliGPTHelper"
        )
        return msg_list

    @staticmethod
    def chain_callback(retry_state):
        exception = retry_state.outcome.exception()
        _LOGGER.error(f"捕获到错误：{exception}")
        traceback.print_tb(retry_state.outcome.exception().__traceback__)
        _LOGGER.debug(f"当前重试次数为{retry_state.attempt_number}")
        _LOGGER.debug(f"下一次重试将在{retry_state.next_action.sleep}秒后进行")

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(Exception),
        wait=tenacity.wait_fixed(10),
        before_sleep=chain_callback,
    )
    async def start_private_reply(self):
        """发送评论"""
        while True:
            try:
                data: AtItems = await self.private_queue.get()
                _LOGGER.debug(f"获取到新的私信任务，开始处理")
                video_obj, _type = await BiliVideo(
                    credential=self.credential, url=data["item"]["uri"]
                ).get_video_obj()
                if not video_obj:
                    _LOGGER.warning(f"视频{data['item']['uri']}不存在")
                    return False
                if _type != ResourceType.VIDEO:
                    _LOGGER.warning(f"视频{data['item']['uri']}不是视频，跳过处理")
                    return False
                video_obj: video.Video
                msg_list = BiliSession.build_reply_content(data["item"]["ai_response"])
                for msg in msg_list:
                    await session.send_msg(
                        self.credential,
                        data["item"]["private_msg_event"]["sender_uid"],
                        "1",
                        msg,
                    )
                    await asyncio.sleep(3)
            except asyncio.CancelledError:
                _LOGGER.info("评论处理链关闭")
                return
