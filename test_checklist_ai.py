"""Экономия на разборе фото чек-листов: четыре предохранителя.

Запуск:  python3 test_checklist_ai.py

В модель не ходим: проверяем правила отбора, сжатие, кэш и подсчёт стоимости.
"""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(prefix="chk-ai-"), "t.db"))

import checklist_ai as C  # noqa: E402


def test_off_by_default():
    """Пока владелец не включил CHECKLIST_AI, ни один кадр не уходит в модель."""
    assert C.AI_ENABLED is False, "рубильник должен быть выключен по умолчанию"
    assert C._client is None, C._client
    print("  [OK] разбор выключен по умолчанию — платить не за что")


def test_sampling_keeps_most_uploads_free():
    """Обычная сдача идёт через модель только выборочно."""
    upload = {"photos": [1, 2, 3, 4]}
    do_low, why_low = C.should_review(upload, rnd=0.05)      # попал в выборку
    do_high, _ = C.should_review(upload, rnd=0.9)            # не попал
    assert do_low and "выборочный" in why_low, why_low
    assert not do_high
    print(f"  [OK] выборка {C.SAMPLE_PCT}%: 0.05 → проверяем, 0.9 → нет")


def test_edge_cases_always_reviewed():
    """Спорное проверяем всегда, даже если не попало в выборку."""
    late, why1 = C.should_review({"photos": [1, 2, 3]}, late=True, rnd=0.99)
    rep, why2 = C.should_review({"photos": [1, 2, 3]}, had_issue_yesterday=True, rnd=0.99)
    few, why3 = C.should_review({"photos": [1]}, rnd=0.99)
    assert late and "опоздан" in why1, why1
    assert rep and "вчера" in why2, why2
    assert few and "трёх" in why3, why3
    print("  [OK] опоздание, вчерашнее нарушение и мало кадров — всегда проверяем")


def test_shrink_cuts_tokens_fourfold():
    """512 px вместо 1024 — вчетверо дешевле: vision считает по площади."""
    big = C.tokens_for(1024, 768)
    small = C.tokens_for(512, 384)
    assert big > 1000 and small < 300, (big, small)
    assert big / small >= 3.9, (big, small)
    print(f"  [OK] кадр 1024×768 ≈ {big} токенов, 512×384 ≈ {small} — в {big // small} раза дешевле")


def test_hash_is_stable_and_short():
    a = C.photo_hash(b"\xff\xd8kadr")
    b = C.photo_hash(b"\xff\xd8kadr")
    c = C.photo_hash(b"\xff\xd8drugoy")
    assert a == b and a != c and len(a) == 32, (a, b, c)
    print("  [OK] хеш кадра стабилен — повтор не оплачивается")


def test_cached_slot_costs_nothing():
    """Все кадры уже в кэше — модель не зовём даже при включённом рубильнике."""
    import asyncio
    photos = [(b"\xff\xd8kadr1", "зал"), (b"\xff\xd8kadr2", "кухня")]
    cache = {C.photo_hash(d): {"ok": True, "issues": []} for d, _ in photos}
    res = asyncio.run(C.review_slot(photos, cache=cache))
    assert res["checked"] and res.get("cached") and res["ok"], res
    print("  [OK] знакомые кадры отдаются из кэша, запроса нет")


def test_one_request_per_slot_not_per_photo():
    """В один запрос уходит слот целиком, но не больше разумного числа кадров."""
    assert C.MAX_PHOTOS_PER_SLOT <= 8, C.MAX_PHOTOS_PER_SLOT
    print(f"  [OK] один запрос на слот, до {C.MAX_PHOTOS_PER_SLOT} кадров в нём")


def test_daily_cost_estimate():
    """Прикидка на сеть: 9 филиалов × 4 слота × 3 зоны × 3 кадра."""
    per_photo = C.tokens_for(C.MAX_SIDE, int(C.MAX_SIDE * 0.75))
    slots = 9 * 4
    naive = slots * 9 * C.tokens_for(1024, 768)                 # всё, без сжатия
    ours = slots * (C.SAMPLE_PCT / 100) * (per_photo * C.MAX_PHOTOS_PER_SLOT + 200)
    assert ours < naive / 10, (ours, naive)
    print(f"  [OK] в день: слепой прогон ≈ {naive:,.0f} токенов, наш ≈ {ours:,.0f}")


if __name__ == "__main__":
    failed = 0
    for t in (test_off_by_default, test_sampling_keeps_most_uploads_free,
              test_edge_cases_always_reviewed, test_shrink_cuts_tokens_fourfold,
              test_hash_is_stable_and_short, test_cached_slot_costs_nothing,
              test_one_request_per_slot_not_per_photo, test_daily_cost_estimate):
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
