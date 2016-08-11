import asyncio
import functools
import signal

from grissli_test.app import create_app


def main():
    loop = asyncio.get_event_loop()
    app = loop.run_until_complete(create_app(loop))
    handler = app.make_handler()
    server = loop.run_until_complete(loop.create_server(
        handler, '127.0.0.1', 8000))

    def ask_exit(signame):
        """Остановить эвент-луп при получении сигнала остановки."""
        loop.stop()

    # Чистая остановка при получении SIGINT или SIGTERM
    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(
            getattr(signal, signame), functools.partial(ask_exit, signame))

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        loop.run_until_complete(server.wait_closed())
        loop.run_until_complete(app.shutdown())
        loop.run_until_complete(handler.finish_connections(60.0))
        loop.run_until_complete(app.cleanup())
    loop.close()

if __name__ == '__main__':
    main()
