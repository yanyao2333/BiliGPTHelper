import copy
import json
import shutil
import traceback

from src.utils.file_tools import read_file, save_file
from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="safe-update")


def merge_cache_to_new_version(cache_file_path: str) -> bool:
    """迁移老缓存文件到新版本格式"""
    content = read_file(cache_file_path)
    try:
        content_dict: dict = json.loads(content)
        if content_dict:
            if content_dict.get("summarize") is None and content_dict.get("ask_ai") is None:
                # 判断cache文件的内部结构，是否存在summarize或ask_ai键，全都不存在就是老版缓存，要转换
                _LOGGER.warning("缓存似乎是旧版的，尝试转换为新格式")
                _LOGGER.debug(f"备份老版缓存到{cache_file_path}.bak")
                shutil.copy(cache_file_path, cache_file_path + ".bak")
                new_summarize_dict = copy.deepcopy(content_dict)
                new_content_dict = {
                    "summarize": new_summarize_dict,
                    "ask_ai": {},
                }  # 老版本缓存只存在于只有summarize处理链的时代，直接这样转换
                save_file(
                    json.dumps(new_content_dict, ensure_ascii=False, indent=4),
                    cache_file_path,
                )
                _LOGGER.info("转换缓存完成！")
                return True
            return True
        return True
    except Exception:
        traceback.print_exc()
        _LOGGER.error("在尝试转换缓存文件时出现问题！请自行查看！")
        return False
