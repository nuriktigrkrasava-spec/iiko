"""«Гора»: роли по ссылке, баллы, ступени, кто может ставить задачи.

Запуск:  python3 test_mountain.py

Ни iiko, ни Claude не дёргаем: проверяем правила доступа и арифметику баллов.
"""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(prefix="mountain-"), "t.db"))
os.environ.pop("TELEGRAM_BOT_TOKEN", None)

import database as db  # noqa: E402
import mountain_routes as M  # noqa: E402
import assistant_ai as A  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import api  # noqa: E402

client = TestClient(api.app)
OWNER, MANAGER = 900001, 900002
ORG_A, ORG_B = "org-a", "org-b"


def _seed():
    db.init_db()
    conn = db.get_db()
    conn.execute("DELETE FROM restaurants WHERE telegram_id IN (?,?)", (OWNER, MANAGER))
    conn.commit(); conn.close()
    db.add_restaurant(OWNER, "login", ORG_A, "Астана, Филиал А", iiko_server="", api_password="")
    db.add_restaurant(OWNER, "login", ORG_B, "Астана, Филиал Б", iiko_server="", api_password="")
    db.set_branch_manager(ORG_B, MANAGER, "Управляющий Б")


def test_token_is_signed():
    """Ссылку нельзя подделать, поменяв uid: подпись не сойдётся."""
    t = M.token_for(OWNER)
    assert M.uid_from_token(t) == OWNER
    fake = f"{MANAGER}." + t.split(".", 1)[1]
    assert M.uid_from_token(fake) is None, "чужой uid с чужой подписью не должен проходить"
    print("  [OK] токен подписан: подмена uid не проходит")


def test_owner_sees_all_manager_sees_one():
    _seed()
    o = client.get(f"/api/mountain/data/{M.token_for(OWNER)}").json()
    m = client.get(f"/api/mountain/data/{M.token_for(MANAGER)}").json()
    assert o["role"] == "owner" and len(o["branches"]) == 2, o
    assert m["role"] == "manager" and len(m["branches"]) == 1, m
    assert m["branches"][0]["organization_id"] == ORG_B, m
    print("  [OK] владелец видит 2 филиала, управляющий — только свой")


def test_only_owner_assigns():
    _seed()
    task = [{"organization_id": ORG_B, "title": "Разобрать списания", "effort": "средне"}]
    bad = client.post(f"/api/mountain/assign/{M.token_for(MANAGER)}", json={"tasks": task})
    assert bad.status_code == 403, (bad.status_code, bad.text[:120])
    ok = client.post(f"/api/mountain/assign/{M.token_for(OWNER)}", json={"tasks": task})
    assert ok.status_code == 200 and ok.json()["created"] == 1, ok.text[:150]
    print("  [OK] задачу ставит только владелец, управляющему — 403")


def test_points_and_step():
    """Три задачи не поднимают на вершину: 40 ступеней по 25 баллов."""
    _seed()
    tasks = [{"organization_id": ORG_A, "title": f"Задача {i}", "effort": "долго"} for i in range(3)]
    client.post(f"/api/mountain/assign/{M.token_for(OWNER)}", json={"tasks": tasks})
    board = client.get(f"/api/mountain/data/{M.token_for(OWNER)}").json()
    a = next(b for b in board["branches"] if b["organization_id"] == ORG_A)
    for t in a["tasks_open"]:
        client.post(f"/api/mountain/close/{M.token_for(OWNER)}", json={"task_id": t["id"]})
    board = client.get(f"/api/mountain/data/{M.token_for(OWNER)}").json()
    a = next(b for b in board["branches"] if b["organization_id"] == ORG_A)
    assert a["points"] == 150, a          # 3 × «долго» = 150
    assert a["level"]["step"] == 6, a     # 150 / 25
    assert a["level"]["steps"] == 40, a
    print(f"  [OK] 3 задачи «долго» = {a['points']} баллов → ступень {a['level']['step']} из 40")


