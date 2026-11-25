"""Страница «Изображения каталога»: что на картинке и где пробелы (#463).

Вход — разметка `docs/catalog/visual-truth.csv`, привязки файлов из прод-БД и
сами файлы из storage. Выход — одна самодостаточная страница: счётчики,
фильтры, карточки с превью, список пробелов и список расхождений.
"""

from __future__ import annotations

import html
from collections import Counter, defaultdict
from pathlib import Path

from . import audit, common, template
from . import decisions as decisions_mod

PAGE = "visual-review.html"
SIBLING = "skipped-review.html"
TITLE = "Изображения каталога: что на картинке и где пробелы"

# Надпись на проверенной группе: что именно общее — лист/плакат, чертёж или фото.
SHARED_LABELS = {
    "drawing": "общий чертёж",
    "plakat": "общий плакат",
    "photo": "общее фото",
}


def articles(count: int) -> str:
    """«1 артикул / 2 артикула / 10 артикулов» — подпись группы без кривого счёта."""
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} артикул"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} артикула"
    return f"{count} артикулов"

# Переключение вида: «превью» — мелкая картинка для обзора, «чертёж» и «плакат» —
# полный файл из storage, с него читают размеры. Кнопка в панели задаёт вид всем
# карточкам, кнопки на карточке переопределяют её и сбрасываются при смене
# общего вида.
PREVIEW_JS = """
const slotCards = [...document.querySelectorAll('[data-has-drawing]')];
// Превью (base64) уже стоит в src — запоминаем его, чтобы вернуться из полного
// файла без второй копии картинки в разметке.
const previewSrc = new Map();
for (const img of document.querySelectorAll('img[data-full]')) {
  previewSrc.set(img, img.getAttribute('src'));
}
// Полный файл открывается через file://; если браузер его не отдал (страница
// поднята по http), показываем превью вместо битой картинки.
document.addEventListener('error', (event) => {
  const img = event.target;
  if (!(img instanceof HTMLImageElement)) return;
  const fallback = previewSrc.get(img);
  if (fallback && img.getAttribute('src') !== fallback) img.src = fallback;
}, true);
let previewMode = 'preview';
// Вид — что именно показывать: 'preview' (мелкая картинка) | 'drawing' | 'plakat'.
// Слот — какой источник: при виде 'preview' берём тот, что размечен.
function viewOf(card) {
  return card.dataset.mode || previewMode;
}
function variantOf(card, view) {
  if (view !== 'preview') return view;
  return card.dataset.hasDrawing === '1' ? 'drawing' : 'plakat';
}
function paintPreviews() {
  document.body.dataset.pmode = previewMode;
  for (const card of slotCards) {
    const view = viewOf(card);
    const variant = variantOf(card, view);
    const empty = card.dataset.hasDrawing === '0' && card.dataset.hasPlakat === '0';
    for (const shot of card.querySelectorAll('[data-variant]')) {
      const visible = empty || shot.dataset.variant === variant;
      shot.hidden = !visible;
      const img = shot.querySelector('img[data-full]');
      if (!img) continue;
      // Скрытый слот держим на превью: полный файл в памяти нужен только тому,
      // что реально показан.
      const want = visible && view !== 'preview' ? img.dataset.full : previewSrc.get(img);
      if (want && img.getAttribute('src') !== want) img.src = want;
    }
    for (const btn of card.querySelectorAll('[data-pick]')) {
      btn.setAttribute('aria-pressed', String(btn.dataset.pick === variant));
    }
  }
  for (const btn of document.querySelectorAll('[data-gmode]')) {
    btn.setAttribute('aria-pressed', String(btn.dataset.gmode === previewMode));
  }
}
// Вид сразу включает и фильтр: «чертёж» показывает только тех, у кого чертёж
// есть, «плакат» — только тех, у кого есть плакат. Кнопки фильтра при этом
// подсвечиваются, чтобы это не было скрытой магией.
const VIEW_FILTER = { preview: 'all', drawing: 'has-drawing', plakat: 'has-plakat' };
document.querySelectorAll('[data-gmode]').forEach((btn) => btn.addEventListener('click', () => {
  previewMode = btn.dataset.gmode;
  for (const card of slotCards) delete card.dataset.mode;
  paintPreviews();
  setCardFilter(VIEW_FILTER[previewMode] || 'all');
}));
document.querySelectorAll('[data-pick]').forEach((btn) => btn.addEventListener('click', () => {
  const card = btn.closest('[data-has-drawing]');
  if (!card) return;
  if (card.dataset.mode === btn.dataset.pick) delete card.dataset.mode;
  else card.dataset.mode = btn.dataset.pick;
  paintPreviews();
}));
paintPreviews();
"""


