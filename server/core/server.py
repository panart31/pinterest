"""TCP-сервер: цикл accept и поток на каждое соединение.

Главный поток только принимает соединения. Вся обработка запроса
выполняется в отдельном потоке, поэтому медленный клиент не блокирует
остальных. Для учебного масштаба такой модели достаточно: операции
ограничены диском и SQLite, а не процессором.

Каждый запрос получает короткий идентификатор, который попадает
в журнал доступа и в заголовок ответа ``X-Request-Id``. По нему можно
связать строку журнала с конкретным ответом клиенту.
"""

from __future__ import annotations

import errno
import logging
import socket
import threading
import time
import traceback
import uuid
from types import TracebackType

from ..config import Config
from ..http.request import HTTPError, Request, read_request
from ..http.response import Response
from .clock import utc_now

access_logger = logging.getLogger("mosaic.access")
error_logger = logging.getLogger("mosaic.server")

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

SLOW_REQUEST_MS = 1000.0


def _access_stamp() -> str:
    """Дата в формате журнала веб-сервера: 22/Nov/2026:10:15:00 +0300."""
    now = utc_now().astimezone()
    return (f"{now.day:02d}/{_MONTHS[now.month - 1]}/{now.year}:"
            f"{now.hour:02d}:{now.minute:02d}:{now.second:02d} "
            f"{now.strftime('%z')}")


def _lingering_close(connection: socket.socket) -> None:
    """Аккуратно закрывает соединение, дочитывая остаток тела.

    Если сервер отверг большой запрос (413), но не прочитал тело,
    обычное close() сбрасывает соединение (RST), и клиент может
    потерять уже отправленный ответ. Поэтому сначала закрываем
    отправляющую половину, а затем дочитываем поток до конца.
    """
    try:
        connection.shutdown(socket.SHUT_WR)
    except OSError:
        return
    try:
        connection.settimeout(0.5)
        while connection.recv(65536):
            pass
    except OSError:
        pass


def _port_in_use(host: str, port: int) -> bool:
    """Проверяет, принимает ли адрес TCP-подключения.

    На Windows ``SO_REUSEADDR`` позволяет двум процессам слушать один
    порт, поэтому проверка выполняется заранее: иначе второй сервер
    молча перехватывал бы часть запросов.

    Args:
        host: адрес из конфигурации (может быть ``0.0.0.0``).
        port: проверяемый порт.

    Returns:
        True, если подключение установилось.
    """
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    try:
        with socket.create_connection((probe_host, port), timeout=0.4):
            return True
    except OSError:
        return False


class HTTPServer:
    """Минимальный TCP-сервер с моделью «поток на соединение».

    Attributes:
        config: Конфигурация с адресом, портом и лимитами.
        application: Приложение, которое превращает Request в Response.
        port: Фактический порт после bind (полезно при port=0 в тестах).
    """

    def __init__(self, config: Config, application):
        """Запоминает конфигурацию и приложение, но не открывает сокет.

        Args:
            config: Параметры сервера.
            application: Объект с методом ``dispatch(request)``.
        """
        self.config = config
        self.application = application
        self.port = config.port
        self._socket: socket.socket | None = None
        self._running = False
        self._threads: list[threading.Thread] = []

    # ------------------------------------------------------------- запуск
    def start(self) -> None:
        """Создаёт сокет, привязывает к адресу и начинает слушать.

        Raises:
            OSError: если порт занят или адрес недоступен.
        """
        if self.config.port and _port_in_use(self.config.host,
                                             self.config.port):
            raise OSError(errno.EADDRINUSE,
                          f"Порт {self.config.port} уже занят")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.config.host, self.config.port))
        sock.listen(self.config.backlog)
        self._socket = sock
        self.port = sock.getsockname()[1]
        self._running = True
        error_logger.info("Сервер слушает %s:%s", self.config.host, self.port)

    def serve_forever(self) -> None:
        """Принимает соединения до вызова ``shutdown()``.

        На каждое соединение создаётся поток-демон. Список потоков
        периодически очищается от завершившихся, чтобы не рос бесконечно.
        """
        if self._socket is None:
            self.start()
        assert self._socket is not None
        while self._running:
            try:
                connection, address = self._socket.accept()
            except OSError:
                break
            self._threads = [thread for thread in self._threads
                             if thread.is_alive()]
            thread = threading.Thread(
                target=self._handle_client,
                args=(connection, address),
                name=f"client-{address[1]}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def shutdown(self) -> None:
        """Останавливает цикл accept и закрывает слушающий сокет."""
        self._running = False
        sock, self._socket = self._socket, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    # --------------------------------------------------------- обработка
    def _handle_client(self, connection: socket.socket,
                       address: tuple[str, int]) -> None:
        """Обслуживает одно соединение: запрос, ответ, закрытие.

        Метод никогда не выбрасывает исключения наружу: любая ошибка
        превращается в HTTP-ответ или запись в журнал. В конце пишется
        строка доступа с IP, пользователем, кодом, размером, временем
        и идентификатором запроса.

        Args:
            connection: принятый сокет.
            address: пара (IP, порт) клиента.
        """
        client_ip = address[0]
        status = 500
        size = 0
        linger = False
        method = "-"
        target = "-"
        version = "-"
        username = "-"
        request: Request | None = None
        request_id = uuid.uuid4().hex[:8]
        started = time.perf_counter()
        connection.settimeout(self.config.timeout)
        try:
            with connection:
                try:
                    request = read_request(connection, self.config.max_header,
                                           self.config.max_body)
                    request.remote_addr = client_ip
                    request.request_id = request_id
                    response = self.application.dispatch(request)
                except HTTPError as exc:
                    response = Response.error(exc.status, exc.message)
                    linger = exc.status == 413
                except (socket.timeout, TimeoutError):
                    response = Response.error(400, "Таймаут чтения запроса")
                except ConnectionError:
                    return
                except Exception:  # noqa: BLE001 - клиент не должен ронять сервер
                    error_logger.error(
                        "Ошибка обработки запроса id=%s %s %s:\n%s",
                        request_id, method, target, traceback.format_exc())
                    response = Response.error(500, "Внутренняя ошибка сервера")

                if request is not None:
                    method = request.method
                    target = request.target
                    version = request.version
                    if request.user:
                        username = request.user["username"]

                response.headers["X-Request-Id"] = request_id
                try:
                    size = response.send(connection)
                except OSError:
                    return
                status = response.status
                if linger:
                    _lingering_close(connection)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            access_logger.info(
                '%s - %s [%s] "%s %s %s" %s %s %.1fms id=%s',
                client_ip, username, _access_stamp(), method, target,
                version, status, size, duration_ms, request_id)
            if duration_ms >= SLOW_REQUEST_MS:
                access_logger.warning(
                    "Медленный запрос %.0f мс: %s %s id=%s",
                    duration_ms, method, target, request_id)
            if status >= 500:
                error_logger.error(
                    "Ответ %s на %s %s id=%s (%s)",
                    status, method, target, request_id, client_ip)
