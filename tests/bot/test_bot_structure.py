"""Smoke tests: verify bot module structure after decomposition."""


def test_all_routers_importable():
    from app.bot.handlers import all_routers
    assert len(all_routers) >= 14, f"Expected >=14 routers, got {len(all_routers)}"


def test_main_is_coroutine():
    import inspect
    from app.bot.main import main
    assert inspect.iscoroutinefunction(main)
