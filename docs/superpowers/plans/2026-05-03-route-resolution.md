# Автоподбор маршрута из импорта — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить автоматический подбор ожидаемого маршрута из импортных данных Excel, жесткую валидацию соответствия активному маршруту изделия, отображение в UI и блокировку approve/release при несоответствии.

**Architecture:** Создаем чистый сервис `route_resolution.py`, который из `source_payload` позиции (operation_code, output_kind, additional_pack_operations) строит ожидаемую сигнатуру маршрута. Затем в `plan_validation.py` добавляем сравнение ожидаемой сигнатуры с активным маршрутом из БД. API `/route-check` возвращает результат сравнения. UI плана показывает expected vs active с индикатором mismatch.

**Tech Stack:** FastAPI, SQLAlchemy async, PostgreSQL, React/TypeScript, pytest

---

## File Structure

| File | Responsibility |
|------|----------------|
| `backend/app/services/route_resolution.py` | Чистый сервис: из source_payload -> expected_route_signature |
| `backend/app/services/route_validation.py` | Валидация expected vs active route; возвращает список ошибок-кодов |
| `backend/app/services/plan_validation.py` | Модифицировать: добавить вызов route_validation |
| `backend/app/api/routes/production_plans.py` | Добавить endpoint GET /{plan_id}/positions/{position_id}/route-check |
| `backend/app/services/production_plan_service.py` | Модифицировать approve_plan_position: добавить route_validation |
| `backend/app/services/plan_generation.py` | Модифицировать create_release_batch: добавить route_validation перед созданием batch |
| `frontend/src/shared/api/productionPlans.ts` | Добавить типы и функцию routeCheck |
| `frontend/src/features/plan-flow/` | Обновить экран плана: показать expected/active route, индикатор mismatch |
| `backend/tests/test_route_resolution.py` | Unit-тесты сервиса route_resolution |
| `backend/tests/test_route_validation.py` | Unit-тесты валидации маршрутов |
| `backend/tests/test_plan_validation.py` | Дополнить: тесты на route mismatch |
| `backend/tests/test_plan_generation.py` | Дополнить: тесты на блокировку release при mismatch |

---

## Task 1: Сервис route_resolution

**Files:**
- Create: `backend/app/services/route_resolution.py`
- Test: `backend/tests/test_route_resolution.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_route_resolution.py`:

```python
import pytest
from app.services.route_resolution import resolve_route_signature, RouteStepSignature

@pytest.mark.parametrize(
    "payload,expected_steps",
    [
        # NONE -> semi_finished_shipment
        (
            {
                "operation_code": None,
                "output_kind": "semi_finished_shipment",
                "additional_pack_operations": [],
                "paired_profile": False,
            },
            ["WH/ISSUE_RAW", "SHOT", "ANOD", "FG_WH/ACCEPT_FINISHED"],
        ),
        # DRILL -> finished_good
        (
            {
                "operation_code": "DRILL",
                "output_kind": "finished_good",
                "additional_pack_operations": [],
                "paired_profile": False,
            },
            ["WH/ISSUE_RAW", "DRILL", "SHOT", "ANOD", "WIP_WH/MOVE_TO_WIP", "SAW", "PACK", "FG_WH/ACCEPT_FINISHED"],
        ),
        # PRESS_WINDOW + PACK_GLUE -> finished_good
        (
            {
                "operation_code": "PRESS_WINDOW",
                "output_kind": "finished_good",
                "additional_pack_operations": [{"operation_code": "PACK_GLUE"}],
                "paired_profile": False,
            },
            ["WH/ISSUE_RAW", "PRESS_WINDOW", "SHOT", "ANOD", "WIP_WH/MOVE_TO_WIP", "SAW", "PACK", "PACK_GLUE", "FG_WH/ACCEPT_FINISHED"],
        ),
        # PRESS_COMB + PACK_DIFFUSER -> finished_good
        (
            {
                "operation_code": "PRESS_COMB",
                "output_kind": "finished_good",
                "additional_pack_operations": [{"operation_code": "PACK_DIFFUSER"}],
                "paired_profile": False,
            },
            ["WH/ISSUE_RAW", "PRESS_COMB", "SHOT", "ANOD", "WIP_WH/MOVE_TO_WIP", "SAW", "PACK", "PACK_DIFFUSER", "FG_WH/ACCEPT_FINISHED"],
        ),
    ],
)
def test_resolve_route_signature(payload, expected_steps):
    result = resolve_route_signature(payload)
    assert [step.step_id for step in result.steps] == expected_steps
    assert result.primary_operation == payload["operation_code"]
    assert result.output_kind == payload["output_kind"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_route_resolution.py -v`
