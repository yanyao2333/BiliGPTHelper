def parse_prompt(prompt_template, **kwargs):
    """解析填充prompt"""
    for key, value in kwargs.items():
        prompt_template = prompt_template.replace(f"[{key}]", str(value))
    return prompt_template


def build_openai_style_messages(user_msg, system_msg=None, user_keyword="user", system_keyword="system"):
    """构建消息
    :param user_msg: 用户消息
    :param system_msg: 系统消息
    :param user_keyword: 用户关键词（这个和下面的system_keyword要根据每个llm不同的要求来填）
    :param system_keyword: 系统关键词
    :return: 消息列表
    """
    messages = []
    if system_msg:
        messages.append({"role": system_keyword, "content": system_msg})
    messages.append({"role": user_keyword, "content": user_msg})
    return messages
