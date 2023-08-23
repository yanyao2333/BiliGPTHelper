from bilibili_api import video, Credential, parse_link, ResourceType


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
        _type = ResourceType.VIDEO
        if self.video_obj:
            return self.video_obj
        if self.url:
            self.video_obj, _type = await parse_link(self.url, credential=self.credential)
        elif self.aid:
            self.video_obj = video.Video(aid=self.aid, credential=self.credential)
        elif self.bvid:
            self.video_obj = video.Video(bvid=self.bvid, credential=self.credential)
        else:
            raise ValueError("缺少必要参数")
        return self.video_obj, _type

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

    async def get_video_subtitle(self, cid: int = None, page_index: int = 0):
        """返回字幕链接，如果有多个字幕则优先返回非ai和翻译字幕，如果没有则返回ai字幕"""
        if not self.video_obj:
            await self.get_video_obj()
        if not cid:
            cid = await self.video_obj.get_cid(page_index=page_index)
        info = await self.video_obj.get_player_info(cid=cid)
        json_files = info["subtitle"]["subtitles"]
        if len(json_files) == 0:
            return None
        if len(json_files) == 1:
            return json_files[0]["subtitle_url"]
        for subtitle in json_files:
            if subtitle["lan_doc"] != "中文（自动翻译）" and subtitle["lan_doc"] != "中文（自动生成）":
                return subtitle["subtitle_url"]
        for subtitle in json_files:
            if subtitle["lan_doc"] == "中文（自动翻译）" or subtitle["lan_doc"] == "中文（自动生成）":
                return subtitle["subtitle_url"]
