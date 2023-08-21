from datetime import datetime

from bilibili_api import Credential
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="bilibili-credential")


class BiliCredential(Credential):
    """B站凭证类，主要增加定时检查cookie是否过期"""

    def __init__(
        self,
        SESSDATA: str,
        bili_jct: str,
        buvid3: str,
        dedeuserid: str,
        ac_time_value: str,
    ):
        """
        全部强制要求传入，以便于cookie刷新
        :param SESSDATA:
        :param bili_jct:
        :param buvid3:
        :param dedeuserid:
        :param ac_time_value:
        """
        super().__init__(
            sessdata=SESSDATA,
            bili_jct=bili_jct,
            buvid3=buvid3,
            dedeuserid=dedeuserid,
            ac_time_value=ac_time_value,
        )
        self.sched = AsyncIOScheduler(timezone="Asia/Shanghai")

    async def _check_refresh(self):
        """检查cookie是否过期"""
        if await self.check_refresh():
            _LOGGER.info("cookie过期，正在刷新")
            await self.refresh()
            _LOGGER.info("cookie刷新成功")
        else:
            _LOGGER.debug("cookie未过期")
        if await self.check_valid():
            _LOGGER.debug("cookie有效")
        else:
            _LOGGER.warning("cookie刷新后依旧无效，请关注！")

    def start_check(self):
        self.sched.add_job(
            self.check_refresh,
            trigger="interval",
            seconds=60,
            id="check_refresh",
            max_instances=3,
            next_run_time=datetime.now(),
        )
        self.sched.start()
        _LOGGER.info("[定时任务]检查cookie是否过期定时任务注册成功， 每60秒检查一次")
