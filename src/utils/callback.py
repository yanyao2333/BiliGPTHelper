import traceback

import loguru


def chain_callback(retry_state):
    """处理链重试回调函数"""
    _LOGGER = loguru.logger
    exception = retry_state.outcome.exception()
    _LOGGER.error(f"捕获到错误：{exception}")
    traceback.print_tb(retry_state.outcome.exception().__traceback__)
    _LOGGER.debug(f"当前重试次数为{retry_state.attempt_number}")
    _LOGGER.debug(f"下一次重试将在{retry_state.next_action.sleep}秒后进行")