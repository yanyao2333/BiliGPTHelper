from injector import inject

from src.models.config import Config
from src.models.task import BiliGPTTask, Chains
from src.utils.logging import LOGGER
from src.utils.queue_manager import QueueManager

_LOGGER = LOGGER.bind(name="chain-router")


class ChainRouter:
    @inject
    def __init__(self, config: Config, queue_manager: QueueManager):
        self.config = config
        self.queue_manager = queue_manager
        self.summarize_queue = None
        self._get_queues()

    def _get_queues(self):
        self.summarize_queue = self.queue_manager.get_queue("summarize")

    async def dispatch_a_task(self, task: BiliGPTTask):
        content = task.source_extra_text
        _LOGGER.info(f"开始处理消息，原始消息内容为：{content}")
        summarize_keyword = self.config.chain_keywords.summarize_keywords
        match content:
            case content if any(keyword in content for keyword in summarize_keyword):
                keyword = next(keyword for keyword in summarize_keyword if keyword in content)
                _LOGGER.info(f"检测到关键字 {keyword} ，放入【总结】队列")
                task.chain = Chains.SUMMARIZE.value
                _LOGGER.debug(task)
                await self.summarize_queue.put(task)
                return
            case _:
                _LOGGER.debug("没有检测到关键字，跳过")
