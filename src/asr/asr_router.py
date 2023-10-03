import inspect
import os

from src.asr.asr_base import ASR
from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="ASR-Router")


class ASRouter:
    """ASR路由器，用于加载所有ASR子类"""

    def load_from_dir(self, dir_name: str = "src.asr"):
        """从一个文件夹中加载所有ASR子类"""
        raw_path = "./" + dir_name.replace(".", "/")
        for file_name in os.listdir(raw_path):
            if file_name.endswith(".py") and file_name != "__init__.py":
                module_name = file_name[:-3]
                module = __import__(f"{dir_name}.{module_name}", fromlist=[module_name])
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if inspect.isclass(attr) and issubclass(attr, ASR) and attr != ASR:
                        _LOGGER.info(f"正在加载 {attr_name}")
                        self.load(attr)

    def load(self, attr):
        """加载一个ASR子类"""
        self.__setattr__(attr.__name__, attr())
        _LOGGER.info(f"加载 {attr.__name__} 成功")

    @property
    def asr_list(self):
        """获取所有已加载的ASR子类"""
        return [attr for attr in dir(self) if isinstance(getattr(self, attr), ASR)]

    def get(self, name):
        """获取一个已加载的ASR子类"""
        try:
            return getattr(self, name)
        except Exception as e:
            _LOGGER.error(f"获取ASR子类失败，错误信息为{e}", exc_info=True)
            return None
