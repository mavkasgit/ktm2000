from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.health import router as health_router
from app.api.routes.auth import router as auth_router
from app.api.routes.products import router as products_router
from app.api.routes.sections import router as sections_router
from app.api.routes.sections_seed import router as sections_seed_router
from app.api.routes.techcards import router as techcards_router
from app.api.routes.imports import router as imports_router
from app.api.routes.production_plans import router as production_plans_router
from app.api.routes.production_planning import router as production_planning_router
from app.api.routes.release_batches import router as release_batches_router
from app.api.routes.routes import router as routes_router
from app.api.routes.routes_seed import router as routes_seed_router
from app.api.routes.import_templates import router as import_templates_router
from app.api.routes.catalog_import import router as catalog_import_router
from app.api.routes.shopfloor import router as shopfloor_router
from app.api.backups import router as backups_router
from app.core.config import settings
from app.core.database import async_session

app = FastAPI(
    title="KTM-2000",
    description="Manufacturing planning and execution control system",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (product photos, imports)
storage_dir = Path(settings.PRODUCT_PHOTO_DIR).parent
storage_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(storage_dir)), name="static")

app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(products_router, prefix="/api")
app.include_router(sections_router, prefix="/api")
app.include_router(sections_seed_router, prefix="/api")
app.include_router(techcards_router, prefix="/api")
app.include_router(routes_router, prefix="/api")
app.include_router(routes_seed_router, prefix="/api")
app.include_router(imports_router, prefix="/api")
app.include_router(production_plans_router, prefix="/api")
app.include_router(production_planning_router, prefix="/api")
app.include_router(release_batches_router, prefix="/api")
app.include_router(import_templates_router, prefix="/api")
app.include_router(catalog_import_router, prefix="/api")
app.include_router(shopfloor_router, prefix="/api")
app.include_router(backups_router, prefix="/api")


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception:
        return {"status": "ok", "db": "disconnected"}
