from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bilibili_api import Credential
from injector import inject

from src.utils.logging import LOGGER

_LOGGER = LOGGER.bind(name="bilibili-credential")


class BiliCredential(Credential):
    """B站凭证类，主要增加定时检查cookie是否过期"""

    @inject
    def __init__(
        self,
        SESSDATA: str,
        bili_jct: str,
        buvid3: str,
        dedeuserid: str,
        ac_time_value: str,
        sched: AsyncIOScheduler = AsyncIOScheduler(timezone="Asia/Shanghai"),
    ):
        """
        全部强制要求传入，以便于cookie刷新。

        :param SESSDATA: SESSDATA cookie值
        :param bili_jct: bili_jct cookie值
        :param buvid3: buvid3 cookie值
        :param dedeuserid: dedeuserid cookie值
        :param ac_time_value: ac_time_value cookie值
        :param sched: 调度器，默认为 Asia/Shanghai 时区
        """
        super().__init__(
            sessdata=SESSDATA,
            bili_jct=bili_jct,
            buvid3=buvid3,
            dedeuserid=dedeuserid,
            ac_time_value=ac_time_value,
        )
        self.sched = sched

    async def _check_refresh(self):
        """
        检查cookie是否过期
        """
        _LOGGER.debug("正在检查cookie是否过期")
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
        """
        开始检查cookie是否过期的定时任务
        """
        self.sched.add_job(
            self._check_refresh,
            trigger="interval",
            seconds=600,
            id="check_refresh",
            max_instances=3,
            next_run_time=datetime.now(),
        )
        _LOGGER.info("[定时任务]检查cookie是否过期定时任务注册成功，每60秒检查一次")
