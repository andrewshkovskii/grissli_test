"""

    grissli_test.application
    ~~~~~~~~~~~~~~~~~~~~~~~~

    Базовое приложение aiohttp.

"""
from aiohttp import web


class Application(web.Application):
    """Базовое приложение aiohttp.

    :param loop: эвент-луп.
    :param websockets: список всех ws-соединений для дальнейшей зачистки.
    """

    websockets = []

    def __init__(self, *, loop, **kwargs):
        super().__init__(**kwargs)
