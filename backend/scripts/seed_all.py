#!/usr/bin/env python
"""CLI seed script — runs full seed pipeline."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from app.seeds.run_seed import run_full_seed


async def main():
    force = "--force" in sys.argv
    async with async_session() as db:
        try:
            result = await run_full_seed(db, force=force)
            await db.commit()
            print("Seed completed successfully:")
            for key, value in result.items():
                print(f"  {key}: {value}")
        except RuntimeError as e:
            await db.rollback()
            print(f"Seed failed: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            await db.rollback()
            print(f"Unexpected error: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
