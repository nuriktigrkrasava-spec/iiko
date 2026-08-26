"""Вход на сайт: подпись Telegram, личная ссылка ?m= и dev-режим.

Запуск:  python3 test_site_auth.py

Зачем: сайт живёт НЕ внутри Telegram, init-data ему взять негде. На проде
BOT_TOKEN задан, и без отдельного пути входа каждый запрос отвечал бы 401 —
задеплоенный сайт был бы экраном сплошных ошибок.
"""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(prefix="siteauth-"), "t.db"))
os.environ.setdefault("ENCRYPTION_KEY", "test-key-for-site-auth")
os.environ.pop("TELEGRAM_BOT_TOKEN", None)

import asyncio  # noqa: E402
import api  # noqa: E402
import mountain_routes as M  # noqa: E402
from fastapi import HTTPException  # noqa: E402

OWNER = 900777


def _call(init=None, site=None):
    return asyncio.run(api.get_current_user(init, site))


def test_site_token_lets_the_owner_in():
    """Личная ссылка ?m=… — полноценный вход: uid из подписи и есть личность."""
    u = _call(site=M.token_for(OWNER))
    assert u["id"] == OWNER, u
    print("  [OK] по личной ссылке сайт входит как владелец 900777")


def test_forged_token_is_rejected():
    """Подпись чужая — 401, а не молчаливый вход под чужим uid."""
    real = M.token_for(OWNER)
    fake = f"999999.{real.split('.', 1)[1]}"
    try:
        _call(site=fake)
    except HTTPException as e:
        assert e.status_code == 401, e.status_code
        print("  [OK] подделанный uid отвергнут 401")
        return
    raise AssertionError("подделанный токен пустили внутрь")


def test_prod_without_any_credential_is_401():
    """Главное, ради чего тест: с заданным BOT_TOKEN и без входных данных —
    401. Локально это маскировалось пустым токеном и DEV_TID."""
    was = api.BOT_TOKEN
    api.BOT_TOKEN = "1234:prod-token"
    try:
        _call()
    except HTTPException as e:
        assert e.status_code == 401
        print("  [OK] прод без подписи и без ссылки — 401, dev-режим не срабатывает")
        return
    finally:
        api.BOT_TOKEN = was
    raise AssertionError("на проде пустили без каких-либо входных данных")


def test_site_token_works_on_prod_too():
    """И наоборот: с боевым BOT_TOKEN ссылка ?m= обязана работать — иначе
    задеплоенный сайт снова превратится в 401 на каждом запросе."""
    was = api.BOT_TOKEN
    api.BOT_TOKEN = "1234:prod-token"
    try:
        assert _call(site=M.token_for(OWNER))["id"] == OWNER
    finally:
        api.BOT_TOKEN = was
    print("  [OK] на проде вход по личной ссылке работает")


def test_telegram_signature_still_wins():
    """Подпись Telegram — по-прежнему первый и главный путь: мини-аппа нет,
    но сайт могут открыть из бота, и тогда init-data приходит."""
    was = api.validate_telegram_init_data
    api.validate_telegram_init_data = lambda s: {"id": 1, "username": "tg", "first_name": "T"}
    try:
        assert _call(init="query_id=…")["username"] == "tg"
    finally:
        api.validate_telegram_init_data = was
    print("  [OK] подпись Telegram разбирается раньше остальных путей")


def test_dev_mode_only_without_bot_token():
    """DEV_TID — только когда бота нет. Иначе это дыра размером с прод."""
    os.environ["DEV_TID"] = "555"
    was = api.BOT_TOKEN
    api.BOT_TOKEN = ""
    try:
        assert _call()["id"] == 555
    finally:
        api.BOT_TOKEN = was
        os.environ.pop("DEV_TID", None)
    print("  [OK] DEV_TID работает только при пустом BOT_TOKEN")


if __name__ == "__main__":
    failed = 0
    for t in (test_site_token_lets_the_owner_in, test_forged_token_is_rejected,
              test_prod_without_any_credential_is_401, test_site_token_works_on_prod_too,
              test_telegram_signature_still_wins, test_dev_mode_only_without_bot_token):
        print(f"\n>>> {t.__name__}")
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {e}")
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {type(e).__name__}: {e}")
    print(f"\n{'='*50}\n{'ВСЕ ТЕСТЫ ОК' if not failed else f'ПРОВАЛЕНО: {failed}'}")
    raise SystemExit(1 if failed else 0)