Expected: FAIL with "module not found" or "function not defined"

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/route_resolution.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RouteStepSignature:
    step_id: str
    operation_code: str | None = None
    section_kind: str | None = None
    description: str = ""


@dataclass
class ResolvedRouteSignature:
    steps: list[RouteStepSignature] = field(default_factory=list)
    primary_operation: str | None = None
    output_kind: str | None = None
    additional_pack_operations: list[str] = field(default_factory=list)


def resolve_route_signature(source_payload: dict[str, Any]) -> ResolvedRouteSignature:
    operation_code = source_payload.get("operation_code")
    output_kind = source_payload.get("output_kind")
    additional_pack = source_payload.get("additional_pack_operations") or []
    paired = source_payload.get("paired_profile", False)

    additional_codes = [op["operation_code"] for op in additional_pack if "operation_code" in op]

    steps: list[RouteStepSignature] = [
        RouteStepSignature(step_id="WH/ISSUE_RAW", operation_code=None, section_kind="issue", description="Выдача сырья"),
    ]

    # Первичная операция
    if operation_code in ("DRILL", "PRESS_WINDOW", "PRESS_COMB"):
        steps.append(RouteStepSignature(step_id=operation_code, operation_code=operation_code, section_kind="production", description="Первичная операция"))

    # SHOT по умолчанию включен
    steps.append(RouteStepSignature(step_id="SHOT", operation_code="SHOT", section_kind="production", description="Дробеструй"))

    # ANOD
    steps.append(RouteStepSignature(step_id="ANOD", operation_code="ANOD", section_kind="production", description="Анодирование"))

    # Ветка после анодирования
    if output_kind == "semi_finished_shipment":
        steps.append(RouteStepSignature(step_id="FG_WH/ACCEPT_FINISHED", operation_code="ACCEPT_FINISHED", section_kind="final", description="Приемка на склад ГП"))
    elif output_kind == "finished_good":
        steps.append(RouteStepSignature(step_id="WIP_WH/MOVE_TO_WIP", operation_code="MOVE_TO_WIP", section_kind="intermediate", description="Перемещение на промежуточный склад"))
        steps.append(RouteStepSignature(step_id="SAW", operation_code="SAW", section_kind="production", description="Пила"))
        steps.append(RouteStepSignature(step_id="PACK", operation_code="PACK", section_kind="production", description="Упаковка"))

        # Допоперации упаковки
        for add_code in additional_codes:
            if add_code in ("PACK_GLUE", "PACK_DIFFUSER"):
                steps.append(RouteStepSignature(step_id=add_code, operation_code=add_code, section_kind="production", description=f"Доп. упаковка: {add_code}"))

        steps.append(RouteStepSignature(step_id="FG_WH/ACCEPT_FINISHED", operation_code="ACCEPT_FINISHED", section_kind="final", description="Приемка на склад ГП"))

    return ResolvedRouteSignature(
        steps=steps,
        primary_operation=operation_code,
        output_kind=output_kind,
        additional_pack_operations=additional_codes,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_route_resolution.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/route_resolution.py backend/tests/test_route_resolution.py
git commit -m "feat: add route_resolution service for expected route signatures from import payload"
```

---

## Task 2: Валидация expected vs active route

**Files:**
- Create: `backend/app/services/route_validation.py`
- Modify: `backend/app/services/plan_validation.py`
- Test: `backend/tests/test_route_validation.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_route_validation.py`:

```python
import pytest
from sqlalchemy import select

from app.models.bom import BOM, BOMLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
)
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.services.route_validation import validate_route_match


