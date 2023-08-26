from enum import Enum
from typing import TypedDict, List, Union, NotRequired, Dict

from bilibili_api import Picture
from bilibili_api.video import Video


class AtCursor(TypedDict):
    is_end: bool
    id: int
    time: int


class PrivateMsg(TypedDict):
    """
    事件参数:
    + receiver_id:   收信人 UID
    + receiver_type: 收信人类型，1: 私聊, 2: 应援团通知, 3: 应援团
    + sender_uid:    发送人 UID
    + talker_id:     对话人 UID
    + msg_seqno:     事件 Seqno
    + msg_type:      事件类型
    + msg_key:       事件唯一编号
    + timestamp:     事件时间戳
    + content:       事件内容

    事件类型:
    + TEXT:           纯文字消息
    + PICTURE:        图片消息
    + WITHDRAW:       撤回消息
    + GROUPS_PICTURE: 应援团图片，但似乎不常触发，一般使用 PICTURE 即可
    + SHARE_VIDEO:    分享视频
    + NOTICE:         系统通知
    + PUSHED_VIDEO:   UP主推送的视频
    + WELCOME:        新成员加入应援团欢迎

    TEXT = "1"
    PICTURE = "2"
    WITHDRAW = "5"
    GROUPS_PICTURE = "6"
    SHARE_VIDEO = "7"
    NOTICE = "10"
    PUSHED_VIDEO = "11"
    WELCOME = "306"
    """

    receiver_id: int
    receiver_type: int
    sender_uid: int
    talker_id: int
    msg_seqno: int
    msg_type: int
    msg_key: int
    timestamp: int
    content: Union[str, int, Picture, Video]


class AiResponse(TypedDict):
    """AI回复"""

    summary: str  # 摘要
    score: str  # ai对自己生成内容的评分
    thinking: str  # 思考
    noneed: bool  # 是否需要摘要


class TaskProcessStage(Enum):
    """视频处理阶段"""
    IN_QUEUE = "in_queue"  # 在队列中
    PREPROCESS = "preprocess"  # 包括构建prompt之前都是这个阶段（包含获取信息、字幕读取），处在这个阶段恢复时就直接从头开始
    WAITING_LLM_RESPONSE = "waiting_llm_response"  # 等待llm的回复 这个阶段应该重新加载字幕或从items中的whisper_subtitle节点读取
    WAITING_SEND = "waiting_send"  # 等待发送 这是llm回复后的阶段，需要解析llm的回复，然后发送
    WAITING_PUSH_TO_CACHE = "waiting_push_to_cache"  # 等待推送到缓存（就是发送后）
    WAITING_RETRY = "waiting_retry"  # 等待重试（ai返回数据格式不对）
    END = "end"  # 结束 按理来说应该删除，但为了后期统计，保留


class TaskProcessEvent(Enum):
    SUMMARIZE = "summarize"
    EVALUATE = "evaluate"


class AtItem(TypedDict):
    type: str  # 基本都为reply
    business: str  # 基本都为评论
    business_id: int  # 基本都为1
    title: str  # 如果是一级回复，这里是视频标题，如果是二级回复，这里是一级回复的内容
    image: str  # 一级回复是视频封面，二级回复为空
    uri: str  # 视频链接
    source_content: str  # 回复内容
    source_id: int  # 该评论的id，对应send_comment中的root（如果要回复的话）
    target_id: int  # 上一级评论id， 二级评论指向的就是root_id，三级评论指向的是二级评论的id
    root_id: int  # 暂时还没出现过
    native_url: str  # 评论链接，包含根评论id和父评论id
    at_details: List[dict]  # at的人的信息，常规的个人信息dict
    ai_response: NotRequired[AiResponse | str]  # AI回复的内容，需要等到处理完才能获取到dict，否则为还没处理的str
    is_private_msg: NotRequired[bool]  # 是否为私信
    private_msg_event: NotRequired[PrivateMsg]  # 私信事件
    whisper_subtitle: NotRequired[str]  # whisper字幕
    stage: NotRequired[TaskProcessStage]  # 视频处理阶段
    event: NotRequired[TaskProcessEvent]  # 视频处理事件
    uuid: NotRequired[str]  # 视频处理uuid


class AtItems(TypedDict):
    id: int
    user: dict  # at发送者的个人信息，常规的个人信息dict
    item: AtItem
    at_time: int


class AtAPIResponse(TypedDict):
    """API返回的at消息"""

    cursor: AtCursor
    items: List[AtItems]


class TaskProcessEndReason(Enum):
    """视频处理结束原因"""
    NORMAL = "normal"  # 正常结束
    ERROR = "error"  # 错误结束
    NONEED = "noneed"  # AI认为这个视频不需要处理


class TaskStatus(TypedDict):
    """视频记录"""
    gmt_create: int
    gmt_end: NotRequired[int]
    event: TaskProcessEvent
    stage: TaskProcessStage
    data: AtItems
    end_reason: NotRequired[TaskProcessEndReason]
    error_msg: NotRequired[str]
    use_whisper: NotRequired[bool]
    if_retry: NotRequired[bool]


class TaskStatusFile(TypedDict):
    tasks: Dict[str, TaskStatus]  # 键为uuid
    queue: List[AtItems]
