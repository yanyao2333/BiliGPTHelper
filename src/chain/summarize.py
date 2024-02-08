import asyncio
import json
import time
import traceback

import tenacity

from src.bilibili.bili_session import BiliSession
from src.chain.base_chain import BaseChain
from src.llm.templates import Templates
from src.models.task import BiliGPTTask, Chains, ProcessStages, SummarizeAiResponse
from src.utils.callback import chain_callback
from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="summarize-chain")


class Summarize(BaseChain):
    """摘要处理链"""

    async def _precheck(self, task: BiliGPTTask) -> bool:
        """检查是否满足处理条件"""
        match task.source_type:
            case "bili_private":
                _LOGGER.debug("该消息是私信消息，继续处理")
                await BiliSession.quick_send(self.credential, task, "视频已开始处理，你先别急")
                return True
            case "bili_comment":
                _LOGGER.debug("该消息是评论消息，继续处理")
                return True
            case "api":
                _LOGGER.debug("该消息是api消息，继续处理")
                return True
        # if task["item"]["type"] != "reply" or task["item"]["business_id"] != 1:
        #     _LOGGER.warning(f"该消息目前并不支持，跳过处理")
        #     self._set_err_end(_uuid, "该消息目前并不支持，跳过处理")
        #     return False
        # if task["item"]["root_id"] != 0 or task["item"]["target_id"] != 0:
        #     _LOGGER.warning(f"该消息是楼中楼消息，暂时不受支持，跳过处理")  # TODO 楼中楼消息的处理
        #     self._set_err_end(_uuid, "该消息是楼中楼消息，暂时不受支持，跳过处理")
        #     return False
        return False

    async def _on_start(self):
        """在启动处理链时先处理一下之前没有处理完的视频"""
        _LOGGER.info("正在启动摘要处理链，开始将上次未处理完的视频加入队列")
        uncomplete_task = []
        uncomplete_task += self.task_status_recorder.get_record_by_stage(
            chain=Chains.SUMMARIZE
        )  # 有坑，这里会把之前运行过的也重新加回来，不过我下面用判断简单补了一手，叫我天才！
        for task in uncomplete_task:
            if task["process_stage"] != ProcessStages.END.value:
                try:
                    _LOGGER.debug(f"恢复uuid: {task['uuid']} 的任务")
                    self.summarize_queue.put_nowait(BiliGPTTask.model_validate(task))
                except Exception:
                    traceback.print_exc()
                    # TODO 这里除了打印日志，是不是还应该记录在视频状态中？
                    _LOGGER.error(f"在恢复uuid: {task['uuid']} 时出现错误！跳过恢复")
        # _LOGGER.info(f"之前未处理完的视频已经全部加入队列，共{len(uncomplete_task)}个")
        # self.queue_manager.(self.summarize_queue, "summarize")
        # _LOGGER.info("正在将上次在队列中的视频加入队列")
        # self.task_status_recorder.delete_queue("summarize")

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
                task: BiliGPTTask = await self.summarize_queue.get()
                _item_uuid = task.uuid
                self._create_record(task)
                _LOGGER.info(f"summarize处理链获取到任务了：{task.uuid}")
                # 检查是否满足处理条件
                if task.process_stage == ProcessStages.END:
                    _LOGGER.info(f"任务{task.uuid}已经结束，获取下一个")
                    continue
                if not await self._precheck(task):
                    continue
                # 获取视频相关信息
                # data = self.task_status_recorder.get_data_by_uuid(_item_uuid)
                resp = await self._get_video_info(task)
                if resp is None:
                    continue
                (
                    video,
                    video_info,
                    format_video_name,
                    video_tags_string,
                    video_comments,
                ) = resp
                if task.process_stage in (
                    ProcessStages.PREPROCESS,
                    ProcessStages.WAITING_LLM_RESPONSE,
                ):
                    begin_time = time.perf_counter()
                    if await self._is_cached_video(task, _item_uuid, video_info):
                        continue
                    # 处理视频音频流和字幕
                    _LOGGER.debug("视频信息获取成功，正在获取视频音频流和字幕")
                    if task.subtitle is not None:
                        text = task.subtitle
                        _LOGGER.debug("使用字幕缓存，开始使用模板生成prompt")
                    else:
                        text = await self._smart_get_subtitle(video, _item_uuid, format_video_name, task)
                        if text is None:
                            continue
                        task.subtitle = text
                    _LOGGER.info(
                        f"视频{format_video_name}音频流和字幕处理完成，共用时{time.perf_counter() - begin_time}s，开始调用LLM生成摘要"
                    )
                    self.task_status_recorder.update_record(
                        _item_uuid, new_task_data=task, process_stage=ProcessStages.WAITING_LLM_RESPONSE
                    )
                    llm = self.llm_router.get_one()
                    if llm is None:
                        _LOGGER.warning("没有可用的LLM，关闭系统")
                        self._set_err_end(_item_uuid, "没有可用的LLM，被迫结束处理")
                        self.stop_event.set()
                        continue
                    prompt = llm.use_template(
                        Templates.SUMMARIZE_USER,
                        Templates.SUMMARIZE_SYSTEM,
                        title=video_info["title"],
                        tags=video_tags_string,
                        comments=video_comments,
                        subtitle=text,
                        description=video_info["desc"],
                    )
                    _LOGGER.debug("prompt生成成功，开始调用llm")
                    # 调用openai的Completion API
                    response = await llm.completion(prompt)
                    if response is None:
                        _LOGGER.warning(f"任务{task.uuid}：ai未返回任何内容，请自行检查问题，跳过处理")
                        self._set_err_end(_item_uuid, "ai未返回任何内容，请自行检查问题，跳过处理")
                        self.llm_router.report_error(llm.alias)
                        continue
                    answer, tokens = response
                    self.now_tokens += tokens
                    _LOGGER.debug(f"llm输出内容为：{answer}")
                    _LOGGER.debug("调用llm成功，开始处理结果")
                    task.process_result = answer
                    task.process_stage = ProcessStages.WAITING_SEND
                    self.task_status_recorder.update_record(_item_uuid, task)
                if task.process_stage in (
                    ProcessStages.WAITING_SEND,
                    ProcessStages.WAITING_RETRY,
                ):
                    begin_time = time.perf_counter()
                    answer = task.process_result
                    # obj, _type = await video.get_video_obj()
                    # 处理结果
                    if answer:
                        try:
                            if task.process_stage == ProcessStages.WAITING_RETRY:
                                raise Exception("触发重试")
                            if "false" in answer:
                                answer = answer.replace("false", "False")  # 解决一部分因为大小写问题导致的json解析失败
                            if "true" in answer:
                                answer = answer.replace("true", "True")
                            resp = json.loads(answer)
                            task.process_result = SummarizeAiResponse.model_validate(resp)
                            if task.process_result.if_no_need_summary is True:
                                _LOGGER.warning(f"视频{format_video_name}被ai判定为不需要摘要，跳过处理")
                                await BiliSession.quick_send(
                                    self.credential,
                                    task,
                                    "AI觉得你的视频不需要处理，换个更有意义的视频再试试看吧！",
                                )
                                # await BiliSession.quick_send(
                                #     self.credential, task, answer
                                # )
                                self._set_noneed_end(_item_uuid)
                                continue
                            _LOGGER.info(
                                f"ai返回内容解析正确，视频{format_video_name}摘要处理完成，共用时{time.perf_counter() - begin_time}s"
                            )
                            await self.finish(task)

                        except Exception as e:
                            _LOGGER.error(f"处理结果失败：{e}，大概是ai返回的格式不对，尝试修复")
                            traceback.print_tb(e.__traceback__)
                            self.task_status_recorder.update_record(
                                _item_uuid, new_task_data=task, process_stage=ProcessStages.WAITING_RETRY
                            )
                            await self.retry(
                                answer,
                                task,
                                format_video_name,
                                begin_time,
                                video_info,
                            )
        except asyncio.CancelledError:
            _LOGGER.info("收到关闭信号，摘要处理链关闭")

    async def retry(self, ai_answer, task: BiliGPTTask, format_video_name, begin_time, video_info):
        """通过重试prompt让chatgpt重新构建json

        :param ai_answer: ai返回的内容
        :param task: queue中的原始数据
        :param format_video_name: 格式化后的视频名称
        :param begin_time: 开始时间
        :param video_info: 视频信息
        :return: None
        """
        _LOGGER.debug(f"任务{task.uuid}：ai返回内容解析失败，正在尝试重试")
        task.gmt_retry_start = int(time.time())
        llm = self.llm_router.get_one()
        if llm is None:
            _LOGGER.warning("没有可用的LLM，关闭系统")
            self._set_err_end(task.uuid, "没有可用的LLM，跳过处理")
            self.stop_event.set()
            return False
        prompt = llm.use_template(Templates.SUMMARIZE_RETRY, input=ai_answer)
        response = await llm.completion(prompt)
        if response is None:
            _LOGGER.warning(f"视频{format_video_name}摘要生成失败，请自行检查问题，跳过处理")
            self._set_err_end(
                task.uuid,
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
                task.process_result = SummarizeAiResponse.model_validate(resp)
                if task.process_result.if_no_need_summary is True:
                    _LOGGER.warning(f"视频{format_video_name}被ai判定为不需要摘要，跳过处理")
                    self._set_noneed_end(task.uuid)
                    return False
                else:
                    # TODO 这种运行时间的显示存在很大问题，有空了统一一下，但现在我是没空了
                    _LOGGER.info(
                        f"ai返回内容解析正确，视频{format_video_name}摘要处理完成，共用时{time.perf_counter() - begin_time}s"
                    )
                    await self.finish(task)
                    return True
            except Exception as e:
                _LOGGER.trace(f"处理结果失败：{e}，大概是ai返回的格式不对，拿你没辙了，跳过处理")
                traceback.print_tb(e.__traceback__)
                self._set_err_end(
                    task.uuid,
                    "重试后处理结果失败，大概是ai返回的格式不对，跳过",
                )
                return False
