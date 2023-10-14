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

    async def transcribe(self, audio_path: str, **kwargs) -> Optional[str]:
        openai.api_key = self.config.ASRs.openai_whisper.api_key
        openai.api_base = self.config.ASRs.openai_whisper.api_base
        response = openai.Audio.transcribe(
            model="whisper-1", file=open(audio_path, "rb")
        )

        if response.status_code != 200:
            _LOGGER.error(f"转写失败，api返回信息为：{response.json()}")
            return None

        return response.json()["text"]

    async def after_process(self, text: str, **kwargs) -> str:
        llm = self.llm_router.get_one()
        prompt = llm.use_template(Templates.AFTER_PROCESS_SUBTITLE, subtitle=text)
        answer, _ = await llm.completion(prompt)
        if answer is None:
            _LOGGER.error(f"后处理失败，返回原字幕")
            return text
        return answer
