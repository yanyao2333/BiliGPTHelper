from bilibili_api import comment
import random
from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="bilibili-comment")


class BiliComment:
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
