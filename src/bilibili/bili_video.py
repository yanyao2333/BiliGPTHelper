from bilibili_api import video, Credential, parse_link


class BiliVideo:
    def __init__(
        self, credential: Credential, bvid: str = None, aid: int = None, url: str = None
    ):
        """
        三选一，优先级为url > aid > bvid
        :param credential:
        :param bvid:
        :param aid:
        :param url:
        """
        self.credential = credential
        self.bvid = bvid
        self.aid = aid
        self.url = url
        self.video_obj: video.Video = None

    async def get_video_obj(self):
        if self.video_obj:
            return self.video_obj
        if self.url:
            self.video_obj = await parse_link(self.url, credential=self.credential)
        elif self.aid:
            self.video_obj = video.Video(aid=self.aid, credential=self.credential)
        elif self.bvid:
            self.video_obj = video.Video(bvid=self.bvid, credential=self.credential)
        else:
            raise ValueError("缺少必要参数")
        return self.video_obj

    async def get_video_info(self):
        if not self.video_obj:
            await self.get_video_obj()
        return await self.video_obj.get_info()

    async def get_video_pages(self):
        if not self.video_obj:
            await self.get_video_obj()
        return await self.video_obj.get_pages()

    async def get_video_tags(self, page_index: int = 0):
        if not self.video_obj:
            await self.get_video_obj()
        return await self.video_obj.get_tags(page_index=page_index)

    async def get_video_download_url(self, page_index: int = 0):
        if not self.video_obj:
            await self.get_video_obj()
        return await self.video_obj.get_download_url(page_index=page_index)
