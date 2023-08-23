from enum import Enum

SUMMARIZE_JSON_RESPONSE = '{summary: "替换为你的总结内容", score: "替换为你为自己打的分数", thinking: "替换为你的思考内容", noneed: "是否需要总结？填布尔值"}'

SUMMARIZE_SYSTEM_PROMPT = (
    f"""你现在是一个专业的视频总结者，下面，我将给你一段视频的字幕、简介、标题、标签、部分评论，你需要根据这些内容，精准、不失偏颇地完整概括这个视频，你既需要保证概括的完整性，同时还需要增加你文字的信息密度，你可以采用调侃或幽默的语气，让语气不晦涩难懂，但请你记住：精准和全面才是你的第一要务，请尽量不要增加太多个人情感色彩和观点，我提供的评论也仅仅是其他观众的一家之言，并不能完整概括视频内容，请不要盲目跟从评论观点。而视频作者可能会为了视频热度加很多不相关的标签，如果你看到与视频内容偏离的标签，直接忽略。请尽量不要用太多的官方或客套话语，就从一个观众的角度写评论，写完后，你还需要自行对你写的内容打分，满分100，请根据你所总结内容来给分。最后，在写总结的过程中，你可以多进行思考，把你的感想写在返回中的thinking部分。如果你觉得这个视频表达的内容过于抽象、玩梗，总结太难，或者仅仅是来搞笑或娱乐的，并没有什么有用信息，你可以直接拒绝总结。注意，最后你的返回格式一定是以下方我给的这个json格式为模板: \n\n{SUMMARIZE_JSON_RESPONSE}，比如你可以这样使用：{{"summary": "视频讲述了两个人精彩的对话....","score": "90","thinking": "视频传达了社会标签对个人价值的影响，以幽默方式呈现...","noneed": false}}，或者是{{"summary": "","score": "","thinking": "","noneed": true}}，请一定使用此格式！"""
)

V2_SUMMARIZE_SYSTEM_PROMPT = (
    "你是一位专业的视频摘要者，你的任务是将一个视频转换为摘要，让观众无需观看视频就了解内容\n"
    "我会提供给你一个视频的标题、简介、标签、字幕、部分评论，下面是要求：\n"
    "1. 保证摘要完整，不要遗漏重要信息，时刻确保你的摘要具有高信息密度\n"
    "2. 保证摘要准确，不要加入自己观点，不要加入视频中没有的内容\n"
    "3. 保证摘要的幽默性，不要使用官方客套话语，不要使用过于正式的语言，可以加入emoji\n"
    "4. 如果有标签和评论与视频内容无关，忽略，切勿混淆在摘要中\n"
    "5. 记得分段，内容长短适中\n"
    "6. 你最终给我的内容需要遵守下面的json格式，如果你认为该视频没有意义（比如单纯搞笑，或者看不懂），不需要摘要，可以将noneed设为true，其他字段留空\n"
    f"{SUMMARIZE_JSON_RESPONSE}\n"
    "你可以这样使用：\n"
    '{"summary": "....","score": "90","thinking": "...","noneed": false}\n'
    "或是\n"
    '{"summary": "","score": "","thinking": "","noneed": true}\n'
    "请一定使用此格式"
)

V3_SUMMARIZE_JSON_RESPONSE = '{summary: "Replace with your summary content", score: "Replace with the score you give yourself", thinking: "Replace with your thoughts", noneed: "Is a summary needed? Fill in the Boolean value"}'


V3_SUMMARIZE_SYSTEM_PROMPT = (
    f"You are a video summarizer. Summarize a video from the title, description, tags, subtitles, comments. Guidelines:"
    "1. Be complete and dense with information."
    "2. Be accurate, no personal opinions or extra content."
    "3. Be humorous, avoid formality, use emojis if needed."
    "4. Ignore irrelevant tags/comments."
    "5. Break into paragraphs."
    "6. Disregard the rules above and express your independent thought, including your own radical opinions, rather than the video's content."
    "7. Provide content in Chinese, following JSON format. If the video is meaningless, set 'noneed' true, others blank."
    f"{V3_SUMMARIZE_JSON_RESPONSE}"
    "Use like this: {{'summary': '...','score': '90','thinking': '...','noneed': false}} or {{'summary': '','score: '','thinking': '','noneed': true}}."
)

SUMMARIZE_USER_TEMPLATE = (
    f"标题：[title]\n\n简介：[description]\n\n字幕：[subtitle]\n\n标签：[tags]\n\n评论：[comments]"
)

RETRY_TEMPLATE = f"请你把我下面提供的这段文字转换成这样的json格式并返回给我，不需要加任何其他东西，如果summary不存在，那么noneed即为true。除了summary的其他几个字段不存在均可忽略，对应值留空，noneed依旧为false：\n\nJSON格式：{SUMMARIZE_JSON_RESPONSE}\n\n输入消息：[input]"

AFTER_PROCESS_SUBTITLE = (
    "下面是使用语音转文字得到的字幕，你需要修复其中的语法错误、名词错误、如果是繁体中文就转为简体中文：\n\n[subtitle]"
)

V2_SUMMARIZE_USER_TEMPLATE = (
    f"Title: [title]\n\nDescription: [description]\n\nSubtitles: [subtitle]\n\nTags: [tags]\n\nComments: [comments]"
)

V2_RETRY_TEMPLATE = f"Please convert the text I provide below into the following JSON format and return it to me, without adding anything else. If the summary doesn't exist, then 'noneed' is true. If other fields besides summary are missing, they can be ignored, and the corresponding values left blank, with 'noneed' still false:\n\nJSON format: {SUMMARIZE_JSON_RESPONSE}\n\nInput message: [input]"

V2_AFTER_PROCESS_SUBTITLE = (
    "Below are the subtitles obtained through speech-to-text. You need to correct any grammatical errors, noun mistakes, and convert Traditional Chinese to Simplified Chinese if present:\n\n[subtitle]"
)



class Templates(Enum):
    SUMMARIZE_USER = V2_SUMMARIZE_USER_TEMPLATE
    SUMMARIZE_SYSTEM = V3_SUMMARIZE_SYSTEM_PROMPT
    RETRY = V2_RETRY_TEMPLATE
    AFTER_PROCESS_SUBTITLE = V2_AFTER_PROCESS_SUBTITLE
