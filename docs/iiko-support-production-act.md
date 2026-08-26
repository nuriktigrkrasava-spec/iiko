# Письмо в поддержку iiko: проводка акта приготовления через API

Готовое сообщение — скопировать и отправить на **api@iiko.ru** (можно и в
техподдержку через личный кабинет). Всё, что в нём написано, проверено
запросами к нашему серверу 24.08.2026.

---

**Тема:** iikoServer API — как провести документ productionDocument (акт приготовления)

Здравствуйте.

Мы автоматизируем разбор полуфабрикатов в сети из 9 ресторанов (самохостед
iikoServer, домены вида `ss-mira.iiko.it`, `ss-turk-new.iiko.it`). Наш сервис
считает себестоимость и создаёт акт приготовления через API. Документ
создаётся успешно, но **остаётся черновиком** — провести его через API мы не
нашли способа. Подскажите, пожалуйста, правильный путь.

**Что делаем.** POST `/resto/api/documents/import/productionDocument`, тело XML:

```xml
<document>
  <dateIncoming>2026-08-24T12:00:00</dateIncoming>
  <status>PROCESSED</status>
  <storeFrom>{store}</storeFrom>
  <storeTo>{store}</storeTo>
  <accountTo>{account}</accountTo>
  <products>
    <item><productId>{П/Ф стейк}</productId><amount>1</amount></item>
  </products>
  <preparedProducts>
    <item><productId>{П/Ф обрезки}</productId><amount>0.2</amount></item>
    <item><productId>{отход}</productId><amount>0.1</amount></item>
    <item><productId>{П/Ф нарезка}</productId><amount>0.7</amount></item>
  </preparedProducts>
</document>
```

Ответ: `<documentValidationResult><valid>true</valid><documentNumber>0003</documentNumber></documentValidationResult>`

**Проблема.** Остатки не меняются. Проверяли замером
`/resto/api/v2/reports/balance/stores` до и после импорта: по всем трём
позициям значения совпадают до тысячных. То есть документ создан, но не
проведён.

**Что мы уже пробовали:**

1. `<status>PROCESSED</status>` в теле импорта — принимается, результата нет.
2. Повторный импорт с тем же `<documentNumber>` и статусом — принимается,
   результата нет.
3. Приём, который работает у приходных накладных (ре-импорт с `<id>`
   существующего документа), применить не можем: **id акта получить неоткуда**.
   Все известные нам маршруты экспорта отвечают 404:
   `documents/export/productionDocument`, `documents/export/production`,
   `documents/export/produce`, `documents/export/writeoff`,
   `v2/documents/production`, `v2/documents/production/list`,
   `documents/production`.
   `GET /resto/api/v2/entities/list?rootType=ProductionDocument` →
   `Following types are not supported: [ProductionDocument]`.
4. Отдельных маршрутов импорта для акта разбора/переработки не нашли.
   Проверено перебором 26.08.2026: существующий маршрут отвечает на GET
   `405 Method Not Allowed`, несуществующий — `404`. По этому признаку на
   сервере есть **ровно пять** маршрутов импорта документов:
   `productionDocument`, `incomingInvoice`, `outgoingInvoice`,
   `incomingInventory`, `returnedInvoice`. Экспорт — только два:
   `incomingInvoice`, `outgoingInvoice` (оба отвечают 409 без параметров).
   Маршрутов `documents/import/disassembleDocument`, `.../disassembly`,
   `.../disassemble`, `.../processingDocument`, `.../writeoffDocument`,
   `.../internalTransfer`, `.../menuChangeDocument` — нет (404).
5. Тип документа `DISASSEMBLE_DOCUMENT` (и варианты `DisassembleDocument`,
   `DisassemblyDocument`) сервер не знает:
   `GET /resto/api/v2/entities/list?rootType=DisassembleDocument` →
   `409 Following types are not supported: [DisassembleDocument]`.
   Эндпоинтов `/resto/api/v2/documents` и `/resto/api/v2/documents/create`
   на сервере тоже нет (404).

**Вопросы:**

1. Как провести акт приготовления через API? Есть ли эндпоинт смены статуса
   документа для iikoServer этой версии?
2. Есть ли способ получить id созданного акта (экспорт, список документов)?
3. Каким типом документа корректно оформлять **акт разбора** (одно сырьё →
   несколько полуфабрикатов) — тем же `productionDocument` или другим, и
   поддерживается ли он в API?
4. Если проводка через API не поддерживается принципиально — планируется ли
   она, и какой обходной путь вы рекомендуете?

Сервер, на котором воспроизводится: `ss-mira.iiko.it` (филиал «Бейбітшілік
71»), API-логин `nignarok`. Документы №0001–0003 от 24.08.2026 — наши тестовые.

Спасибо!

---

## Что делать с ответом

Если дадут эндпоинт статуса — добавляем вызов в `iiko.create_production_act`
после импорта, снимаем предупреждение на экране актов (`SalmonAct.tsx`) и
меняем текст на «Акт проведён».

Если скажут «не поддерживается» — оставляем как есть: сайт считает и создаёт
черновик, проводка одним кликом в iikoOffice. Тогда стоит убрать из интерфейса
слово «черновик» как проблему и написать прямо: «Готово. Проведите в Office».
