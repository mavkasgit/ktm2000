"""Общий шаблон страниц обзора: каркас, стили, фильтры, мелкие хелперы.

Страницы отличаются только содержимым (`visual`, `skipped`), поэтому каркас,
CSS и клиентский фильтр живут здесь — иначе две страницы разъедутся по виду и
по поведению поиска.
"""

from __future__ import annotations

import html
from datetime import datetime

from . import common

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--line:#dfe3e8;--ink:#1b1f24;--muted:#6b7280;
--drawing:#0f766e;--plakat:#b45309;--photo:#1d4ed8;--none:#6b7280;--bad:#b91c1c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{background:#fff;border-bottom:1px solid var(--line);
padding:12px 20px 10px}
h1{font-size:17px;margin:0 0 2px}
.sub{color:var(--muted);font-size:12px}
.wrap{padding:16px 20px 60px;max-width:1760px;margin:0 auto}
.sum{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
.chip{border:1px solid var(--line);border-radius:999px;background:#fff;padding:4px 10px;
font-size:12px;color:var(--muted)}
.chip b{color:var(--ink)}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0 16px}
button{font:inherit;border:1px solid var(--line);background:#fff;border-radius:8px;
padding:6px 12px;cursor:pointer}
button[aria-pressed="true"]{background:var(--ink);color:#fff;border-color:var(--ink)}
input[type=search]{font:inherit;border:1px solid var(--line);border-radius:8px;padding:7px 10px;
min-width:260px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
body[data-pmode="drawing"] .grid{grid-template-columns:repeat(auto-fill,minmax(560px,1fr))}
.share{display:grid;grid-template-columns:minmax(260px,380px) 1fr;gap:14px;background:#fff;
border:1px solid var(--line);border-radius:12px;padding:12px;margin:10px 0}
.share .pic{border-radius:8px;aspect-ratio:4/3;background:#fff}
.share table{border:0}
.share th{position:static;background:#f0f2f5}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;
display:flex;flex-direction:column}
.card[hidden]{display:none}
.card.problem{border-color:var(--bad);box-shadow:inset 3px 0 0 var(--bad)}
.pic{background:#eef1f4;aspect-ratio:4/3;display:flex;align-items:center;
justify-content:center;overflow:hidden}
.pic img{max-width:100%;max-height:100%;object-fit:contain;display:block}
.pic .empty{color:var(--muted);font-size:12px;text-align:center;padding:16px}
.shot[hidden]{display:none}
.pickbar{display:flex;gap:6px}
.pickbar button{font-size:11px;padding:3px 9px;border-radius:7px}
.seg{display:inline-flex;gap:6px;align-items:center;color:var(--muted);font-size:12px;
margin-right:6px}
.seg button{font-size:12px;padding:4px 10px}
.body{padding:10px 12px 12px;display:flex;flex-direction:column;gap:6px;flex:1}
.sku{font-weight:650;font-size:15px}
.name{color:var(--muted);font-size:12px}
.badges{display:flex;flex-wrap:wrap;gap:6px}
.b{font-size:11px;border-radius:6px;padding:2px 7px;border:1px solid currentColor}
.b.drawing{color:var(--drawing)}.b.plakat{color:var(--plakat)}
.b.photo{color:var(--photo)}.b.none{color:var(--none)}
.b.not_mes{color:var(--none)}.b.purchased{color:var(--plakat)}
.b.no_catalog{color:var(--photo)}
.b.alias{color:#7c3aed}
.b.problem{color:var(--bad)}
.ev{font-size:12px}
.note{font-size:12px;color:var(--muted)}
.links{margin-top:auto;display:flex;gap:10px;font-size:12px;align-items:baseline}
.links a{color:var(--photo);text-decoration:none}
.links a:hover{text-decoration:underline}
table{border-collapse:separate;border-spacing:0;width:100%;background:#fff;
border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);font-size:13px;
vertical-align:top}
th{background:#f0f2f5;font-weight:600;position:sticky;top:0;z-index:2}
tr:last-child td{border-bottom:0}
tr[hidden]{display:none}
td.code{font-variant-numeric:tabular-nums;white-space:nowrap}
.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px}
.section{margin:28px 0 8px;font-size:15px;font-weight:650}
.hint{color:var(--muted);font-size:12px;margin:6px 0 14px}
.fold{margin:10px 0;border:1px solid var(--line);border-radius:12px;background:#fff}
.fold>summary{cursor:pointer;padding:10px 14px;font-size:13px;font-weight:600;list-style:none}
.fold>summary::-webkit-details-marker{display:none}
.fold>summary::before{content:"▸";display:inline-block;width:14px;color:var(--muted)}
.fold[open]>summary{border-bottom:1px solid var(--line)}
.fold[open]>summary::before{content:"▾"}
.fold .inner{padding:0 12px 4px}
.warn{background:#fff7ed;border:1px solid #fdba74;color:#7c2d12;border-radius:10px;
padding:10px 12px;margin:12px 0;font-size:13px}
.ok{background:#ecfdf5;border:1px solid #6ee7b7;color:#065f46;border-radius:10px;
padding:10px 12px;margin:12px 0;font-size:13px}
.bad{background:#fef2f2;border:1px solid #fca5a5;color:#7f1d1d;border-radius:10px;
padding:10px 12px;margin:12px 0;font-size:13px}
footer{margin-top:36px;color:var(--muted);font-size:12px}
a.nav{color:var(--photo);text-decoration:none}
a.nav:hover{text-decoration:underline}
"""

# Фильтр по кнопке + поиск по подстроке. Работает по `data-tags` / `data-search`,
# поэтому разметку страницы не знает и годится любой странице.
# `setCardFilter` — вход для соседних скриптов: панель вида переключает фильтр
# так, чтобы выбранная кнопка была видна подсвеченной, а не действовала тайно.
FILTER_JS = """
const items = [...document.querySelectorAll('[data-filterable]')];
const search = document.getElementById('q');
const buttons = [...document.querySelectorAll('[data-f]')];
let active = 'all';
function applyFilters() {
  const q = (search?.value || '').trim().toLowerCase();
  let shown = 0;
  for (const el of items) {
    const tags = (el.dataset.tags || '').split(' ');
    const okFilter = active === 'all' || tags.includes(active);
    const okSearch = !q || (el.dataset.search || '').includes(q);
    const visible = okFilter && okSearch;
    el.hidden = !visible;
    if (visible) shown += 1;
  }
  const counter = document.getElementById('shown');
  if (counter) counter.textContent = shown;
}
function setCardFilter(value) {
  active = value;
  buttons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.f === value)));
  applyFilters();
}
buttons.forEach((b) => b.addEventListener('click', () => setCardFilter(b.dataset.f)));
search?.addEventListener('input', applyFilters);
applyFilters();
"""


def stamp() -> str:
    return datetime.now().astimezone().strftime("%d.%m.%Y %H:%M")


def chip(label: str, value) -> str:
    return f'<span class="chip">{html.escape(label)} <b>{html.escape(str(value))}</b></span>'


def filters(placeholder: str, buttons: list[tuple[str, str]], total: int, prefix: str = "") -> str:
    """Панель фильтров: поиск, кнопки `(значение, надпись)`, счётчик показанных.

    `prefix` — управление, которое живёт перед поиском (например, режим превью).
    """
    controls = "".join(
        f'<button data-f="{html.escape(value)}" aria-pressed="{"true" if value == "all" else "false"}">'
        f"{html.escape(label)}</button>"
        for value, label in buttons
    )
    return (
        '<div class="bar">'
        f"{prefix}"
        f'<input id="q" type="search" placeholder="{html.escape(placeholder)}">'
        f"{controls}"
        f'<span class="chip">показано <b id="shown">{total}</b> из {total}</span>'
        "</div>"
    )


def problem_table(problems: list[dict], first_column: str) -> str:
    """Таблица расхождений; колонки одинаковы на обеих страницах.

    Строки с `severity = "warn"` — к разбору, они не валят проверку.
    """
    rows = "".join(
        f'<tr{" style=\"color:#b45309\"" if problem.get("severity") == "warn" else ""}>'
        f'<td class="code">{html.escape(str(problem.get("key", "")))}</td>'
        f'<td>{html.escape(problem["kind"])}</td>'
        f"<td>{html.escape(problem['text'])}</td></tr>"
        for problem in problems
    )
    return (
        f'<table><thead><tr><th>{html.escape(first_column)}</th><th>Вид</th>'
        f"<th>Что именно</th></tr></thead><tbody>{rows}</tbody></table>"
    )


def page(title: str, subtitle: str, body: str, script: str = "") -> str:
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head>
<body>
<header>
  <h1>{html.escape(title)}</h1>
  <div class="sub">{subtitle}</div>
</header>
<div class="wrap">
{body}
<footer>Страница собрана генератором <span class="mono">{common.GENERATED_BY}</span>.
Правки руками теряются при следующей сборке — меняйте источник и пересобирайте
(<span class="mono">npm run docs:reviews</span>).</footer>
</div>
<script>{script}</script>
</body></html>
"""