async def _make_factory_route(session, sku: str, step_codes: list[tuple[str, str]]) -> tuple[Product, ProductionRoute]:
    product = Product(sku=sku, name=f"Finished {sku}", type=ProductType.finished_good, unit="pcs")
    component = Product(sku=f"{sku}-RAW", name=f"Raw {sku}", type=ProductType.component, unit="pcs")
    session.add_all([product, component])
    await session.flush()

    bom = BOM(product_id=product.id, version="v1", is_active=True)
    session.add(bom)
    await session.flush()
    session.add(BOMLine(bom_id=bom.id, component_product_id=component.id, quantity=1, unit="pcs"))

    sections = []
    for code, _ in step_codes:
        sections.append(Section(code=code, name=code))
    session.add_all(sections)
    await session.flush()

    route = ProductionRoute(product_id=product.id, name="Main", version="v1", is_active=True)
    session.add(route)
    await session.flush()

    for index, (code, op_name) in enumerate(step_codes, start=1):
        section = next(s for s in sections if s.code == code)
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=index,
                section_id=section.id,
                operation_name=op_name,
                is_final=index == len(step_codes),
            )
        )
    await session.flush()
    return product, route


@pytest.mark.asyncio
async def test_validate_route_match_valid(session):
    product, route = await _make_factory_route(
        session, "FG-OK",
        [("ISSUE", "Выдача"), ("DRILL", "Сверло"), ("SHOT", "Дробеструй"), ("ANOD", "Анод"), ("INTER", "Пром.склад"), ("SAW", "Пила"), ("PACK", "Упаковка"), ("FINAL", "Сдача")]
    )
    plan = ProductionPlan(plan_no="PLAN-OK", name="OK")
    session.add(plan)
    await session.flush()
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.excel_import,
        source_sku=product.sku,
        quantity=100,
        source_payload={
            "operation_code": "DRILL",
            "output_kind": "finished_good",
            "additional_pack_operations": [],
            "paired_profile": False,
        },
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    session.add(position)
    await session.flush()

    issues = await validate_route_match(session, position)
    assert issues == []


@pytest.mark.asyncio
async def test_validate_route_match_missing_pack_glue(session):
    product, route = await _make_factory_route(
        session, "FG-NO-GLUE",
        [("ISSUE", "Выдача"), ("DRILL", "Сверло"), ("SHOT", "Дробеструй"), ("ANOD", "Анод"), ("INTER", "Пром.склад"), ("SAW", "Пила"), ("PACK", "Упаковка"), ("FINAL", "Сдача")]
    )
    plan = ProductionPlan(plan_no="PLAN-NO-GLUE", name="NO GLUE")
    session.add(plan)
    await session.flush()
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.excel_import,
        source_sku=product.sku,
        quantity=100,
        source_payload={
            "operation_code": "DRILL",
            "output_kind": "finished_good",
            "additional_pack_operations": [{"operation_code": "PACK_GLUE"}],
            "paired_profile": False,
        },
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    session.add(position)
    await session.flush()

    issues = await validate_route_match(session, position)
    assert any("route_missing_pack_additional_operation" in i for i in issues)


@pytest.mark.asyncio
async def test_validate_route_match_wrong_branch(session):
    # ГП маршрут, а в импорте ПФ
    product, route = await _make_factory_route(
        session, "FG-BRANCH",
        [("ISSUE", "Выдача"), ("DRILL", "Сверло"), ("SHOT", "Дробеструй"), ("ANOD", "Анод"), ("INTER", "Пром.склад"), ("SAW", "Пила"), ("PACK", "Упаковка"), ("FINAL", "Сдача")]
    )
    plan = ProductionPlan(plan_no="PLAN-BRANCH", name="BRANCH")
    session.add(plan)
    await session.flush()
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.excel_import,
        source_sku=product.sku,
        quantity=100,
        source_payload={
            "operation_code": "DRILL",
            "output_kind": "semi_finished_shipment",
            "additional_pack_operations": [],
            "paired_profile": False,
        },
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
    )
    session.add(position)
    await session.flush()

    issues = await validate_route_match(session, position)
    assert any("route_not_matching_import_signature" in i for i in issues)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_route_validation.py -v`
Expected: FAIL

- [ ] **Step 3: Write implementation**

Create `backend/app/services/route_validation.py`:

```python
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.production_plan import PlanPosition
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.services.route_resolution import resolve_route_signature


