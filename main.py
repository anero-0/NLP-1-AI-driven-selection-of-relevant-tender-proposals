"""
FastAPI-приложение: ИИ-отбор тендеров.

Маршруты:
  GET  /          → форма загрузки xlsx
  POST /upload    → парсинг + скоринг → редирект на /results
  GET  /results   → таблица результатов
  GET  /download  → скачать xlsx с результатами
  GET  /metrics   → страница метрик модели
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Annotated

import jinja2
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.exporter import export_to_xlsx
from app.parser import ParseError, parse_xlsx
from app.scorer import model_status, score_records, using_model

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
METRICS_PATH = BASE_DIR / "models" / "metrics.json"

app = FastAPI(title="ИИ-отбор тендеров", version="1.0")

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")

# Jinja2 напрямую — обходим баг starlette 1.3.1 с кешем на Python 3.14
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(BASE_DIR / "app" / "templates")),
    autoescape=True,
)

# Простое in-memory хранилище сессий: {session_id: [records]}
# Для демо — достаточно. Для продакшна заменить на Redis.
_sessions: dict[str, list[dict]] = {}


def _session_store(records: list[dict]) -> str:
    sid = str(uuid.uuid4())
    _sessions[sid] = records
    # Чистим старые сессии если их больше 50
    if len(_sessions) > 50:
        oldest = list(_sessions.keys())[0]
        del _sessions[oldest]
    return sid


def _session_get(sid: str) -> list[dict] | None:
    return _sessions.get(sid)


# ---------------------------------------------------------------------------
# Фильтры Jinja2
# ---------------------------------------------------------------------------

def fmt_price(value) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):,.0f} ₽".replace(",", "\u202f")
    except (ValueError, TypeError):
        return str(value)


def fmt_date(value) -> str:
    if value is None:
        return "—"
    from datetime import datetime
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    return str(value)


def score_class(score) -> str:
    """CSS-класс для цветового кодирования балла."""
    if score is None:
        return "score-unknown"
    if float(score) >= 70:
        return "score-high"
    if float(score) >= 40:
        return "score-mid"
    return "score-low"


_jinja_env.filters["fmt_price"] = fmt_price
_jinja_env.filters["fmt_date"] = fmt_date
_jinja_env.filters["score_class"] = score_class


def render(template_name: str, **ctx) -> HTMLResponse:
    """Рендерит Jinja2-шаблон и возвращает HTMLResponse."""
    tmpl = _jinja_env.get_template(template_name)
    html = tmpl.render(**ctx)
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# Маршруты
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, error: str = "", warn: str = ""):
    return render("index.html",
        error=error,
        warn=warn,
        model_status=model_status(),
        using_model=using_model(),
    )


@app.post("/upload")
async def upload(request: Request, file: Annotated[UploadFile, File()]):
    # Проверка расширения
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        return RedirectResponse(
            url="/?error=Пожалуйста, загрузите файл в формате .xlsx",
            status_code=303,
        )

    # Проверка размера (максимум 20 МБ)
    content = await file.read()
    if len(content) == 0:
        return RedirectResponse(
            url="/?error=Файл пустой — загрузите корректный xlsx",
            status_code=303,
        )
    if len(content) > 20 * 1024 * 1024:
        return RedirectResponse(
            url="/?error=Файл слишком большой (максимум 20 МБ)",
            status_code=303,
        )

    # Парсинг
    try:
        records = parse_xlsx(content)
    except ParseError as exc:
        return RedirectResponse(
            url=f"/?error={str(exc)}",
            status_code=303,
        )
    except Exception as exc:
        logger.exception("Неожиданная ошибка при парсинге")
        return RedirectResponse(
            url=f"/?error=Не удалось прочитать файл: {exc}",
            status_code=303,
        )

    # Скоринг
    records = score_records(records)

    # Сохраняем в сессию
    sid = _session_store(records)

    warn = "" if using_model() else "Модель не найдена — используется базовый скоринг v0"
    return RedirectResponse(
        url=f"/results?sid={sid}&warn={warn}",
        status_code=303,
    )


@app.get("/results", response_class=HTMLResponse)
async def results(request: Request, sid: str = "", warn: str = "", min_score: int = 0):
    records = _session_get(sid) if sid else None
    if records is None:
        return RedirectResponse(url="/?error=Сессия не найдена — загрузите файл заново")

    # Фильтрация по минимальному баллу
    filtered = [r for r in records if (r.get("score") or 0) >= min_score]

    return render("results.html",
        records=filtered,
        total=len(records),
        shown=len(filtered),
        sid=sid,
        warn=warn,
        min_score=min_score,
        using_model=using_model(),
        model_status=model_status(),
    )


@app.get("/download")
async def download(sid: str = ""):
    records = _session_get(sid) if sid else None
    if records is None:
        return RedirectResponse(url="/?error=Сессия не найдена — загрузите файл заново")

    xlsx_bytes = export_to_xlsx(records)

    return StreamingResponse(
        iter([xlsx_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=tenders_scored.xlsx"},
    )


@app.get("/metrics", response_class=HTMLResponse)
async def metrics(request: Request):
    metrics_data = None
    metrics_error = None

    if METRICS_PATH.exists():
        try:
            metrics_data = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            metrics_error = f"Ошибка загрузки метрик: {exc}"
    else:
        metrics_error = "Файл metrics.json не найден. Метрики появятся после обучения модели."

    return render("metrics.html",
        metrics=metrics_data,
        error=metrics_error,
        using_model=using_model(),
        model_status=model_status(),
    )
