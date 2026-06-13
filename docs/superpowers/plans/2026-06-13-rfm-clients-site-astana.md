# Сайт «RFM-клиенты · Астана» — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Отдельная страница `GET /rfm?key=…`, которая по реальным доставкам iiko всех филиалов Астаны считает RFM по правилам Obsidian-заметки и выводит сегменты с действиями + все идеи из «Тактика».

**Architecture:** Всё в `api.py` (существующий FastAPI). Чистые функции-хелперы (`_astana_restaurants`, `_aggregate_clients`, `_rfm_by_thresholds`, `_branch_stats`, `_render_rfm_html`) + один роут `/rfm`, который их оркеструет. Данные тянутся через уже существующий `IikoWebClient.olap_clients_rfm`. Сегментация — по фиксированным порогам из заметки (НЕ квинтильная `_compute_rfm`, её не трогаем).

**Tech Stack:** Python 3.x, FastAPI (`HTMLResponse`), sqlite (`get_all_restaurants`). Тесты — standalone-скрипт `test_rfm_site.py` (как `test_invoice_xml.py`), запуск `.venv/bin/python test_rfm_site.py`. TestClient из starlette для роута.

Спека: `docs/superpowers/specs/2026-06-13-rfm-clients-site-astana-design.md`

---

## Файлы

- Modify: `api.py` — импорт `HTMLResponse`; `RFM_SITE_KEY`; функции `_astana_restaurants`, `_aggregate_clients`, `_rfm_by_thresholds`, `_branch_stats`, `_render_rfm_html`; роут `@app.get("/rfm")`.
- Create: `test_rfm_site.py` — растёт по задачам, единый runner в конце.
- Modify: `render.yaml` — env `RFM_SITE_KEY`.

Существующее, что переиспользуем (НЕ менять): `get_all_restaurants()` (database, отдаёт расшифрованный `api_password`), `get_client()`, `IikoWebClient.olap_clients_rfm(dept, date_from, date_to)`, `_norm_phone()`, `local_now()`. Уже импортированы в `api.py`.

Формат строк `olap_clients_rfm`: `{"Delivery.CustomerPhone", "OpenDate.Typed", "UniqOrderId.OrdersCount", "DishDiscountSumInt"}`.

---

## Task 1: `test_rfm_site.py` каркас + `_astana_restaurants`

**Files:** Create `test_rfm_site.py`; Modify `api.py`.

- [ ] **Step 1: Создать `test_rfm_site.py` с первым тестом и runner**

```python
"""Локальные мини-тесты для сайта /rfm. Запуск: .venv/bin/python test_rfm_site.py
В iiko не ходим — get_all_restaurants и данные подменяются."""
import api
from datetime import date


def test_astana_filter():
    api.get_all_restaurants = lambda: [
        {"organization_name": "Астана, ул. Бокейхана 25а", "api_login": "x"},
        {"organization_name": "Астана, ул. Сыганак 11 (Жагалау)", "api_login": "x"},
        {"organization_name": "Актау, 12 микрорайон 30а", "api_login": "x"},
        {"organization_name": "Костанай, ул. Абая 153", "api_login": "x"},
    ]
    out = api._astana_restaurants()
    names = [r["organization_name"] for r in out]
    assert len(out) == 2, names
    assert all(n.lower().startswith("астана") for n in names), names


if __name__ == "__main__":
    failed = 0
    for t in (test_astana_filter,):
        print(f"\n>>> {t.__name__}")
        try:
            t()
            print("  [OK]")
        except AssertionError as e:
            failed += 1; print(f"  [FAIL] {e}")
        except Exception as e:
            failed += 1; print(f"  [ERROR] {type(e).__name__}: {e}")
    print(f"\n{'='*50}\n{'ВСЕ ТЕСТЫ ОК' if not failed else f'ПРОВАЛЕНО: {failed}'}")
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 2: Запустить — упадёт**

Run: `.venv/bin/python test_rfm_site.py`
Expected: FAIL/ERROR — `api._astana_restaurants` не существует (`AttributeError`).

- [ ] **Step 3: Реализовать в `api.py`** (рядом с другими client-хелперами, напр. возле `_clients_segments`)

```python
def _astana_restaurants():
    """Филиалы Астаны (по префиксу имени) из всех ресторанов с расшифрованными кредами."""
    out = []
    for r in get_all_restaurants():
        if (r.get("organization_name") or "").strip().lower().startswith("астана"):
            out.append(r)
    return out
