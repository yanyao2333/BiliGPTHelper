import asyncio
import enum
import json
import os
import uuid

from bilibili_api.video import Video

from src.utils.logging import LOGGER
from src.utils.types import TaskStatus, TaskProcessStage, AtItems, TaskProcessEvent

_LOGGER = LOGGER.bind(name="task-status-record")


class TaskStatusRecorder:
    """视频状态记录器"""

    def __init__(self, file_path):
        self.file_path = file_path
        self.video_status = {}
        self.tasks = {}
        self.queue = {}
        self.load()

    def load(self):
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, "r", encoding="utf-8") as f:
                    if os.path.getsize(self.file_path) == 0:
                        self.video_status = {}
                    else:
                        self.video_status = json.load(f)
                        self.tasks = self.video_status.get("tasks", {})
                        self.queue = self.video_status.get("queue", {})
            else:
                self.video_status = {}
                self.save()
        except Exception as e:
            _LOGGER.error(f"读取视频状态记录文件失败，错误信息为{e}，恢复为初始文件")
            self.video_status = {}
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.video_status, f, ensure_ascii=False, indent=4)

    def save(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            self.video_status = {"tasks": self.tasks, "queue": self.queue}
            json.dump(self.video_status, f, ensure_ascii=False, indent=4)

    def get_record_by_stage(
        self,
        stage: TaskProcessStage,
        event: TaskProcessEvent = TaskProcessEvent.SUMMARIZE,
    ):
        """根据stage获取记录"""
        records = []
        for record in self.tasks.values():
            if record["stage"] == stage.value and record["event"] == event.value:
                records.append(record)
        return records

    def create_record(
        self,
        item: AtItems,
        stage: TaskProcessStage,
        event: TaskProcessEvent,
        gmt_create: int,
    ):
        """创建一条记录，返回一条uuid，可以根据uuid修改记录"""
        _uuid = str(uuid.uuid4())
        if isinstance(
                item.get("item")
                        .get("private_msg_event", {"video_event": {"content": "None"}})
                        .get("video_event", {})
                        .get("content", None),
                Video,
        ):
            item["item"]["private_msg_event"]["video_event"]["content"] = item["item"][
                "private_msg_event"
            ]["video_event"]["content"].get_bvid()
        record: TaskStatus = {
            "stage": stage.value,
            "data": item,
            "event": event.value,
            "gmt_create": gmt_create,
        }
        record["data"]["item"]["stage"] = stage.value
        record["data"]["item"]["event"] = event.value
        record["data"]["item"]["uuid"] = _uuid
        self.tasks[_uuid] = record
        self.save()
        return _uuid

    def update_record(self, _uuid: str, **kwargs) -> bool:
        """根据uuid更新记录"""
        record = self.tasks[_uuid]
        if not record:
            return False
        for key, _value in kwargs.items():
            if isinstance(_value, enum.Enum):
                _value = _value.value
            if key == "stage":
                record["data"]["item"]["stage"] = _value
                if _value == TaskProcessStage.END.value:
                    if record["data"]["item"].get("whisper_subtitle", None):
                        del record["data"]["item"]["whisper_subtitle"]  # 避免过多冗余信息
            record[key] = _value
        self.save()
        return True

    def save_queue(
        self,
        queue: asyncio.Queue,
        queue_name: str,
        event: TaskProcessEvent = TaskProcessEvent.SUMMARIZE,
    ):
        """保存队列"""
        queue_list = []
        while not queue.empty():
            item: AtItems = queue.get_nowait()
            item["item"]["stage"] = TaskProcessStage.IN_QUEUE.value
            item["item"]["event"] = event.value
            if isinstance(
                    item.get("item")
                            .get("private_msg_event", {"video_event": {"content": "None"}})
                            .get("video_event", {})
                            .get("content", None),
                    Video,
            ):
                item["item"]["private_msg_event"]["video_event"]["content"] = item["item"][
                    "private_msg_event"
                ]["video_event"]["content"].get_bvid()
            queue_list.append(item)
        self.queue[queue_name] = queue_list
        self.save()

    def load_queue(self, queue: asyncio.Queue, name: str):
        """加载队列"""
        if "queue" not in self.video_status or name not in self.video_status["queue"]:
            return
        for item in self.queue[name]:
            queue.put_nowait(item)

    def get_uuid_by_data(self, data: AtItems):
        """根据data获取uuid"""
        for _uuid, record in self.tasks.items():
            if record["data"] == data:
                return _uuid
        return None

    def delete_queue(self, name: str):
        """删除队列"""
        if "queue" in self.video_status and name in self.video_status["queue"]:
            del self.video_status["queue"][name]
            self.save()

    def get_data_by_uuid(self, _uuid: str) -> TaskStatus:
        """根据uuid获取data"""
        return self.tasks[_uuid]
