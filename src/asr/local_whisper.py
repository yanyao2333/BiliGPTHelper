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

    @staticmethod
    def whisper_audio(
            model,
            audio_path,
            after_process=False,
            prompt=None,
            openai_api_key=None,
            openai_endpoint=None,
    ) -> str:
        """
        使用whisper转写音频
        :param model: whisper模型
        :param audio_path: 音频路径
        :param after_process: 是否使用gpt-3.5-turbo后处理
        :param prompt: 提交给whisper的prompt
        :param openai_api_key: 如果要进行后处理需要提供
        :param openai_endpoint: 如果要进行后处理可根据需要提供
        :return: 字幕文本
        """
        begin_time = time.perf_counter()
        _LOGGER.info(f"开始转写 {audio_path}")
        result = whi.transcribe(
            model, audio_path, initial_prompt=prompt
        )  # 存在各种包括但不限于标点丢失、简繁中转换，语气词丢失等问题，后期尝试使用llm后处理
        text = result["text"]
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
