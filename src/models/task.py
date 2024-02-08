# pylint: disable=missing-function-docstring
import time
import uuid
from enum import Enum
from typing import Annotated, List, Optional, Union

from pydantic import BaseModel, Field, StringConstraints


class SummarizeAiResponse(BaseModel):
    """总结处理链的AI回复"""

    # TODO 加上这行就跑不了了
    # 防ai呆措施，让数字评分变成字符串
    # model_config = ConfigDict(coerce_numbers_to_str=True)  # type: ignore

    summary: str  # 摘要
    score: str  # 视频评分
    thinking: str  # 思考
    if_no_need_summary: bool  # 是否需要摘要


class AskAIResponse(BaseModel):
    """问问ai的回复"""

    # 防ai呆措施，让数字评分变成字符串
    # model_config = ConfigDict(coerce_numbers_to_str=True)  # type: ignore

    answer: str  # 回答
    score: str  # 评分


class ProcessStages(Enum):
    """视频处理阶段"""

    PREPROCESS = (
        "preprocess"  # 包括构建prompt之前都是这个阶段（包含获取信息、字幕读取），处在这个阶段恢复时就直接从头开始
    )
    WAITING_LLM_RESPONSE = (
        "waiting_llm_response"  # 等待llm的回复 这个阶段应该重新加载字幕或从items中的whisper_subtitle节点读取
    )
    WAITING_SEND = "waiting_send"  # 等待发送 这是llm回复后的阶段，需要解析llm的回复，然后发送
    WAITING_PUSH_TO_CACHE = "waiting_push_to_cache"  # 等待推送到缓存（就是发送后）
    WAITING_RETRY = "waiting_retry"  # 等待重试（ai返回数据格式不对）
    END = "end"  # 结束 按理来说应该删除，但为了后期统计，保留


class Chains(Enum):
    SUMMARIZE = "summarize"
    ASK_AI = "ask_ai"


class EndReasons(Enum):
    """视频处理结束原因"""

    NORMAL = "正常结束"  # 正常结束
    ERROR = "视频在处理过程中出现致命错误或多次重试失败，详细见具体的msg"  # 错误结束
    NONEED = "AI认为该视频不需要被处理，可能是因为内容无意义"  # AI认为这个视频不需要处理


class BiliAtSpecialAttributes(BaseModel):
    """包含来自at的task的特殊属性"""

    source_id: int  # 该评论的id，对应send_comment中的root（如果要回复的话）
    target_id: int  # 上一级评论id， 二级评论指向的就是root_id，三级评论指向的是二级评论的id
    root_id: int  # 暂时还没出现过
    native_url: str  # 评论链接，包含根评论id和父评论id
    at_details: List[dict]  # at的人的信息，常规的个人信息dict


class AskAICommandParams(BaseModel):
    """问问ai包含的参数"""

    question: str  # 用户提出的问题


class BiliGPTTask(BaseModel):
    """单任务全生命周期的数据模型 用于替代其他所有的已有类型"""

    source_type: Annotated[str, StringConstraints(pattern=r"^(bili_comment|bili_private|api)$")]  # type: ignore # 设置task的获取来源
    raw_task_data: dict  # 原始的task数据，包含所有信息
    sender_id: int  # task提交者的id，用于统计。来自b站的task就是uid，其他来源的task要自己定义
    # video_title: str  # 视频标题
    video_url: str  # 视频链接
    video_id: str  # bvid
    source_command: str  # 用户发送的原始指令（eg. "总结一下" "问一下：xxxxxxx"）
    command_params: Optional[AskAICommandParams] = None  # 用户原始指令经解析后的参数
    source_extra_attr: Optional[BiliAtSpecialAttributes] = None  # 在获取到task时附加的其他原始参数（比如评论id等）
    process_result: Optional[
        Union[SummarizeAiResponse, AskAIResponse, str]
    ] = None  # 最终处理结果，根据不同的处理链会有不同的结果
    subtitle: Optional[str] = None  # 该视频字幕，与之前不同的是，现在不管是什么方式得到的字幕都要保存下来
    process_stage: Optional[ProcessStages] = Field(default=ProcessStages.PREPROCESS.value)  # 视频处理阶段
    chain: Optional[Chains] = None  # 视频处理事件，即对应的处理链
    uuid: Optional[str] = Field(default=str(uuid.uuid4()))  # 该任务的uuid4
    gmt_create: int = Field(default=int(time.time()))  # 任务创建时间戳，默认为当前时间戳
    gmt_start_process: int = Field(default=0)  # 任务开始处理时间，不同于上方的gmt_create，这个是真正开始处理的时间
    gmt_retry_start: int = Field(default=0)  # 如果该任务被重试，就在开始重试时填写该属性
    gmt_end: int = Field(default=0)  # 任务彻底结束时间
    error_msg: Optional[str] = None  # 更详细的错误信息
    end_reason: Optional[EndReasons] = None  # 任务结束原因


