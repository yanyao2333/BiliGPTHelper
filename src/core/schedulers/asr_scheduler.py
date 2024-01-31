import inspect
import os
import traceback
from typing import Optional

from injector import inject

from src.asr.asr_base import ASRBase
from src.core.schedulers.llm_scheduler import LLMRouter
from src.models.config import Config
from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="ASR-Router")


class ASRouter:
    """ASR路由器，用于加载所有ASR子类并进行合理路由"""

    @inject
    def __init__(self, config: Config, llm_router: LLMRouter):
        self.config = config
        self._asr_dict = {}
        self.llm_router = llm_router
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
                    if (
                        inspect.isclass(attr)
                        and issubclass(attr, ASRBase)
                        and attr != ASRBase
                    ):
                        self.load(attr)

    def load(self, attr):
        """加载一个ASR子类"""
        try:
            _asr = attr(self.config, self.llm_router)
            setattr(self, _asr.alias, _asr)
            _LOGGER.info(f"正在加载 {_asr.alias}")
            _config = self.config.model_dump()["ASRs"][_asr.alias]
            priority = _config["priority"]
            enabled = _config["enable"]
            if priority is None or enabled is None:
                raise ValueError
            # 设置属性
            self.asr_dict[_asr.alias] = {
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
            _LOGGER.debug(f"当前已加载的ASR子类有 {self.asr_dict}")

    @property
    def asr_dict(self):
        """获取所有已加载的ASR子类"""
        return self._asr_dict

    def get(self, name):
        """获取一个已加载的ASR子类"""
        try:
            return getattr(self, name)
        except Exception as e:
            _LOGGER.error(f"获取ASR子类失败，错误信息为{e}", exc_info=True)
            return None

    @asr_dict.setter
    def asr_dict(self, value):
        self._asr_dict = value

    def order(self):
        """
        对ASR子类进行排序
        优先级高的排在前面，未启用的排在最后"""
        self.asr_dict = dict(
            sorted(
                self.asr_dict.items(),
                key=lambda item: (
                    not item[1].get("enabled", True),
                    item[1]["priority"],
                ),
                reverse=True,
            )
        )

    def get_one(self) -> Optional[ASRBase]:
        """根据优先级获取一个可用的ASR子类，如果所有都不可用则返回None"""
        self.order()
        for asr in self.asr_dict.values():
            if asr["enabled"] and asr["err_times"] <= 10:
                if not asr["prepared"]:
                    _LOGGER.info(f"正在初始化 {asr['obj'].alias}")
                    asr["obj"].prepare()
                    asr["prepared"] = True
                return asr["obj"]
        LOGGER.error("没有可用的ASR子类")
        return None

    def report_error(self, name: str):
        """报告一个ASR子类的错误"""
        for asr in self.asr_dict.values():
            if asr["obj"].alias == name:
                asr["err_times"] += 1
                if asr["err_times"] >= self.max_err_times:
                    asr["enabled"] = False
                break
        else:
            raise ValueError(f"ASR子类 {name} 不存在")
        _LOGGER.info(f"{name} 发生错误，已累计错误{asr['err_times']}次")
        _LOGGER.debug(f"当前已加载的ASR子类有 {self.asr_dict}")