```

- [ ] **Step 4: Запустить — пройдёт**

Run: `.venv/bin/python test_rfm_site.py`
Expected: `ВСЕ ТЕСТЫ ОК`

- [ ] **Step 5: Commit**

```bash
git add api.py test_rfm_site.py
git commit -m "feat(rfm): _astana_restaurants + каркас теста"
```

---

## Task 2: `_aggregate_clients` (разбивка по 90д)

**Files:** Modify `api.py`, `test_rfm_site.py`.

- [ ] **Step 1: Добавить тест в `test_rfm_site.py`** (и в список runner)

```python
def test_aggregate_clients():
    today = date(2026, 6, 13)
    rows = [
        # phone A: заказ 5 дней назад + заказ 100 дней назад
        {"Delivery.CustomerPhone": "+7 701 000 0001", "OpenDate.Typed": "2026-06-08", "UniqOrderId.OrdersCount": 1, "DishDiscountSumInt": 5000},
        {"Delivery.CustomerPhone": "+7 701 000 0001", "OpenDate.Typed": "2026-03-05", "UniqOrderId.OrdersCount": 1, "DishDiscountSumInt": 3000},
        # phone B: пустой телефон — отбросить
        {"Delivery.CustomerPhone": "", "OpenDate.Typed": "2026-06-08", "UniqOrderId.OrdersCount": 1, "DishDiscountSumInt": 1000},
        # phone C: 0 заказов — отбросить строку
        {"Delivery.CustomerPhone": "+7 701 000 0003", "OpenDate.Typed": "2026-06-08", "UniqOrderId.OrdersCount": 0, "DishDiscountSumInt": 0},
    ]
    agg = api._aggregate_clients(rows, today)
    assert len(agg) == 1, list(agg)
    a = next(iter(agg.values()))
    assert a["orders_total"] == 2 and a["spend_total"] == 8000, a
    assert a["orders_90"] == 1 and a["spend_90"] == 5000, a   # только заказ 5 дней назад
    assert a["last_date"] == "2026-06-08", a
```

- [ ] **Step 2: Запустить — упадёт** (`.venv/bin/python test_rfm_site.py`) — нет `_aggregate_clients`.

- [ ] **Step 3: Реализовать в `api.py`**

```python
def _aggregate_clients(rows, today):
    """Сырые строки olap_clients_rfm → {phone: {orders_90, spend_90, orders_total, spend_total, last_date}}.
    90д-окно считается относительно today."""
    cutoff = (today - timedelta(days=90)).isoformat()
    agg = {}
    for d in rows:
        ph = _norm_phone(d.get("Delivery.CustomerPhone") or "")
        if not ph:
            continue
        n = int(d.get("UniqOrderId.OrdersCount") or 0)
        if n <= 0:
            continue
        spend = float(d.get("DishDiscountSumInt") or 0)
        od = (d.get("OpenDate.Typed") or "")[:10]
        a = agg.setdefault(ph, {"orders_90": 0, "spend_90": 0.0,
                                "orders_total": 0, "spend_total": 0.0, "last_date": ""})
        a["orders_total"] += n
        a["spend_total"] += spend
        if od and od >= cutoff:
            a["orders_90"] += n
            a["spend_90"] += spend
        if od and od > a["last_date"]:
            a["last_date"] = od
    return agg