def dimension_section(rows: list[dict]) -> str:
    """Таблица «периметр на изображении против БД»."""
    if not rows:
        return ""
    body = "".join(
        f'<tr{" style=\"color:#b91c1c\"" if row["severity"] == "error" else ""}>'
        f'<td class="code">{html.escape(row["sku"])}</td>'
        f'<td class="code">{row["db"]}</td>'
        f'<td class="code">{row["image"]}</td>'
        f'<td class="code"><b>{row["delta"]}</b></td>'
        f'<td>{html.escape(common.KIND_LABELS.get(row["kind"], row["kind"] or "—"))}</td>'
        f'<td class="mono">{html.escape(row["file"])}</td></tr>'
        for row in rows
    )
    big = sum(1 for row in rows if row["severity"] == "error")
    return f"""
<div class="section">Сверка размеров: чертёж ↔ БД — {len(rows)}</div>
<div class="hint">Считаем только чертёж: плакат — визуальное подтверждение, его
периметр в сверке не участвует. Красным — Δ ≥ 0,5 мм ({big} шт.), жёлтым —
округление чертежа. Ничего не правим молча: размер может быть верным, а БД —
ошибочной, и наоборот. Снятые расхождения хранятся в
<span class="mono">docs/catalog/visual-review-decisions.csv</span> и в списке не
появляются.</div>
<table><thead><tr><th>Артикул</th><th>БД, мм</th><th>На чертеже</th>
<th>Δ, мм</th><th>Вид по разметке</th><th>Файл чертежа</th></tr></thead>
<tbody>{body}</tbody></table>
"""


def duplicate_section(groups: list[dict], by_sku: dict[str, dict], register: dict[str, dict], thumbs: dict) -> str:
    """Сравнение «один файл на несколько артикулов»: картинка и все её артикулы.

    Смысл блока — посмотреть глазами: семейный каталожный снимок законно один на
    группу, и это норма. Поэтому вердикт «ок» хранится в
    `docs/catalog/visual-review-decisions.csv` и переживает пересборку.
    """
    if not groups:
        return ""

    blocks: list[tuple[dict, str]] = []
    for group in groups:
        uri = common.thumb_data_uri(group["file"], thumbs)
        href = common.full_href(group["file"])
        if group["state"] == "ok":
            status = (
                '<span class="b drawing">проверено: '
                f'{html.escape(SHARED_LABELS.get(group["kind"], "общий файл"))}</span>'
            )
        else:
            status = '<span class="b plakat">к разбору</span>'
        rows = []
        for sku in group["skus"]:
            member = by_sku.get(sku) or {}
            reg = register.get(sku) or {}
            marks = []
            if sku in group["marked"]:
                marks.append('<span class="b alias">алиас</span>')
            if sku in group["foreign"]:
                marks.append('<span class="b problem">чужой файл</span>')
            rows.append(
                "<tr>"
                f'<td class="code">{html.escape(sku)}</td>'
                f'<td>{html.escape(member.get("name") or reg.get("name") or "—")}</td>'
                f'<td class="code">{html.escape(reg.get("perimeter_mm") or "—")}</td>'
                f'<td class="mono">{html.escape(", ".join(str(length) for length in (member.get("lengths") or [])) or "—")}</td>'
                f'<td>{"".join(marks)}</td>'
                "</tr>"
            )
        picture = (
            f'<a class="pic" href="{html.escape(href)}" target="_blank" title="{html.escape(group["file"] or "")}">'
            f'<img loading="lazy" src="{uri}" alt="{html.escape(group["skus"][0])}"></a>'
            if uri and href
            else '<div class="pic"><span class="empty">файл не читается</span></div>'
        )
        blocks.append(
            (
                group,
                f"""<div class="share">
  {picture}
  <div>
    <div class="badges">{status}<span class="b none">{articles(len(group["skus"]))}</span>
      <span class="b mono">sha256 {html.escape(group["hash"])}</span></div>
    <table><thead><tr><th>Артикул</th><th>Наименование</th><th>P, мм</th>
    <th>Длины, мм</th><th>Пометки</th></tr></thead>
    <tbody>{''.join(rows)}</tbody></table>
    <div class="note" style="margin-top:6px">{html.escape(group["state_note"] or "")}</div>
  </div>
</div>""",
            )
        )

    reviewed = [block for group, block in blocks if group["state"] == "ok"]
    pending = [block for group, block in blocks if group["state"] != "ok"]
    fold = ""
    if reviewed:
        fold = (
            '<details class="fold">'
            f"<summary>проверено групп: {len(reviewed)} — раскрыть</summary>"
            f'<div class="inner">{"".join(reviewed)}</div>'
            "</details>"
        )
    return f"""
<div class="section">Один файл на несколько артикулов — {len(groups)} групп
({len(reviewed)} проверено)</div>
<div class="hint">Совпадение байт в байт — не дефект: у семейства законно один общий
файл — каталожный лист, плакат или чертёж. Блок нужен, чтобы посмотреть и пройти
дальше. Вердикт «ок» хранится в
<span class="mono">docs/catalog/visual-review-decisions.csv</span> и переживает
пересборку; «чужой файл» помечает артикул, которому досталась картинка не про
него. Проверенные группы свёрнуты — раскройте, только если нужно пересмотреть.</div>
{''.join(pending)}{fold}
"""


