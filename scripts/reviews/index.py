"""Стартовая страница обзоров: две ссылки и сводка по обоим источникам."""

from __future__ import annotations

import html
from pathlib import Path

from . import template

PAGE = "index.html"


def render(visual_stats: dict, skipped_stats: dict) -> str:
    kinds = visual_stats.get("kinds", {})
    body = f"""
<div class="sum">
  {template.chip("артикулов", visual_stats.get("articles", 0))}
  {template.chip("чертежей", kinds.get("drawing", 0))}
  {template.chip("плакатов", kinds.get("plakat", 0))}
  {template.chip("без изображения", kinds.get("none", 0))}
  {template.chip("расхождений", visual_stats.get("problems", 0))}
  {template.chip("решений о пропуске", skipped_stats.get("records", 0))}
  {template.chip("замечаний к реестру", skipped_stats.get("problems", 0))}
</div>
<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(420px,1fr))">
  <article class="card"><div class="body" style="padding:16px">
    <div class="sku">Изображения каталога</div>
    <div class="note">Что на картинке — чертёж, плакат или фото; какие взяты
    у алиаса; у кого изображения нет и с чего начинать съёмку.</div>
    <div class="links"><a href="{visual_stats.get('file', 'visual-review.html')}">открыть</a></div>
  </div></article>
  <article class="card"><div class="body" style="padding:16px">
    <div class="sku">Реестр исключений ОСВ</div>
    <div class="note">Что решено не импортировать: химия, плёнки, крепёж,
    покупные рейки и панели, новые артикулы. Проверка, что реестр не перекрывает
    каталог.</div>
    <div class="links"><a href="{skipped_stats.get('file', 'skipped-review.html')}">открыть</a></div>
  </div></article>
</div>
<div class="hint">Источник реестра: <span class="mono">{html.escape(skipped_stats.get('source', '—'))}</span></div>
"""
    return template.page("Каталог: обзоры для приёмки", f"Сгенерировано {template.stamp()}", body)


def write(out: Path, visual_stats: dict, skipped_stats: dict) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / PAGE
    path.write_text(render(visual_stats, skipped_stats), encoding="utf-8")
    return path
