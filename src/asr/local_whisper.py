import asyncio
import time
from typing import Optional

import whisper as whi

from src.asr.asr_base import ASRBase
from src.llm.gpt import OpenAIGPTClient
from src.llm.templates import Templates
from src.utils.logging import LOGGER
from src.utils.models import Config

_LOGGER = LOGGER.bind(name="LocalWhisper")


class LocalWhisper(ASRBase):
    alias = "local_whisper"

    def __init__(self, config: Config):
        super().__init__(config)
        self.model = None
        self.config = config
        self.alias = "local_whisper"

    def prepare(self) -> None:
        """
        加载whisper模型
        :return: None
        """
        _LOGGER.info(
            f"正在加载whisper模型，模型大小{self.config.ASRs.local_whisper.model_size}，设备{self.config.ASRs.local_whisper.device}"
        )
        self.model = whi.load_model(
            self.config.ASRs.local_whisper.model_size,
            self.config.ASRs.local_whisperdevice,
            download_root=self.config.ASRs.local_whisper.model_dir,
        )
        _LOGGER.info(f"加载whisper模型成功")
        return None

    async def after_process(self, text):
        w = self.config.LLMs.openai
        if w.api_key:
            openai = OpenAIGPTClient(
                api_key=w.api_key,
                endpoint=w.api_base if w.api_base else "https://api.openai.com/v1",
            )
            prompt = openai.use_template(
                Templates.AFTER_PROCESS_SUBTITLE, subtitle=text
            )
            answer, _ = await openai.completion(prompt)
            return answer
        else:
            _LOGGER.warning("没有提供openai api key，停止进行后处理，返回原值！")
            return text

    def _wait_transcribe(self, audio_path) -> Optional[str]:
        try:
            begin_time = time.perf_counter()
            o = self.config.LLMs.openai
            w = self.config.ASRs.local_whisper
            _LOGGER.info(f"开始转写 {audio_path}")
            if self.model is None:
                return None
            text = whi.transcribe(self.model, audio_path)
            text = text["text"]
            _LOGGER.debug(f"转写成功")
            if w.after_process:
                _LOGGER.info(f"正在进行后处理")
                text = self.after_process(text)
                _LOGGER.debug(f"后处理完成")
            time_elapsed = time.perf_counter() - begin_time
            _LOGGER.info(f"字幕转译完成，共用时{time_elapsed}s")
            return text
        except Exception as e:
            _LOGGER.error(f"转写失败，错误信息为{e}", exc_info=True)
            return None

    async def transcribe(
        self,  # 添加self参数以访问线程池
        audio_path,
        after_process=False,
        prompt=None,
        openai_api_key=None,
        openai_endpoint=None,
    ) -> Optional[str]:
        loop = asyncio.get_event_loop()

        result = await loop.run_in_executor(
            None,  # None 用于默认的 ThreadPoolExecutor
            self._wait_transcribe,
            audio_path,
        )

        return result
