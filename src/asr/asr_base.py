import abc
import re
from typing import Optional

from src.llm.llm_router import LLMRouter
from src.utils.models import Config


class ASRBase:
    """ASR基类，所有ASR子类都应该继承这个类"""

    def __init__(self, config: Config, llm_router: LLMRouter):
        self.config = config
        self.llm_router = llm_router

    def __new__(cls, *args, **kwargs):
        """将类名转换为alias"""
        instance = super().__new__(cls)
        name = cls.__name__
        name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        name = re.sub("([a-z0-9])([A-Z])", r"\1_\2", name).lower()
        instance.alias = name
        return instance

    @abc.abstractmethod
    def prepare(self) -> None:
        """
        准备方法，例如加载模型
        会在该类被 **第一次** 使用时调用
        这个函数不应该有入参，所有参数都从self.config中获取
        """
        pass

    @abc.abstractmethod
    async def transcribe(self, audio_path: str, **kwargs) -> Optional[str]:
        """
        转写方法
        该方法最好只传入音频路径，返回转写结果，对于其他配置参数需要从self.config中获取
        注意，这个方法中的转写部分不能阻塞，否则你要实现下方的_wait_transcribe方法，并在这里采用 **线程池** 方式调用
        None建议当且仅当在转写失败时返回，因为当接收方收到None时会报告错误，当错误计数达到一定值时会停止使用该ASR
        """
        pass

    def _sync_transcribe(self, audio_path: str, **kwargs) -> Optional[str]:
        """
        阻塞转写方法，选择性实现
        """
        pass

    async def after_process(self, text: str, **kwargs) -> str:
        """
        后处理方法，例如将转写结果塞回llm，获得更高质量的字幕
        直接通过self.llm_router调用llm
        记得代码逻辑一定要是异步

        如果处理过程中出错应该返回原字幕
        """
        pass

    def __repr__(self):
        return self.alias

    def __str__(self):
        return self.__class__.__name__
