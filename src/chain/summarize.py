import asyncio
import json
import time
import traceback

import tenacity

from src.bilibili.bili_session import BiliSession
from src.chain.base_chain import BaseChain
from src.llm.gpt import Openai
from src.llm.templates import Templates
from src.utils.callback import chain_callback
from src.utils.logging import LOGGER
from src.utils.types import *

_LOGGER = LOGGER.bind(name="summarize-chain")


class SummarizeChain(BaseChain):
    """摘要处理链"""

    async def _precheck(self, at_items: AtItems, _uuid: str) -> bool:
        """检查是否满足处理条件"""
        if (
            at_items["item"]["type"] == "private_msg"
            and at_items["item"]["business_id"] == 114
        ):
            _LOGGER.debug(f"该消息是私信消息，继续处理")
            await BiliSession.quick_send(self.credential, at_items, "视频已开始处理，你先别急")
            return True
        elif (
            at_items["item"]["type"] != "reply" or at_items["item"]["business_id"] != 1
        ):
            _LOGGER.warning(f"该消息目前并不支持，跳过处理")
            self._set_err_end(_uuid, "该消息目前并不支持，跳过处理")
            return False
        if at_items["item"]["root_id"] != 0 or at_items["item"]["target_id"] != 0:
            _LOGGER.warning(f"该消息是楼中楼消息，暂时不受支持，跳过处理")  # TODO 楼中楼消息的处理
            self._set_err_end(_uuid, "该消息是楼中楼消息，暂时不受支持，跳过处理")
            return False
        return True

    async def _on_start(self):
        """在启动处理链时先处理一下之前没有处理完的视频"""
        _LOGGER.info("正在启动摘要处理链，开始将上次未处理完的视频加入队列")
        oncomplete_task = []
        oncomplete_task += self.task_status_recorder.get_record_by_stage(
            TaskProcessStage.PREPROCESS, TaskProcessEvent.SUMMARIZE
        )
        oncomplete_task += self.task_status_recorder.get_record_by_stage(
            TaskProcessStage.WAITING_LLM_RESPONSE, TaskProcessEvent.SUMMARIZE
        )
        oncomplete_task += self.task_status_recorder.get_record_by_stage(
            TaskProcessStage.WAITING_SEND, TaskProcessEvent.SUMMARIZE
        )
        oncomplete_task += self.task_status_recorder.get_record_by_stage(
            TaskProcessStage.WAITING_PUSH_TO_CACHE, TaskProcessEvent.SUMMARIZE
        )
        oncomplete_task += self.task_status_recorder.get_record_by_stage(
            TaskProcessStage.WAITING_RETRY, TaskProcessEvent.SUMMARIZE
        )
        for task in oncomplete_task:
            self.summarize_queue.put_nowait(task["data"])
        _LOGGER.info(f"之前未处理完的视频已经全部加入队列，共{len(oncomplete_task)}个")
        self.task_status_recorder.load_queue(self.summarize_queue, "summarize")
        _LOGGER.info(f"正在将上次在队列中的视频加入队列")
        self.task_status_recorder.delete_queue("summarize")

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(Exception),
        wait=tenacity.wait_fixed(10),
        before_sleep=chain_callback,
    )
    async def main(self):
        try:
            await self._on_start()
            while True:
                # if self.max_tokens is not None and self.now_tokens >= self.max_tokens:
                #     _LOGGER.warning(
                #         f"当前已使用token数{self.now_tokens}，超过最大token数{self.max_tokens}，摘要处理链停止运行"
                #     )
                #     raise asyncio.CancelledError

                # 从队列中获取摘要
                at_items: AtItems = await self.summarize_queue.get()
                if at_items.get("item").get("uuid", None) is not None:
                    _item_uuid = at_items["item"][
                        "uuid"
                    ]  # TODO 有uuid就一定有视频记录，但如果是继续处理的话，gmt_create时间就会不准确，要不要在读取时再修改一次？
                else:
                    _item_uuid = self._create_record(at_items)
                _LOGGER.info(f"摘要处理链获取到任务了：{at_items['item']['uri']}")
                # 检查是否满足处理条件
                if not await self._precheck(at_items, _item_uuid):
                    continue
                # 获取视频相关信息
                data = self.task_status_recorder.get_data_by_uuid(_item_uuid)
                resp = await self._get_video_info(at_items, _item_uuid)
                if resp is None:
                    continue
                (
                    video,
                    video_info,
                    format_video_name,
                    video_tags_string,
                    video_comments,
                ) = resp
                if (
                    data["stage"] == TaskProcessStage.PREPROCESS.value
                    or data["stage"] == TaskProcessStage.WAITING_LLM_RESPONSE.value
                ):
                    begin_time = time.perf_counter()
                    if await self._is_cached_video(at_items, _item_uuid, video_info):
                        continue
                    # 处理视频音频流和字幕
                    _LOGGER.debug(f"视频信息获取成功，正在获取视频音频流和字幕")
                    if at_items["item"].get("whisper_subtitle", None) is not None:
                        text = at_items["item"]["whisper_subtitle"]
                        _LOGGER.debug(f"使用whisper转写缓存，开始使用模板生成prompt")
                    else:
                        text = await self._smart_get_subtitle(
                            video, _item_uuid, format_video_name, at_items
                        )
                        if text is None:
                            continue
                    _LOGGER.info(
                        f"视频{format_video_name}音频流和字幕处理完成，共用时{time.perf_counter() - begin_time}s，开始调用LLM生成摘要"
                    )
                    self.task_status_recorder.update_record(
                        _item_uuid, stage=TaskProcessStage.WAITING_LLM_RESPONSE
                    )
                    prompt = Openai.use_template(
                        Templates.SUMMARIZE_USER,
                        Templates.SUMMARIZE_SYSTEM,
                        title=video_info["title"],
                        tags=video_tags_string,
                        comments=video_comments,
                        subtitle=text,
                        description=video_info["desc"],
                    )
                    _LOGGER.debug(f"prompt生成成功，开始调用llm")
                    # 调用openai的Completion API
                    llm = self.llm_router.get_one()
                    if llm is None:
                        _LOGGER.warning(f"没有可用的LLM，关闭系统")
                        self._set_err_end(_item_uuid, "没有可用的LLM，跳过处理")
                        self.stop_event.set()
                        continue
                    response = await llm.completion(prompt)
                    if response is None:
                        _LOGGER.warning(f"视频{format_video_name}摘要生成失败，请自行检查问题，跳过处理")
                        self._set_err_end(_item_uuid, "摘要生成失败，请自行检查问题，跳过处理")
                        self.llm_router.report_error(llm.alias)
                        continue
                    answer, tokens = response
                    self.now_tokens += tokens
                    _LOGGER.debug(f"llm输出内容为：{answer}")
                    _LOGGER.debug(f"调用llm成功，开始处理结果")
                    at_items["item"]["ai_response"] = answer
                    self.task_status_recorder.update_record(
                        _item_uuid, stage=TaskProcessStage.WAITING_SEND, data=at_items
                    )

                data = self.task_status_recorder.get_data_by_uuid(_item_uuid)
                if (
                    data["stage"] == TaskProcessStage.WAITING_SEND.value
                    or data["stage"] == TaskProcessStage.WAITING_RETRY.value
                ):
                    begin_time = time.perf_counter()
                    answer = at_items["item"]["ai_response"]
                    # obj, _type = await video.get_video_obj()
                    # 处理结果
                    if answer:
                        try:
                            if data["stage"] == TaskProcessStage.WAITING_RETRY.value:
                                raise Exception("触发重试")
                            if "false" in answer:
                                answer.replace(
                                    "false", "False"
                                )  # 解决一部分因为大小写问题导致的json解析失败
                            if "true" in answer:
                                answer.replace("true", "True")
                            resp = json.loads(answer)
                            if resp["noneed"] is True:
                                _LOGGER.warning(
                                    f"视频{format_video_name}被ai判定为不需要摘要，跳过处理"
                                )
                                await BiliSession.quick_send(
                                    self.credential,
                                    at_items,
                                    f"AI觉得你的视频不需要处理，换个更有意义的视频再试试看吧！",
                                )
                                # await BiliSession.quick_send(
                                #     self.credential, at_items, answer
                                # )
                                self._set_noneed_end(_item_uuid)
                                continue
                            else:
                                _LOGGER.info(
                                    f"ai返回内容解析正确，视频{format_video_name}摘要处理完成，共用时{time.perf_counter() - begin_time}s"
                                )
                                await self.finish(
                                    at_items, resp, video_info["bvid"], _item_uuid
                                )

                        except Exception as e:
                            _LOGGER.error(f"处理结果失败：{e}，大概是ai返回的格式不对，尝试修复")
                            traceback.print_tb(e.__traceback__)
                            self.task_status_recorder.update_record(
                                _item_uuid, stage=TaskProcessStage.WAITING_RETRY
                            )
                            await self.retry(
                                answer,
                                at_items,
                                format_video_name,
                                begin_time,
                                video_info,
                                _item_uuid,
                            )
        except asyncio.CancelledError:
            _LOGGER.info("收到关闭信号，摘要处理链关闭")

    async def retry(
        self, ai_answer, at_item, format_video_name, begin_time, video_info, _item_uuid
    ):
        """通过重试prompt让chatgpt重新构建json

        :param _item_uuid:
        :param ai_answer: ai返回的内容
        :param at_item: queue中的原始数据
        :param format_video_name: 格式化后的视频名称
        :param begin_time: 开始时间
        :param video_info: 视频信息
        :return: None
        """
        _LOGGER.debug(f"ai返回内容解析失败，正在尝试重试")
        prompt = Openai.use_template(Templates.RETRY, input=ai_answer)
        llm = self.llm_router.get_one()
        if llm is None:
            _LOGGER.warning(f"没有可用的LLM，关闭系统")
            self._set_err_end(_item_uuid, "没有可用的LLM，跳过处理")
            self.stop_event.set()
            return False
        response = await llm.completion(prompt)
        if response is None:
            _LOGGER.warning(f"视频{format_video_name}摘要生成失败，请自行检查问题，跳过处理")
            self._set_err_end(
                _item_uuid,
                f"视频{format_video_name}摘要生成失败，请自行检查问题，跳过处理",
            )
            self.llm_router.report_error(llm.alias)
            return False
        answer, tokens = response
        _LOGGER.debug(f"openai api输出内容为：{answer}")
        self.now_tokens += tokens
        if answer:
            try:
                resp = json.loads(answer)
                if resp["noneed"] is True:
                    _LOGGER.warning(f"视频{format_video_name}被ai判定为不需要摘要，跳过处理")
                    self._set_noneed_end(_item_uuid)
                    return False
                else:
                    _LOGGER.info(
                        f"ai返回内容解析正确，视频{format_video_name}摘要处理完成，共用时{time.perf_counter() - begin_time}s"
                    )
                    await self.finish(
                        at_item, resp, video_info["bvid"], _item_uuid, True
                    )
                    return True
            except Exception as e:
                _LOGGER.trace(f"处理结果失败：{e}，大概是ai返回的格式不对，拿你没辙了，跳过处理")
                traceback.print_tb(e.__traceback__)
                self._set_err_end(
                    _item_uuid,
                    "重试后处理结果失败，大概是ai返回的格式不对，跳过",
                )
                return False
