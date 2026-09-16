"""Веб-регистрация по демо-ссылке и счётчик «пришло / подключили / активные».

Запуск:  python3 test_signup.py
"""
import os
import tempfile

os.environ.setdefault("DB_PATH", tempfile.mktemp(suffix=".db"))
import database as D  # noqa: E402

D.init_db()


def test_web_signup_gets_an_identity_that_cannot_collide_with_telegram():
    """Человек с сайта регистрируется ДО того, как написал боту: телеграм-id у
    него ещё нет. Выдаём свой, заведомо отрицательный — телеграм таких не
    выдаёт, значит перепутать два аккаунта невозможно."""
    uid1 = D.web_signup("kolya", "Коля")
    uid2 = D.web_signup("masha", "Маша")
    assert uid1 < 0 and uid2 < 0, (uid1, uid2)
    assert uid1 != uid2
    assert D.get_user(uid1)["username"] == "kolya"
    print("  [OK] веб-аккаунты получают свои отрицательные id")


def test_username_is_stored_without_the_at_sign():
    """@kolya и kolya — один человек. Иначе бот не нашёл бы его при /start."""
    uid = D.web_signup("@Petya", "Петя")
    assert D.get_user(uid)["username"] == "petya", D.get_user(uid)
    print("  [OK] @ и регистр не мешают найти человека")


def test_bot_start_claims_the_account_registered_on_the_site():
    """Человек подключил iiko на сайте, потом написал боту. Это ОДИН человек:
    его рестораны обязаны переехать на настоящий телеграм-id, иначе уведомления
    придут в пустой аккаунт, а данные останутся в другом."""
    uid = D.web_signup("vasya", "Вася")
    D.add_restaurant(uid, "login", "org-1", "Мой ресторан", "https://s", "pwd")
    moved = D.claim_web_signup("vasya", 555001)
    assert moved is True
    assert [r["organization_id"] for r in D.get_restaurants(555001)] == ["org-1"]
    assert D.get_restaurants(uid) == []
    print("  [OK] ресторан переехал на настоящий телеграм-id")


def test_claim_is_idempotent_and_ignores_strangers():
    """Второй /start не должен ничего переносить снова, а чужой username —
    вообще ничего трогать."""
    assert D.claim_web_signup("vasya", 555001) is False
    assert D.claim_web_signup("кто-то-ещё", 555002) is False
    print("  [OK] повторный вход и чужой username безвредны")


def test_counter_separates_arrived_connected_and_active():
    """Три разных числа. «Пришёл» — открыл ссылку. «Подключил» — дошёл до конца
    и у него есть ресторан. «Активный» — заходил за последние 7 дней. Мешать их
    нельзя: воронка тогда врёт в обе стороны."""
    import time
    now = int(time.time())
    before = D.acquisition_stats()
    for tid, days_ago in [(900001, 0), (900002, 3), (900003, 30)]:
        D.record_acquisition(tid, f"u{tid}", "site")
        D.touch_acquisition(tid, ts=now - days_ago * 86400)
    D.add_restaurant(900001, "l", "org-c", "Есть", "https://s", "p")
    s = D.acquisition_stats()
    # Сравниваем ПРИРОСТ: таблицу наполняют и соседние тесты.
    assert s["total"] - before["total"] == 3, (before, s)
    assert s["active"] - before["active"] == 2, (before, s)   # третий заходил месяц назад
    assert s["connected"] - before["connected"] == 1, (before, s)
    print("  [OK] пришло / подключили / активные считаются раздельно")


def test_a_visit_updates_activity_but_not_the_arrival_date():
    """Дата прихода — это атрибуция источника, её переписывать нельзя."""
    D.record_acquisition(900010, "old", "instagram")
    first = D.acquisition_stats()
    D.touch_acquisition(900010)
    rows = D.acquisitions_today()
    assert any(r["telegram_id"] == 900010 and r["source"] == "instagram" for r in rows)
    assert D.acquisition_stats()["total"] == first["total"]
    print("  [OK] заход обновляет активность, но не дату прихода и не источник")


if __name__ == "__main__":
    failed = 0
    for t in (test_web_signup_gets_an_identity_that_cannot_collide_with_telegram,
              test_username_is_stored_without_the_at_sign,
              test_bot_start_claims_the_account_registered_on_the_site,
              test_claim_is_idempotent_and_ignores_strangers,
              test_counter_separates_arrived_connected_and_active,
              test_a_visit_updates_activity_but_not_the_arrival_date):
        print(f"\n>>> {t.__name__}")
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {e}")
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {type(e).__name__}: {e}")
    print("\n" + "=" * 50)
    print("ВСЕ ТЕСТЫ ОК" if not failed else f"ПРОВАЛЕНО: {failed}")
