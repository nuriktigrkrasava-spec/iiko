"""Демо-ссылка: показ продукта новым клиентам.

Главное, что здесь проверяется, — что демо НЕ МОЖЕТ дотянуться до настоящих
данных. Это ссылка, которую раздают незнакомым людям.

Запуск:  python3 -m pytest -q test_demo_link.py
"""
import os
import tempfile

os.environ.setdefault("DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("ENCRYPTION_KEY", "demo-test-key")

import database as D  # noqa: E402
import demo  # noqa: E402
import mountain_routes as M  # noqa: E402
import api  # noqa: E402

D.init_db()


def _link(label="Сеть Ромашка"):
    import secrets
    code = secrets.token_urlsafe(6)
    D.add_demo_link(code, label, created_by=0)
    return code, M.token_for_demo(code)


def test_demo_link_opens_a_made_up_network():
    code, token = _link()
    sc = M.scope_of_token(token)
    assert sc["valid"] and sc["role"] == "owner" and sc["demo"] is True
    names = {b["name"] for b in sc["branches"]}
    assert names == {b["name"] for b in demo.BRANCHES}, names
    assert all(b["organization_id"].startswith("demo-") for b in sc["branches"])


def test_a_forged_signature_opens_nothing():
    """Подпись — единственная защита ссылки: кода мало."""
    assert M.scope_of_token("dабвгд.подделка")["valid"] is False
    code, token = _link()
    assert M.scope_of_token(token[:-1] + "x")["valid"] is False


def test_demo_never_reaches_a_real_branch():
    """Главное свойство. Демо-филиалы уходят в демо-режим ПО ПРЕФИКСУ, до любого
    обращения к iiko, а настоящий UUID-филиал в демо-режим не попадает."""
    user = {"id": 0}
    for b in demo.BRANCHES:
        assert api._use_demo_data(user, b["organization_id"]) is True
    # реальный организационный id — UUID, префикса demo- у него быть не может
    assert api._use_demo_data(user, "4d56a98e-ba42-11ee-0a80-0c4b0002dc21") is False


def test_demo_scope_has_no_credentials():
    """uid=0 намеренно: от его имени в iiko не сходить — филиалов у него нет."""
    code, token = _link()
    sc = M.scope_of_token(token)
    assert sc["uid"] == 0
    assert D.get_restaurants(0) == [] or all(
        r.get("organization_id", "").startswith("demo-") for r in D.get_restaurants(0))


def test_counter_counts_every_open():
    code, token = _link("Клиент А")
    M.scope_of_token(token)
    M.scope_of_token(token)
    M.scope_of_token(token)
    row = [r for r in D.get_demo_links(0) if r["code"] == code][0]
    assert row["opens"] == 3, row
    assert row["first_open_at"] and row["last_open_at"]
    assert row["label"] == "Клиент А"


def test_counter_remembers_the_first_open_separately():
    """«Посмотрел через час» и «через неделю» — разные разговоры с клиентом."""
    code, token = _link()
    M.scope_of_token(token)
    first = [r for r in D.get_demo_links(0) if r["code"] == code][0]["first_open_at"]
    M.scope_of_token(token)
    again = [r for r in D.get_demo_links(0) if r["code"] == code][0]
    assert again["first_open_at"] == first, "первое открытие не должно переписываться"
    assert again["opens"] == 2


def test_the_demo_network_is_worth_showing():
    """Сеть, где все одинаковы, показывать нечего: продукт ровно про разницу."""
    import scoring as S
    scores = [S.score_branch(sig, {"done": 20, "missed": 4})["score"]
              for sig in demo.signals().values()]
    assert all(s is not None for s in scores), scores
    assert max(scores) - min(scores) >= 20, scores       # лидер и отстающий видны
    assert all(30 <= s <= 95 for s in scores), scores    # без карикатуры


def test_seeding_twice_does_not_double_the_data(tmp_path, monkeypatch):
    """Засев зовут при каждом открытии ссылки.

    Своя база: засев пишет разборы и задачи в ОБЫЧНЫЕ таблицы, и в общей
    тестовой базе демо-филиалы протекали в чужие проверки — таблица разборов по
    сети начинала видеть «Абая 52» рядом с настоящими филиалами.
    """
    monkeypatch.setattr(D, "DB_PATH", str(tmp_path / "seed.db"))
    D.init_db()
    orgs = [b["organization_id"] for b in demo.BRANCHES]
    demo.seed()
    before = len(D.get_branch_tasks(orgs))
    assert before > 0, "засев должен что-то создать"
    demo.seed()
    assert len(D.get_branch_tasks(orgs)) == before


def test_every_screen_has_a_hint():
    """Подсказка объясняет ЗАЧЕМ экран, а не что на нём нарисовано."""
    assert set(demo.HINTS) >= {"mountain", "plan", "acts", "checklists"}
    for key, h in demo.HINTS.items():
        assert h["title"] and h["body"], key
        assert len(h["body"]) > 60, f"{key}: слишком коротко, чтобы что-то объяснить"


def test_counter_starts_even_for_a_link_issued_outside_the_cabinet():
    """Ссылка действительна по ПОДПИСИ, а не по строке в базе. Без этого
    выпущенная в обход кабинета открывалась бы молча, и счётчик врал бы нулём."""
    token = M.token_for_demo("вне-кабинета")
    assert M.scope_of_token(token)["valid"] is True
    row = [r for r in D.get_demo_links(0) if r["code"] == "вне-кабинета"]
    assert row and row[0]["opens"] == 1, row
