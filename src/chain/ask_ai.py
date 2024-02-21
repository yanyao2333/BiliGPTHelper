import asyncio
import json
import time
import traceback

import tenacity

from src.bilibili.bili_session import BiliSession
from src.chain.base_chain import BaseChain
from src.llm.templates import Templates
from src.models.task import AskAIResponse, BiliGPTTask, Chains, ProcessStages
from src.utils.callback import chain_callback
from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="ask-ai-chain")


class AskAI(BaseChain):
    async def _precheck(self, task: BiliGPTTask) -> bool:
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
        return False

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(Exception),
        wait=tenacity.wait_fixed(10),
        before_sleep=chain_callback,
    )
    async def main(self):
        try:
            await self._on_start()
            while True:
                task: BiliGPTTask = await self.ask_ai_queue.get()
                _item_uuid = task.uuid
                self._create_record(task)
                _LOGGER.info(f"ask_ai处理链获取到任务了：{task.uuid}")
                # 检查是否满足处理条件
                if task.process_stage == ProcessStages.END:
                    _LOGGER.info(f"任务{task.uuid}已经结束，获取下一个")
                    continue
                if not await self._precheck(task):
                    continue
                # 获取视频相关信息
                # data = self.task_status_recorder.get_data_by_uuid(_item_uuid)
                resp = await self._get_video_info(task, if_get_comments=False)
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
                    # FIXME: 需要修改项目的cache实现，标注来自于哪个处理链，否则事有点大
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
                        await self._set_err_end(msg="没有可用的LLM，被迫结束处理", task=task)
                        self.stop_event.set()
                        continue
                    prompt = llm.use_template(
                        Templates.ASK_AI_USER,
                        Templates.ASK_AI_SYSTEM,
                        title=video_info["title"],
                        subtitle=text,
                        description=video_info["desc"],
                        question=task.command_params.question,
                    )
                    _LOGGER.debug("prompt生成成功，开始调用llm")
                    # 调用openai的Completion API
                    response = await llm.completion(prompt)
                    if response is None:
                        _LOGGER.warning(f"任务{task.uuid}：ai未返回任何内容，请自行检查问题，跳过处理")
                        await self._set_err_end(msg="ai未返回任何内容，请自行检查问题，跳过处理", task=task)
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
                                answer.replace("false", "False")  # 解决一部分因为大小写问题导致的json解析失败
                            if "true" in answer:
                                answer.replace("true", "True")
                            resp = json.loads(answer)
                            task.process_result = AskAIResponse.model_validate(resp)
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
            _LOGGER.info("收到关闭信号，ask_ai处理链关闭")

    async def _on_start(self):
        """在启动处理链时先处理一下之前没有处理完的视频"""
        _LOGGER.info("正在启动摘要处理链，开始将上次未处理完的视频加入队列")
        uncomplete_task = []
        uncomplete_task += self.task_status_recorder.get_record_by_stage(
            chain=Chains.ASK_AI
        )  # 有坑，这里会把之前运行过的也重新加回来，不过我下面用判断简单补了一手，叫我天才！
        for task in uncomplete_task:
            if task["process_stage"] != ProcessStages.END.value:
                try:
                    _LOGGER.debug(f"恢复uuid: {task['uuid']} 的任务")
                    self.ask_ai_queue.put_nowait(BiliGPTTask.model_validate(task))
                except Exception:
                    traceback.print_exc()
                    # TODO 这里除了打印日志，是不是还应该记录在视频状态中？
                    _LOGGER.error(f"在恢复uuid: {task['uuid']} 时出现错误！跳过恢复")

    async def retry(self, ai_answer, task: BiliGPTTask, format_video_name, begin_time, video_info):
        """通过重试prompt让chatgpt重新构建json

        :param ai_answer: ai返回的内容
        :param task: queue中的原始数据
        :param format_video_name: 格式化后的视频名称
        :param begin_time: 开始时间
        :param video_info: 视频信息
        :return: None
        """
        _LOGGER.error(
            f"任务{task.uuid}：真不好意思！但是我ask_ai部分的retry还没写！所以只能先全给你设置成错误结束了嘿嘿嘿"
        )
        await self._set_err_end(
            msg="重试代码未实现，跳过",
            task=task,
        )
        return False
