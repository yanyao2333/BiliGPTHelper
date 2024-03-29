import asyncio
import functools
import time
import traceback
from typing import Optional

from src.asr.asr_base import ASRBase
from src.core.routers.llm_router import LLMRouter
from src.llm.templates import Templates
from src.models.config import Config
from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="LocalWhisper")


class LocalWhisper(ASRBase):
    def __init__(self, config: Config, llm_router: LLMRouter):
        super().__init__(config, llm_router)
        self.llm_router = llm_router
        self.model = None
        self.config = config

    def prepare(self) -> None:
        """
        加载whisper模型
        :return: None
        """
        _LOGGER.info(
            f"正在加载whisper模型，模型大小{self.config.ASRs.local_whisper.model_size}，设备{self.config.ASRs.local_whisper.device}"
        )
        import whisper as whi

        self.model = whi.load_model(
            self.config.ASRs.local_whisper.model_size,
            self.config.ASRs.local_whisper.device,
            download_root=self.config.ASRs.local_whisper.model_dir,
        )
        _LOGGER.info("加载whisper模型成功")

    async def after_process(self, text, **kwargs) -> str:
        llm = self.llm_router.get_one()
        prompt = llm.use_template(Templates.AFTER_PROCESS_SUBTITLE, subtitle=text)
        answer, _ = await llm.completion(prompt)
        if answer is None:
            _LOGGER.error("后处理失败，返回原字幕")
            return text
        return answer

    def _sync_transcribe(self, audio_path, **kwargs) -> Optional[str]:
        try:
            begin_time = time.perf_counter()
            _LOGGER.info(f"开始转写 {audio_path}")
            if self.model is None:
                return None
            import whisper as whi

            text = whi.transcribe(self.model, audio_path)
            text = text["text"]
            _LOGGER.debug("转写成功")
            time_elapsed = time.perf_counter() - begin_time
            _LOGGER.info(f"字幕转译完成，共用时{time_elapsed}s")
            return text
        except Exception as e:
            _LOGGER.error(f"转写失败，错误信息为{e}", exc_info=True)
            return None

    async def transcribe(self, audio_path, **kwargs) -> Optional[str]:  # 添加self参数以访问线程池
        loop = asyncio.get_event_loop()

        func = functools.partial(self._sync_transcribe, audio_path, **kwargs)

        result = await loop.run_in_executor(None, func)
        w = self.config.ASRs.local_whisper
        try:
            if w.after_process and result is not None:
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
