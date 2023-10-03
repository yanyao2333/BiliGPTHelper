import abc


class ASR:
    @abc.abstractmethod
    async def transcribe(self, *args, **kwargs):
        """
        转写方法，需要实现
        注意，这个方法中的转写部分不能阻塞，否则你要实现下方的_wait_transcribe方法，并在这里采用 **线程池** 方式调用
        """
        pass

    def _wait_transcribe(self, *args, **kwargs):
        """
        阻塞转写方法，选择性实现
        """
        pass
