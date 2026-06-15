from openpyxl import Workbook
from io import BytesIO
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.spg import SpgSection
from app.models.section import Section
from app.models.route import SectionOperation

async def generate_remainders_excel_template(db: AsyncSession, spg_id: int) -> bytes:
    """Generates an Excel workbook template (.xlsx) for SPG Remainders import."""
    # Получаем все значимые операции в системе по порядку участков и операций
    query = (
        select(SectionOperation)
        .join(Section, Section.id == SectionOperation.section_id)
        .where(SectionOperation.is_significant == True)
        .order_by(Section.sort_order, Section.id, SectionOperation.sort_order, SectionOperation.id)
    )
    ops = (await db.execute(query)).scalars().all()
    
    op_names = []
    seen = set()
    for op in ops:
        if op.operation_name not in seen:
            seen.add(op.operation_name)
            op_names.append(op.operation_name)
            
    if not op_names:
        op_names = ["Дробеструй", "Сверловка"]
        
    wb = Workbook()
    ws = wb.active
    ws.title = "Остатки ГХП"
    
    # Первая строка: Справочник доступных операций
    ws.append([f"Доступные операции: {', '.join(op_names)}"])
    
    # Вторая строка: Заголовки таблицы
    ws.append(["Артикул", "Количество", "Выполненные операции"])
    
    # 3 примера с перечислением операций через запятую
    ws.append(["ALS-1289", 150, "Дробеструй"])
    ws.append(["ЮП-2630", 80, "Сверловка, Дробеструй"])
    ws.append(["361", 200])

    # Настроим ширину колонок
    ws.column_dimensions["A"].width = 25
    ws.column_dimensions["B"].width = 15
    ws.column_dimensions["C"].width = 30

    file_stream = BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)
    return file_stream.getvalue()
