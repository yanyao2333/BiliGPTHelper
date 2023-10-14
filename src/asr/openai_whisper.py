import asyncio
import functools
import json
import time
import traceback
from typing import Optional

import openai

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
        response = openai.Audio.transcribe(
            model="whisper-1", file=open(audio_path, "rb")
        )

        _LOGGER.debug(f"返回内容为{response}")

        if isinstance(response, dict) and "text" in response:
            return response["text"]
        else:
            try:
                response = json.loads(response)
                return response["text"]
            except Exception as e:
                _LOGGER.error(f"返回内容不是字典或者没有text字段，返回None")
                return None

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
