"""llm对接的基础类"""
import abc
from typing import Tuple

from src.llm.templates import Templates
from src.utils.parse_prompt import parse_prompt, build_messages
from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="llm_base")


class LLMBase:
    """实现这个类，即可轻松对接其他的LLM模型"""

    @abc.abstractmethod
    def completion(self, prompt, **kwargs) -> Tuple[str, int] | None:
        """使用LLM生成文本（如果出错的话需要在这里自己捕捉错误并返回None）
        :param prompt: 最终的输入文本，确保格式化过
        :param kwargs: 其他参数
        :return: 返回生成的文本和token总数 或 None
        """
        pass

    @staticmethod
    @abc.abstractmethod
    def use_template(template_user_name: Templates, template_system_name: Templates, **kwargs) -> list | None:
        """使用模板生成最终prompt（可能需要根据llm需求的prompt格式不同修改）
        :param template_user_name: 用户模板名称
        :param template_system_name: 系统模板名称
        :param kwargs: 模板参数
        :return: 返回生成的prompt 或 None
        """
        try:
            template_user = template_user_name.value
            template_system = template_system_name.value
            utemplate = parse_prompt(template_user, **kwargs)
            stemplate = parse_prompt(template_system, **kwargs)
            prompt = build_messages(utemplate, stemplate)
            _LOGGER.info(f"使用模板成功，生成的prompt为：{prompt}")
            return prompt
        except Exception as e:
            _LOGGER.trace(f"使用模板失败：{e}")
            return None
