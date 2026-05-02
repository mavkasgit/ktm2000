from app.main import app


def test_health() -> None:
    assert app is not None