ROUTE_ERROR_CODES = {
    "route_not_matching_import_signature",
    "route_missing_required_step",
    "route_missing_pack_additional_operation",
    "route_primary_operation_mismatch",
}


async def validate_route_match(db: AsyncSession, position: PlanPosition) -> list[str]:
    if position.product_id is None:
        return []

    route = await db.scalar(
        select(ProductionRoute).where(
            ProductionRoute.product_id == position.product_id,
            ProductionRoute.is_active.is_(True),
        )
    )
    if route is None:
        return []

    steps = (
        await db.execute(select(RouteStep).where(RouteStep.route_id == route.id).order_by(RouteStep.sequence))
    ).scalars().all()
    if not steps:
        return []

    # Загрузить секции для kind
    section_kinds: dict[int, str] = {}
    for step in steps:
        section = await db.get(Section, step.section_id)
        if section:
            section_kinds[step.section_id] = section.kind

    active_signature = [
        _route_step_token(step, section_kinds.get(step.section_id, "production"))
        for step in steps
    ]

    expected = resolve_route_signature(position.source_payload or {})
    expected_signature = [step.step_id for step in expected.steps]

    issues: list[str] = []

    # Проверка: первый шаг должен быть issue
    if active_signature and not active_signature[0].startswith("WH/") and not active_signature[0].startswith("ISSUE"):
        issues.append("route_not_matching_import_signature: first step must be issue")

    # Проверка ключевых узлов: ISSUE -> ... -> ANOD -> ... -> FINAL
    def _find_index(sig: list[str], needle: str) -> int | None:
        for i, token in enumerate(sig):
            if needle in token:
                return i
        return None

    issue_idx = _find_index(active_signature, "ISSUE") if _find_index(active_signature, "ISSUE") is not None else _find_index(active_signature, "WH")
    anod_idx = _find_index(active_signature, "ANOD")
    final_idx = _find_index(active_signature, "FINAL") if _find_index(active_signature, "FINAL") is not None else _find_index(active_signature, "FG_WH")

    expected_issue_idx = _find_index(expected_signature, "WH/") if _find_index(expected_signature, "WH/") is not None else _find_index(expected_signature, "ISSUE")
    expected_anod_idx = _find_index(expected_signature, "ANOD")
    expected_final_idx = _find_index(expected_signature, "FINAL") if _find_index(expected_signature, "FINAL") is not None else _find_index(expected_signature, "FG_WH")

    if expected_issue_idx is not None and issue_idx is None:
        issues.append("route_missing_required_step: missing issue/wh step")
    if expected_anod_idx is not None and anod_idx is None:
        issues.append("route_missing_required_step: missing ANOD step")
    if expected_final_idx is not None and final_idx is None:
        issues.append("route_missing_required_step: missing final/fg_wh step")

    # Проверка порядка ключевых узлов
    if issue_idx is not None and anod_idx is not None and final_idx is not None:
        if not (issue_idx < anod_idx < final_idx):
            issues.append("route_not_matching_import_signature: invalid order of key nodes")

    # Проверка primary operation
    if expected.primary_operation is not None:
        primary_codes = ["DRILL", "PRESS_WINDOW", "PRESS_COMB"]
        has_primary = any(token in active_signature for token in primary_codes)
        expected_has_primary = expected.primary_operation in primary_codes
        if expected_has_primary and not has_primary:
            issues.append(f"route_primary_operation_mismatch: expected {expected.primary_operation}")
        elif not expected_has_primary and has_primary:
            issues.append("route_primary_operation_mismatch: unexpected primary operation in route")

    # Проверка допопераций упаковки
    for add_op in expected.additional_pack_operations:
        if add_op not in active_signature:
            issues.append(f"route_missing_pack_additional_operation: {add_op}")

    # Проверка ветки output_kind
    expected_has_wip = _find_index(expected_signature, "WIP_WH") is not None or _find_index(expected_signature, "INTER") is not None
    active_has_wip = _find_index(active_signature, "INTER") is not None
    expected_direct_final = expected.output_kind == "semi_finished_shipment"
    active_direct_final = _find_index(active_signature, "FINAL") == len(active_signature) - 1 or _find_index(active_signature, "FG_WH") == len(active_signature) - 1

    if expected_direct_final and not active_direct_final:
        issues.append("route_not_matching_import_signature: expected direct final branch (semi-finished)")
    if expected_has_wip and not active_has_wip:
        issues.append("route_not_matching_import_signature: expected WIP branch (finished good)")

    return issues


