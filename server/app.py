"""Сборка приложения: маршруты, статические файлы, обработка ошибок.

Класс ``Application`` — это «клей» между HTTP-слоем и бизнес-логикой.
Обработчики API получают его как контекст (``ctx``) и берут оттуда
репозиторий, менеджер сессий, хранилище и конфигурацию.

Метод ``dispatch`` выполняет полный цикл: находит пользователя по cookie,
ищет маршрут, проверяет необходимость сессии, вызывает обработчик и
превращает исключения в HTTP-ответы. Здесь же пишутся отладочные записи
журнала и события аудита о запрещённом доступе.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

from .api import auth, messages, posts, users
from .config import Config
from .core.audit import audit_event
from .core.security import ValidationError, safe_join
from .core.sessions import COOKIE_NAME, SessionManager
from .core.storage import Storage, content_type_for
from .db.database import Database
from .db.repository import Repository
from .http.request import HTTPError, Request
from .http.response import Response
from .http.router import MethodNotAllowed, NotFound, Router

logger = logging.getLogger("mosaic.server")


class Application:
    """Приложение целиком: БД, сессии, хранилище и таблица маршрутов.

    Attributes:
        config: Конфигурация путей и лимитов.
        db: Обёртка SQLite с соединением на поток.
        repo: Репозиторий с SQL-запросами.
        sessions: Менеджер сессий на cookie.
        storage: Хранилище загруженных изображений.
        router: Таблица маршрутов «метод + путь → обработчик».
    """

    def __init__(self, config: Config):
        """Инициализирует базу, хранилище и регистрирует маршруты.

        Args:
            config: Конфигурация приложения. Каталоги должны существовать
                (обычно их создаёт ``config.ensure_dirs()``).
        """
        self.config = config
        self.db = Database(config.db_path)
        self.db.init_schema()
        self.repo = Repository(self.db)
        self.sessions = SessionManager(self.repo, config.session_days)
        self.sessions.purge_expired()
        self.storage = Storage(config.uploads_dir)

        self.router = Router()
        auth.register_routes(self.router)
        posts.register_routes(self.router)
        users.register_routes(self.router)
        messages.register_routes(self.router)
        self._register_static_routes()
        logger.info("База данных: %s", config.db_path)
        logger.info("Хранилище файлов: %s", config.uploads_dir)

    # ------------------------------------------------------------ маршруты
    def _register_static_routes(self) -> None:
        """Добавляет маршруты страниц, статики и изображений."""
        self.router.add("GET", "/", self._index, auth=False)
        self.router.add("GET", "/login", self._login_page, auth=False)
        self.router.add("GET", "/static/{name}", self._static, auth=False)
        self.router.add("GET", "/uploads/{name}", self._upload, auth=False)
        self.router.add("GET", "/favicon.ico", self._favicon, auth=False)

    def _web_file(self, name: str) -> Response:
        """Читает файл из каталога ``web`` и отдаёт его с MIME-типом.

        Args:
            name: имя файла без каталогов.

        Raises:
            HTTPError: 404, если файл не найден или имя недопустимо.
        """
        path = safe_join(self.config.web_dir, name)
        if path is None or not path.is_file():
            raise HTTPError(404, "Файл не найден")
        response = Response.binary(path.read_bytes(), content_type_for(name))
        # На этапе разработки статику не кэшируем: иначе браузер
        # показывает старую версию JS после правок.
        response.headers["Cache-Control"] = "no-store"
        return response

    def _index(self, request: Request, params: dict[str, str],
               ctx: "Application", user: dict | None) -> Response:
        """Отдаёт главную страницу SPA."""
        return self._web_file("index.html")

    def _login_page(self, request: Request, params: dict[str, str],
                    ctx: "Application", user: dict | None) -> Response:
        """Отдаёт страницу входа и регистрации."""
        return self._web_file("login.html")

    def _static(self, request: Request, params: dict[str, str],
                ctx: "Application", user: dict | None) -> Response:
        """Отдаёт CSS, JS и другие файлы из каталога ``web``."""
        return self._web_file(params["name"])

    def _upload(self, request: Request, params: dict[str, str],
                ctx: "Application", user: dict | None) -> Response:
        """Отдаёт загруженное изображение по имени файла."""
        found = self.storage.read(params["name"])
        if found is None:
            raise HTTPError(404, "Изображение не найдено")
        data, mime = found
        response = Response.binary(data, mime)
        response.headers["Cache-Control"] = "no-store"
        return response

    def _favicon(self, request: Request, params: dict[str, str],
                 ctx: "Application", user: dict | None) -> Response:
        """Отвечает 204 на запрос иконки, чтобы не засорять журнал 404."""
        return Response.no_content()

    # ------------------------------------------------------------ dispatch
    def dispatch(self, request: Request) -> Response:
        """Находит маршрут, проверяет сессию и вызывает обработчик.

        Args:
            request: Разобранный HTTP-запрос.

        Returns:
            Готовый Response; исключения наружу не выбрасываются —
            ожидаемые превращаются в 4xx, непредвиденные в 500.
        """
        user = self.sessions.resolve(request.cookies.get(COOKIE_NAME))
        request.user = user
        try:
            route, params = self.router.match(request.method, request.path)
            logger.debug("id=%s %s %s -> %s", request.request_id,
                         request.method, request.path, route.pattern)
            if route.auth and user is None:
                audit_event("access_denied", path=request.path,
                            ip=request.remote_addr, reason="no_session")
                raise HTTPError(401, "Требуется вход в систему")
            response = route.handler(request, params, self, user)
            if not isinstance(response, Response):
                raise TypeError(f"Обработчик {route.pattern} вернул не Response")
            return response
        except HTTPError as exc:
            return Response.error(exc.status, exc.message)
        except MethodNotAllowed as exc:
            return Response.error(405, "Метод не поддерживается",
                                  {"Allow": ", ".join(exc.allowed)})
        except NotFound:
            return Response.error(404, "Запрашиваемый ресурс не найден")
        except ValidationError as exc:
            return Response.error(400, str(exc))
        except Exception:  # noqa: BLE001 - непредвиденная ошибка не должна ронять сервер
            logger.error("Необработанная ошибка при %s %s id=%s:\n%s",
                         request.method, request.path, request.request_id,
                         traceback.format_exc())
            return Response.error(500, "Внутренняя ошибка сервера")

    # ------------------------------------------------------------- закрытие
    def close(self) -> None:
        """Закрывает соединения с базой данных."""
        self.db.close()
