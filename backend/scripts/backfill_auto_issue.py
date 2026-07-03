"""Backfill script — obsolete since Этап 3 removed the Movement table writes.

This script is kept for reference only. All transfer operations now use
StockTransaction directly via StockCommandService. Auto-issue on receive
is handled inline in transfers/services.py.
"""
import asyncio


async def main() -> None:
    print("backfill_auto_issue is obsolete since Этап 3. Nothing to do.")


if __name__ == "__main__":
    asyncio.run(main())
