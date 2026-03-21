"""采集器统一错误层级。灵感：OpenCLI 的 CliError (code + hint)。"""


class CollectorError(Exception):
    code: str = "UNKNOWN"
    hint: str = ""
    retryable: bool = False

    def __init__(self, code: str = None, hint: str = None):
        self.code = code or self.__class__.code
        self.hint = hint or self.__class__.hint
        super().__init__(f"[{self.code}] {self.hint}")


class TransientError(CollectorError):
    retryable = True


class PermanentError(CollectorError):
    retryable = False
