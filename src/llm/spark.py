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
from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="spark")

class Spark(LLMBase):
    def prepare(self):
        self._answer_temp = "" # 用于存储讯飞星火大模型的返回结果
        self._once_total_tokens = 0 # 用于存储讯飞星火大模型的返回结果的token数

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
        signature_sha = hmac.new(self.config.LLMs.spark.api_secret.encode('utf-8'), signature_origin.encode('utf-8'),
                                 digestmod=hashlib.sha256).digest()

        signature_sha_base64 = base64.b64encode(signature_sha).decode(encoding='utf-8')

        authorization_origin = f'api_key="{self.config.LLMs.spark.api_key}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature_sha_base64}"'

        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')

        # 将请求的鉴权参数组合为字典
        v = {
            "authorization": authorization,
            "date": date,
            "host": host
        }
        # 拼接鉴权参数，生成url
        url = self.config.LLMs.spark.spark_url + '?' + urlencode(v)
        _LOGGER.debug(f"生成的url为：{url}")
        # 此处打印出建立连接时候的url,参考本demo的时候可取消上方打印的注释，比对相同参数时生成的url与自己代码生成的url是否一致
        return url

    async def on_message(self, ws, message):
        data = json.loads(message)
        code = data['header']['code']
        if code != 0:
            _LOGGER.error(f'讯飞星火大模型请求失败:    错误代码：{code}  返回内容：{data}')
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
                f"调用讯飞星火大模型成功，返回结果为：{self._answer_temp}，本次调用中，prompt+response的长度为{self._once_total_tokens}")

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
            "parameter": {
                "chat": {
                    "domain": self.config.LLMs.spark.domain,
                    "temperature": 0.5,
                    "max_tokens": 8192
                }
            },
            "payload": {
                "message": {
                    "text": prompt_list
                }
            }
        }
        _LOGGER.debug(f"生成的参数为：{data}")
        return data