def _route_step_token(step: RouteStep, section_kind: str) -> str:
    # Преобразуем шаг маршрута в токен для сравнения
    # Используем operation_name как fallback
    if step.operation_name in ("Дробеструй", "SHOT"):
        return "SHOT"
    if step.operation_name in ("Анодирование", "ANOD"):
        return "ANOD"
    if step.operation_name in ("Пила", "SAW"):
        return "SAW"
    if step.operation_name in ("Упаковка", "PACK"):
        return "PACK"
    if step.operation_name in ("Сверло", "DRILL"):
        return "DRILL"
    if section_kind == "issue":
        return "ISSUE"
    if section_kind == "intermediate":
        return "INTER"
    if section_kind == "final":
        return "FINAL"
    return step.operation_name.upper()
```

- [ ] **Step 4: Modify plan_validation.py**

Add to `backend/app/services/plan_validation.py` at the end of `validate_plan_position`:

```python
    from app.services.route_validation import validate_route_match

    route_errors = await validate_route_match(db, position)
    errors.extend(route_errors)

    return errors
```

- [ ] **Step 5: Run tests**

Run: `pytest backend/tests/test_route_validation.py backend/tests/test_plan_validation.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/route_validation.py backend/app/services/plan_validation.py backend/tests/test_route_validation.py
git commit -m "feat: add route validation against expected import signature"
```

---

## Task 3: Связка с approve/release

**Files:**
- Modify: `backend/app/services/production_plan_service.py:approve_plan_position`
- Modify: `backend/app/services/plan_generation.py:create_release_batch`
- Test: `backend/tests/test_plan_generation.py`

- [ ] **Step 1: Modify approve_plan_position**

In `backend/app/services/production_plan_service.py` add after validate_plan_position call:

```python
    from app.services.route_validation import validate_route_match

    route_issues = await validate_route_match(db, position)
    if route_issues:
        errors.extend(route_issues)
        position.validation_errors = errors
        position.validation_status = PlanPositionValidationStatus.invalid
        position.status = PlanPositionStatus.invalid
        raise ValueError("; ".join(errors))
```

- [ ] **Step 2: Modify create_release_batch**

In `backend/app/services/plan_generation.py` add inside the loop over selected_positions:

```python
        from app.services.route_validation import validate_route_match

        route_issues = await validate_route_match(db, position)
        if route_issues:
            raise ValueError(f"Route mismatch for position {position.id}: " + "; ".join(route_issues))
