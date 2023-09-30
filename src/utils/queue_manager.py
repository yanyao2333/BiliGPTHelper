import asyncio

from src.utils.logging import LOGGER

_LOGGER = LOGGER


class QueueManager:
    """队列管理器"""

    def __init__(self):
        self.queues = {}

    def get_queue(self, queue_name: str):
        if queue_name not in self.queues:
            self.queues[queue_name] = asyncio.Queue()
        return self.queues.get(queue_name)
