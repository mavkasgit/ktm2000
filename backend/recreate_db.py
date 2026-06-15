import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://ktm2000_user:ktm2000_pass@localhost:5432/postgres')
    await conn.execute('DROP DATABASE IF EXISTS ktm2000_dev WITH (FORCE)')
    await conn.execute('CREATE DATABASE ktm2000_dev')
    await conn.close()
    print('DB recreated')

asyncio.run(main())
