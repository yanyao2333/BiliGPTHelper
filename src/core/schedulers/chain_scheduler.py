import injector

from src.chain.summarize import Summarize
from src.models.config import Config
from src.utils.queue_manager import QueueManager


class ChainScheduler:
    """处理链调度器"""

    @injector.inject
    def __init__(self, config: Config, queue_manager: QueueManager):
        self.config = config
        self.queue_manager = queue_manager

    @property
    def chains(self):
        """别问我为什么这样实现，问就是懒得改了"""
        return {Summarize: "summarize"}