```

- [ ] **Step 3: Write integration test**

Add to `backend/tests/test_plan_generation.py`:

```python
@pytest.mark.asyncio
async def test_release_blocked_on_route_mismatch(client, session) -> None:
    # Создаем продукт с маршрутом без PACK_GLUE
    product, _, _ = await _make_ready_product(session, "FG-MISMATCH")
    # Пересоздаем маршрут без допоперации
    from sqlalchemy import select
    from app.models.route import ProductionRoute, RouteStep
    route = await session.scalar(select(ProductionRoute).where(ProductionRoute.product_id == product.id, ProductionRoute.is_active.is_(True)))
    if route:
        route.is_active = False
    await session.flush()
    
    # Создаем новый маршрут без PACK_GLUE
    sections = [
        Section(code="ISSUE", name="Выдача", kind="issue"),
        Section(code="DRILL", name="Сверло", kind="production"),
        Section(code="SHOT", name="Дробеструй", kind="production"),
        Section(code="ANOD", name="Анод", kind="production"),
        Section(code="INTER", name="Пром.склад", kind="intermediate"),
        Section(code="SAW", name="Пила", kind="production"),
        Section(code="PACK", name="Упаковка", kind="production"),
        Section(code="FINAL", name="Сдача", kind="final"),
    ]
    session.add_all(sections)
    await session.flush()
    new_route = ProductionRoute(product_id=product.id, name="Main", version="v2", is_active=True)
    session.add(new_route)
    await session.flush()
    for index, section in enumerate(sections, start=1):
        session.add(RouteStep(route_id=new_route.id, sequence=index, section_id=section.id, operation_name=section.name, is_final=index == len(sections)))
    await session.flush()

    plan = ProductionPlan(plan_no="PLAN-MISMATCH", name="Mismatch", status=ProductionPlanStatus.approved, period_start=date(2026, 5, 1), period_end=date(2026, 5, 31))
    session.add(plan)
    await session.flush()
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.excel_import,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("100"),
        source_payload={"operation_code": "DRILL", "output_kind": "finished_good", "additional_pack_operations": [{"operation_code": "PACK_GLUE"}]},
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
    )
    session.add(position)
    await session.commit()

    response = await client.post(
        f"/api/production-plans/{plan.id}/release-batches",
        json={"positions": [{"plan_position_id": position.id, "release_quantity": "100"}]},
    )
    assert response.status_code == 400
    assert "route_missing_pack_additional_operation" in response.json()["detail"]
```

- [ ] **Step 4: Run tests**

Run: `pytest backend/tests/test_plan_generation.py::test_release_blocked_on_route_mismatch -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/production_plan_service.py backend/app/services/plan_generation.py backend/tests/test_plan_generation.py
git commit -m "feat: block approve and release on route mismatch"
```

---

## Task 4: API endpoint route-check

**Files:**
- Modify: `backend/app/api/routes/production_plans.py`
- Test: extend existing tests

- [ ] **Step 1: Add endpoint**

Add to `backend/app/api/routes/production_plans.py`:

```python
from app.services.route_resolution import resolve_route_signature
from app.services.route_validation import validate_route_match


class RouteCheckOut(BaseModel):
    expected_signature: dict
    active_route_snapshot: dict | None
    match: bool
    issues: list[str]


@router.get("/{production_plan_id}/positions/{position_id}/route-check", response_model=RouteCheckOut)
async def route_check_position(
    production_plan_id: int,
    position_id: int,
    db: AsyncSession = Depends(get_db),
) -> RouteCheckOut:
    position = await db.get(PlanPosition, position_id)
    if position is None or position.production_plan_id != production_plan_id:
        raise HTTPException(status_code=404, detail="Position not found")

    expected = resolve_route_signature(position.source_payload or {})
    expected_dict = {
        "steps": [{"step_id": s.step_id, "operation_code": s.operation_code, "section_kind": s.section_kind, "description": s.description} for s in expected.steps],
        "primary_operation": expected.primary_operation,
        "output_kind": expected.output_kind,
        "additional_pack_operations": expected.additional_pack_operations,
    }

    issues = await validate_route_match(db, position)

    active_snapshot = None
    if position.product_id:
        route = await db.scalar(select(ProductionRoute).where(ProductionRoute.product_id == position.product_id, ProductionRoute.is_active.is_(True)))
        if route:
            steps = (await db.execute(select(RouteStep).where(RouteStep.route_id == route.id).order_by(RouteStep.sequence))).scalars().all()
            sections = {s.id: s for s in (await db.execute(select(Section))).scalars().all()}
            active_snapshot = {
                "route_id": route.id,
                "route_name": route.name,
                "route_version": route.version,
                "steps": [
                    {
                        "sequence": step.sequence,
                        "section_id": step.section_id,
                        "section_code": sections.get(step.section_id, Section(code="?", name="?")).code,
                        "section_name": sections.get(step.section_id, Section(code="?", name="?")).name,
                        "section_kind": sections.get(step.section_id, Section(code="?", name="?")).kind,
                        "operation_name": step.operation_name,
                    }
                    for step in steps
                ],
            }

    return RouteCheckOut(
        expected_signature=expected_dict,
        active_route_snapshot=active_snapshot,
        match=len(issues) == 0,
        issues=issues,
    )
