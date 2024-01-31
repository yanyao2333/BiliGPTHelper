import asyncio

from src.utils.logging import LOGGER

_LOGGER = LOGGER


class QueueManager:
    """队列管理器"""

    def __init__(self):
        _LOGGER.debug("初始化队列管理器")
        self.queues = {}

    def get_queue(self, queue_name: str):
        if queue_name not in self.queues:
            _LOGGER.debug(f"正在创建{queue_name}队列")
            self.queues[queue_name] = asyncio.Queue()
        return self.queues.get(queue_name)

    def safe_close_queue(self, queue_name: str, save_file_path: str):
        """
        安全关闭队列（会对队列中任务进行保存）
        :param queue_name: 队列名
        :param save_file_path: 保存位置
        :return:
        """
