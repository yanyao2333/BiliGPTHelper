import traceback
from typing import Tuple

import openai

from src.llm.base import LLMBase
from src.llm.templates import Templates
from src.utils.logging import LOGGER
from src.utils.parse_prompt import parse_prompt, build_messages

_LOGGER = LOGGER.bind(name="openai_gpt")


class OpenAIGPTClient(LLMBase):
    def __init__(self, api_key, endpoint="https://api.openai.com/v1"):
        self.api_key = api_key
        self.endpoint = endpoint
        self.openai = openai
        self.set_openai()

    def set_openai(self):
        self.openai.api_base = self.endpoint
        self.openai.api_key = self.api_key

    def get_openai(self):
        return self.openai

    def completion(
        self, prompt, model="gpt-3.5-turbo", **kwargs
    ) -> Tuple[str, int] | None:
        """调用openai的Completion API
        :param model: 模型名称
        :param prompt: 输入的文本（请确保格式化为openai的prompt格式）
        :param kwargs: 其他参数
        :return: 返回生成的文本和token总数 或 None
        """
        try:
            self.set_openai()
            resp = self.openai.ChatCompletion.create(
                model=model, messages=prompt, **kwargs
            )
            _LOGGER.debug(f"调用openai的Completion API成功，API返回结果为：{resp}")
            _LOGGER.info(
                f"调用openai的Completion API成功，本次调用中，prompt+response的长度为{resp['usage']['total_tokens']}"
            )
            return (
                resp["choices"][0]["message"]["content"],
                resp["usage"]["total_tokens"],
            )
        except Exception as e:
            _LOGGER.trace(f"调用openai的Completion API失败：{e}")
            return None

    @staticmethod
    def use_template(
        template_user_name: Templates, template_system_name: Templates = None, **kwargs
    ) -> list | None:
        """使用模板生成最终prompt
        :param template_user_name: 用户模板名称
        :param template_system_name: 系统模板名称
        :param kwargs: 模板参数
        :return: 返回生成的prompt 或 None
        """
        try:
            template_user = template_user_name.value
            template_system = template_system_name.value if template_system_name else None
            utemplate = parse_prompt(template_user, **kwargs)
            stemplate = (
                parse_prompt(template_system, **kwargs) if template_system else None
            )
            prompt = (
                build_messages(utemplate, stemplate)
                if stemplate
                else build_messages(utemplate)
            )
            _LOGGER.info(f"使用模板成功，生成的prompt为：{prompt}")
            return prompt
        except Exception as e:
            _LOGGER.error(f"使用模板失败：{e}")
            traceback.print_exc()
            return None
