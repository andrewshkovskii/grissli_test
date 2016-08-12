"""

    grissli_test.parsman.ext
    ~~~~~~~~~~~~~~~~~~~~~~~~

    Реализация подсистемы парсинга и оповещения о состоянии обработки URL.

    Caveats:
        -   Запись на диск файла является блокирующей операцией, можно
            выполнить ее в отдельном процессе, но такого в задании указано
            не было
        -   Сервер хранит результаты обработки только в период своей "жизни",
            обратного в задании указано не было. Можно использовать любое
            легковесное хранилище (я бы взял redis и aioredis)
        -   Неплохо было бы добавить логирование
        -   Хорошо бы вынести все настройки путей, портов и адресо в .conf
            файл для облегчения настройки
        -   Статику отдавать через nginx

"""
import asyncio
import concurrent.futures
import json
import os
from datetime import datetime
from enum import Enum
from functools import partial
from urllib.parse import urljoin
from uuid import uuid4

from aiohttp import ClientSession
from aiohttp import web
from aiohttp.errors import HttpProcessingError
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from grissli_test import settings

TEMPLATE_CACHE = {}


# Статусы процесса обработки URL
class URLStatus(Enum):
    """Статусы обработки URL"""
    DOWNLOADING = 'downloading'
    DOWNLOADED = 'downloaded'
    PARSING = 'parsing'
    DONE_PARSING = 'done_parsing'
    IMAGE_LOAD = 'image_load'
    DONE = 'done'
    CANCEL = 'cancel'
    FAIL_TO_CANCEL = 'fail_to_cancel'
    CANCELLED = 'cancelled'
    ERROR = 'error'

    def __str__(self):
        return self.value

# Шаблоны сообщение об ошибках
ERROR_IMAGE_IO = 'Не смогли сохранить изображение на сервере ({0})'
ERROR_IMAGE_HTTP = 'Не смогли загрузить изображение на сервер ({0})'
ERROR_PARSING = 'Произошла ошибка при парсинге URL ({0})'
ERROR_URL_DOWNLOAD = 'Не смогли загрузить содержимое URL({0})'

# Сообщения для клиентов
MSG_LIMIT_EXCEED = 'Первышено количество одновременно обрабатываемых URL'

# Количество одновременно обрабатываемых URL
MAX_ACTIVE = 5
MAX_ACTIVE_CLASSES = (URLStatus.DOWNLOADING, URLStatus.DOWNLOADED)


class URL:
    """Класс представляющий объект задачи парсинга URL результат
    этого парсинга

    Attributes:
        uuid (str): Уникальный идентификатор URL
        url (str): URL
        status (str): текущий статус обработки URL
        title (str): текст тега title в скачанном html
        h1 (str): Текст первого тега H1 в скачанном html
        image_src (str): Аттрибут src первого тега img в скачанном html
        image_path (str): Путь к файлу-изображению, закаченнуму на сервер
        date (datetime): Дата для начала обработки URL
        future (asyncio.Future): Future-объект текущей задачи обработки URL
        error (str): Текст ошибки при обработке URL
        html (str): HTML-код скачанного URL

    """
    uuid = None
    url = None
    status = None
    html = None
    title = None
    h1 = None
    image_src = None
    image_path = None
    date = None
    future = None
    error = None

    def __init__(self, url, date):
        """Инициализация класса

        :param url: URL для парсинга
        :param date: Дата для начала парсинга URL

        """
        self.uuid = str(uuid4())
        self.status = URLStatus.DOWNLOADING
        self.date = date
        self.url = url

    def as_dict(self):
        """Вернуть представление URL ввиде словаря

        :return dict-объект представления класса URL

        """
        image_path = None
        if self.image_path:
            image_path = os.path.basename(self.image_path)
            image_path = os.path.join('images', image_path)

        data = {
            'uuid': str(self.uuid),
            'url': self.url,
            'status': str(self.status),
            'title': self.title,
            'h1': self.h1,
            'image_src': self.image_src,
            'image_path': image_path,
            'error': self.error
        }
        return data

    def set_parse_result(self, title, h1, image_src):
        """Записать результат парсинга URL

        :param title:
        :param h1:
        :param image_src:

        """
        self.title = title
        self.h1 = h1
        if image_src:
            self.image_src = urljoin(self.url, image_src)
        return None


def parse_html(html):
    """Парсинг HTML-документа.

    :param html: HTML-документ для парсинга

    :return: tuple из 3 элементов:
        содержимое тега title
        содержимое первого тега h1
        аттрибут src первого тега img

    """
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title
    if title:
        title = title.text
    h1 = soup.find('h1')
    if h1:
        h1 = h1.text
    image = soup.find('img')
    if image:
        image = image.get('src')

    return title, h1, image


