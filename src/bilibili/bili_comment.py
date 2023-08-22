import asyncio
import sys
from asyncio import Queue

from bilibili_api import comment, ResourceType, video
import random
from src.utils.logging import LOGGER, custom_format
from src.utils.types import AtItem, AtItems, AiResponse
from src.bilibili.bili_video import BiliVideo

_LOGGER = LOGGER.bind(name="bilibili-comment")
_LOGGER.add(sys.stdout, format=custom_format)


class RiskControlFindError(Exception):
    def __init__(self, message):
        super().__init__(message)


class BiliComment:
    def __init__(self, comment_queue: Queue, credential):
        self.comment_queue = comment_queue
        self.credential = credential

    @staticmethod
    async def get_random_comment(
            aid,
            credential,
            type_=comment.CommentResourceType.VIDEO,
            page_index=1,
            order=comment.OrderType.LIKE,
    ):
        """随机获取几条热评，直接生成评论prompt string"""
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
                comment_str += (
                    f"【{_comment['member']['uname']}】：{_comment['content']['message']}\n"
                )
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
    def build_reply_content(self, response: AiResponse):
        """构建回复内容"""
        return f"[兔年吉祥東雪蓮_哈哈]就你这b召唤我出来的啊\n\n【视频摘要】{response['summary']}\n\n【咱对本次生成内容的自我评分】{response['score']}\n\n【咱的思考】{response['thinking']}\n\n关注qwert233喵，关注qwert233谢谢喵!我先润了[兔年吉祥東雪蓮_润]"

    async def start(self):
        while True:
            try:
                await self._start_comment()
            except asyncio.CancelledError:
                _LOGGER.info("收到取消信号，评论发送关闭")
                break
            except Exception as e:
                _LOGGER.trace(f"评论发送出现错误：{e}，正在重启并处理剩余任务")

    async def _start_comment(self):
        """发送评论"""
        while True:
            try:
                data: AtItems = await self.comment_queue.get()
                _LOGGER.debug(f"获取到新的评论任务，开始处理")
                video_obj, _type = await BiliVideo(credential=self.credential, url=data["item"]["url"]).get_video_obj()
                if not video_obj:
                    _LOGGER.warning(f"视频{data['item']['url']}不存在")
                    return False
                if _type != ResourceType.VIDEO:
                    _LOGGER.warning(f"视频{data['item']['url']}不是视频，跳过处理")
                    return False
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
                    _LOGGER.debug(f"发送评论成功，休息30秒")
                    await asyncio.sleep(30)
                    continue
                else:
                    _LOGGER.warning(f"发送评论失败，大概率被风控了，咱们歇会儿再试吧")
                    raise RiskControlFindError
            except RiskControlFindError:
                await asyncio.sleep(60)
                continue
            except asyncio.CancelledError:
                _LOGGER.info("摘要处理链关闭")
                raise asyncio.CancelledError
