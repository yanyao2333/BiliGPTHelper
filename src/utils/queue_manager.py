import asyncio

from src.utils.logging import LOGGER

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
