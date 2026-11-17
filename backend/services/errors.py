class ServiceError(Exception):
    """上游服务错误。默认 503（暂时不可用）；调用方可指定 404/429/502 等更准确的语义。"""

    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code

class ModelOutputError(ServiceError):
    """模型返回内容无法按要求解析：属于上游异常，默认 502。"""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message, status_code)
