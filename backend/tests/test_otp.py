import pytest
from datetime import UTC, datetime, timedelta
from jose import jwt
from sqlalchemy import select

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.models.user_login_token import UserLoginToken


@pytest.mark.asyncio
async def test_otp_generation_and_login_flow(session, client) -> None:
    # 1. Создаем пользователя-админа и пользователя-оператора
    admin_user = User(
        username="admin_otp",
        email="admin_otp@example.com",
        password_hash=get_password_hash("pass"),
        full_name="Admin OTP",
        role=UserRole.admin,
        is_active=True,
    )
    operator_user = User(
        username="operator_otp",
        email="operator_otp@example.com",
        password_hash=get_password_hash("pass"),
        full_name="Operator OTP",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(admin_user)
    session.add(operator_user)
    await session.commit()

    # Токены авторизации
    from app.core.security import create_access_token
    admin_jwt = create_access_token(subject=admin_user.username)
    operator_jwt = create_access_token(subject=operator_user.username)

    # 2. Админ генерирует OTP для оператора (код 1)
    # Сессия на 1 смену (8 часов / 28800 сек)
    response = await client.post(
        "/api/auth/otp/generate",
        json={
            "user_id": operator_user.id,
            "session_duration_seconds": 28800,
            "code_lifetime_seconds": 600
        },
        headers={"Authorization": f"Bearer {admin_jwt}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert "token" in body
    otp_code_1 = body["token"]

    # Проверим, что код 1 записан в БД
    tokens_in_db = (await session.execute(
        select(UserLoginToken).where(UserLoginToken.user_id == operator_user.id)
    )).scalars().all()
    assert len(tokens_in_db) == 1
    assert tokens_in_db[0].token == otp_code_1

    # 3. Оператор пытается сгенерировать OTP для админа (должно дать 403)
    response_403 = await client.post(
        "/api/auth/otp/generate",
        json={
            "user_id": admin_user.id,
            "session_duration_seconds": 3600
        },
        headers={"Authorization": f"Bearer {operator_jwt}"}
    )
    assert response_403.status_code == 403

    # 4. Оператор генерирует OTP для самого себя (код 2).
    # Это должно сработать и удалить код 1 (автоочистка: только один последний активный)
    response_self = await client.post(
        "/api/auth/otp/generate",
        json={
            "user_id": operator_user.id,
            "session_duration_seconds": 3600
        },
        headers={"Authorization": f"Bearer {operator_jwt}"}
    )
    assert response_self.status_code == 200
    body_self = response_self.json()
    otp_code_2 = body_self["token"]

    # Проверяем, что в БД остался ТОЛЬКО код 2, а код 1 удален
    tokens_in_db_after = (await session.execute(
        select(UserLoginToken).where(UserLoginToken.user_id == operator_user.id)
    )).scalars().all()
    assert len(tokens_in_db_after) == 1
    assert tokens_in_db_after[0].token == otp_code_2

    # Попытка войти по коду 1 должна дать 400 (так как он удален)
    response_login_1 = await client.post(
        "/api/auth/otp/login",
        json={"token": otp_code_1}
    )
    assert response_login_1.status_code == 400

    # 5. Логинимся по коду 2 (для оператора)
    response_login_2 = await client.post(
        "/api/auth/otp/login",
        json={"token": otp_code_2}
    )
    assert response_login_2.status_code == 200
    login_body = response_login_2.json()
    assert "access_token" in login_body
    retrieved_jwt = login_body["access_token"]

    # Раскодируем токен и проверим время жизни (должно быть около 1 часа / 3600 сек)
    payload = jwt.decode(retrieved_jwt, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert payload["sub"] == operator_user.username
    exp_time = datetime.fromtimestamp(payload["exp"], UTC)
    now_time = datetime.now(UTC)
    duration = exp_time - now_time
    assert 3500 < duration.total_seconds() < 3700

    # 6. Проверяем БЕССРОЧНЫЙ токен входа
    # Админ генерирует бессрочный OTP для оператора
    response_inf = await client.post(
        "/api/auth/otp/generate",
        json={
            "user_id": operator_user.id,
            "session_duration_seconds": -1, # Сигнал бессрочности
            "code_lifetime_seconds": 600
        },
        headers={"Authorization": f"Bearer {admin_jwt}"}
    )
    assert response_inf.status_code == 200
    otp_code_inf = response_inf.json()["token"]

    # Входим по бессрочному коду
    response_login_inf = await client.post(
        "/api/auth/otp/login",
        json={"token": otp_code_inf}
    )
    assert response_login_inf.status_code == 200
    inf_jwt = response_login_inf.json()["access_token"]

    # Проверяем, что в токене НЕТ поля 'exp'
    payload_inf = jwt.decode(inf_jwt, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert "exp" not in payload_inf
    assert payload_inf["sub"] == operator_user.username

    # 7. Попытка повторного логина по тому же OTP коду (должна дать 400, так как он одноразовый)
    response_reuse = await client.post(
        "/api/auth/otp/login",
        json={"token": otp_code_inf}
    )
    assert response_reuse.status_code == 400

    # 8. Попытка логина по несуществующему коду
    response_invalid = await client.post(
        "/api/auth/otp/login",
        json={"token": "999999"}
    )
    assert response_invalid.status_code == 400
