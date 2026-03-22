class AppError(Exception):
    def __init__(self, detail: str, status_code: int = 400, code: str | None = None):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.code = code


class ValidationError(AppError):
    def __init__(self, detail: str, code: str | None = None):
        super().__init__(detail=detail, status_code=400, code=code)


class NotFoundError(AppError):
    def __init__(self, detail: str, code: str | None = None):
        super().__init__(detail=detail, status_code=404, code=code)


class ConflictError(AppError):
    def __init__(self, detail: str, code: str | None = None):
        super().__init__(detail=detail, status_code=409, code=code)


class ForbiddenError(AppError):
    def __init__(self, detail: str, code: str | None = None):
        super().__init__(detail=detail, status_code=403, code=code)
