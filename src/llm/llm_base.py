"""llm对接的基础类"""
import abc
import re
import traceback
from typing import Tuple

from src.llm.templates import Templates
from src.models.config import Config
from src.utils.logging import LOGGER
from src.utils.prompt_utils import build_openai_style_messages, parse_prompt

_LOGGER = LOGGER.bind(name="llm_base")


class LLMBase:
    """实现这个类，即可轻松对接其他的LLM模型"""

    def __init__(self, config: Config):
        self.config = config

    def __new__(cls, *args, **kwargs):
        """将类名转换为alias"""
        instance = super().__new__(cls)
        name = cls.__name__
        name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        name = re.sub("([a-z0-9])([A-Z])", r"\1_\2", name).lower()
        instance.alias = name
        return instance

    def prepare(self):
        """
        初始化方法，例如设置参数等
        会在该类被 **第一次** 使用时调用
        这个函数不应该有入参，所有参数都从self.config中获取
        """
        pass

    @abc.abstractmethod
    async def completion(self, prompt, **kwargs) -> Tuple[str, int] | None:
        """使用LLM生成文本（如果出错的话需要在这里自己捕捉错误并返回None）
        请确保整个过程为 **异步**，否则会阻塞整个程序
        :param prompt: 最终的输入文本，确保格式化过
        :param kwargs: 其他参数
        :return: 返回生成的文本和token总数 或 None
        """
        pass

    def _sync_completion(self, prompt, **kwargs) -> Tuple[str, int] | None:
        """如果你的调用方式为同步，请先在这里实现，然后在completion中使用线程池调用
        :param prompt: 最终的输入文本，确保格式化过
        :param kwargs: 其他参数
        :return: 返回生成的文本和token总数 或 None
        """
        pass

    @staticmethod
    def use_template(
        user_template_name: Templates,
        system_template_name: Templates = None,
        user_keyword="user",
        system_keyword="system",
        **kwargs,
    ) -> list | None:
        """使用模板生成最终prompt（最终格式可能需要根据llm所需格式不同修改，默认为openai的system、user格式）
        :param user_template_name: 用户模板名称
        :param system_template_name: 系统模板名称
        :param user_keyword: 用户关键词（这个和下面的system_keyword要根据每个llm不同的要求来填）
        :param system_keyword: 系统关键词
        :param kwargs: 模板参数
        :return: 返回生成的prompt 或 None
        """
        try:
            template_user = user_template_name.value
            template_system = (
                system_template_name.value if system_template_name else None
            )
            utemplate = parse_prompt(template_user, **kwargs)
            stemplate = (
                parse_prompt(template_system, **kwargs) if template_system else None
            )
            prompt = (
                build_openai_style_messages(
                    utemplate, stemplate, user_keyword, system_keyword
                )
                if stemplate
                else build_openai_style_messages(utemplate, user_keyword=user_keyword)
            )
            _LOGGER.info("使用模板成功")
            _LOGGER.debug(f"生成的prompt为：{prompt}")
            return prompt
        except Exception as e:
            _LOGGER.error(f"使用模板失败：{e}")
            traceback.print_exc()
            return None

    def __repr__(self):
        return self.alias

    def __str__(self):
        return self.__class__.__name__
