import asyncio
import json
import os

from src.utils.logging import LOGGER
from src.utils.types import AtItems

_LOGGER = LOGGER


class QueueManager:
    """队列管理器"""

    def __init__(self):
        self.queues = {
            "summarize": asyncio.Queue(),
            "evaluate": asyncio.Queue(),
            "reply": asyncio.Queue(),
            "private": asyncio.Queue(),
        }

    def get_queue(self, queue_name: str):
        return self.queues.get(queue_name)

    @staticmethod
    async def save_queue(queue: asyncio.Queue, file_path: str):
        """保存队列到文件"""
        items = []
        while not queue.empty():
            items.append(await queue.get())
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(items, ensure_ascii=False, indent=4))

    @staticmethod
    async def load_queue(queue: asyncio.Queue, file_path: str):
        """从文件加载队列"""
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                items = json.loads(f.read())
            for item in items:
                await queue.put(item)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump([], f)

    @staticmethod
    async def save_single_item_to_file(file_path: str, item: AtItems):
        """保存单个item到文件（第一项执行）"""
        with open(file_path, "w", encoding="utf-8") as f:
            if f.read() == "":
                f.write(json.dumps([item], ensure_ascii=False, indent=4))
            else:
                items = json.loads(f.read())
                items.insert(0, item)
                f.write(json.dumps(items, ensure_ascii=False, indent=4))