def problems(
    products: list[dict],
    truth: dict[str, dict],
    register: dict[str, dict],
) -> list[dict]:
    """Расхождения карточка ↔ разметка ↔ storage — то, что валит проверку."""
    found: list[dict] = []
    by_sku = {product["sku"]: product for product in products}

    def add(sku: str, kind: str, text: str) -> None:
        found.append({"key": sku, "kind": kind, "text": text})

    for product in (item for item in products if item.get("is_catalog_item")):
        sku = product["sku"]
        slots = {
            "photo_full": product.get("photo_full"),
            "photo_thumb": product.get("photo_thumb"),
            "drawing_full": product.get("drawing_full"),
        }
        row = truth.get(sku)
        if any(slots.values()) and row is None:
            add(sku, "нет разметки", "в карточке есть изображение, строки в visual-truth.csv нет")
        if row is None:
            continue
        kind = row.get("kind", "")
        if kind not in common.KIND_LABELS:
            add(sku, "битая разметка", f"kind={kind!r} вне drawing/plakat/photo/none")
        for slot, rel in slots.items():
            if common.file_state(rel) == "missing":
                add(sku, "файл пропал", f"{slot} = {rel}, файла нет в storage")
        has_file = any(common.file_state(rel) == "ok" for rel in slots.values())
        if kind == "none" and has_file:
            found.append(
                {
                    "key": sku,
                    "kind": "заглушка / лишний файл",
                    "severity": "warn",
                    "text": "разметка none, но файл привязан — заглушка это или "
                    "неразмеченное изображение, решает человек",
                }
            )
        if kind != "none" and not has_file:
            add(
                sku,
                "нет файла",
                f"разметка {kind}, но ни один слот не указывает на существующий файл",
            )

    for sku in truth:
        if sku not in by_sku:
            found.append(
                {"key": sku, "kind": "лишняя строка", "text": "артикула нет в справочнике прода"}
            )
    return found