```

(`timedelta` уже импортирован в `api.py` — он используется в других местах; если вдруг нет, добавить к `from datetime import ...`.)

- [ ] **Step 4: Запустить — пройдёт.**
- [ ] **Step 5: Commit**

```bash
git add api.py test_rfm_site.py
git commit -m "feat(rfm): _aggregate_clients — агрегат с разбивкой по 90д"
```

---

## Task 3: `_rfm_by_thresholds` (сегментация по заметке)

**Files:** Modify `api.py`, `test_rfm_site.py`.

- [ ] **Step 1: Добавить тест** (в runner)

```python
def _agg(orders_90, spend_90, orders_total, last_date):
    return {"orders_90": orders_90, "spend_90": spend_90,
            "orders_total": orders_total, "spend_total": spend_90, "last_date": last_date}

def test_rfm_segments():
    today = date(2026, 6, 13)
    agg = {
        "champ":   _agg(8, 90000, 12, "2026-06-12"),   # R~1, F7+, высокий M -> champions
        "loyal":   _agg(3, 12000, 5,  "2026-06-10"),   # R~3, F2-3 -> loyal
        "bigrare": _agg(1, 80000, 2,  "2026-05-20"),   # R~24, F=1, топ-M -> big_rare
        "new":     _agg(1, 1500,  1,  "2026-06-11"),   # R~2, F=1, низкий M -> new
        "atrisk":  _agg(0, 0.0,   5,  "2026-05-01"),   # R~43, был частый -> at_risk
        "lost":    _agg(0, 0.0,   1,  "2026-01-10"),   # R 90+ -> lost
    }
    out = api._rfm_by_thresholds(agg, today)
    got = {s["key"]: s["count"] for s in out["segments"]}
    assert out["total"] == 6, out
    for k in ("champions", "loyal", "big_rare", "new", "at_risk", "lost"):
        assert got.get(k) == 1, (k, got)
    # у каждого сегмента есть действие и пример
    for s in out["segments"]:
        assert s["action"] and s["example"], s
```

- [ ] **Step 2: Запустить — упадёт** — нет `_rfm_by_thresholds`.

- [ ] **Step 3: Реализовать в `api.py`**

```python
# (key, emoji, label, action, example) — действия/примеры из заметки «Тактика»/«Сегменты RFM»
_RFM_META = [
    ("champions", "🏆", "Чемпионы",      "беречь, без скидок — ранний доступ к новинкам",
     "Вы в числе первых пробуете новый сет 🔥"),
    ("loyal",     "💛", "Лояльные",      "апселл, поднимать чек",
     "К вашему сету — мисо-суп и напиток за полцены"),
    ("big_rare",  "💸", "Крупные редкие", "дать повод заходить чаще",
     "Подписка «Сет недели» — вкуснее и выгоднее"),
    ("new",       "🌱", "Новички",        "онбординг до 3-го заказа",
     "−15% на второй заказ, действует 7 дней"),
    ("at_risk",   "⚠️", "В зоне риска",    "win-back, окно ещё открыто",
     "Давно не виделись — собрали для вас сет −20%"),
    ("lost",      "⚰️", "Уснувшие",       "последний шанс или отпустить",
     "Последнее предложение: 1+1 на роллы"),
]


