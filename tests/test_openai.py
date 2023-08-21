from src.llm.openai_gpt import OpenAIGPTClient, build_messages
import pytest


@pytest.fixture(scope="module")
def openai_gpt_client():
    openai = OpenAIGPTClient("mk-0fNJ9BxvtXJNQYBtsC3Q6sg9J3k12cdEsnCBQdAaDkqSrosq",
                             endpoint="https://api.aiproxy.io/v1")
    prompt = build_messages("你好", "你好")
    answer, tokens = openai.completion(prompt)
    return answer, tokens


def test_openai_gpt(openai_gpt_client):
    assert isinstance(openai_gpt_client, tuple), "openai_gpt_client 不是一个元组"
