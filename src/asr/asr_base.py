import abc
import re
from typing import Optional

from injector import inject

from src.utils.models import Config


class ASR:
    """ASR基类，所有ASR子类都应该继承这个类"""

    @inject
    def __init__(self, config: Config):
        """记得使用@inject装饰器，否则无法注入config"""
        self.config = config

    def __new__(cls, *args, **kwargs):
        """将类名转换为alias"""
        instance = super(ASR, cls).__new__(cls)
        name = cls.__name__
        name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        name = re.sub("([a -z0-9])([A-Z])", r"\1_\2", name).lower()
        instance.alias = name
        return instance

    @abc.abstractmethod
    def prepare(self) -> None:
        """
        准备方法，例如加载模型
        会在该类被 **第一次** get时调用
        这个函数不应该有入参，所有参数都从self.config中获取
        """
        pass

    @abc.abstractmethod
    async def transcribe(self, audio_path: str) -> Optional[str]:
        """
        转写方法，需要实现
        该方法只要求传入音频路径，返回转写结果，对于其他配置参数需要从self.config中获取
        注意，这个方法中的转写部分不能阻塞，否则你要实现下方的_wait_transcribe方法，并在这里采用 **线程池** 方式调用
        None建议当且仅当在转写失败时返回，因为当接收方收到None时会请求切换ASR
        """
        pass

    def _wait_transcribe(self, text: str) -> Optional[str]:
        """
        阻塞转写方法，选择性实现
        """
        pass

    async def after_process(self, text: str) -> str:
        """
        后处理方法，例如将转写结果塞回llm，获得更高质量的字幕
        能别阻塞就别阻塞，你好我也好

        如果处理过程中出错应该返回原字幕
        """
        pass

    def __repr__(self):
        return self.__class__.__name__

    def __str__(self):
        return self.__class__.alias