def test_manager_closes_only_his_branch():
    _seed()
    client.post(f"/api/mountain/assign/{M.token_for(OWNER)}",
                json={"tasks": [{"organization_id": ORG_A, "title": "Чужая задача"}]})
    tid = db.get_branch_tasks([ORG_A])[0]["id"]
    r = client.post(f"/api/mountain/close/{M.token_for(MANAGER)}", json={"task_id": tid})
    assert r.status_code == 404, (r.status_code, r.text[:120])
    print("  [OK] управляющий не закрывает задачу чужого филиала")


def test_penalty_pulls_down():
    """Штрафы за чек-листы вычитаются: филиал реально опускается по горе."""
    # считаем по своим сдачам: сдал слот +1, пропустил −1
    ch = M._checklist_points_own({ORG_A: {"done": 4, "expect": 34, "missed": -30}}, ORG_A)
    assert ch["points"] == 4 - 30, ch
    assert M._level(max(0, 150 + ch["points"]))["step"] < M._level(150)["step"], "штраф должен опускать"
    print(f"  [OK] штраф тянет вниз: {ch['points']} баллов за чек-листы")


def test_rules_pick_the_costliest():
    """Правила выбирают самое дорогое больное место — модель зовём один раз на сеть."""
    rows = A._task_rows({"branches": [{
        "name": "Актау", "revenue": 9_000_000,
        "foodcost": {"fact_pct": 38.0, "norm_pct": 30, "coverage": 85},
        "cancels": 120000, "writeoffs": {"total": 300000, "pct": 7},
        "reviews": [{"label": "2ГИС", "rating": 4.1}], "stop_count": 3,
    }, {"name": "Пустой", "revenue": 0}]})
    assert len(rows) == 1 and rows[0]["key"] == "fc", rows
    assert rows[0]["money"] == 720000, rows
    print(f"  [OK] выбран фудкост на {rows[0]['money']} ₸, филиал без проблем задачи не получил")


def test_low_recipe_coverage_is_not_money():
    """При низком покрытии техкарт факт-фудкост завышен — деньги по нему не обещаем."""
    rows = A._task_rows({"branches": [{
        "name": "Мало техкарт", "revenue": 9_000_000,
        "foodcost": {"fact_pct": 92.0, "norm_pct": 30, "coverage": 12},
        "writeoffs": {"total": 200000},
    }]})
    assert rows and rows[0]["key"] == "wo", rows
    print("  [OK] фудкост с покрытием 12% отброшен, задача ушла на списания")


def test_money_is_capped_by_revenue():
    """Задача не может «стоить» больше трети месячной выручки филиала."""
    rows = A._task_rows({"branches": [{
        "name": "Перекос", "revenue": 1_000_000, "cancels": 90_000_000,
    }]})
    assert rows and rows[0]["money"] == 330000, rows
    print(f"  [OK] 90 млн отмен урезаны до {rows[0]['money']} ₸ — трети выручки")


def test_service_orgs_are_out():
    """КЦ, ЦЕХ, ОФИС — не точки продаж: в горе и задачах им делать нечего."""
    assert M._is_branch("Астана, ул. Г.Алиева 10 (EXPO)")
    for junk in ("КЦ", "ЦЕХ", "ОФИС ", "РОЯЛТИ", "Астана, ул. Алпамыс 61 (ЦЕХ)"):
        assert not M._is_branch(junk), junk
    print("  [OK] служебные организации отфильтрованы, филиалы остались")


if __name__ == "__main__":
    failed = 0
    for t in (test_token_is_signed,
              test_owner_sees_all_manager_sees_one,
              test_only_owner_assigns,
              test_points_and_step,
              test_manager_closes_only_his_branch,
              test_penalty_pulls_down,
              test_rules_pick_the_costliest,
              test_low_recipe_coverage_is_not_money,
              test_money_is_capped_by_revenue,
              test_service_orgs_are_out):
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
