import asyncio
import random
from asyncio import Queue
from typing import Optional

import tenacity
from bilibili_api import comment, video
from injector import inject

from src.bilibili.bili_credential import BiliCredential
from src.bilibili.bili_video import BiliVideo
from src.utils.callback import chain_callback
from src.utils.logging import LOGGER
from src.utils.types import AtItems, AiResponse

_LOGGER = LOGGER.bind(name="bilibili-comment")


class RiskControlFindError(Exception):
    def __init__(self, message):
        super().__init__(message)


class BiliComment:
    @inject
    def __init__(self, comment_queue: Queue, credential: BiliCredential):
        self.comment_queue = comment_queue
        self.credential = credential

    @staticmethod
    async def get_random_comment(
        aid,
        credential,
        type_=comment.CommentResourceType.VIDEO,
        page_index=1,
        order=comment.OrderType.LIKE,
    ) -> str | None:
        """
        随机获取几条热评，直接生成评论prompt string

        :param aid: 视频ID
        :param credential: 身份凭证
        :param type_: 评论资源类型
        :param page_index: 评论页数索引
        :param order: 评论排序方式
        :return: 拼接的评论字符串
        """
        if str(aid).startswith("av"):
            aid = aid[2:]
        _LOGGER.debug(f"正在获取视频{aid}的评论列表")
        comment_list = await comment.get_comments(
            oid=aid,
            credential=credential,
            type_=type_,
            page_index=page_index,
            order=order,
        )
        _LOGGER.debug(f"获取视频{aid}的评论列表成功")
        if len(comment_list) == 0:
            _LOGGER.warning(f"视频{aid}没有评论")
            return None
        _LOGGER.debug(f"正在随机选择评论")
        ignore_name_list = [
            "哔哩哔哩",
            "AI",
            "课代表",
            "机器人",
            "小助手",
            "总结",
            "有趣的程序员",
        ]  # TODO 从配置文件中读取（设置过滤表尽可能避免低质量评论）
        new_comment_list = []
        for _comment in comment_list["replies"]:
            for name in ignore_name_list:
                if name in _comment["member"]["uname"]:
                    _LOGGER.debug(f"评论{_comment['member']['uname']}包含过滤词{name}，跳过")
                    break
            else:
                _LOGGER.debug(f"评论{_comment['member']['uname']}不包含过滤词，加入新列表")
                new_comment_list.append(_comment)
        if len(new_comment_list) == 0:
            _LOGGER.warning(f"视频{aid}没有合适的评论")
            return None
        # 挑选三条评论
        if len(new_comment_list) < 3:
            _LOGGER.debug(f"视频{aid}的评论数量小于3，直接挑选")
            _LOGGER.debug(f"正在拼接评论")
            comment_str = ""
            for _comment in new_comment_list:
                comment_str += f"【{_comment['member']['uname']}】：{_comment['content']['message']}\n"
            _LOGGER.debug(f"拼接评论成功")
            return comment_str
        _LOGGER.debug(f"正在挑选三条评论")
        selected_comment_list = random.sample(new_comment_list, 3)
        _LOGGER.debug(f"挑选三条评论成功")
        # 拼接评论
        _LOGGER.debug(f"正在拼接评论")
        comment_str = ""
        for _comment in selected_comment_list:
            comment_str += (
                f"【{_comment['member']['uname']}】：{_comment['content']['message']}\n"
            )
        _LOGGER.debug(f"拼接评论成功")
        return comment_str

    @staticmethod
    def build_reply_content(response: AiResponse) -> str:
        """
        构建回复内容

        :param response: AI响应内容
        :return: 回复内容字符串
        """
        return f"【视频摘要】{response['summary']}\n\n【咱对本次生成内容的自我评分】{response['score']}\n\n【咱的思考】{response['thinking']}"

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(Exception),
        wait=tenacity.wait_fixed(10),
        before_sleep=chain_callback,
    )
    async def start_comment(self):
        """发送评论"""
        while True:
            risk_control_count = 0
            data = None
            while risk_control_count < 3:
                try:
                    if data is not None:
                        _LOGGER.debug(f"继续处理上一次失败的评论任务")
                    if data is None:
                        data: Optional[AtItems] = await self.comment_queue.get()
                        _LOGGER.debug(f"获取到新的评论任务，开始处理")
                    video_obj, _type = await BiliVideo(
                        credential=self.credential, url=data["item"]["uri"]
                    ).get_video_obj()
                    video_obj: video.Video
                    aid = video_obj.get_aid()
                    if str(aid).startswith("av"):
                        aid = aid[2:]
                    oid = int(aid)
                    root = data["item"]["source_id"]
                    text = BiliComment.build_reply_content(data["item"]["ai_response"])
                    resp = await comment.send_comment(
                        oid=oid,
                        credential=self.credential,
                        text=text,
                        type_=comment.CommentResourceType.VIDEO,
                        root=root,
                    )
                    if not resp["need_captcha"] and resp["success_toast"] == "发送成功":
                        _LOGGER.debug(resp)
                        _LOGGER.debug(f"发送评论成功，休息30秒")
                        await asyncio.sleep(30)
                        break  # 评论成功，退出当前任务的重试循环
                    else:
                        _LOGGER.warning(f"发送评论失败，大概率被风控了，咱们歇会儿再试吧")
                        risk_control_count += 1
                        if risk_control_count >= 3:
                            _LOGGER.warning(f"连续3次风控，跳过当前任务处理下一个")
                            data = None
                            break
                        else:
                            raise RiskControlFindError
                except RiskControlFindError:
                    _LOGGER.warning(f"遇到风控，等待60秒后重试当前任务")
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    _LOGGER.info("评论处理链关闭")
                    return
