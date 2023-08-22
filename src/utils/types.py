from typing import TypedDict, List, Optional


class AtCursor(TypedDict):
    is_end: bool
    id: int
    time: int


class AiResponse(TypedDict):
    """AI回复"""

    summary: str  # 摘要
    score: str  # ai对自己生成内容的评分
    thinking: str  # 思考
    noneed: bool  # 是否需要摘要


class AtItem(TypedDict):
    type: str  # 基本都为reply
    business: str  # 基本都为评论
    business_id: int  # 基本都为1
    title: str  # 如果是一级回复，这里是视频标题，如果是二级回复，这里是一级回复的内容
    image: str  # 一级回复是视频封面，二级回复为空
    url: str  # 视频链接
    source_content: str  # 回复内容
    source_id: int  # 该评论的id，对应send_comment中的root（如果要回复的话）
    target_id: int  # 上一级评论id， 二级评论指向的就是root_id，三级评论指向的是二级评论的id
    root_id: int  # 暂时还没出现过
    native_url: str  # 评论链接，包含根评论id和父评论id
    at_details: List[dict]  # at的人的信息，常规的个人信息dict
    ai_response: Optional[AiResponse]  # AI回复的内容，需要等到处理完才能获取到


class AtItems(TypedDict):
    id: int
    user: dict  # at发送者的个人信息，常规的个人信息dict
    item: AtItem
    at_time: int


class AtAPIResponse(TypedDict):
    """API返回的at消息"""

    cursor: AtCursor
    items: List[AtItems]
