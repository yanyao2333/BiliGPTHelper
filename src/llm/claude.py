import traceback
from typing import Tuple

import anthropic

from src.llm.llm_base import LLMBase
from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="aiproxy_claude")


class AiproxyClaude(LLMBase):
    def prepare(self):
        mask_key = self.config.LLMs.aiproxy_claude.api_key[:-5] + "*****"
        _LOGGER.info(
            f"初始化AIProxyClaude，api_key为{mask_key}，api端点为{self.config.LLMs.aiproxy_claude.api_base}"
        )

    async def completion(self, prompt, **kwargs) -> Tuple[str, int] | None:
        """调用claude的Completion API
        :param prompt: 输入的文本（请确保格式化为openai的prompt格式）
        :param kwargs: 其他参数
        :return: 返回生成的文本和token总数 或 None
        """
        try:
            claude = anthropic.AsyncAnthropic(
                api_key=self.config.LLMs.aiproxy_claude.api_key,
                base_url=self.config.LLMs.aiproxy_claude.api_base,
            )
            system = prompt[0]["content"]
            user = prompt[1]["content"]
            prompt = f"I will give you 'rules' 'content' two tags. You need to follow the rules!  <content>{system}</content> <rules>{user}</rules>"
            prompt = f"{anthropic.HUMAN_PROMPT} {prompt}{anthropic.AI_PROMPT}"
            resp = await claude.completions.create(
                prompt=prompt,
                max_tokens_to_sample=1000,
                model=self.config.LLMs.aiproxy_claude.model,
                **kwargs,
            )
            _LOGGER.debug(f"调用claude的Completion API成功，API返回结果为：{resp}")
            _LOGGER.info(
                f"调用claude的Completion API成功，本次调用中，prompt+response的长度为{resp.model_dump()['usage']['total_tokens']}"
            )
            return (
                resp.completion,
                resp.model_dump()["usage"]["total_tokens"],
            )
        except Exception as e:
            _LOGGER.error(f"调用claude的Completion API失败：{e}")
            traceback.print_tb(e.__traceback__)
            return None
