import asyncio
import json
import traceback
from copy import deepcopy

from src.models.task import BiliGPTTask
from src.utils.file_tools import load_file, save_file
from src.utils.logging import LOGGER

_LOGGER = LOGGER


class QueueManager:
    """队列管理器"""

    def __init__(self):
        _LOGGER.debug("初始化队列管理器")
        self.queues = {}
        self.saved_queue = {}

    def get_queue(self, queue_name: str) -> asyncio.Queue:
        if queue_name not in self.queues:
            _LOGGER.debug(f"正在创建{queue_name}队列")
            self.queues[queue_name] = asyncio.Queue()
        return self.queues.get(queue_name)

    def _save(self, file_path: str):
        content = json.dumps(self.saved_queue, ensure_ascii=False, indent=4)
        save_file(content, file_path)

    def _load(self, file_path: str):
        try:
            content = load_file(file_path)
            if not content:
                self.saved_queue = json.loads(content)
            else:
                self.saved_queue = {}
                self._save(file_path)
        except Exception:
            _LOGGER.error("在读取已保存的队列文件中出现问题！暂时跳过恢复，但不影响使用，请自行检查！")
            traceback.print_exc()
            self.saved_queue = {}

    def safe_close_queue(self, queue_name: str, saved_json_path: str):
        """
        安全关闭队列（会对队列中任务进行保存）
        :param queue_name: 队列名
        :param saved_json_path: 保存位置
        :return:
        """
        queue_list = []
        queue = self.get_queue(queue_name)
        while not queue.empty():
            item: BiliGPTTask = queue.get_nowait()
            queue_list.append(item)
        _LOGGER.debug(f"共保存了{len(queue_list)}条数据！")
        self.saved_queue[queue_name] = queue_list
        self._save(saved_json_path)

    def safe_close_all_queues(self, saved_json_path: str):
        """
        保存所有的队列(我建议使用这个)
        :param saved_json_path:
        :return:
        """
        for queue in list(self.saved_queue.keys()):
            _LOGGER.debug(f"保存{queue}队列的任务")
            self.safe_close_queue(queue, saved_json_path)

    def recover_queue(self, saved_json_path: str):
        """
        恢复保存在文件中的任务信息
        :param saved_json_path:
        :return:
        """
        self._load(saved_json_path)
        _queue_dict = deepcopy(self.saved_queue)
        for queue_name in list(self.saved_queue.keys()):
            _LOGGER.debug(f"开始恢复{queue_name}")
            queue = self.get_queue(queue_name)
            for task in self.saved_queue[queue_name]:
                queue.put_nowait(task)
            del _queue_dict[queue_name]
        self.saved_queue = _queue_dict
        self._save(saved_json_path)
