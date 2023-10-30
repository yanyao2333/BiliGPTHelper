import inspect
import os
import traceback
from typing import Optional

from injector import inject

from src.llm.llm_base import LLMBase
from src.models.config import Config
from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="LLM-Router")


class LLMRouter:
    """LLM路由器，用于加载所有LLM子类并进行合理路由"""

    @inject
    def __init__(self, config: Config):
        self.config = config
        self._llm_dict = {}
        self.max_err_times = 10  # TODO i know i know，硬编码很不优雅，但这种选项开放给用户似乎也没必要

    def load_from_dir(self, py_style_path: str = "src.llm"):
        """
        从一个文件夹中加载所有LLM子类

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
                    if (
                        inspect.isclass(attr)
                        and issubclass(attr, LLMBase)
                        and attr != LLMBase
                    ):
                        self.load(attr)

    def load(self, attr):
        """加载一个ASR子类"""
        try:
            _asr = attr(self.config)
            setattr(_asr.alias, _asr)
            _LOGGER.info(f"正在加载 {_asr.alias}")
            _config = self.config.model_dump()["LLMs"][_asr.alias]
            priority = _config["priority"]
            enabled = _config["enable"]
            if priority is None or enabled is None:
                raise ValueError
            # 设置属性
            self.llm_dict[_asr.alias] = {
                "priority": priority,
                "enabled": enabled,
                "prepared": False,
                "err_times": 0,
                "obj": self.get(_asr.alias),
            }
        except Exception as e:
            _LOGGER.error(f"加载 {str(attr)} 失败，错误信息为{e}")
            traceback.print_exc()
        else:
            _LOGGER.info(f"加载 {_asr.alias} 成功，优先级为{priority}，启用状态为{enabled}")
            _LOGGER.debug(f"当前已加载的LLM子类有 {self.llm_dict}")

    @property
    def llm_dict(self):
        """获取所有已加载的LLM子类"""
        return self._llm_dict

    def get(self, name):
        """获取一个已加载的LLM子类"""
        try:
            return getattr(self, name)
        except Exception as e:
            _LOGGER.error(f"获取LLM子类失败，错误信息为{e}", exc_info=True)
            return None

    @llm_dict.setter
    def llm_dict(self, value):
        self._llm_dict = value

    def order(self):
        """
        对ASR子类进行排序
        优先级高的排在前面，未启用的排在最后"""
        self.llm_dict = dict(
            sorted(
                self.llm_dict.items(),
                key=lambda item: (
                    not item[1].get("enabled", True),
                    item[1]["priority"],
                ),
                reverse=True,
            )
        )

    def get_one(self) -> Optional[LLMBase]:
        """根据优先级获取一个可用的LLM子类，如果所有都不可用则返回None"""
        self.order()
        for llm in self.llm_dict.values():
            if llm["enabled"]:
                if llm["err_times"] <= 10:
                    if not llm["prepared"]:
                        _LOGGER.info(f"正在初始化 {llm['obj'].alias}")
                        llm["obj"].prepare()
                        llm["prepared"] = True
                    return llm["obj"]
        return None

    def report_error(self, name: str):
        """报告一个LLM子类的错误"""
        for llm in self.llm_dict.values():
            if llm["obj"].alias == name:
                llm["err_times"] += 1
                if llm["err_times"] >= self.max_err_times:
                    llm["enabled"] = False
                break
        else:
            raise ValueError(f"LLM子类 {name} 不存在")
        _LOGGER.info(f"{name} 发生错误，已累计错误{llm['err_times']}次")
        _LOGGER.debug(f"当前已加载的LLM类有 {self.llm_dict}")