class Parsman:
    def __init__(self, app=None):
        self.app = app
        if self.app:
            self.init_app(self.app)
        self.executor = concurrent.futures.ProcessPoolExecutor()
        self.message_queue = asyncio.Queue()
        self.processing_futures = {}
        self.urls = {}
        # Инициализация кеша шаблонов
        template_path = os.path.join(settings.TEMPLATES_DIR, 'index.html')
        template_file = open(template_path, 'rb')
        template = template_file.read()
        template_file.close()
        TEMPLATE_CACHE[template_path] = template

    async def init_app(self, app):
        """Инициировать приложение."""
        # assert app
        self.app = app

        await self.init_routes()
        await self.init_listener()
        self.app.on_shutdown.append(self.on_shutdown)
        return None

    async def init_routes(self):
        """Инициировать хэндлеры точек API."""
        self.app.router.add_route('GET', '/', self.index)
        self.app.router.add_route('POST', '/url/', self.add_urls)
        self.app.router.add_route('GET', '/url/', self.get_urls)
        self.app.router.add_route('POST', '/url/{uuid}/cancel/',
                                  self.cancel_url)
        self.app.router.add_route('GET', '/events/', self.handle_sock)
        # Статика и изображения
        self.app.router.add_static('/images/', settings.IMAGE_DIR)
        self.app.router.add_static('/static/', settings.STATIC_DIR)
        return None

    async def init_listener(self):
        """Инициировать обработчики сообщений из очереди."""
        self.messaging = asyncio.ensure_future(self.handle_messages(),
                                               loop=self.app.loop)
        self.scheduler = asyncio.ensure_future(self.start_scheduler(),
                                               loop=self.app.loop)
        return None

    async def on_shutdown(self, app):
        """Остановить подсистему приложения."""
        self.executor.shutdown(False)
        self.messaging.cancel()
        self.scheduler.cancel()
        for url in self.urls.values():
            future = url.future
            if future:
                future.cancel()
        for client in self.app.websockets:
            await client.close(code=999, message='Server shutdown')
        return None

    async def handle_messages(self):
        """Прослушивание и обработка очереди сообщений"""
        while True:
            message = await self.message_queue.get()
            if message['message'] == 'status_change':
                # Отправим сообщение о смене статуса клиентам
                self.socket_message('status_change', message['payload'])

                # Оповестить всех клиентов о новом URL
                if message['payload']['status'] == str(URLStatus.DOWNLOADING):
                    uuid = message['payload']['uuid']
                    self.socket_message('url_add', self.urls[uuid].as_dict())

    @asyncio.coroutine
    def handle_sock(self, request):
        """Инициировать соединение через websocket.

        :param request: запрос.

        """
        ws = web.WebSocketResponse()
        yield from ws.prepare(request)

        self.app.websockets.append(ws)
        try:
            while not ws.closed:
                msg = yield from ws.receive()
                if msg.tp == web.MsgType.close:
                    break
        finally:
            self.app.websockets.remove(ws)
        return ws

    async def index(self, request):
        """Начальная страница приложения

        :param request: запрос.

        """
        template_path = os.path.join(settings.TEMPLATES_DIR, 'index.html')
        template = TEMPLATE_CACHE[template_path]
        return web.Response(body=template)

    async def get_urls(self, request):
        """Получить список текущих URL

        :param request: запрос.

        """
        data = []
        for uuid, url in self.urls.items():
            data.append(url.as_dict())
        return web.Response(body=json.dumps(data).encode('utf-8'))

    async def add_urls(self, request):
        """Добавить URL на обработку

        :param request: запрос.

        """
        # Если есть 5 не подвергнутых парсингу URL
        current_urls = 0
        for url in self.urls.values():
            if url.status in MAX_ACTIVE_CLASSES:
                current_urls += 1
        # То мы не можем добавить URL для обработки
        if current_urls >= MAX_ACTIVE:
            message = {'error_message': MSG_LIMIT_EXCEED}
            return web.Response(body=json.dumps(message).encode('utf-8'))

        data = await request.json()
        urls = data['urls']

        # игнорируют таймзону т.к. будем сранивать эту дату с
        # tz-aware datetime.utcnow()
        date = date_parser.parse(data['date'], ignoretz=True)
        added_urls = []
        for url in urls:
            url = self.add_url(url['url'], date)
            added_urls.append(url.as_dict())

        return web.Response(body=json.dumps(added_urls).encode('utf-8'))

    async def cancel_url(self, request):
        """Отменить обработку URL"""
        uuid = request.match_info['uuid']
        self.cancel_parsing(uuid)
        return web.Response(body=b'')

    def add_url(self, url, date):
        """Создать URL, скачать ее ресурс и добавить к обработке

        :param url: URL-адрес для обработки
        :param date: Дата-время начала обработки URL

        :return Созданный объект класса URL

        """
        url = URL(url, date)
        self.urls[url.uuid] = url
        future = asyncio.ensure_future(self.download(url.uuid),
                                       loop=self.app.loop)
        url.future = future
        payload = {'status': str(URLStatus.DOWNLOADING), 'uuid': url.uuid}
        self.message('status_change', payload)
        return url

    async def start_scheduler(self):
        """Обработчик отложенных задач по парсингу URL"""
        while True:
            for uuid, url in self.urls.items():
                # Парсингу подвергаются только те url, что были скачаны
                if url.status != URLStatus.DOWNLOADED:
                    continue

                # И пришло время их парсить
                if url.date > datetime.utcnow():
                    continue

                payload = {'status': str(URLStatus.PARSING), 'uuid': uuid}
                url.status = URLStatus.PARSING
                self.message('status_change', payload)
                # Запускаем парсинг в отдельном процессе
                future = self.executor.submit(parse_html, url.html)
                url.future = future
                # И продолжим обработки как только фьючер закончит
                future.add_done_callback(partial(self.message_done_parsing,
                                                 uuid))
            # Проверяем новые задачи каждые 5 секунд
            await asyncio.sleep(5)
        return None

    async def download(self, uuid):
        """Загрузить контент URL

        :param uuid: UUID URL

        """
        url = self.urls[uuid]
        async with ClientSession() as session:
            try:
                async with session.get(url.url) as resp:
                    resp.raise_for_status()
                    url.html = await resp.text()
            except (HttpProcessingError, ValueError) as e:
                status = URLStatus.ERROR
                url.error = ERROR_URL_DOWNLOAD.format(e)
            else:
                status = URLStatus.DOWNLOADED

            url.status = status
            payload = {'status': str(status), 'uuid': uuid}
            self.message('status_change', payload)
        return None

    async def download_image(self, uuid):
        """Загрузить и сохранить в файл изображение из тега img URL'а

        :param uuid: UUID URL

        """
        url = self.urls[uuid]
        url.status = URLStatus.IMAGE_LOAD
        payload = {'status': str(URLStatus.IMAGE_LOAD), 'uuid': uuid}
        self.message('status_change', payload)
        image_src = url.image_src
        image_name = os.path.basename(image_src)
        file_path = os.path.join(settings.IMAGE_DIR, uuid + '-' + image_name)

        async with ClientSession() as session:
            try:
                async with session.get(image_src) as resp:
                    resp.raise_for_status()
                    img_data = await resp.read()
                    try:
                        with open(file_path, 'wb') as file:
                            file.write(img_data)
                    except IOError as e:
                        url.error = ERROR_IMAGE_IO.format(e)
            except (HttpProcessingError, ValueError) as e:
                url.error = ERROR_IMAGE_HTTP.format(e)

        url.image_path = file_path
        url.status = URLStatus.DONE
        payload = url.as_dict()

        self.message('status_change', payload)
        return None

    def cancel_parsing(self, uuid):
        """Отменить выполнение парсинга URL

        :param uuid: UUID URL

        """
        url = self.urls.get(uuid)
        if not url:
            return None
        if url.status == URLStatus.DONE:
            return None
        url.status = URLStatus.CANCEL
        payload = {'status': str(URLStatus.CANCEL), 'uuid': uuid}
        self.message('status_change', payload)
        future = url.future
        if future:
            # Если удалось отменить
            if future.cancel():
                url.status = URLStatus.CANCELLED
                payload = {'status': str(URLStatus.CANCELLED), 'uuid': uuid}
            else:
                url.status = URLStatus.FAIL_TO_CANCEL
                payload = {'status': str(URLStatus.FAIL_TO_CANCEL),
                           'uuid': uuid}

            self.message('status_change', payload)
        return None

    def message_done_parsing(self, uuid, future):
        """Отправить сообщение о завершении парсинга URL

        :param uuid: UUID URL
        :param future: Future задачи парсинга URL.

        """
        # Если фьючер не был отменен
        if not future.cancelled():
            url = self.urls[uuid]
            try:
                title, h1, src = future.result()
            except Exception as e:
                status = URLStatus.ERROR
                payload = {'status': str(URLStatus.ERROR), 'uuid': uuid}
                url.error = ERROR_PARSING.format(e)
            else:
                status = URLStatus.DONE_PARSING
                payload = {'uuid': uuid, 'title': title,
                           'h1': h1, 'image_src': src,
                           'status': str(URLStatus.DONE_PARSING)}
                url.set_parse_result(title, h1, src)

                # Отправим на дальнейшую обработку для скачивания изображения
                future = asyncio.ensure_future(self.download_image(uuid),
                                               loop=self.app.loop)
                url.future = future

            url.status = status
            self.message('status_change', payload, True)
        return None

    def message(self, message, payload, no_wait=False):
        """Отправить сообщение message с нагрузкой payload для обработке
        в общей очереди сообщений обработчика

        :param message: Текст сообщения
        :param payload: Полезная нагрузка сообщения
        :param no_wait: Отправить сообщение с блокировкой или нет

        """
        message = {'message': message, 'payload': payload}
        if no_wait:
            self.message_queue.put_nowait(message)
        else:
            asyncio.ensure_future(self.message_queue.put(message),
                                  loop=self.app.loop)
        return None

    def socket_message(self, message, payload=None):
        """Отправить сообщение в вебсокеты клиентов

        :param message: Заголовок сообщения
        :param payload: Полезная нагрузка сообщения
        """
        message = {'message': message, 'payload': payload}
        message = json.dumps(message)
        for socket in self.app.websockets:
            socket.send_str(message)
        return None
