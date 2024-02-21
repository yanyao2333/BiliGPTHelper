import traceback

import loguru

_LOGGER = loguru.logger


def chain_callback(retry_state):
    """处理链重试回调函数"""
    exception = retry_state.outcome.exception()
    _LOGGER.error(f"捕获到错误：{exception}")
    traceback.print_tb(retry_state.outcome.exception().__traceback__)
    _LOGGER.debug(f"当前重试次数为{retry_state.attempt_number}")
    _LOGGER.debug(f"下一次重试将在{retry_state.next_action.sleep}秒后进行")


def scheduler_error_callback(event):
    match event.exception.__class__.__name__:
        case "ClientOSError":
            _LOGGER.warning(
                f"捕获到异常：{event.exception}    可能是新版bilibili_api库的问题，接收消息没问题就不用管"
            )
        case _:
            return
