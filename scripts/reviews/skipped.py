"""Страница «Реестр исключений ОСВ»: что решено пропускать (#464).

Вход — таблица `product_1c_skipped`, пока её нет на проде — сид, из которого она
наполняется. Выход — страница с решениями по причинам, поиском и проверкой
«реестр не перекрывает каталог».
"""

from __future__ import annotations

import html
from collections import Counter
from pathlib import Path

from . import common, template

PAGE = "skipped-review.html"
SIBLING = "visual-review.html"
TITLE = "Реестр исключений ОСВ: что решено пропускать"


def problems(skipped: list[dict], products: list[dict]) -> list[dict]:
    """Реестр не должен глушить артикул каталога и не должен дублироваться."""
    found: list[dict] = []
    catalog_keys: dict[str, str] = {}
    for product in products:
        catalog_keys[common.norm_cell(product["sku"])] = f"артикул {product['sku']}"
        if product.get("code"):
            catalog_keys[common.norm_cell(product["code"])] = f"код {product['code']} ({product['sku']})"
        for alias in product.get("aliases") or []:
            catalog_keys[common.norm_cell(alias)] = f"алиас {alias} ({product['sku']})"

    for row in skipped:
        key = row.get("code") or row.get("name_norm") or "—"
        for needle in (row.get("code"), row.get("name_norm")):
            if not needle:
                continue
            hit = catalog_keys.get(common.norm_cell(needle))
            if hit:
                found.append(
                    {
                        "key": key,
                        "kind": "перекрывает каталог",
                        "text": f"«{needle}» есть в каталоге как {hit}; "
                        "такая запись ничего не исключает — каталог главнее",
                    }
                )

    for field, label in (("code", "код"), ("name_norm", "нормализованное имя")):
        for value, count in Counter(row[field] for row in skipped if row.get(field)).items():
            if count > 1:
                found.append(
                    {
                        "key": value,
                        "kind": "дубль",
                        "text": f"{label} «{value}» встречается {count} раза в реестре",
                    }
                )
    return found


def render(skipped: list[dict], found: list[dict], source: str) -> tuple[str, dict]:
    by_reason = Counter(row["reason"] for row in skipped)

    def order(row: dict) -> tuple[int, str]:
        reason = row["reason"]
        return (
            common.REASON_ORDER.index(reason) if reason in common.REASON_ORDER else 9,
            row.get("code") or "",
        )

    rows = "".join(
        f"""<tr data-filterable data-tags="{html.escape(row['reason'])}"
  data-search="{html.escape(' '.join([row.get('code') or '', row.get('name_norm') or '', row['reason']]).lower())}">
  <td class="code">{index}</td>
  <td class="code">{html.escape(row.get('code') or '—')}</td>
  <td>{html.escape(row.get('name_norm') or '—')}</td>
  <td><span class="b {html.escape(row['reason'])}">{html.escape(common.REASON_LABELS.get(row['reason'], row['reason']))}</span></td>
  <td class="note">{html.escape(row.get('note') or '')}</td>
  <td class="mono" title="{html.escape(row.get('decided_by') or '')}">{html.escape((row.get('decided_at') or '')[:10] or '—')}</td>
</tr>"""
        for index, row in enumerate(sorted(skipped, key=order), 1)
    )

    summary = "".join(
        [template.chip("всего решений", len(skipped))]
        + [
            template.chip(common.REASON_LABELS[reason].split(" (")[0], by_reason.get(reason, 0))
            for reason in common.REASON_ORDER
        ]
        + [
            template.chip(
                "перекрывают каталог", sum(1 for p in found if p["kind"] == "перекрывает каталог")
            ),
            template.chip("дублей", sum(1 for p in found if p["kind"] == "дубль")),
        ]
    )

    if found:
        notice = (
            f'<div class="bad">Реестр не в порядке: <b>{len(found)}</b> замечаний. '
            "Запись, которая находится в каталоге, — это решение, записанное зря: "
            "каталог главнее, и строка такой записью не глушится.</div>"
        )
        problem_section = (
            '<div class="section">Замечания</div>' + template.problem_table(found, "Код 1С")
        )
    else:
        notice = (
            '<div class="ok">Реестр чист: ни одна запись не находится в каталоге, дублей нет. '
            "Каталог главнее реестра — если артикул заведут позже, строка перестанет глушиться.</div>"
        )
        problem_section = ""

    panel = template.filters(
        "поиск: код или наименование 1С",
        [
            ("all", "все"),
            ("not_mes", f"не наша номенклатура · {by_reason.get('not_mes', 0)}"),
            ("purchased", f"покупное · {by_reason.get('purchased', 0)}"),
            ("no_catalog", f"нет в каталоге · {by_reason.get('no_catalog', 0)}"),
        ],
        len(skipped),
    )

    body = f"""
<div class="sum">{summary}</div>
{notice}
<div class="hint">Источник: <span class="mono">{html.escape(source)}</span>.
Запись означает «эта позиция 1С не наша»: предпросмотр перестаёт считать её
ошибкой и переносит в статус <span class="mono">skipped</span>. Наименование
показано в нормализации импорта (lower, без NBSP, схлопнутые пробелы) — по ней
и идёт сравнение.</div>
<div class="section">Решения</div>
{panel}
<table><thead><tr><th>#</th><th>Код 1С</th><th>Наименование 1С</th><th>Причина</th>
<th>Примечание</th><th>Решено</th></tr></thead><tbody>{rows}</tbody></table>
{problem_section}
"""
    subtitle = (
        f"Реестр исключений разбора ОСВ · сгенерировано {template.stamp()} · "
        f'<a class="nav" href="{SIBLING}">изображения каталога →</a>'
    )
    return template.page(TITLE, subtitle, body, template.FILTER_JS), {
        "by_reason": dict(by_reason),
        "problems": len(found),
        "records": len(skipped),
        "source": source,
    }


def write(
    out: Path,
    rows: list[dict],
    source: str,
    products: list[dict],
    found: list[dict] | None = None,
) -> dict:
    found = problems(rows, products) if found is None else found
    text, stats = render(rows, found, source)
    out.mkdir(parents=True, exist_ok=True)
    (out / PAGE).write_text(text, encoding="utf-8")
    stats["file"] = PAGE
    stats["problems_list"] = found
    return stats