```

- [ ] **Step 2: Add import for select and Section**

Ensure `backend/app/api/routes/production_plans.py` has:
```python
from sqlalchemy import select
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
```

- [ ] **Step 3: Run smoke**

Run: `pytest backend/tests_smoke.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/routes/production_plans.py
git commit -m "feat: add GET route-check endpoint for plan positions"
```

---

## Task 5: UI плана — отображение маршрутов

**Files:**
- Modify: `frontend/src/shared/api/productionPlans.ts`
- Modify: `frontend/src/features/plan-flow/ImportDiffTable.tsx` or relevant plan table component

- [ ] **Step 1: Add API types and function**

Add to `frontend/src/shared/api/productionPlans.ts`:

```typescript
export type RouteCheckStep = {
  step_id: string;
  operation_code: string | null;
  section_kind: string | null;
  description: string;
};

export type RouteCheckResponse = {
  expected_signature: {
    steps: RouteCheckStep[];
    primary_operation: string | null;
    output_kind: string | null;
    additional_pack_operations: string[];
  };
  active_route_snapshot: {
    route_id: number;
    route_name: string;
    route_version: string;
    steps: {
      sequence: number;
      section_id: number;
      section_code: string;
      section_name: string;
      section_kind: string;
      operation_name: string;
    }[];
  } | null;
  match: boolean;
  issues: string[];
};

export async function routeCheck(planId: number, positionId: number) {
  const { data } = await apiClient.get<RouteCheckResponse>(`/production-plans/${planId}/positions/${positionId}/route-check`);
  return data;
}
```

- [ ] **Step 2: Update plan table component**

Find the main plan positions table component (likely in `frontend/src/features/plan-flow/`) and add columns:
- "Ожидаемый маршрут" — render first 2-3 step_ids from expected_signature + tooltip with full list
- "Активный маршрут" — render active_route_snapshot route_name + version
- "Статус маршрута" — green badge "OK" if match, red badge "Mismatch" with issues tooltip
- "Доп. упаковка" — comma-separated additional_pack_operations

For mismatch rows, disable approve/release buttons and show issues text.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/shared/api/productionPlans.ts frontend/src/features/plan-flow/
git commit -m "feat: show expected vs active route in plan UI with mismatch indicator"
```

---

## Task 6: Тесты backend — финализация

- [ ] **Step 1: Run full backend test suite**

```bash
cd backend && pytest tests/ -v --tb=short
```

- [ ] **Step 2: Fix any failures**

- [ ] **Step 3: Commit**

```bash
git commit -m "test: add route resolution and validation test coverage"
```

---

## Task 7: Тесты frontend + smoke

- [ ] **Step 1: Run frontend build**

```bash
cd frontend && npm run build
```

- [ ] **Step 2: Run frontend tests if any**

```bash
cd frontend && npm test
```

- [ ] **Step 3: Commit**

```bash
git commit -m "test: frontend build and smoke tests pass"
```

---

## Task 8: Финальная верификация

- [ ] **Step 1: Run full pytest**

```bash
cd backend && pytest -v
```

- [ ] **Step 2: Run frontend build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

- [ ] **Step 3: Manual check**

Start: `npm run dev`
Import test Excel file.
Check route-check on positions.
Try approve/release on mismatching positions — should block.

- [ ] **Step 4: Report**

Write a short note about any ambiguous rules encountered during implementation.

---

## Spec Coverage Check

| Requirement | Task |
|-------------|------|
| route_resolution сервис | Task 1 |
| Жесткая валидация vs активный маршрут | Task 2 |
| Блокировка approve | Task 3 |
| Блокировка release | Task 3 |
| UI: expected/active route + mismatch | Task 5 |
| API GET route-check | Task 4 |
| Unit тесты route_resolution | Task 1 |
| Unit тесты validation | Task 2 |
| Integration тесты approve/release | Task 3 |
| Frontend тесты | Task 7 |
