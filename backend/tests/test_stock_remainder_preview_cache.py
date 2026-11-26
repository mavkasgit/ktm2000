"""Кэш разбора предпросмотра остатков (#472).

Предпросмотр принимает файл один раз и отдаёт ``source_token``: смена
фильтра, сортировки или чипа статуса не должна снова отправлять байты и
заново разбирать лист. Здесь проверяется контракт токена, а не скорость —
время меряется отдельно.
"""

from __future__ import annotations

from io import BytesIO

from app.models import Product, ProductType
from app.stock import api as stock_api
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

PREVIEW_URL = "/api/stock/import/remainders/preview"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _make_product(session: AsyncSession, sku: str, name: str | None = None) -> Product:
    product = Product(
        sku=sku,
        name=name or sku,
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()
    return product


def _make_excel(
    rows: list[tuple],
    *,
    sheet_title: str = "Остатки",
    second_sheet: list[tuple] | None = None,
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title
    ws.append(["SKU", "Количество", "Комментарий"])
    for row in rows:
        ws.append(list(row))
    if second_sheet is not None:
        ws2 = wb.create_sheet("Второй лист")
        ws2.append(["SKU", "Количество", "Комментарий"])
        for row in second_sheet:
            ws2.append(list(row))
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _upload(client: AsyncClient, content: bytes, *, sheet_index: int = 0) -> dict:
    resp = await client.post(
        PREVIEW_URL,
        files={"file": ("остатки.xlsx", content, XLSX_MIME)},
        data={"sheet_index": str(sheet_index)},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _preview_by_token(
    client: AsyncClient,
    token: str,
    *,
    sheet_index: int = 0,
    **params: str,
) -> dict:
    resp = await client.post(
        PREVIEW_URL,
        data={"sheet_index": str(sheet_index), "source_token": token, **params},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _count_parse_calls(monkeypatch) -> list[int]:
    """Считать разборы листа, не подменяя сам парсер."""
    calls: list[int] = []
    real_parse = stock_api.parse_remainders_sheet

    async def counting_parse(content, sheet_index=0, row_selection=None, column_mapping=None):
        calls.append(sheet_index)
        return await real_parse(content, sheet_index, row_selection, column_mapping)

    monkeypatch.setattr(stock_api, "parse_remainders_sheet", counting_parse)
    return calls


async def test_source_token_skips_file_reparse(
    client: AsyncClient, session: AsyncSession, monkeypatch
) -> None:
    await _make_product(session, "CACHE-001")
    await _make_product(session, "CACHE-002")
    await session.commit()
    calls = _count_parse_calls(monkeypatch)

    content = _make_excel(
        [
            ("CACHE-001", 10, None),
            ("CACHE-002", 20, None),
        ]
    )
    first = await _upload(client, content)
    token = first["source_token"]
    assert token
    assert calls == [0]

    # Смена сортировки и поиска — только параметры: файл не отправляется,
    # лист повторно не разбирается.
    second = await _preview_by_token(client, token, sort="sku:desc", search="CACHE")
    assert calls == [0]
    assert second["source_token"] == token
    assert second["total_rows"] == first["total_rows"]
    assert len(second["items"]) == 2
    # Сортировка применилась к тем же разобранным строкам.
    assert [item["sku"] for item in second["items"]] == ["CACHE-002", "CACHE-001"]

    # Фильтр статуса тоже считается по готовым строкам.
    only_skipped = await _preview_by_token(client, token, filter_status="skipped")
    assert calls == [0]
    assert only_skipped["items"] == []


async def test_new_file_gets_new_token_and_fresh_parse(
    client: AsyncClient, session: AsyncSession, monkeypatch
) -> None:
    await _make_product(session, "CACHE-NEW-1")
    await _make_product(session, "CACHE-NEW-2")
    await session.commit()
    calls = _count_parse_calls(monkeypatch)

    first = await _upload(client, _make_excel([("CACHE-NEW-1", 5, None)]))
    second = await _upload(client, _make_excel([("CACHE-NEW-2", 7, None)]))

    assert first["source_token"] != second["source_token"]
    assert calls == [0, 0]
    assert second["items"][0]["sku"] == "CACHE-NEW-2"


async def test_token_parses_another_sheet_of_same_file(
    client: AsyncClient, session: AsyncSession, monkeypatch
) -> None:
    await _make_product(session, "CACHE-SHEET-1")
    await _make_product(session, "CACHE-SHEET-2")
    await session.commit()
    calls = _count_parse_calls(monkeypatch)

    content = _make_excel(
        [("CACHE-SHEET-1", 5, None)],
        second_sheet=[("CACHE-SHEET-2", 9, None)],
    )
    first = await _upload(client, content, sheet_index=0)
    token = first["source_token"]

    # Другой лист того же файла — без повторной загрузки байтов: содержимое
    # уже лежит на сервере под токеном.
    another = await _preview_by_token(client, token, sheet_index=1)
    assert calls == [0, 1]
    assert another["sheet_name"] == "Второй лист"
    assert another["items"][0]["sku"] == "CACHE-SHEET-2"

    # Возврат на разобранный лист — снова кэш.
    await _preview_by_token(client, token, sheet_index=0)
    assert calls == [0, 1]


async def test_unknown_or_expired_token_returns_gone(client: AsyncClient) -> None:
    resp = await client.post(
        PREVIEW_URL,
        data={"sheet_index": "0", "source_token": "0" * 64},
    )
    assert resp.status_code == 410
    assert "загрузите файл заново" in resp.json()["detail"]


async def test_token_and_file_together_are_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _make_product(session, "CACHE-BOTH")
    await session.commit()
    content = _make_excel([("CACHE-BOTH", 1, None)])
    first = await _upload(client, content)

    resp = await client.post(
        PREVIEW_URL,
        files={"file": ("остатки.xlsx", content, XLSX_MIME)},
        data={"sheet_index": "0", "source_token": first["source_token"]},
    )
    assert resp.status_code == 422
