import json

from src.utils.exceptions import LoadJsonError
from src.utils.file_tools import read_file, save_file
from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="video_cache")


def load_cache(file_path):
    try:
        content = read_file(file_path)
        if content:
            cache = json.loads(content)
            return cache
        else:
            save_file(json.dumps({}, ensure_ascii=False, indent=4), file_path)
    except Exception as e:
        raise LoadJsonError("在读取缓存文件时出现问题！程序已停止运行，请自行检查问题所在") from e


def set_cache(file_path, cache, data: dict, key: str):
    if key not in cache:
        cache[key] = {}
    cache[key] = data
    save_file(json.dumps(cache, ensure_ascii=False, indent=4), file_path)


def get_up_file(file_path):
    with open(file_path, encoding="utf-8") as f:
        up_list = json.loads(f.read())
    return up_list["all_area"]
