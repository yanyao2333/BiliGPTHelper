import os
import traceback

from src.utils.logging import LOGGER

_LOGGER = LOGGER


def read_file(file_path: str, mode: str = "r", encoding: str = "utf-8"):
    """
    读取一个文件，如果不存在就创建这个文件及其所有中间路径
    :param encoding: utf-8
    :param mode: 读取的模式（默认为只读）
    :param file_path:
    :return: 文件内容
    """
    dir_path = os.path.dirname(file_path)
    try:
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
        with open(file_path, mode, encoding=encoding) as file:
            return file.read()
    except FileNotFoundError:
        with open(file_path, "w", encoding=encoding):
            pass
    except Exception:
        _LOGGER.error("在读取文件时发生意料外的问题，返回空值")
        traceback.print_exc()
        return ""
    with open(file_path, mode, encoding=encoding) as f_r:
        return f_r.read()


def save_file(content: str, file_path: str, mode: str = "w", encoding: str = "utf-8") -> bool:
    """
    保存一个文件，如果不存在就创建这个文件及其所有中间路径
    :param content:
    :param file_path:
    :param mode: 默认为w
    :param encoding: utf8
    :return: bool
    """
    dir_path = os.path.dirname(file_path)
    try:
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
        with open(file_path, mode, encoding=encoding) as file:
            file.write(content)
            return True
    except Exception:
        _LOGGER.error("在读取文件时发生意料外的问题，返回空值")
        traceback.print_exc()
        return False
