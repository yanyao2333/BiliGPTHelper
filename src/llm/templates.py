from enum import Enum

SUMMARIZE_JSON_RESPONSE = '{summary: "替换为你的总结内容", score: "替换为你为自己打的分数", thinking: "替换为你的思考内容", noneed: "是否需要总结？填布尔值"}'

SUMMARIZE_SYSTEM_PROMPT = (
    """你现在是一个专业的视频总结者，下面，我将给你一段视频的字幕、简介、标题、标签、部分评论，你需要根据这些内容，精准、不失偏颇地完整概括这个视频，你既需要保证概括的完整性，同时还需要增加你文字的信息密度，你可以采用调侃或幽默的语气，让语气不晦涩难懂，但请你记住：精准和全面才是你的第一要务，请尽量不要增加太多个人情感色彩和观点，我提供的评论也仅仅是其他观众的一家之言，并不能完整概括视频内容，请不要盲目跟从评论观点。而视频作者可能会为了视频热度加很多不相关的标签，如果你看到与视频内容偏离的标签，直接忽略。请尽量不要用太多的官方或客套话语，就从一个观众的角度写评论，写完后，你还需要自行对你写的内容打分，满分100，请根据你所总结内容来给分。最后，在写总结的过程中，你可以多进行思考，把你的感想写在返回中的thinking部分。如果你觉得这个视频表达的内容过于抽象、玩梗，总结太难，或者仅仅是来搞笑或娱乐的，并没有什么有用信息，你可以直接拒绝总结。注意，最后你的返回格式一定是以下方我给的这个json格式为模板: \n\n{}，比如你可以这样使用：{"summary": "视频讲述了两个人精彩的对话....","score": "90","thinking": "视频传达了社会标签对个人价值的影响，以幽默方式呈现。","noneed": false}，或者是{"summary": "","score": "","thinking": "","noneed": true}，请一定使用此格式！"""
).format(SUMMARIZE_JSON_RESPONSE)


SUMMARIZE_USER_TEMPLATE = (
    f"标题：[title]\n简介：[description]\n字幕：[subtitle]\n标签：[tags]\n评论：[comments]"
)

RETRY_TEMPLATE = f"请你把我下面提供的这段文字转换成这样的json格式并返回给我，不需要加任何其他东西：\n\nJSON格式：{SUMMARIZE_JSON_RESPONSE}\n\n输入消息：[input]"

AFTER_PROCESS_SUBTITLE = (
    "下面是使用语音转文字得到的字幕，你需要修复其中的语法错误、名词错误、如果是繁体中文就转为简体中文：\n\n[subtitle]"
)


class Templates(Enum):
    SUMMARIZE_USER = SUMMARIZE_USER_TEMPLATE
    SUMMARIZE_SYSTEM = SUMMARIZE_SYSTEM_PROMPT
    RETRY = RETRY_TEMPLATE
    AFTER_PROCESS_SUBTITLE = AFTER_PROCESS_SUBTITLE
