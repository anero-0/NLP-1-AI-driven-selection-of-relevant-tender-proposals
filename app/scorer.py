"""
Скорер закупок.

Два режима:
  1. Если models/pipeline.joblib существует — используем Дашину модель (predict_proba).
  2. Иначе — скоринг v0: TF-IDF близость к ключевым словам + простые правила.
"""

from __future__ import annotations

import logging
import math
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

# app/scorer.py lives in app/, parent = app/, parent.parent = project root
_PROJECT_ROOT = Path(__file__).parent.parent
MODEL_PATH = _PROJECT_ROOT / "models" / "pipeline.joblib"
KEYWORDS_PATH = _PROJECT_ROOT / "keywords.txt"

# Fallback-ключевые слова если keywords.txt пустой или отсутствует
DEFAULT_KEYWORDS = [
    "разработка", "сайт", "портал", "программное обеспечение", "по", "система",
    "платформа", "приложение", "интеграция", "автоматизация", "цифров",
    "информационн", "it", "ит", "веб", "web", "техническ", "поддержка",
    "сопровождение", "внедрение", "доработка", "модернизация",
]


def _load_keywords() -> list[str]:
    if KEYWORDS_PATH.exists():
        text = KEYWORDS_PATH.read_text(encoding="utf-8")
        kws = [line.strip().lower() for line in text.splitlines() if line.strip()]
        if kws:
            return kws
    return DEFAULT_KEYWORDS


def _tokenize(text: str) -> list[str]:
    """Простая токенизация: lowercase, только буквы и цифры."""
    return re.findall(r"[а-яёa-z0-9]+", text.lower())


def _score_v0(record: dict, keywords: list[str]) -> float:
    """
    Скоринг v0 — без обучения.

    Алгоритм:
      - Считаем долю ключевых слов, встречающихся в названии закупки
      - Бонус если НМЦ указана (признак серьёзной закупки)
      - Небольшой бонус за регион Москва/МО (чаще интересуют)
      - Бонус если торги не 44-ФЗ (в шаблоне они отключены, но на всякий случай)
      - Итог нормируем в [0, 1]
    """
    name = str(record.get("name") or "").lower()
    tokens = set(_tokenize(name))

    # 1. Совпадение ключевых слов (max вклад: 0.6)
    matched = sum(1 for kw in keywords if kw in name or any(kw in t for t in tokens))
    kw_score = min(matched / max(len(keywords) * 0.15, 1), 1.0) * 0.6

    # 2. НМЦ указана (вклад: 0.15)
    price_score = 0.15 if record.get("has_price") else 0.0

    # 3. Регион (вклад: 0.1)
    region = str(record.get("region") or "").lower()
    region_score = 0.1 if ("москва" in region or "московск" in region) else 0.04

    # 4. Тип торгов (вклад: 0.1)
    trade_type = str(record.get("trade_type") or "").lower()
    trade_score = 0.05 if "44" in trade_type else 0.1

    # 5. Дни до дедлайна — слишком мало времени = снижаем (вклад: до -0.1)
    days = record.get("days_to_deadline")
    deadline_penalty = 0.0
    if days is not None and days < 3:
        deadline_penalty = -0.1

    total = kw_score + price_score + region_score + trade_score + deadline_penalty
    return int(round(max(0.0, min(1.0, total)) * 100))


# ---------------------------------------------------------------------------
# Публичный интерфейс
# ---------------------------------------------------------------------------

_model = None
_threshold = None
_model_loaded = False
_model_error: str | None = None
_keywords: list[str] | None = None


def _get_model():
    """Ленивая загрузка модели и порога."""
    global _model, _threshold, _model_loaded, _model_error
    if _model_loaded:
        return _model, _threshold, _model_error
    _model_loaded = True
    if MODEL_PATH.exists():
        try:
            import joblib
            _model = joblib.load(MODEL_PATH)
            
            threshold_path = _PROJECT_ROOT / "models" / "threshold.joblib"
            if threshold_path.exists():
                _threshold = joblib.load(threshold_path)
            else:
                _threshold = 0.5
                
            logger.info("Модель загружена: %s (Порог: %s)", MODEL_PATH, _threshold)
        except Exception as exc:
            _model_error = f"Ошибка загрузки модели: {exc}"
            logger.warning(_model_error)
            _model = None
            _threshold = None
    else:
        _model_error = "Файл модели не найден — используется базовый скоринг v0."
        logger.info(_model_error)
    return _model, _threshold, _model_error


def _get_keywords() -> list[str]:
    global _keywords
    if _keywords is None:
        _keywords = _load_keywords()
    return _keywords


def using_model() -> bool:
    """Возвращает True если будет использоваться обученная модель."""
    model, _, _ = _get_model()
    return model is not None


def model_status() -> str:
    """Человекочитаемый статус модели."""
    _, _, err = _get_model()
    if err:
        return err
    return f"Модель загружена из {MODEL_PATH.name}"


def score_records(records: list[dict]) -> list[dict]:
    """
    Проставляет поле score каждому записи (in-place) и возвращает тот же список.

    С моделью: строит DataFrame с нужными признаками, вызывает predict_proba.
    Без модели: вызывает _score_v0 для каждой строки.
    """
    model, threshold, _ = _get_model()
    keywords = _get_keywords()

    if model is not None:
        try:
            import pandas as pd
            import sys
            
            # Добавляем корень в sys.path для импорта features.py
            if str(_PROJECT_ROOT) not in sys.path:
                sys.path.append(str(_PROJECT_ROOT))
            import features

            # Формируем датафрейм с русскими названиями колонок, как ожидает features.py
            df_raw = pd.DataFrame([{
                "Название": r.get("name"),
                "Способ отбора": r.get("selection_method"),
                "Регион": r.get("region"),
                "Тип торгов": r.get("trade_type"),
                "НМЦ": r.get("price"),
                "Дата публикации": r.get("pub_date"),
                "Окончание приема заявок": r.get("deadline"),
                "Метка ": ""  # Заглушка, так как класс неизвестен
            } for r in records])

            # Применяем трансформации Даши
            df_features = features.build_features(df_raw)

            # Получаем вероятности (predict_proba[:, 1] — это класс "Интересно")
            probas = model.predict_proba(df_features)[:, 1]
            
            for record, prob in zip(records, probas):
                # Масштабируем скор так, чтобы порог (0.106) был равен 0.5 для удобства UI
                # Если prob == threshold, score = 0.5
                # Если prob > threshold, score от 0.5 до 1.0
                # Если prob < threshold, score от 0.0 до 0.5
                if prob >= threshold:
                    # Нормируем от 0.5 до 1.0
                    scaled_score = 0.5 + 0.5 * ((prob - threshold) / (1.0 - threshold))
                else:
                    # Нормируем от 0.0 до 0.5
                    scaled_score = 0.5 * (prob / threshold)
                
                record["score"] = int(round(float(scaled_score) * 100))
                record["raw_prob"] = int(round(float(prob) * 100))

        except Exception as exc:
            logger.warning("Ошибка при вызове модели (%s), переключаемся на v0.", exc)
            for record in records:
                record["score"] = _score_v0(record, keywords)
    else:
        for record in records:
            record["score"] = _score_v0(record, keywords)

    # Сортируем по убыванию балла
    records.sort(key=lambda r: r["score"], reverse=True)
    return records
