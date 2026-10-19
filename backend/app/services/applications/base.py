"""Expected domain errors are safe to return at both authenticated interfaces."""


class ApplicationError(Exception):
    status_code = 409


class ApplicationNotFound(ApplicationError):
    status_code = 404


class ApplicationInvalid(ApplicationError):
    status_code = 422


class ApplicationConflict(ApplicationError):
    pass