def render(
    products: list[dict],
    truth: dict[str, dict],
    register: dict[str, dict],
    found: list[dict],
) -> tuple[str, dict]:
    by_sku = {product["sku"]: product for product in products}
    thumbs: dict[str, str | None] = {}
    kinds = Counter(row.get("kind", "") for row in truth.values())
    origins = Counter(row.get("origin", "") for row in truth.values() if row.get("origin"))
    problem_by_sku: dict[str, list[dict]] = defaultdict(list)
    for problem in found:
        problem_by_sku[problem["key"]].append(problem)
    blocking = [problem for problem in found if problem.get("severity") != "warn"]
    notes = [problem for problem in found if problem.get("severity") == "warn"]

    def order(sku: str) -> tuple[int, str]:
        kind = truth[sku].get("kind", "none")
        return (common.KIND_ORDER.index(kind) if kind in common.KIND_ORDER else 9, sku)

    cards: list[str] = []
    both_slots = 0
    drawing_available = 0
    plakat_available = 0
    for sku in sorted(truth, key=order):
        row = truth[sku]
        product = by_sku.get(sku) or {}
        kind = row.get("kind", "none")
        origin = row.get("origin", "")
        reg = register.get(sku) or {}
        drawing_rel = product.get("drawing_full")
        photo_rel = product.get("photo_full") or product.get("photo_thumb")
        has_drawing_file = common.file_state(drawing_rel) == "ok"
        has_photo_file = common.file_state(photo_rel) == "ok"

        # Два источника: слот чертежа и слот фото (плакат/фото изделия).
        # Пока `drawing_full` пуст (миграция 087 не применена на проде), чертёж
        # показывается из слота фото — он там и лежит по разметке.
        # У каждого источника два вида: превью (base64, 420px) для обзорной
        # сетки и полный файл из storage — для чтения размеров.
        photo_thumb_rel = product.get("photo_thumb") or product.get("photo_full")
        variants: dict[str, tuple[str, str, str]] = {}
        if has_drawing_file:
            variants["drawing"] = (drawing_rel, drawing_rel, "чертёж")
        if has_photo_file:
            if kind == "drawing" and not has_drawing_file:
                variants["drawing"] = (photo_thumb_rel, photo_rel, "чертёж (слот фото)")
            else:
                variants["plakat"] = (
                    photo_thumb_rel,
                    photo_rel,
                    {"plakat": "плакат", "photo": "фото изделия"}.get(kind, "файл"),
                )
        has_drawing = "drawing" in variants
        has_plakat = "plakat" in variants
        if has_drawing:
            drawing_available += 1
        if has_plakat:
            plakat_available += 1
        if has_drawing and has_plakat:
            both_slots += 1

        def shot(variant: str, missing: str) -> str:
            if variant not in variants:
                return (
                    f'<div class="shot" data-variant="{variant}">'
                    f'<div class="pic"><span class="empty">{missing}</span></div></div>'
                )
            thumb_rel, full_rel, label = variants[variant]
            href = common.full_href(full_rel)
            preview = common.thumb_data_uri(thumb_rel, thumbs)
            # Один тег на два вида: превью (base64) для обзорной сетки и полный
            # файл из storage — для чтения размеров. Переключает `PREVIEW_JS`;
            # base64 запоминается им на старте, поэтому в разметке он один раз.
            if href:
                inner = (
                    f'<a class="pic" href="{html.escape(href)}" target="_blank" title="{html.escape(label)}">'
                    f'<img loading="lazy" src="{preview or html.escape(href)}" '
                    f'data-full="{html.escape(href)}"'
                    f' alt="{html.escape(sku)} — {html.escape(label)}"></a>'
                )
            elif preview:
                inner = (
                    f'<div class="pic" title="{html.escape(label)}">'
                    f'<img loading="lazy" src="{preview}" alt="{html.escape(sku)}"></div>'
                )
            else:
                inner = f'<div class="pic"><span class="empty">{html.escape(label)}: файл не читается</span></div>'
            return f'<div class="shot" data-variant="{variant}">{inner}</div>'

        if variants:
            shots = shot("drawing", "чертежа нет") + shot("plakat", "плаката нет")
            picker = ""
            if has_drawing and has_plakat:
                picker = (
                    '<div class="pickbar">'
                    '<button data-pick="drawing">Чертёж</button>'
                    '<button data-pick="plakat">Плакат</button>'
                    "</div>"
                )
        else:
            shots = (
                '<div class="shot" data-variant="plakat">'
                '<div class="pic"><span class="empty">изображения нет</span></div></div>'
            )
            picker = ""

        badges = [
            f'<span class="b {kind if kind in common.KIND_LABELS else "none"}">'
            f"{html.escape(common.KIND_LABELS.get(kind, kind or '?'))}</span>"
        ]
        if origin == "alias":
            badges.append('<span class="b alias">картинка алиаса</span>')
        if product and not product.get("is_catalog_item"):
            badges.append('<span class="b none">вне каталога</span>')
        issues = problem_by_sku.get(sku, [])
        blocking_here = [item for item in issues if item.get("severity") != "warn"]
        warn_here = [item for item in issues if item.get("severity") == "warn"]
        if blocking_here:
            badges.append('<span class="b problem">проверить</span>')
        elif warn_here:
            badges.append('<span class="b plakat">к разбору</span>')

        tags = [kind or "none", "gap" if kind == "none" else "filled"]
        if origin:
            tags.append(origin)
        if has_drawing:
            tags.append("has-drawing")
        if has_plakat:
            tags.append("has-plakat")
        if blocking_here:
            tags.append("problem")
        if warn_here:
            tags.append("warn")
        if reg.get("archive_file"):
            tags.append("archive")
        if both_slots and has_drawing and has_plakat:
            tags.append("both")
        meta = []
        if reg.get("perimeter_mm"):
            meta.append(f"P = {reg['perimeter_mm']} мм")
        if reg.get("archive_file"):
            meta.append("исходник есть")
        search_blob = " ".join(
            [sku, product.get("name") or "", row.get("evidence", ""), row.get("note", ""), kind, origin]
        ).lower()
        problems_html = "".join(
            f'<div class="note" style="color:{"#b45309" if item.get("severity") == "warn" else "#b91c1c"}">'
            f'{"⚠" if item.get("severity") == "warn" else "✖"} {html.escape(item["text"])}</div>'
            for item in issues
        )
        href_full = common.full_href(drawing_rel) or common.full_href(photo_rel)
        cards.append(
            f"""<article class="card{" problem" if blocking_here else ""}"
  data-filterable data-tags="{html.escape(' '.join(tags))}" data-search="{html.escape(search_blob)}"
  data-has-drawing="{1 if has_drawing else 0}" data-has-plakat="{1 if has_plakat else 0}">
  {shots}
  <div class="body">
    <div class="sku">{html.escape(sku)}</div>
    <div class="name">{html.escape(product.get('name') or '—')}</div>
    <div class="badges">{''.join(badges)}</div>
    {picker}
    <div class="ev">{html.escape(row.get('evidence') or '—')}</div>
    <div class="note">{html.escape(row.get('note') or '')}</div>
    {problems_html}
    <div class="links">
      {'<a href="' + html.escape(href_full) + '" target="_blank">полный файл</a>' if href_full else ''}
      <span class="note">{html.escape(' · '.join(meta))}</span>
    </div>
  </div>
</article>"""
        )

    decisions = decisions_mod.load()
    dims = audit.perimeter_rows(audit.load_dimensions(), truth, decisions)
    duplicates = audit.duplicate_files(products, truth, decisions=decisions)
    dims_section = dimension_section(dims)
    duplicates_section = duplicate_section(duplicates, by_sku, register, thumbs)

    gaps = sorted((row for row in truth.values() if row.get("kind") == "none"), key=lambda r: r["sku"])
    gap_rows = "".join(
        "<tr>"
        f'<td class="code">{index}</td><td class="code">{html.escape(row["sku"])}</td>'
        f"<td>{html.escape((register.get(row['sku']) or {}).get('name') or '—')}</td>"
        f'<td class="mono">{html.escape((register.get(row["sku"]) or {}).get("archive_file") or "")}</td>'
        f'<td>{"да" if (register.get(row["sku"]) or {}).get("archive_file") else "нет"}</td>'
        "</tr>"
        for index, row in enumerate(gaps, 1)
    )
    gap_section = f"""
<div class="section">Без изображения — {len(gaps)} артикулов</div>
<div class="hint">Сверху те, у кого есть архивный исходник: их снимать первыми.
Строки «нет исходника» — отдельная заявка на съёмку.</div>
<table><thead><tr><th>#</th><th>Артикул</th><th>Наименование</th>
<th>Архивный исходник</th><th>Исходник есть</th></tr></thead>
<tbody>{gap_rows}</tbody></table>
"""

    if blocking:
        notice = (
            f'<div class="bad">Расхождений: <b>{len(blocking)}</b> — список ниже, '
            "на карточках красная метка. Это то, что валит "
            '<span class="mono">docs:reviews:check</span>.</div>'
        )
    elif notes:
        notice = (
            f'<div class="warn">Блокирующих расхождений нет; к разбору <b>{len(notes)}</b> — '
            "жёлтая метка, проверку не валит.</div>"
        )
    else:
        notice = '<div class="ok">Карточки, разметка и storage согласованы: расхождений нет.</div>'
    problem_section = (
        '<div class="section">Расхождения</div>' + template.problem_table(found, "Артикул")
        if found
        else ""
    )

    filled = sum(kinds.get(kind, 0) for kind in ("drawing", "plakat", "photo"))
    summary = "".join(
        [
            template.chip("всего артикулов", len(truth)),
            template.chip("с изображением", filled),
            template.chip("чертёж", kinds.get("drawing", 0)),
            template.chip("плакат", kinds.get("plakat", 0)),
            template.chip("фото изделия", kinds.get("photo", 0)),
            template.chip("без изображения", kinds.get("none", 0)),
            template.chip("картинка алиаса", origins.get("alias", 0)),
            template.chip("в обоих слотах", both_slots),
            template.chip("расхождения чертежа", len(dims)),
            template.chip("общий файл", len(duplicates)),
            template.chip("расхождений", len(blocking)),
            template.chip("к разбору", len(notes)),
        ]
    )
    preview_control = (
        '<span class="seg">'
        '<button data-gmode="preview">превью</button>'
        '<button data-gmode="drawing">чертёж</button>'
        '<button data-gmode="plakat">плакат</button>'
        "</span>"
    )
    panel = template.filters(
        "поиск: артикул, наименование, доказательство",
        [
            ("all", "все"),
            ("drawing", f"чертежи · {kinds.get('drawing', 0)}"),
            ("plakat", f"плакаты · {kinds.get('plakat', 0)}"),
            ("photo", f"фото · {kinds.get('photo', 0)}"),
            ("none", f"без изображения · {kinds.get('none', 0)}"),
            ("alias", f"картинка алиаса · {origins.get('alias', 0)}"),
            ("has-drawing", f"с чертежом · {drawing_available}"),
            ("has-plakat", f"с плакатом · {plakat_available}"),
            ("both", f"оба слота · {both_slots}"),
            ("problem", f"с расхождением · {len({p['key'] for p in blocking})}"),
            ("warn", f"к разбору · {len({p['key'] for p in notes})}"),
        ],
        len(cards),
        prefix=preview_control,
    )

    body = f"""
<div class="sum">{summary}</div>
{notice}
<div class="hint">Вердикты — <span class="mono">docs/catalog/visual-truth.csv</span>,
файлы — прод-storage, привязки — прод-БД. Вид задаёт, что смотреть:
<b>превью</b> — мелкая картинка для обзора; <b>чертёж</b> и <b>плакат</b> — сам
файл из storage, с него читают размеры (файлов: чертёж {drawing_available},
плакат {plakat_available}). Вид сразу включает фильтр «с чертежом» / «с
плакатом» — кнопка в панели подсвечивается, её можно снять кнопкой «все», тогда
видны и пустые слоты. Кнопки на карточке переопределяют вид и появляются, когда у
артикула есть оба изображения. Плакат занимает слот чертежа, пока настоящего
чертежа нет; картинка алиаса требует сверки размеров.</div>
{panel}
<div class="grid">{''.join(cards)}</div>
{gap_section}
{dims_section}
{duplicates_section}
{problem_section}
"""
    subtitle = (
        f"Прод-каталог · сгенерировано {template.stamp()} · "
        f'<a class="nav" href="{SIBLING}">реестр исключений ОСВ →</a>'
    )
    return template.page(
        TITLE, subtitle, body, template.FILTER_JS + PREVIEW_JS
    ), {
        "kinds": dict(kinds),
        "origins": dict(origins),
        "problems": len(blocking),
        "notes": len(notes),
        "articles": len(truth),
        "both_slots": both_slots,
        "conflicts": len(dims),
        "duplicate_groups": len(duplicates),
    }


def write(
    out: Path,
    products: list[dict],
    truth: dict[str, dict],
    register: dict[str, dict],
    found: list[dict] | None = None,
) -> dict:
    found = problems(products, truth, register) if found is None else found
    text, stats = render(products, truth, register, found)
    out.mkdir(parents=True, exist_ok=True)
    (out / PAGE).write_text(text, encoding="utf-8")
    stats["file"] = PAGE
    stats["problems_list"] = found
    return stats
