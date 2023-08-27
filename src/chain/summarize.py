import asyncio
import copy
import json
import os
import time
import traceback

import ffmpeg
import httpx
import tenacity
from bilibili_api import Credential, HEADERS, ResourceType

from src.bilibili.bili_comment import BiliComment
from src.bilibili.bili_session import BiliSession
from src.bilibili.bili_video import BiliVideo
from src.llm.gpt import OpenAIGPTClient
from src.llm.templates import Templates
from src.utils.cache import Cache
from src.utils.global_variables_manager import GlobalVariablesManager
from src.utils.logging import LOGGER
from src.utils.queue_manager import QueueManager
from src.utils.task_status_record import TaskStatusRecorder
from src.utils.types import *

_LOGGER = LOGGER.bind(name="summarize-chain")


class SummarizeChain:
    """摘要处理链"""

    def __init__(
            self,
            queue_manager: QueueManager,
            value_manager: GlobalVariablesManager,
            credential: Credential,
            cache: Cache,
            whisper_model_obj,
            whisper_obj,
            task_status_recorder: TaskStatusRecorder,
    ):
        self.summarize_queue = queue_manager.get_queue("summarize")
        self.reply_queue = queue_manager.get_queue("reply")
        self.private_queue = queue_manager.get_queue("private")
        self.value_manager = value_manager
        self.api_key = self.value_manager.get_variable("api-key")
        self.api_base = (
            self.value_manager.get_variable("api-base")
            if self.value_manager.get_variable("api-base")
            else "https://api.openai.com/v1"
        )
        self.temp_dir = (
            self.value_manager.get_variable("temp-dir")
            if self.value_manager.get_variable("temp-dir")
            else os.path.join(os.getcwd(), "temp")
        )
        self.queue_dir = (
            self.value_manager.get_variable("queue-dir")
            if self.value_manager.get_variable("queue-dir")
            else os.path.join(os.getcwd(), "queue")
        )
        self.whisper_model = (
            self.value_manager.get_variable("whisper-model-size")
            if self.value_manager.get_variable("whisper-model-size")
            else "medium"
        )
        self.model = (
            self.value_manager.get_variable("model")
            if self.value_manager.get_variable("model")
            else "gpt-3.5-torbo"
        )
        self.whisper_device = (
            self.value_manager.get_variable("whisper-device")
            if self.value_manager.get_variable("whisper-device")
            else "cpu"
        )
        self.credential = credential
        self.whisper_after_process = (
            self.value_manager.get_variable("whisper-after-process")
            if self.value_manager.get_variable("whisper-after-process")
            else False
        )
        self.cache = cache
        self.whisper_model_obj = whisper_model_obj
        self.max_tokens = (
            self.value_manager.get_variable("max-total-tokens")
            if self.value_manager.get_variable("max-total-tokens")
            else None
        )
        self.now_tokens = 0
        self.whisper_obj = whisper_obj
        self.task_status_recorder = task_status_recorder

    # async def start(self):
    #     while True:
    #         try:
    #             _LOGGER.info("正在启动摘要处理链")
    #             await self._start_chain()
    #         except asyncio.CancelledError:
    #             _LOGGER.info("收到取消信号，摘要处理链关闭")
    #             break
    #         except Exception as e:
    #             _LOGGER.trace(f"摘要处理链出现错误：{e}，正在重启并处理剩余任务")

    @staticmethod
    def chain_callback(retry_state):
        exception = retry_state.outcome.exception()
        _LOGGER.error(f"捕获到错误：{exception}")
        traceback.print_tb(retry_state.outcome.exception().__traceback__)
        _LOGGER.debug(f"当前重试次数为{retry_state.attempt_number}")
        _LOGGER.debug(f"下一次重试将在{retry_state.next_action.sleep}秒后进行")

    async def _check_require(self, at_items: AtItems, _uuid: str) -> bool:
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
            self.task_status_recorder.update_record(
                _uuid,
                stage=TaskProcessStage.END,
                end_reason=TaskProcessEndReason.ERROR,
                gmt_end=int(time.time()),
                error_msg="该消息目前并不支持，跳过处理",
            )
            return False
        if at_items["item"]["root_id"] != 0 or at_items["item"]["target_id"] != 0:
            _LOGGER.warning(f"该消息是楼中楼消息，暂时不受支持，跳过处理")  # TODO 楼中楼消息的处理
            self.task_status_recorder.update_record(
                _uuid,
                stage=TaskProcessStage.END,
                end_reason=TaskProcessEndReason.ERROR,
                gmt_end=int(time.time()),
                error_msg="该消息是楼中楼消息，暂时不受支持，跳过处理",
            )
            return False
        return True

    async def _process_video_info(self, at_items: AtItems, _uuid: str) -> bool | tuple:
        """处理视频信息"""
        _LOGGER.info(f"开始处理该视频音频流和字幕")
        video = BiliVideo(self.credential, url=at_items["item"]["uri"])
        _, _type = await video.get_video_obj()
        # _LOGGER.debug(_type)
        if _type != ResourceType.VIDEO:
            _LOGGER.warning(f"视频{at_items['item']['uri']}不是视频或不存在，跳过")
            self.task_status_recorder.update_record(
                _uuid,
                stage=TaskProcessStage.END,
                end_reason=TaskProcessEndReason.ERROR,
                gmt_end=int(time.time()),
                error_msg="视频不是视频或不存在，跳过",
            )
            return False
        _LOGGER.debug(f"视频对象创建成功，正在获取视频信息")
        video_info = await video.get_video_info()
        if self.cache.get_cache(key=video_info["bvid"]):
            _LOGGER.debug(f"视频{video_info['title']}已经处理过，直接使用缓存")
            if (
                    at_items["item"]["type"] == "private_msg"
                    and at_items["item"]["business_id"] == 114
            ):
                cache = self.cache.get_cache(key=video_info["bvid"])
                at_items["item"]["ai_response"] = cache
                await self.private_queue.put(at_items)
            else:
                cache = self.cache.get_cache(key=video_info["bvid"])
                at_items["item"]["ai_response"] = cache
                await self.reply_queue.put(at_items)
            self.task_status_recorder.update_record(
                _uuid,
                stage=TaskProcessStage.END,
                end_reason=TaskProcessEndReason.NORMAL,
                gmt_end=int(time.time()),
            )
            return True
        _LOGGER.debug(f"视频信息获取成功，正在获取视频标签")
        format_video_name = f"『{video_info['title']}』"
        # video_pages = await video.get_video_pages() # TODO 不清楚b站回复和at时分P的展现机制，暂时遇到分P视频就跳过
        if len(video_info["pages"]) > 1:
            _LOGGER.info(f"视频{format_video_name}分P，跳过处理")
            self.task_status_recorder.update_record(
                _uuid,
                stage=TaskProcessStage.END,
                end_reason=TaskProcessEndReason.ERROR,
                gmt_end=int(time.time()),
                error_msg="视频分P，跳过处理",
            )
            return False
        # 获取视频标签
        video_tags = (
            await video.get_video_tags()
        )  # 增加tag有概率导致输出内容变差，后期通过prompt engineering解决
        video_tags_string = ""
        for tag in video_tags:
            video_tags_string += f"#{tag['tag_name']} "
        _LOGGER.debug(f"视频标签获取成功，开始获取视频评论")
        # 获取视频评论
        video_comments = await BiliComment.get_random_comment(
            video_info["aid"], self.credential
        )
        return video, video_info, format_video_name, video_tags_string, video_comments

    async def _get_subtitle_from_bilibili(
            self, video: BiliVideo, _uuid: str, format_video_name: str
    ) -> bool | str:
        subtitle_url = await video.get_video_subtitle(page_index=0)
        if subtitle_url is None:
            _LOGGER.warning(f"视频{format_video_name}因未知原因无法获取字幕，跳过处理")
            self.task_status_recorder.update_record(
                _uuid,
                stage=TaskProcessStage.END,
                end_reason=TaskProcessEndReason.ERROR,
                gmt_end=int(time.time()),
                error_msg="视频因未知原因无法获取字幕，跳过处理",
            )
            return False
        _LOGGER.debug(f"视频字幕获取成功，正在读取字幕")
        # 下载字幕
        async with httpx.AsyncClient() as client:
            resp = await client.get("https:" + subtitle_url, headers=HEADERS)
        _LOGGER.debug(f"字幕获取成功，正在转换为纯字幕")
        # 转换字幕格式
        text = ""
        for subtitle in resp.json()["body"]:
            # from_time = int(subtitle["from"])
            # f_min, f_sec = divmod(from_time, 60)
            # f_format = f"{f_min}:{f_sec}"
            # to_time = int(subtitle["to"])
            # t_min, t_sec = divmod(to_time, 60)
            # t_format = f"{t_min}:{t_sec}"
            # text += f"{f_format} --> {t_format}  {subtitle['content']}\n"
            text += f"{subtitle['content']}\n"
        return text

    async def _get_subtitle_by_whisper(
            self,
            video_info,
            video: BiliVideo,
            _uuid: str,
            format_video_name,
            at_items: AtItems,
    ) -> bool | str:
        _LOGGER.debug(f"视频信息获取成功，正在获取视频音频流和字幕")
        if len(video_info["subtitle"]["list"]) == 0:
            if self.value_manager.get_variable("whisper-enable") is False:
                _LOGGER.warning(f"视频{format_video_name}没有字幕，你没有开启whisper，跳过处理")
                self.task_status_recorder.update_record(
                    _uuid,
                    stage=TaskProcessStage.END,
                    end_reason=TaskProcessEndReason.ERROR,
                    gmt_end=int(time.time()),
                    error_msg="视频没有字幕，你没有开启whisper，跳过处理",
                )
                return False
            _LOGGER.warning(
                f"视频{format_video_name}没有字幕，开始使用whisper转写并处理，时间会更长（长了不是一点点）"
            )
            video_download_url = await video.get_video_download_url()
            audio_url = video_download_url["dash"]["audio"][0]["baseUrl"]
            _LOGGER.debug(f"视频下载链接获取成功，正在下载视频中的音频流")
            # 下载视频中的音频流
            async with httpx.AsyncClient() as client:
                resp = await client.get(audio_url, headers=HEADERS)
                temp_dir = self.temp_dir
                if not os.path.exists(temp_dir):
                    os.mkdir(temp_dir)
                with open(f"{temp_dir}/{video_info['aid']} temp.m4s", "wb") as f:
                    f.write(resp.content)
            _LOGGER.debug(f"视频中的音频流下载成功，正在转换音频格式")
            # 转换音频格式
            (
                ffmpeg.input(f"{temp_dir}/{video_info['aid']} temp.m4s")
                .output(f"{temp_dir}/{video_info['aid']} temp.mp3")
                .run(overwrite_output=True)
            )
            _LOGGER.debug(f"音频格式转换成功，正在使用whisper转写音频")
            # 使用whisper转写音频
            audio_path = f"{temp_dir}/{video_info['aid']} temp.mp3"
            text = await self.whisper_obj.whisper_audio(
                self.whisper_model_obj,
                audio_path,
                after_process=self.whisper_after_process,
                openai_api_key=self.api_key,
                openai_endpoint=self.api_base,
            )
            text = text["text"]
            temp = at_items
            temp["item"]["whisper_subtitle"] = text
            self.task_status_recorder.update_record(_uuid, data=temp, use_whisper=True)
            _LOGGER.debug(f"音频转写成功，正在删除临时文件")
            # 删除临时文件
            os.remove(f"{temp_dir}/{video_info['aid']} temp.m4s")
            os.remove(f"{temp_dir}/{video_info['aid']} temp.mp3")
            _LOGGER.debug(f"临时文件删除成功，开始使用模板生成prompt")
            return text

    async def _send_reply(
            self, at_items: AtItems, resp: dict, video_info: dict, _uuid: str
    ):
        _LOGGER.debug(f"正在将结果加入发送队列，等待回复")
        reply_data = copy.deepcopy(at_items)
        reply_data["item"]["ai_response"] = resp
        self.reply_queue.put(reply_data)
        _LOGGER.debug(f"结果加入发送队列成功")
        self.task_status_recorder.update_record(
            _uuid, stage=TaskProcessStage.WAITING_PUSH_TO_CACHE
        )
        self.cache.set_cache(
            key=video_info["bvid"], value=self.cut_items_leaves(reply_data)
        )
        self.task_status_recorder.update_record(
            _uuid,
            stage=TaskProcessStage.END,
            end_reason=TaskProcessEndReason.NORMAL,
            gmt_end=int(time.time()),
        )
        _LOGGER.debug(f"设置缓存成功")
        return True

    async def _send_private(
            self, at_items: AtItems, resp: dict, video_info: dict, _uuid: str
    ):
        _LOGGER.debug(f"该消息是私信消息，将结果放入私信处理队列")
        reply_data = copy.deepcopy(at_items)
        reply_data["item"]["ai_response"] = resp
        await self.private_queue.put(reply_data)
        _LOGGER.debug(f"结果加入私信处理队列成功")
        # reply_data["item"]["private_msg_event"][
        #     "content"
        # ] = reply_data["item"]["private_msg_event"][
        #     "content"
        # ].get_bvid()
        self.task_status_recorder.update_record(
            _uuid, stage=TaskProcessStage.WAITING_PUSH_TO_CACHE
        )
        self.cache.set_cache(
            key=video_info["bvid"], value=self.cut_items_leaves(reply_data)
        )
        self.task_status_recorder.update_record(
            _uuid,
            stage=TaskProcessStage.END,
            end_reason=TaskProcessEndReason.NORMAL,
            gmt_end=int(time.time()),
        )
        _LOGGER.debug(f"设置缓存成功")
        return True

    async def _on_start(self):
        """在启动处理链时先处理一下之前没有处理完的视频"""
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
        self.task_status_recorder.load_queue(self.summarize_queue)
        _LOGGER.info(f"正在将上次在队列中的视频加入队列")
        self.task_status_recorder.delete_queue()  # FIXME 这里有可能会导致队列丢失，但目前只有这一个队列，先不管

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(Exception),
        wait=tenacity.wait_fixed(10),
        before_sleep=chain_callback,
    )
    async def start_chain(self):
        try:
            _LOGGER.info("正在启动摘要处理链，开始将上次未处理完的视频加入队列")
            await self._on_start()
            while True:
                if self.max_tokens is not None and self.now_tokens >= self.max_tokens:
                    _LOGGER.warning(
                        f"当前已使用token数{self.now_tokens}，超过最大token数{self.max_tokens}，摘要处理链停止运行"
                    )
                    raise asyncio.CancelledError

                # 从队列中获取摘要
                at_items: AtItems = await self.summarize_queue.get()
                if at_items.get("item").get("uuid", None) is not None:
                    _item_uuid = at_items["item"][
                        "uuid"
                    ]  # TODO 有uuid就一定有视频记录，但如果是继续处理的话，gmt_create时间就会不准确，要不要在读取时再修改一次？
                else:
                    if isinstance(
                            at_items.get("item")
                                    .get("private_msg_event", {"content": None})
                                    .get("content", None),
                            Video,
                    ):
                        temp = at_items
                        temp["item"]["private_msg_event"]["content"] = temp["item"][
                            "private_msg_event"
                        ]["content"].get_bvid()
                    else:
                        temp = at_items
                    _item_uuid = self.task_status_recorder.create_record(
                        temp,
                        TaskProcessStage.PREPROCESS,
                        TaskProcessEvent.SUMMARIZE,
                        int(time.time()),
                    )
                _LOGGER.info(f"摘要处理链获取到任务了：{at_items['item']['uri']}")
                # 检查是否满足处理条件
                if not await self._check_require(at_items, _item_uuid):
                    continue
                # 获取视频相关信息
                data = self.task_status_recorder.get_data_by_uuid(_item_uuid)
                video = BiliVideo(self.credential, url=at_items["item"]["uri"])
                video_info = await video.get_video_info()
                format_video_name = f"『{video_info['title']}』"
                if (
                        data["stage"] == TaskProcessStage.PREPROCESS.value
                        or data["stage"] == TaskProcessStage.WAITING_LLM_RESPONSE.value
                ):
                    begin_time = time.perf_counter()
                    resp = await self._process_video_info(at_items, _item_uuid)
                    if type(resp) is bool:
                        continue
                    (
                        video,
                        video_info,
                        format_video_name,
                        video_tags_string,
                        video_comments,
                    ) = resp
                    # 处理视频音频流和字幕
                    _LOGGER.debug(f"视频信息获取成功，正在获取视频音频流和字幕")
                    if at_items["item"].get("whisper_subtitle", None) is not None:
                        text = at_items["item"]["whisper_subtitle"]
                        _LOGGER.debug(f"使用whisper转写缓存，开始使用模板生成prompt")
                    else:
                        if len(video_info["subtitle"]["list"]) == 0:
                            resp = await self._get_subtitle_by_whisper(
                                video_info,
                                video,
                                _item_uuid,
                                format_video_name,
                                at_items,
                            )
                            if type(resp) is bool:
                                continue
                            text = resp
                            _LOGGER.debug(f"whisper转写成功，开始使用模板生成prompt")
                        else:
                            text = await self._get_subtitle_from_bilibili(
                                video, _item_uuid, format_video_name
                            )
                            if type(text) is bool:
                                continue
                            _LOGGER.debug(f"字幕转换成功，正在使用模板生成prompt")
                    _LOGGER.info(
                        f"视频{format_video_name}音频流和字幕处理完成，共用时{time.perf_counter() - begin_time}s，开始调用LLM生成摘要"
                    )
                    self.task_status_recorder.update_record(
                        _item_uuid, stage=TaskProcessStage.WAITING_LLM_RESPONSE
                    )
                    prompt = OpenAIGPTClient.use_template(
                        Templates.SUMMARIZE_USER,
                        Templates.SUMMARIZE_SYSTEM,
                        title=video_info["title"],
                        tags=video_tags_string,
                        comments=video_comments,
                        subtitle=text,
                        description=video_info["desc"],
                    )
                    _LOGGER.debug(f"prompt生成成功，开始调用openai的Completion API")
                    # 调用openai的Completion API
                    response = await OpenAIGPTClient(
                        self.api_key, self.api_base
                    ).completion(prompt, model=self.model)
                    if response is None:
                        _LOGGER.warning(f"视频{format_video_name}摘要生成失败，请自行检查问题，跳过处理")
                        self.task_status_recorder.update_record(
                            _item_uuid,
                            stage=TaskProcessStage.END,
                            end_reason=TaskProcessEndReason.ERROR,
                            gmt_end=int(time.time()),
                            error_msg="摘要生成失败，请自行检查问题，跳过处理",
                        )
                        continue
                    answer, tokens = response
                    self.now_tokens += tokens
                    _LOGGER.debug(f"openai api输出内容为：{answer}")
                    _LOGGER.debug(f"调用openai的Completion API成功，开始处理结果")
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
                    video = BiliVideo(self.credential, url=at_items["item"]["uri"])
                    obj, _type = await video.get_video_obj()
                    # 处理结果
                    if answer:
                        try:
                            if data["stage"] == TaskProcessStage.WAITING_RETRY.value:
                                raise Exception("触发重试")
                            if "False" in answer:
                                answer.replace(
                                    "False", "false"
                                )  # 解决一部分因为大小写问题导致的json解析失败
                            if "True" in answer:
                                answer.replace("True", "true")
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
                                self.task_status_recorder.update_record(
                                    _item_uuid,
                                    stage=TaskProcessStage.END,
                                    end_reason=TaskProcessEndReason.NONEED,
                                    gmt_end=int(time.time()),
                                )
                                continue
                            else:
                                _LOGGER.info(
                                    f"ai返回内容解析正确，视频{format_video_name}摘要处理完成，共用时{time.perf_counter() - begin_time}s"
                                )
                                if (
                                        at_items["item"]["type"] == "private_msg"
                                        and at_items["item"]["business_id"] == 114
                                ):
                                    _LOGGER.debug(f"该消息是私信消息，将结果放入私信处理队列")
                                    await self._send_private(
                                        at_items, resp, video_info, _item_uuid
                                    )
                                else:
                                    _LOGGER.debug(f"正在将结果加入发送队列，等待回复")
                                    await self._send_reply(
                                        at_items, resp, video_info, _item_uuid
                                    )

                        except Exception as e:
                            _LOGGER.error(f"处理结果失败：{e}，大概是ai返回的格式不对，尝试修复")
                            traceback.print_tb(e.__traceback__)
                            self.task_status_recorder.update_record(
                                _item_uuid, stage=TaskProcessStage.WAITING_RETRY
                            )
                            res = await self.retry_summarize(
                                answer,
                                at_items,
                                format_video_name,
                                begin_time,
                                video_info,
                            )
                            if res is True:
                                self.task_status_recorder.update_record(
                                    _item_uuid,
                                    stage=TaskProcessStage.END,
                                    end_reason=TaskProcessEndReason.NORMAL,
                                    gmt_end=int(time.time()),
                                    if_retry=True,
                                )
                            elif res is False:
                                self.task_status_recorder.update_record(
                                    _item_uuid,
                                    stage=TaskProcessStage.END,
                                    end_reason=TaskProcessEndReason.ERROR,
                                    gmt_end=int(time.time()),
                                    error_msg="重试后处理结果失败，大概是ai返回的格式不对，跳过",
                                )
                            elif res is None:
                                self.task_status_recorder.update_record(
                                    _item_uuid,
                                    stage=TaskProcessStage.END,
                                    end_reason=TaskProcessEndReason.NONEED,
                                    gmt_end=int(time.time()),
                                )
        except asyncio.CancelledError:
            _LOGGER.info("收到关闭信号，摘要处理链关闭")

    def cut_items_leaves(self, items: AtItems):
        """精简at items数据，只保存ai_response，准备存入cache"""
        return items["item"]["ai_response"]

    async def retry_summarize(
            self, ai_answer, at_item, format_video_name, begin_time, video_info
    ):
        """通过重试prompt让chatgpt重新构建json

        :param ai_answer: ai返回的内容
        :param at_item: queue中的原始数据
        :param format_video_name: 格式化后的视频名称
        :param begin_time: 开始时间
        :param video_info: 视频信息
        :return: None
        """
        _LOGGER.debug(f"ai返回内容解析失败，正在尝试重试")
        prompt = OpenAIGPTClient.use_template(Templates.RETRY, input=ai_answer)
        response = await OpenAIGPTClient(self.api_key, self.api_base).completion(
            prompt, model=self.model
        )
        if response is None:
            _LOGGER.warning(f"视频{format_video_name}摘要生成失败，请自行检查问题，跳过处理")
            return None
        answer, tokens = response
        _LOGGER.debug(f"openai api输出内容为：{answer}")
        self.now_tokens += tokens
        if answer:
            try:
                resp = json.loads(answer)
                if resp["noneed"] is True:
                    _LOGGER.warning(f"视频{format_video_name}被ai判定为不需要摘要，跳过处理")
                    await BiliSession.quick_send(
                        self.credential, at_item, f"AI觉得你的视频不需要处理，换个更有意义的视频再试试看吧！"
                    )
                    # await BiliSession.quick_send(self.credential, at_item, answer)
                    return None
                else:
                    _LOGGER.info(
                        f"ai返回内容解析正确，视频{format_video_name}摘要处理完成，共用时{time.perf_counter() - begin_time}s"
                    )
                    if (
                            at_item["item"]["type"] == "private_msg"
                            and at_item["item"]["business_id"] == 114
                    ):
                        _LOGGER.debug(f"该消息是私信消息，将结果放入私信处理队列")
                        reply_data = copy.deepcopy(at_item)
                        reply_data["item"]["ai_response"] = resp
                        await self.private_queue.put(reply_data)
                        _LOGGER.debug(f"结果加入私信处理队列成功")
                        # reply_data["item"]["private_msg_event"]["content"] = reply_data[
                        #     "item"
                        # ]["private_msg_event"]["content"].get_bvid()
                        self.cache.set_cache(
                            key=video_info["bvid"],
                            value=self.cut_items_leaves(reply_data),
                        )
                        _LOGGER.debug(f"设置缓存成功")
                        return True
                    else:
                        _LOGGER.debug(f"正在将结果加入发送队列，等待回复")
                        reply_data = copy.deepcopy(at_item)
                        reply_data["item"]["ai_response"] = resp
                        self.reply_queue.put(reply_data)
                        _LOGGER.debug(f"结果加入发送队列成功")
                        self.cache.set_cache(
                            key=video_info["bvid"],
                            value=self.cut_items_leaves(reply_data),
                        )
                        _LOGGER.debug(f"设置缓存成功")
                        return True
            except Exception as e:
                _LOGGER.trace(f"处理结果失败：{e}，大概是ai返回的格式不对，拿你没辙了，跳过处理")
                traceback.print_tb(e.__traceback__)
                return False
