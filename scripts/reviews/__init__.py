"""HTML-обзоры каталога: по модулю на страницу и общий шаблон.

Страницы:
  ``visual``  — изображения артикулов: что на картинке, где пробелы (#463)
  ``skipped`` — реестр исключений разбора ОСВ (#464)
  ``index``   — стартовая: две ссылки и сводка

Общее (``common``, ``template``) — источники, storage, превью, каркас и
фильтры. Точки входа — тонкие скрипты в ``scripts/``: один на страницу
(``build-visual-review.py``, ``build-skipped-review.py``) и общий
(``build-catalog-reviews.py``), который собирает всё за один заход.

Страницы — артефакт: руками не правятся, собираются из источников
(``visual-truth.csv``, прод-БД, storage, сид/таблица реестра).
"""

from __future__ import annotations

from . import common, index, skipped, template, visual

__all__ = ["common", "index", "skipped", "template", "visual"]
