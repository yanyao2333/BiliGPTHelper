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
        _LOGGER.info(
            f"初始化OpenaiWhisper，api_key为{apikey}，api端点为{self.config.ASRs.openai_whisper.api_base}"
        )

    def _sync_transcribe(self, audio_path: str, **kwargs) -> Optional[str]:
        openai.api_key = self.config.ASRs.openai_whisper.api_key
        openai.api_base = self.config.ASRs.openai_whisper.api_base
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
                segment = (
                    segment
                    + audio[
                        start_time
                        + segment_length : start_time
                        + segment_length
                        + window_length
                    ]
                )

            output_segments.append(segment)
            start_time += segment_length

        num = 0

        for segment in output_segments:
            num += 1
            with open(f"{temp}/{_uuid}_segment_{num}.mp3", "wb") as file:
                segment.export(file, format="mp3")
            export_file_list.append(f"{_uuid}_segment_{num}.mp3")

        response = []

        num = 0

        def _delete_temp(_list):
            for name in _list:
                try:
                    os.remove(f"{temp}/{name}")
                    _LOGGER.debug(f"Deleted {name}")
                except OSError as e:
                    _LOGGER.warning(f"Error deleting {name}: {e}")
                    traceback.print_exc()

        for name in export_file_list:
            try:
                res = openai.Audio.transcribe(
                    model="whisper-1", file=open(f"{temp}/{name}", "rb")
                )
                if isinstance(res, dict) and "text" in response:
                    text = res["text"]
                else:
                    res = json.loads(res)
                    text = res["text"]
                response.append(text)
                num += 1
                _LOGGER.debug(f"第{num}个切片处理完成，api返回内容：{res}")
            except json.JSONDecodeError as e:
                _LOGGER.error(f"返回内容不是字典或者没有text字段，返回None")
                traceback.print_exc()
                _delete_temp(export_file_list)
                return None
            except Exception as e:
                _LOGGER.error(f"openai.Audio.transcribe 错误：{e}")
                traceback.print_exc()
                _delete_temp(export_file_list)
                return None

        response = "\n".join(response)

        _delete_temp(export_file_list)

        _LOGGER.debug(f"合并后返回内容为{response}")

        return response

    async def transcribe(self, audio_path: str, **kwargs) -> Optional[str]:
        loop = asyncio.get_event_loop()
        func = functools.partial(self._sync_transcribe, audio_path, **kwargs)
        result = await loop.run_in_executor(None, func)
        w = self.config.ASRs.openai_whisper
        try:
            if w.after_process and result is not None:
                bt = time.perf_counter()
                _LOGGER.info(f"正在进行后处理")
                text = await self.after_process(result)
                _LOGGER.debug(f"后处理完成，用时{time.perf_counter()-bt}s")
                return text
            else:
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
            _LOGGER.error(f"后处理失败，返回原字幕")
            return text
        return answer