def _rfm_by_thresholds(agg, today):
    """agg → сегменты по фиксированным порогам заметки (R дни, F за 90д, M-квинтиль spend_90).
    Возвращает {total, segments:[{key,emoji,label,count,pct,revenue,action,example}]}."""
    custs = [(ph, a) for ph, a in agg.items() if a.get("orders_total", 0) > 0]
    total = len(custs)
    if not total:
        return {"total": 0, "segments": []}

    def rec_days(a):
        ld = a.get("last_date") or ""
        try:
            return (today - date.fromisoformat(ld[:10])).days
        except Exception:
            return 9999

    # M-квинтиль по spend_90 среди клиентов с заказами за 90д (5 = топ)
    spenders = sorted([(ph, a["spend_90"]) for ph, a in custs if a.get("orders_90", 0) >= 1],
                      key=lambda kv: kv[1], reverse=True)
    Lm = len(spenders)
    mq = {ph: 5 - (i * 5 // Lm) for i, (ph, _) in enumerate(spenders)} if Lm else {}

    def seg_of(ph, a):
        r = rec_days(a); f = a.get("orders_90", 0); m = mq.get(ph, 0); ot = a.get("orders_total", 0)
        if r <= 30 and f >= 4 and m >= 4:   return "champions"
        if r <= 30 and f >= 2:              return "loyal"
        if m >= 4 and f <= 2 and r <= 60:   return "big_rare"
        if r <= 30 and f == 1:              return "new"
        if 31 <= r <= 90 and ot >= 3:       return "at_risk"
        return "lost"

    buckets = {k: {"count": 0, "revenue": 0.0} for k, *_ in _RFM_META}
    for ph, a in custs:
        b = buckets[seg_of(ph, a)]
        b["count"] += 1
        b["revenue"] += a.get("spend_total", 0.0)
    segs = [{"key": k, "emoji": e, "label": lbl, "action": act, "example": ex,
             "count": buckets[k]["count"],
             "pct": round(buckets[k]["count"] / total * 100),
             "revenue": round(buckets[k]["revenue"])}
            for k, e, lbl, act, ex in _RFM_META if buckets[k]["count"] > 0]
    return {"total": total, "segments": segs}
```

- [ ] **Step 4: Запустить — пройдёт.**
- [ ] **Step 5: Commit**

```bash
git add api.py test_rfm_site.py
git commit -m "feat(rfm): _rfm_by_thresholds — сегменты по порогам из заметки"
```

---

## Task 4: `_branch_stats` (строка таблицы по филиалу)

**Files:** Modify `api.py`, `test_rfm_site.py`.

- [ ] **Step 1: Добавить тест** (в runner)

```python
def test_branch_stats():
    today = date(2026, 6, 13)
    rows = [
        {"Delivery.CustomerPhone": "+7 701 000 0001", "OpenDate.Typed": "2026-06-10", "UniqOrderId.OrdersCount": 2, "DishDiscountSumInt": 10000},
        {"Delivery.CustomerPhone": "+7 701 000 0002", "OpenDate.Typed": "2026-06-09", "UniqOrderId.OrdersCount": 1, "DishDiscountSumInt": 4000},
    ]
    st = api._branch_stats(rows, today)
    assert st["clients"] == 2, st
    assert st["revenue"] == 14000, st
    assert st["repeat_pct"] == 50, st      # 1 из 2 клиентов с 2+ заказами
    assert st["ltv"] == 7000, st
```

- [ ] **Step 2: Запустить — упадёт.**

- [ ] **Step 3: Реализовать в `api.py`**

```python
def _branch_stats(rows, today):
    """Сводка по одному филиалу из его сырых строк olap_clients_rfm."""
    agg = _aggregate_clients(rows, today)
    total = len(agg)
    revenue = sum(a["spend_total"] for a in agg.values())
    repeat = sum(1 for a in agg.values() if a["orders_total"] >= 2)
    return {"clients": total, "revenue": round(revenue),
            "repeat_pct": round(repeat / total * 100) if total else 0,
            "ltv": round(revenue / total) if total else 0}
```

- [ ] **Step 4: Запустить — пройдёт.**
- [ ] **Step 5: Commit**

```bash
git add api.py test_rfm_site.py
git commit -m "feat(rfm): _branch_stats — статистика по филиалу"
```

---

## Task 5: `_render_rfm_html` (страница + идеи)

**Files:** Modify `api.py`, `test_rfm_site.py`.

- [ ] **Step 1: Добавить тест** (в runner)

```python
def test_render_html():
    report = {
        "date": "2026-06-13",
        "kpi": {"clients": 1234, "revenue": 9000000, "ltv": 7300, "repeat_pct": 41},
        "rfm": {"total": 1234, "segments": [
            {"key": "champions", "emoji": "🏆", "label": "Чемпионы", "count": 142, "pct": 12,
             "revenue": 3000000, "action": "беречь, без скидок", "example": "Первыми пробуете новинку"},
        ]},
        "branches": [
            {"name": "Астана, ул. Бокейхана 25а", "clients": 300, "revenue": 2000000, "repeat_pct": 44, "ltv": 6600},
        ],
    }
    html = api._render_rfm_html(report)
    assert "<html" in html.lower()
    assert "RFM" in html and "Астана" in html
    assert "Чемпионы" in html and "беречь, без скидок" in html
    assert "Бокейхана" in html                       # таблица филиалов
    assert "Уснувшие VIP" in html                    # блок идей
    assert "Челлендж" in html or "челлендж" in html  # блок идей
    assert "приложени" in html                       # миграция в приложение
```

- [ ] **Step 2: Запустить — упадёт.**

- [ ] **Step 3: Реализовать в `api.py`** — функция собирает самодостаточный HTML. Идеи вшиты дословно из заметки «Тактика».

```python
def _render_rfm_html(report):
    k = report["kpi"]
    nf = lambda v: f"{int(v):,}".replace(",", " ")
    seg_cards = "".join(
        f'''<div class="seg">
          <div class="seg-h">{s["emoji"]} {s["label"]}</div>
          <div class="seg-n">{nf(s["count"])} <span class="muted">· {s["pct"]}%</span></div>
          <div class="muted">{nf(s["revenue"])} ₸</div>
          <div class="act">→ {s["action"]}</div>
          <div class="ex">«{s["example"]}»</div>
        </div>'''
        for s in report["rfm"]["segments"]
    )
    branch_rows = "".join(
        f'<tr><td>{b["name"]}</td><td>{nf(b["clients"])}</td><td>{nf(b["revenue"])} ₸</td>'
        f'<td>{b["repeat_pct"]}%</td><td>{nf(b["ltv"])} ₸</td></tr>'
        for b in report["branches"]
    )
    ideas = '''
    <h2>💡 Идеи (из плейбука «Тактика»)</h2>

    <h3>😴 Уснувшие VIP — самое ценное</h3>
    <p>Бывший Чемпион с высоким чеком, но 60–90+ дней тишины. Правило: <b>персональный подход, НЕ массовая скидка</b> — его уводят вниманием.</p>
    <ul>
      <li>🤝 Личное касание «от менеджера», не безличная рассылка.</li>
      <li>🎁 Любимое блюдо в подарок (топ-ролл из истории iiko).</li>
      <li>👑 Вернуть статус/баллы: «сгорают через 7 дней — заберите».</li>
      <li>🚪 Эксклюзив: закрытая дегустация новинки.</li>
      <li>❓ Спросить, почему ушёл — часто причина в качестве/доставке.</li>
    </ul>
    <p class="tip"><b>Лестница возврата:</b> День 30 — мягко («скучаем» + маленький бонус) · День 45 — подарок-блюдо · День 60 — максимум (большой бонус + статус). Не давать максимум сразу — приучает уходить ради скидки.</p>

    <h3>🗂️ Что делать с каждым сегментом</h3>
    <table>
      <tr><th>Сегмент</th><th>Действие</th><th>Пример сообщения</th></tr>
      <tr><td>🏆 Активные VIP</td><td>беречь, без скидок</td><td>«Вы в числе первых пробуете новый сет 🔥»</td></tr>
      <tr><td>😴 Уснувшие VIP</td><td>персональный возврат</td><td>«Ваш любимый [ролл] — в подарок»</td></tr>
      <tr><td>💛 Лояльные</td><td>апселл, ↑ чек</td><td>«К вашему сету — мисо+напиток за полцены»</td></tr>
      <tr><td>🌱 Новички</td><td>онбординг до 3-го заказа</td><td>«−15% на 2-й заказ, 7 дней»</td></tr>
      <tr><td>⚠️ At-risk</td><td>win-back, окно открыто</td><td>«Давно не виделись — сет −20%»</td></tr>
      <tr><td>⚰️ Ушедшие</td><td>последний шанс или отпустить</td><td>«Последнее предложение: 1+1 на роллы»</td></tr>
      <tr><td>💸 Редкие крупные</td><td>повод заходить чаще</td><td>подписка «Сет недели»</td></tr>
      <tr><td>🌙 Спящие новички</td><td>не дать стать ушедшими</td><td>«Помните нас? Вот повод вернуться»</td></tr>
    </table>

    <h3>🎮 Челленджи в приложение</h3>
    <ul>
      <li>🔥 Стрик: 3 недели подряд заказ → бонусный ролл.</li>
      <li>📅 «Суши-пятница»: ×2 баллов в выбранный день.</li>
      <li>🏅 Коллекция: попробуй 5 авторских сетов → бейдж + подарок.</li>
      <li>🎯 Личный челлендж под сегмент: «2 заказа на неделе → бонус».</li>
      <li>👥 Реферальный: приведи друга → награда обоим.</li>
      <li>🎉 Сезонные: Наурыз, Новый год, день рождения сети (FOMO).</li>
      <li>🎰 Mystery box / колесо при заказе через приложение.</li>
      <li>🥉🥈🥇 Уровни: Бронза → Серебро → Золото, привилегии растут.</li>
    </ul>
    <p class="tip">Челлендж = ещё один заказ ради цели, без прямой скидки: маржа цела, частота растёт. Живут только в приложении → это и инструмент миграции.</p>

    <h3>📲 Перевести поток в приложение</h3>
    <p><b>Пряник:</b> лучшая цена только в приложении · баллы копятся только там · челленджи и уровни · новинки сначала в приложении · заказ в 1 клик (сохранённый адрес и любимый заказ).</p>
    <p><b>Каналы захода:</b> QR на коробках/чеках/столах → подарок за 1-й заказ · скрипт курьера/кассира · постепенный перенос лучших офферов из WhatsApp/Instagram в push.</p>
    <p class="tip">Экономика: push ≈ бесплатно, WhatsApp/SMS — деньги за каждое касание. Каждый переведённый клиент дешевле в обслуживании и даёт больше данных для RFM.</p>
    '''
    return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RFM клиентов · Астана</title>
<style>
  :root {{ --bg:#0f1115; --card:#1a1d24; --fg:#e8eaed; --muted:#9aa0a6; --accent:#5B9CF6; }}
  *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);
    font-family:-apple-system,system-ui,sans-serif;padding:20px;max-width:900px;margin:0 auto;line-height:1.5}}
  h1{{font-size:22px;margin:0 0 2px}} .sub{{color:var(--muted);font-size:13px;margin-bottom:18px}}
  .kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:18px}}
  .kpi{{background:var(--card);border-radius:12px;padding:12px}} .kpi .v{{font-size:20px;font-weight:600}}
  .kpi .l{{color:var(--muted);font-size:12px}}
  .segs{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;margin-bottom:22px}}
  .seg{{background:var(--card);border-radius:12px;padding:12px}} .seg-h{{font-weight:600;margin-bottom:4px}}
  .seg-n{{font-size:18px}} .act{{color:var(--accent);font-size:13px;margin-top:6px}}
  .ex{{color:var(--muted);font-size:12px;font-style:italic;margin-top:2px}}
  .muted{{color:var(--muted)}} table{{width:100%;border-collapse:collapse;margin:8px 0 22px;font-size:14px}}
  th,td{{text-align:left;padding:7px 8px;border-bottom:1px solid #262a33}} th{{color:var(--muted);font-weight:500}}
  td:nth-child(n+2),th:nth-child(n+2){{text-align:right}}
  h2{{font-size:18px;margin:26px 0 8px}} h3{{font-size:15px;margin:18px 0 6px}}
  ul{{margin:6px 0;padding-left:20px}} li{{margin:3px 0}}
  .tip{{background:var(--card);border-left:3px solid var(--accent);padding:8px 12px;border-radius:8px;font-size:13px}}
</style></head><body>
  <h1>RFM клиентов · филиалы Астаны</h1>
  <div class="sub">доставка iiko · последние 180 дней · {report["date"]}</div>
  <div class="kpis">
    <div class="kpi"><div class="v">{nf(k["clients"])}</div><div class="l">клиентов</div></div>
    <div class="kpi"><div class="v">{nf(k["revenue"])} ₸</div><div class="l">выручка с клиентов</div></div>
    <div class="kpi"><div class="v">{nf(k["ltv"])} ₸</div><div class="l">средний LTV</div></div>
    <div class="kpi"><div class="v">{k["repeat_pct"]}%</div><div class="l">повторных (2+)</div></div>
  </div>
  <div class="segs">{seg_cards}</div>
  <h2>🏪 По филиалам Астаны</h2>
  <table><tr><th>Филиал</th><th>Клиентов</th><th>Выручка</th><th>Повторных</th><th>LTV</th></tr>{branch_rows}</table>
  {ideas}
</body></html>'''
```

- [ ] **Step 4: Запустить — пройдёт.**
- [ ] **Step 5: Commit**

```bash
git add api.py test_rfm_site.py
git commit -m "feat(rfm): _render_rfm_html — страница сегментов, таблица филиалов, идеи"
```

---

## Task 6: Роут `GET /rfm` + контроль доступа

**Files:** Modify `api.py`, `test_rfm_site.py`.

- [ ] **Step 1: Добавить тест доступа** (в runner). TestClient без `with` — чтобы не запускать startup/планировщики.

```python
def test_rfm_route_access():
    from fastapi.testclient import TestClient
    api.get_all_restaurants = lambda: []     # пустой список → роут не ходит в iiko
    client = TestClient(api.app)

    api.RFM_SITE_KEY = ""                     # ключ не задан → 404
    assert client.get("/rfm").status_code == 404
    assert client.get("/rfm?key=anything").status_code == 404

    api.RFM_SITE_KEY = "secret"
    assert client.get("/rfm").status_code == 403          # нет ключа
    assert client.get("/rfm?key=wrong").status_code == 403
    r = client.get("/rfm?key=secret")
    assert r.status_code == 200, r.status_code
    assert "RFM" in r.text and "Астаны" in r.text         # страница отрендерилась
    api.RFM_SITE_KEY = ""                                 # вернуть как было
```

- [ ] **Step 2: Запустить — упадёт** (роут `/rfm` ещё не существует → 404 на валидном ключе вместо 200, и т.д.).

- [ ] **Step 3: Реализовать в `api.py`**

(a) В импортах ответов добавить `HTMLResponse`. Текущая строка:
`from fastapi.responses import JSONResponse, FileResponse`
→
`from fastapi.responses import JSONResponse, FileResponse, HTMLResponse`

(b) Рядом с другими env/конфиг-константами в `api.py` добавить:
```python
RFM_SITE_KEY = os.getenv("RFM_SITE_KEY", "")
```
(`os` уже импортирован.)

(c) Роут (разместить рядом с корневым `@app.get("/")`):
```python
@app.get("/rfm")
async def rfm_site(key: str = ""):
    """Витрина RFM по филиалам Астаны. Доступ по ?key=RFM_SITE_KEY."""
    if not RFM_SITE_KEY:
        raise HTTPException(status_code=404, detail="Not found")
    if key != RFM_SITE_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")
    today = local_now().date()
    date_to = today.isoformat()
    date_from = (today - timedelta(days=180)).isoformat()

    async def fetch(r):
        client = get_client(r["api_login"], r.get("iiko_server"), r.get("api_password"))
        fn = getattr(client, "olap_clients_rfm", None)
        if not fn:
            return (r, [])
        try:
            return (r, await fn(r["organization_name"], date_from, date_to))
        except Exception as e:
            logger.warning(f"[rfm] {r.get('organization_name')}: {e}")
            return (r, [])

    pairs = await asyncio.gather(*(fetch(r) for r in _astana_restaurants()))
    all_rows, branches = [], []
    for r, rows in pairs:
        all_rows.extend(rows)
        branches.append({"name": r["organization_name"], **_branch_stats(rows, today)})

    agg = _aggregate_clients(all_rows, today)
    total = len(agg)
    revenue = round(sum(a["spend_total"] for a in agg.values()))
    repeat = sum(1 for a in agg.values() if a["orders_total"] >= 2)
    report = {
        "date": date_to,
        "kpi": {"clients": total, "revenue": revenue,
                "ltv": round(revenue / total) if total else 0,
                "repeat_pct": round(repeat / total * 100) if total else 0},
        "rfm": _rfm_by_thresholds(agg, today),
        "branches": sorted(branches, key=lambda b: -b["revenue"]),
    }
    return HTMLResponse(_render_rfm_html(report))
```

- [ ] **Step 4: Запустить весь файл — пройдёт.**

Run: `.venv/bin/python test_rfm_site.py`
Expected: `ВСЕ ТЕСТЫ ОК`

- [ ] **Step 5: Проверить, что приложение импортируется**

Run: `.venv/bin/python -c "import api; print('import OK')"`
Expected: `import OK`

- [ ] **Step 6: Commit**

```bash
git add api.py test_rfm_site.py
git commit -m "feat(rfm): роут GET /rfm — сбор по филиалам Астаны + рендер, доступ по ключу"
```

---

## Task 7: env `RFM_SITE_KEY` в render.yaml

**Files:** Modify `render.yaml`.

- [ ] **Step 1: Найти сервис `iiko` в `render.yaml`** и в его `envVars` добавить:

```yaml
      - key: RFM_SITE_KEY
        sync: false
```

(Если в `render.yaml` нет блока для этого сервиса/нет файла — пропустить и зафиксировать в отчёте, что значение задаётся вручную в дашборде Render.)

- [ ] **Step 2: Commit**

```bash
git add render.yaml
git commit -m "chore(rfm): env RFM_SITE_KEY"
```

- [ ] **Step 3 (вне кода):** задать в Render env `RFM_SITE_KEY=<секрет>` → ссылка `https://iiko.onrender.com/rfm?key=<секрет>`.

---

## Self-Review

- **Покрытие спеки:** доступ/токен → Task 6; филиалы Астаны → Task 1; данные+90д → Task 2; сегментация по порогам заметки → Task 3; таблица филиалов → Task 4; страница+идеи (уснувшие VIP, лестница, сегмент→действие, челленджи, миграция) → Task 5; env → Task 7. Приватность (только агрегаты, телефоны не выводятся) — соблюдена: HTML не получает телефоны.
- **Плейсхолдеров нет:** весь код приведён целиком, включая текст идей.
- **Согласованность:** поля `agg` (`orders_90/spend_90/orders_total/spend_total/last_date`) одинаковы в `_aggregate_clients` (Task 2), `_rfm_by_thresholds` (Task 3), `_branch_stats` (Task 4). `report` (`date/kpi/rfm/branches`) одинаков в роуте (Task 6) и `_render_rfm_html` (Task 5). `RFM_SITE_KEY` — Task 6 определяет, тест Task 6 переопределяет. Сегменты-ключи (`champions/loyal/big_rare/new/at_risk/lost`) совпадают между `_RFM_META`, `seg_of` и тестом Task 3.
