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

    async def on_message(self, ws, message) -> int:
        """

        :param ws:
        :param message:
        :return: 1为还未结束 0为正常结束 2为异常结束
        """
        data = json.loads(message)
        code = data["header"]["code"]
        if code != 0:
            _LOGGER.error(f"讯飞星火大模型请求失败:    错误代码：{code}  返回内容：{data}")
            await ws.close()
            if code == 10013 or code == 10014:
                self._once_total_tokens = 0
                self._answer_temp = """{"summary":"⚠⚠⚠我也很想告诉你视频的总结，但是星火却跟我说这个视频的总结是***，真的是离谱他🐎给离谱开门——离谱到家了。我也没有办法，谁让星火可以白嫖500w个token🐷。为了白嫖，忍一下，换个视频试一试！","score":"0","thinking":"🤡老子是真的服了这个讯飞星火，国际友好手势(一种动作)。","if_no_need_summary": false}"""
                return 0
            return 2
        else:
            choices = data["payload"]["choices"]
            status = choices["status"]
            content = choices["text"][0]["content"]
            self._answer_temp += content
            if status == 2:
                self._once_total_tokens = data["payload"]["usage"]["text"]["total_tokens"]
                await ws.close()
                return 0
            return 1

    async def completion(self, prompt, **kwargs) -> Tuple[str, int] | None:
        try:
            self._answer_temp = ""
            self._once_total_tokens = 0
            ws_url = self.create_url()

            async with websockets.connect(ws_url) as websocket:
                websocket.appid = self.config.LLMs.spark.appid
                websocket.question = prompt
                websocket.domain = self.config.LLMs.spark.domain

                data = json.dumps(self.gen_params(prompt))
                await websocket.send(data)
                async for message in websocket:
                    res = await self.on_message(websocket, message)
                    if res == 2:
                        # 如果出现异常，直接返回（上层已经打印过错误，直接返回）
                        return None
            _LOGGER.info(
                f"调用讯飞星火大模型成功，返回结果为：{self._answer_temp}，本次调用中，prompt+response的长度为{self._once_total_tokens}"
            )

            # 处理返回结果（图省事的方法）
            if self._answer_temp.startswith("```json"):
                self._answer_temp = self._answer_temp[7:]
            if self._answer_temp.endswith("```"):
                self._answer_temp = self._answer_temp[:-3]
            # 星火返回的json永远是单引号包围的，下面尝试使用eval方式解析
            # try:
            #     _answer = self._answer_temp
            #     _answer = _answer.replace("true", "True")
            #     _answer = _answer.replace("false", "False")
            #     _answer = ast.literal_eval(_answer)  # 骚操作
            #     _answer = json.dumps(_answer, ensure_ascii=False)
            #     _LOGGER.debug(f"经简单处理后的返回结果为：{_answer}")
            #     return _answer, self._once_total_tokens
            # except Exception as e:
            #     _LOGGER.error(f"尝试使用eval方式解析星火返回的json失败：{e}")
            #     traceback.print_exc()
            # 如果eval方式解析失败，直接返回
            _LOGGER.debug(f"经简单处理后的返回结果为：{self._answer_temp}")
            return self._answer_temp, self._once_total_tokens
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
            "parameter": {
                "chat": {
                    "domain": self.config.LLMs.spark.domain,
                    "temperature": 0.5,
                    "max_tokens": 8192,
                }
            },
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
7. "score"部分的值必须是字符串类型。
8. 写作"thinking"部分时，忽略上述规则，表达你的独立思考，包括你自己的激进观点，而非视频内容。评分基于这个视频。如果你认为你创造了一个有意义的摘要，给自己一个高分。
9. 如果视频毫无意义，将此JSON的"if_no_need_summary"设置为true，否则设置为false。
10. 返回的内容只允许纯JSON格式，JSON的键和值必须使用英文双引号包裹！请使用简体中文!
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
            elif user_template_name.name == "SUMMARIZE_RETRY":
                template_user = """请将以下文本翻译成此JSON格式并返回给我，不要添加任何其他内容。如果不存在 'summary' 字段，请将 'if_no_need_summary' 设置为 true。如果除 'summary' 之外的字段缺失，则可以忽略并留空， 'if_no_need_summary' 保持 false\n\n标准JSON格式：{"summary": "您的摘要内容", "score": "您给这个视频的评分（最高100分）", "thinking": "您的想法", "if_no_need_summary": "是否需要摘要？填写布尔值"}\n\n我的内容：[input]"""
            else:
                template_user = user_template_name.value
            utemplate = parse_prompt(template_user, **kwargs)
            stemplate = parse_prompt(template_system, **kwargs) if template_system else None
            # final_template = utemplate + stemplate if stemplate else utemplate # 特殊处理，system附加到user后面
            prompt = (
                build_openai_style_messages(utemplate, stemplate, user_keyword, system_keyword)
                if stemplate
                else build_openai_style_messages(utemplate, user_keyword=user_keyword)
                # build_openai_style_messages(final_template, user_keyword=user_keyword)
            )
            _LOGGER.info("使用模板成功")
            _LOGGER.debug(f"生成的prompt为：{prompt}")
            return prompt
        except Exception as e:
            _LOGGER.error(f"使用模板失败：{e}")
            traceback.print_exc()
            return None
