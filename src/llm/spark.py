import ast
import base64
import hashlib
import hmac
import json
import traceback
from datetime import datetime
from time import mktime
from typing import Tuple
from urllib.parse import urlencode, urlparse
from wsgiref.handlers import format_date_time

import websockets

from src.llm.llm_base import LLMBase
from src.llm.templates import Templates
from src.utils.logging import LOGGER
from src.utils.prompt_utils import build_openai_style_messages, parse_prompt

_LOGGER = LOGGER.bind(name="spark")


class Spark(LLMBase):
    def prepare(self):
        self._answer_temp = ""  # 用于存储讯飞星火大模型的返回结果
        self._once_total_tokens = 0  # 用于存储讯飞星火大模型的返回结果的token数

    def create_url(self):
        """
        生成鉴权url
        :return:
        """
        host = urlparse(self.config.LLMs.spark.spark_url).netloc
        path = urlparse(self.config.LLMs.spark.spark_url).path
        # 生成RFC1123格式的时间戳
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        # 拼接字符串
        signature_origin = "host: " + host + "\n"
        signature_origin += "date: " + date + "\n"
        signature_origin += "GET " + path + " HTTP/1.1"

        # 进行hmac-sha256进行加密
        signature_sha = hmac.new(
            self.config.LLMs.spark.api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()

        signature_sha_base64 = base64.b64encode(signature_sha).decode(encoding="utf-8")

        authorization_origin = f'api_key="{self.config.LLMs.spark.api_key}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature_sha_base64}"'

        authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode(encoding="utf-8")

        # 将请求的鉴权参数组合为字典
        v = {"authorization": authorization, "date": date, "host": host}
        # 拼接鉴权参数，生成url
        url = self.config.LLMs.spark.spark_url + "?" + urlencode(v)
        _LOGGER.debug(f"生成的url为：{url}")
        # 此处打印出建立连接时候的url,参考本demo的时候可取消上方打印的注释，比对相同参数时生成的url与自己代码生成的url是否一致
        return url

    async def on_message(self, ws, message):
        data = json.loads(message)
        code = data["header"]["code"]
        if code != 0:
            _LOGGER.error(f"讯飞星火大模型请求失败:    错误代码：{code}  返回内容：{data}")
            await ws.close()
        else:
            choices = data["payload"]["choices"]
            status = choices["status"]
            content = choices["text"][0]["content"]
            self._answer_temp += content
            if status == 2:
                self._once_total_tokens = data["payload"]["usage"]["text"]["total_tokens"]
                await ws.close()

    async def completion(self, prompt, **kwargs) -> Tuple[str, int] | None:
        try:
            ws_url = self.create_url()

            async with websockets.connect(ws_url) as websocket:
                websocket.appid = self.config.LLMs.spark.appid
                websocket.question = prompt
                websocket.domain = self.config.LLMs.spark.domain

                data = json.dumps(self.gen_params(prompt))
                await websocket.send(data)
                async for message in websocket:
                    await self.on_message(websocket, message)

            _LOGGER.debug(
                f"调用讯飞星火大模型成功，返回结果为：{self._answer_temp}，本次调用中，prompt+response的长度为{self._once_total_tokens}"
            )

            # 处理返回结果（图省事的方法）
            if self._answer_temp.startswith("```json"):
                self._answer_temp = self._answer_temp[7:]
            if self._answer_temp.endswith("```"):
                self._answer_temp = self._answer_temp[:-3]
                # TODO 星火返回的json永远是单引号包围的
            data = ast.literal_eval(self._answer_temp)  # 骚操作
            data = json.dumps(data, ensure_ascii=False)

            # TODO 重试prompt在星火这里也有很大问题，他会把json返回两遍...

            _LOGGER.debug(f"经简单处理后的返回结果为：{data}")
            return data, self._once_total_tokens
        except Exception as e:
            traceback.print_exc()
            _LOGGER.error(f"调用讯飞星火大模型失败：{e}")
            return None

    def gen_params(self, prompt_list) -> dict:
        """
        通过appid和用户的提问来生成提问参数

        :param prompt_list: 用户的提问
        """
        data = {
            "header": {
                "app_id": self.config.LLMs.spark.appid,
            },
            "parameter": {"chat": {"domain": self.config.LLMs.spark.domain, "temperature": 0.5, "max_tokens": 8192}},
            "payload": {"message": {"text": prompt_list}},
        }
        _LOGGER.debug(f"生成的参数为：{data}")
        return data

    @staticmethod
    def use_template(
        user_template_name: Templates,
        system_template_name: Templates = None,
        user_keyword="user",
        system_keyword="system",
        **kwargs,
    ) -> list | None:
        """使用模板生成最终prompt（最终格式可能需要根据llm所需格式不同修改，默认为openai的system、user格式）
        :param user_template_name: 用户模板名称
        :param system_template_name: 系统模板名称
        :param user_keyword: 用户关键词（这个和下面的system_keyword要根据每个llm不同的要求来填）
        :param system_keyword: 系统关键词
        :param kwargs: 模板参数
        :return: 返回生成的prompt 或 None
        """
        try:
            if system_template_name is None:
                template_system = None
            elif system_template_name.name == "SUMMARIZE_SYSTEM":
                template_system = """
你是一个视频摘要制作人。请根据视频的标题、描述、标签、字幕、评论来制作视频摘要。指南如下：
1. 返回的内容严格遵循此JSON格式：{"summary": "你的摘要内容", "score": "你给这个视频的评分(最高100)", "thinking": "你的想法", "if_no_need_summary": "是否需要摘要？填写布尔值"}
2. 信息要完整且信息量大。
3. 保持准确，不要添加虚构信息。
4. 保持幽默，避免正式，需要时可以使用中文网络语言和表情符号。
5. 忽略不相关的标签/评论。
6. 分段落写作。
7. 'score'部分的值必须是字符串类型。
8. 写作'thinking'部分时，忽略上述规则，表达你的独立思考，包括你自己的激进观点，而非视频内容。评分基于这个视频。如果你认为你创造了一个有意义的摘要，给自己一个高分。
9. 如果视频毫无意义，将此JSON的'if_no_need_summary'设置为true，否则设置为false。
10. 只允许纯JSON内容，必须使用双引号！请使用简体中文!
"""
            else:
                template_system = system_template_name.value
            if user_template_name.name == "SUMMARIZE_USER":
                template_user = (
                    """标题：[title]\n\n简介：[description]\n\n字幕：[subtitle]\n\n标签：[tags]\n\n评论：[comments]"""
                )
            elif user_template_name.name == "ASK_AI_USER":
                template_user = """
标题: [title]\n\n简介: [description]\n\n字幕: [subtitle]\n\n用户问题: [question]\n\n
你是一位专业的视频问答老师。我将提供给你视频的标题、描述和字幕。根据这些信息和你的专业知识，以生动幽默的方式回答用户的问题，必要时使用比喻和例子。
请按照以下JSON格式回复：{"answer": "你的回答", "score": "你对回答质量的自我评分(0-100)"}
!!!只允许使用双引号的纯JSON内容！请使用中文！不要添加任何其他内容!!!
"""
            else:
                template_user = user_template_name.value
            utemplate = parse_prompt(template_user, **kwargs)
            stemplate = parse_prompt(template_system, **kwargs) if template_system else None
            prompt = (
                build_openai_style_messages(utemplate, stemplate, user_keyword, system_keyword)
                if stemplate
                else build_openai_style_messages(utemplate, user_keyword=user_keyword)
            )
            _LOGGER.info("使用模板成功")
            _LOGGER.debug(f"生成的prompt为：{prompt}")
            return prompt
        except Exception as e:
            _LOGGER.error(f"使用模板失败：{e}")
            traceback.print_exc()
            return None
