"""管理视频处理后缓存"""
import json
import os
import traceback

from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="cache")



class Cache:
    def __init__(self, cache_path: str):
        self.cache_path = cache_path
        self.cache = {}
        self.load_cache()

    def load_cache(self):
        """加载缓存"""
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                self.cache = json.load(f)
        except Exception as e:
            _LOGGER.error(f"加载缓存失败：{e}，尝试删除缓存文件并重试")
            traceback.print_exc()
            self.cache = {}
            if os.path.exists(self.cache_path):
                os.remove(self.cache_path)
            _LOGGER.info("已删除缓存文件")
            self.save_cache()
            _LOGGER.info("已重新创建缓存文件")
            self.load_cache()

    def save_cache(self):
        """保存缓存"""
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=4)
        except Exception as e:
            _LOGGER.error(f"保存缓存失败：{e}")
            traceback.print_exc()

    def get_cache(self, key: str):
        """获取缓存"""
        return self.cache.get(key)

    def set_cache(self, key: str, value):
        """设置缓存"""
        self.cache[key] = value
        self.save_cache()

    def delete_cache(self, key: str):
        """删除缓存"""
        self.cache.pop(key)
        self.save_cache()

    def clear_cache(self):
        """清空缓存"""
        self.cache = {}
        self.save_cache()

    def get_all_cache(self):
        """获取所有缓存"""
        return self.cache
