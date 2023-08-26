import asyncio
import time

import whisper as whi

from src.llm.gpt import OpenAIGPTClient
from src.llm.templates import Templates
from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="Whisper")


class Whisper:
    def __init__(self):
        self.model = None

    def load_model(self, model_size="medium", device="cpu", download_dir=None):
        """
        加载whisper模型
        :param model_size: 模型大小，可选small、medium、large
        :param device: 设备，可选cpu、cuda
        :param download_dir: 模型下载目录(None表示默认)
        :return: None
        """
        _LOGGER.info(f"正在加载whisper模型，模型大小{model_size}，设备{device}")
        self.model = whi.load_model(model_size, device, download_root=download_dir)
        _LOGGER.info(f"加载whisper模型成功")
        return self.model

    def get_model(self):
        if self.model is None:
            self.load_model()
        return self.model

    def _run_whisper_audio(
            self, model, audio_path, after_process, prompt, openai_api_key, openai_endpoint
    ):
        begin_time = time.perf_counter()
        _LOGGER.info(f"开始转写 {audio_path}")
        text = whi.transcribe(model, audio_path, initial_prompt=prompt)
        _LOGGER.debug(f"转写成功")
        if after_process:
            if openai_api_key:
                openai = OpenAIGPTClient(
                    api_key=openai_api_key,
                    endpoint=openai_endpoint
                    if openai_endpoint
                    else "https://api.openai.com/v1",
                )
                prompt = openai.use_template(
                    Templates.AFTER_PROCESS_SUBTITLE, subtitle=text
                )
                answer, _ = openai.completion(prompt)
                time_elapsed = time.perf_counter() - begin_time
                _LOGGER.info(f"字幕转译+后处理完成，共用时{time_elapsed}s")
                return answer
            else:
                _LOGGER.warning("没有提供openai api key，停止进行后处理，返回原值！")
        time_elapsed = time.perf_counter() - begin_time
        _LOGGER.info(f"字幕转译完成，共用时{time_elapsed}s")
        return text

    async def whisper_audio(
            self,  # 添加self参数以访问线程池
            model,
            audio_path,
            after_process=False,
            prompt=None,
            openai_api_key=None,
            openai_endpoint=None,
    ) -> str:
        loop = asyncio.get_event_loop()

        result = await loop.run_in_executor(
            None,  # None 用于默认的 ThreadPoolExecutor
            self._run_whisper_audio,
            model,
            audio_path,
            after_process,
            prompt,
            openai_api_key,
            openai_endpoint,
        )

        return result
