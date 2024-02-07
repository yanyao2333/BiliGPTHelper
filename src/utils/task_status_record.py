import enum
import json
from typing import Union

from src.models.task import BiliGPTTask, Chains, ProcessStages
from src.utils.exceptions import LoadJsonError
from src.utils.file_tools import load_file, save_file
from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="task-status-record")


class TaskStatusRecorder:
    """视频状态记录器"""

    def __init__(self, file_path):
        self.file_path = file_path
        self.video_records = {}
        self.load()

    def load(self):
        # if os.path.exists(self.file_path):
        #     with open(self.file_path, encoding="utf-8") as f:
        #         if os.path.getsize(self.file_path) == 0:
        #             self.video_records = {}
        #         else:
        #             self.video_records = json.load(f)
        # else:
        #     self.video_records = {}
        #     self.save()
        try:
            content = load_file(self.file_path)
            if content:
                self.video_records = json.loads(content)
            else:
                self.video_records = {}
                self.save()
        except Exception as e:
            raise LoadJsonError("在读取视频记录文件时出现问题！程序已停止运行，请自行检查问题所在") from e

    # except Exception as e:
    #     _LOGGER.error(f"读取视频状态记录文件失败，错误信息为{e}，恢复为初始文件")
    #     self.video_records = {}
    #     # with open(self.file_path, "w", encoding="utf-8") as f:
    #     #     json.dump(self.video_records, f, ensure_ascii=False, indent=4)
    #     save_file(json.dumps(self.video_records), self.file_path)

    def save(self):
        # with open(self.file_path, "w", encoding="utf-8") as f:
        #     json.dump(self.video_records, f, ensure_ascii=False, indent=4)
        save_file(json.dumps(self.video_records, ensure_ascii=False, indent=4), self.file_path)

    def get_record_by_stage(
        self,
        chain: Chains,
        stage: ProcessStages = None,
    ):
        """
        根据stage获取记录
        当stage为None时，返回所有记录
        """
        records = []
        if stage is None:
            for record in self.video_records.values():
                if record["chain"] == chain.value:
                    records.append(record)
            return records
        for record in self.video_records.values():
            if record["process_stage"] == stage.value and record["chain"] == chain.value:
                records.append(record)
        return records

    def create_record(self, item: BiliGPTTask):
        """创建一条记录，返回一条uuid，可以根据uuid修改记录"""
        self.video_records[str(item.uuid)] = item.model_dump(mode="json")
        # del self.video_records[item.uuid]["raw_task_data"]["video_event"]["content"]
        self.save()
        return item.uuid

    def update_record(self, _uuid: str, new_task_data: Union[BiliGPTTask, None], **kwargs) -> bool:
        """根据uuid更新记录"""
        # record: BiliGPTTask = self.video_records[_uuid]
        if new_task_data is not None:
            self.video_records[_uuid] = new_task_data.model_dump(mode="json")
            # del self.video_records[_uuid]["raw_task_data"]["video_event"]["content"]
        if self.video_records[_uuid] is None:
            return False
        for key, _value in kwargs.items():
            if isinstance(_value, enum.Enum):
                _value = _value.value
            if key == "process_stage":
                self.video_records[_uuid]["process_stage"] = _value
            if key in self.video_records[_uuid]:
                self.video_records[_uuid][key] = _value
            else:
                _LOGGER.warning(f"尝试更新不存在的字段：{key}，跳过")
        self.save()
        return True

    # def get_uuid_by_data(self, data: BiliGPTTask):
    #     """根据data获取uuid"""
    #     for _uuid, record in self.tasks.items():
    #         if record["data"] == data:
    #             return _uuid
    #     return None

    def get_data_by_uuid(self, _uuid: str) -> BiliGPTTask:
        """根据uuid获取data"""
        return self.video_records[_uuid]
