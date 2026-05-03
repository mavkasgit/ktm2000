import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://factoryflow_user:factoryflow_pass@localhost:5202/postgres')
    await conn.execute('DROP DATABASE IF EXISTS factoryflow_dev WITH (FORCE)')
    await conn.execute('CREATE DATABASE factoryflow_dev')
    await conn.close()
    print('DB recreated')

asyncio.run(main())
