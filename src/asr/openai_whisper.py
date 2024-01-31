import asyncio
import functools
import json
import os
import time
import traceback
import uuid
from typing import Optional

import openai
from pydub import AudioSegment

from src.asr.asr_base import ASRBase
from src.llm.templates import Templates
from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="OpenaiWhisper")


class OpenaiWhisper(ASRBase):
    def prepare(self) -> None:
        apikey = self.config.ASRs.openai_whisper.api_key
        apikey = apikey[:-5] + "*****"
        _LOGGER.info(f"初始化OpenaiWhisper，api_key为{apikey}，api端点为{self.config.ASRs.openai_whisper.api_base}")

    def _cut_audio(self, audio_path: str) -> list[str]:
        """将音频切割为300s的片段，前后有5s的滑动窗口，返回切割后的文件名列表
        :param audio_path: 音频文件路径
        :return: 切割后的文件名列表
        """
        temp = self.config.storage_settings.temp_dir
        audio = AudioSegment.from_file(audio_path, "mp3")
        segment_length = 300 * 1000
        window_length = 5 * 1000
        start_time = 0
        output_segments = []
        export_file_list = []
        _uuid = uuid.uuid4()

        while start_time < len(audio):
            segment = audio[start_time : start_time + segment_length]

            if start_time > 0:
                segment = audio[start_time - window_length : start_time] + segment

            if start_time + segment_length < len(audio):
                _LOGGER.debug(f"正在处理{start_time}到{start_time+segment_length}的音频")
                segment = segment + audio[start_time + segment_length: start_time + segment_length + window_length]

            output_segments.append(segment)
            start_time += segment_length

        num = 0

        for segment in output_segments:
            num += 1
            with open(f"{temp}/{_uuid}_segment_{num}.mp3", "wb") as file:
                segment.export(file, format="mp3")
            _LOGGER.debug(f"第{num}个切片导出完成")
            export_file_list.append(f"{_uuid}_segment_{num}.mp3")

        return export_file_list

    def _sync_transcribe(self, audio_path: str, **kwargs) -> Optional[str]:
        """同步调用openai的transcribe API
        :param audio_path: 音频文件路径
        :param kwargs: 其他参数(传递给openai.Audio.transcribe)
        :return: 返回识别结果或None
        """
        _LOGGER.debug(f"正在识别{audio_path}")
        openai.api_key = self.config.ASRs.openai_whisper.api_key
        openai.api_base = self.config.ASRs.openai_whisper.api_base
        response = openai.Audio.transcribe(model="whisper-1", file=open(audio_path, "rb"))

        _LOGGER.debug(f"返回内容为{response}")

        if isinstance(response, dict) and "text" in response:
            return response["text"]
        try:
            response = json.loads(response)
            return response["text"]
        except Exception:
            _LOGGER.error("返回内容不是字典或者没有text字段，返回None")
            return None

    async def transcribe(self, audio_path: str, **kwargs) -> Optional[str]:
        loop = asyncio.get_event_loop()
        func_list = []
        temp = self.config.storage_settings.temp_dir
        _LOGGER.info("正在切割音频")
        export_file_list = self._cut_audio(audio_path)
        _LOGGER.info(f"音频切割完成，共{len(export_file_list)}个切片")
        for file in export_file_list:
            func_list.append(functools.partial(self._sync_transcribe, f"{temp}/{file}", **kwargs))
        _LOGGER.info("正在处理音频")
        result = await asyncio.gather(*[loop.run_in_executor(None, func) for func in func_list])
        _LOGGER.info("音频处理完成")
        if None in result:
            _LOGGER.error("识别失败，返回None")  # TODO 单独重试失败的切片
            return None
        result = "".join(result)
        # 清除临时文件
        for file in export_file_list:
            os.remove(f"{temp}/{file}")
        try:
            if self.config.ASRs.openai_whisper.after_process and result is not None:
                bt = time.perf_counter()
                _LOGGER.info("正在进行后处理")
                text = await self.after_process(result)
                _LOGGER.debug(f"后处理完成，用时{time.perf_counter()-bt}s")
                return text
            return result
        except Exception as e:
            _LOGGER.error(f"后处理失败，错误信息为{e}")
            traceback.print_exc()
            return result

    async def after_process(self, text: str, **kwargs) -> str:
        llm = self.llm_router.get_one()
        prompt = llm.use_template(Templates.AFTER_PROCESS_SUBTITLE, subtitle=text)
        answer, _ = await llm.completion(prompt)
        if answer is None:
            _LOGGER.error("后处理失败，返回原字幕")
            return text
        return answer
