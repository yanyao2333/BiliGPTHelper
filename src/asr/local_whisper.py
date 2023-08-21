import whisper as whi
from src.utils.logging import LOGGER
import time
from src.llm.templates import Templates
from src.llm.openai_gpt import OpenAIGPTClient

_LOGGER = LOGGER.bind(name="asr")

class Whisper:
    def __init__(self):
        pass

    @staticmethod
    def whisper_audio(audio_path, model_size="medium", after_process=False, prompt=None, device="cpu", openai_api_key=None, openai_endpoint=None) -> str:
        """
        使用whisper转写音频
        :param audio_path: 音频路径
        :param model_size:使用的模型大小
        :param after_process: 是否使用gpt-3.5-turbo后处理
        :param prompt: 提交给whisper的prompt
        :param device: 使用的推理设备（使用gpu请填写cuda）
        :param openai_api_key: 如果要进行后处理需要提供
        :param openai_endpoint: 如果要进行后处理可根据需要提供
        :return: 字幕文本
        """
        begin_time = time.perf_counter()
        _LOGGER.info(f"[Whisper]开始转写 {audio_path}")
        model = whi.load_model(model_size, device=device)
        _LOGGER.debug(f"[Whisper]模型加载成功，开始转写")
        result = whi.transcribe(model, audio_path, initial_prompt=prompt)  # TODO 存在各种包括但不限于标点丢失、简繁中转换，语气词丢失等问题，后期尝试使用llm后处理
        text = result["text"]
        _LOGGER.debug(f"[Whisper]转写成功")
        if after_process:
            if openai_api_key:
                openai = OpenAIGPTClient(api_key=openai_api_key, endpoint=openai_endpoint if openai_endpoint else "https://api.openai.com/v1")
                prompt = openai.use_template(Templates.AFTER_PROCESS_SUBTITLE, subtitle=text)
                answer, _ = openai.completion(prompt)
                time_elapsed = time.perf_counter() - begin_time
                _LOGGER.info(f"[whisper]字幕转译+后处理完成，共用时{time_elapsed}s")
                return answer
            else:
                _LOGGER.warning("没有提供openai api key，停止进行后处理，返回原值！")
        time_elapsed = time.perf_counter() - begin_time
        _LOGGER.info(f"[whisper]字幕转译完成，共用时{time_elapsed}s")
        return text




