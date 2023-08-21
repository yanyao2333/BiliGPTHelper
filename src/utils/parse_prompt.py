def parse_prompt(prompt_template, **kwargs):
    """解析填充prompt"""
    for key, value in kwargs.items():
        prompt_template = prompt_template.replace(f"[{key}]", str(value))
    return prompt_template


def build_messages(user_msg, system_msg=None):
    """构建消息
    :param user_msg: 用户消息
    :param system_msg: 系统消息
    :return: 消息列表
    """
    messages = []
    if system_msg:
        messages.append({"role": "system", "content": system_msg})
    messages.append({"role": "user", "content": user_msg})
    return messages