# class AtItem(TypedDict):
#     """里面储存着待处理任务的所有信息，私信消息也会被转换为这种格式再处理，后续可以进一步清洗，形成这个项目自己的格式"""
#
#     type: str  # 基本都为reply
#     business: str  # 基本都为评论
#     business_id: int  # 基本都为1
#     title: str  # 如果是一级回复，这里是视频标题，如果是二级回复，这里是一级回复的内容
#     image: str  # 一级回复是视频封面，二级回复为空
#     uri: str  # 视频链接
#     source_content: str  # 回复内容
#     source_id: int  # 该评论的id，对应send_comment中的root（如果要回复的话）
#     target_id: int  # 上一级评论id， 二级评论指向的就是root_id，三级评论指向的是二级评论的id
#     root_id: int  # 暂时还没出现过
#     native_url: str  # 评论链接，包含根评论id和父评论id
#     at_details: List[dict]  # at的人的信息，常规的个人信息dict
#     ai_response: NotRequired[SummarizeAiResponse | str]  # AI回复的内容，需要等到处理完才能获取到dict，否则为还没处理的str
#     is_private_msg: NotRequired[bool]  # 是否为私信
#     private_msg_event: NotRequired[PrivateMsgSession]  # 单用户私信会话信息
#     whisper_subtitle: NotRequired[str]  # whisper字幕
#     stage: NotRequired[ProcessStages]  # 视频处理阶段
#     event: NotRequired[Chains]  # 视频处理事件
#     uuid: NotRequired[str]  # 视频处理uuid


# class AtItems(TypedDict):
#     id: int
#     user: dict  # at发送者的个人信息，常规的个人信息dict
#     item: List[AtItem]
#     at_time: int


# class AtAPIResponse(TypedDict):
#     """API返回的at消息"""
#
#     cursor: AtCursor
#     items: List[AtItems]


# class TaskStatus(BaseModel):
#     """视频记录"""
#
#     gmt_create: int
#     gmt_end: Optional[int]
#     event: Chains
#     stage: ProcessStages
#     task_data: BiliGPTTask
#     end_reason: Optional[EndReasons]
#     error_msg: Optional[str]
#     use_whisper: Optional[bool]
#     if_retry: Optional[bool]

# class AtCursor(TypedDict):
#     is_end: bool
#     id: int
#     time: int


# class PrivateMsg(BaseModel):
#     """
#     事件参数:
#     + receiver_id:   收信人 UID
#     + receiver_type: 收信人类型，1: 私聊, 2: 应援团通知, 3: 应援团
#     + sender_uid:    发送人 UID
#     + talker_id:     对话人 UID
#     + msg_seqno:     事件 Seqno
#     + msg_type:      事件类型
#     + msg_key:       事件唯一编号
#     + timestamp:     事件时间戳
#     + content:       事件内容
#
#     事件类型:
#     + TEXT:           纯文字消息
#     + PICTURE:        图片消息
#     + WITHDRAW:       撤回消息
#     + GROUPS_PICTURE: 应援团图片，但似乎不常触发，一般使用 PICTURE 即可
#     + SHARE_VIDEO:    分享视频
#     + NOTICE:         系统通知
#     + PUSHED_VIDEO:   UP主推送的视频
#     + WELCOME:        新成员加入应援团欢迎
#
#     TEXT = "1"
#     PICTURE = "2"
#     WITHDRAW = "5"
#     GROUPS_PICTURE = "6"
#     SHARE_VIDEO = "7"
#     NOTICE = "10"
#     PUSHED_VIDEO = "11"
#     WELCOME = "306"
#     """
#
#     receiver_id: int
#     receiver_type: int
#     sender_uid: int
#     talker_id: int
#     msg_seqno: int
#     msg_type: int
#     msg_key: int
#     timestamp: int
#     content: Union[str, int, Picture, Video]

# class PrivateMsgSession(BaseModel):
#     """储存单个用户的私信会话信息"""
#
#     status: str  # 状态
#     text_event: Optional[PrivateMsg]  # 文本事件
#     video_event: Optional[PrivateMsg]  # 视频事件
