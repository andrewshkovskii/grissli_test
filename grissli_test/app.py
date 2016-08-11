"""

    grissli_test.app
    ~~~~~~~~~~~~~~~~

    Инициализация приложения.

"""
from grissli_test.application import Application
from grissli_test.subsystems import parsman


async def create_app(loop, **kwargs):
    """Создать приложение.

    :param loop: эвент-луп.
    """
    app = Application(loop=loop, **kwargs)
    await parsman.init_app(app)
    return app
