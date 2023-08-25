import pytest

from src.llm.gpt import OpenAIGPTClient
from src.utils.parse_prompt import build_messages


@pytest.fixture(scope="module")
def openai_gpt_client():
    openai = OpenAIGPTClient("", endpoint="")
    prompt = build_messages("你好", "你好")
    answer, tokens = openai.completion(prompt)
    return answer, tokens


def test_openai_gpt(openai_gpt_client):
    assert isinstance(openai_gpt_client, tuple), "openai_gpt_client 不是一个元组"
