import inspect
import os
from typing import Optional

from injector import inject

from src.asr.asr_base import ASR
from src.utils.logging import LOGGER
from src.utils.models import Config

_LOGGER = LOGGER.bind(name="ASR-Router")


class ASRouter:
    """ASR路由器，用于加载所有ASR子类并进行合理路由"""

    @inject
    def __init__(self, config: Config):
        self.config = config
        self.asr_list = {}
        self.max_err_times = 10  # TODO i know i know，硬编码很不优雅，但这种选项开放给用户似乎也没必要

    def load_from_dir(self, py_style_path: str = "src.asr"):
        """
        从一个文件夹中加载所有ASR子类

        :param py_style_path: 包导入风格的路径，以文件运行位置为基础路径
        :return: None
        """
        raw_path = "./" + py_style_path.replace(".", "/")
        for file_name in os.listdir(raw_path):
            if file_name.endswith(".py") and file_name != "__init__.py":
                module_name = file_name[:-3]
                module = __import__(
                    f"{py_style_path}.{module_name}", fromlist=[module_name]
                )
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if inspect.isclass(attr) and issubclass(attr, ASR) and attr != ASR:
                        self.load(attr)

    def load(self, attr):
        """加载一个ASR子类"""
        try:
            self.__setattr__(attr.alias, attr(self.config))
            _LOGGER.info(f"正在加载 {attr.alias}")
            priority = self.config.ASRs[attr.alias].priority
            enabled = self.config.ASRs[attr.alias].enable
            if priority or enabled is None:
                raise ValueError
            # 设置属性
            self.asr_list[attr.alias] = {
                "priority": priority,
                "enabled": enabled,
                "prepared": False,
                "err_times": 0,
                "obj": self.get(attr.alias),
            }
        except Exception as e:
            _LOGGER.trace(f"加载 {attr.alias} 失败，错误信息为{e}")
        else:
            _LOGGER.info(f"加载 {attr.alias} 成功，优先级为{priority}，启用状态为{enabled}")
            _LOGGER.debug(f"当前已加载的ASR子类有 {self.asr_list}")

    @property
    def asr_list(self):
        """获取所有已加载的ASR子类"""
        return self._asr_list

    def get(self, name):
        """获取一个已加载的ASR子类"""
        try:
            return getattr(self, name)
        except Exception as e:
            _LOGGER.error(f"获取ASR子类失败，错误信息为{e}", exc_info=True)
            return None

    @asr_list.setter
    def asr_list(self, value):
        self._asr_list = value

    def order(self):
        """
        对ASR子类进行排序
        优先级高的排在前面，未启用的排在最后"""
        self.asr_list = sorted(
            self.asr_list,
            key=lambda x: (not x.get("enable", True), x["priority"]),
            reverse=True,
        )

    def get_one(self) -> Optional[ASR]:
        """根据优先级获取一个可用的ASR子类，如果所有都不可用则返回None"""
        self.order()
        for asr in self.asr_list:
            if asr["enabled"]:
                if asr["err_times"] <= 10:
                    if not asr["prepared"]:
                        _LOGGER.info(f"正在初始化 {asr['obj'].alias}")
                        asr["obj"].prepare()
                        asr["prepared"] = True
                    return asr["obj"]
        return None

    def report_error(self, name: str):
        """报告一个ASR子类的错误"""
        for asr in self.asr_list:
            if asr["obj"].alias == name:
                asr["err_times"] += 1
                if asr["err_times"] >= self.max_err_times:
                    asr["enabled"] = False
                break
        else:
            raise ValueError(f"ASR子类 {name} 不存在")
        _LOGGER.info(f"{name} 发生错误，已累计错误{asr['err_times']}次")
        _LOGGER.debug(f"当前已加载的ASR子类有 {self.asr_list}")
