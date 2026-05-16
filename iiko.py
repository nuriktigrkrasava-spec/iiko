import httpx
import asyncio
import hashlib
import secrets
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, date
from typing import List, Dict, Any, Optional, Tuple

IIKO_CLOUD_BASE = "https://api-ru.iiko.services"

_client_cache: Dict[str, Any] = {}


def _normalize_iiko_url(url: str) -> str:
    """Allow user-entered URLs like 'saya-sushi-aktobe.iiko.it' or
    'saya-sushi-aktobe.iiko.it/resto' → coerce to canonical https://host/resto."""
    u = (url or "").strip()
    if not u:
        return u
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    u = u.rstrip("/")
    # iikoServer endpoints always live under /resto
    if not u.endswith("/resto"):
        u = u + "/resto"
    return u


def get_client(api_login: str, iiko_server: str = None, api_password: str = None):
    if iiko_server:
        iiko_server = _normalize_iiko_url(iiko_server)
        key = f"web:{api_login}@{iiko_server}"
        if key not in _client_cache:
            _client_cache[key] = IikoWebClient(iiko_server, api_login, api_password or api_login)
        return _client_cache[key]
    key = f"cloud:{api_login}"
    if key not in _client_cache:
        _client_cache[key] = IikoClient(api_login)
    return _client_cache[key]


def _dt(date_str: str, end: bool = False) -> str:
    if "T" in date_str:
        return date_str
    if " " in date_str:
        return date_str.replace(" ", "T")
    return f"{date_str}T{'23:59:59' if end else '00:00:00'}"


# ============ iiko CLOUD CLIENT ============

class IikoClient:
    def __init__(self, api_login: str):
        self.api_login = api_login
        self.token: Optional[str] = None
        self.token_expires: Optional[datetime] = None
        self._lock = asyncio.Lock()
        self._columns_cache: Dict[str, List[str]] = {}  # org_id+type → доступные поля

    async def _ensure_token(self):
        async with self._lock:
            if self.token and self.token_expires and datetime.now() < self.token_expires:
                return self.token
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{IIKO_CLOUD_BASE}/api/1/access_token",
                    headers={"Content-Type": "application/json"},
                    json={"apiLogin": self.api_login}
                )
                resp.raise_for_status()
                data = resp.json()
                self.token = data["token"]
                self.token_expires = datetime.now() + timedelta(minutes=14)
                return self.token

    async def _invalidate_token(self, only_if: str):
        async with self._lock:
            if self.token == only_if:
                self.token = None
                self.token_expires = None

    async def get_organizations(self) -> List[Dict[str, Any]]:
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{IIKO_CLOUD_BASE}/api/1/organizations",
                headers={"Authorization": f"Bearer {token}"},
                json={"returnAdditionalInfo": True}
            )
            resp.raise_for_status()
            return resp.json().get("organizations", [])

    async def get_nomenclature(self, org_id: str) -> Dict[str, Any]:
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{IIKO_CLOUD_BASE}/api/1/nomenclature",
                headers={"Authorization": f"Bearer {token}"},
                json={"organizationId": org_id}
            )
            resp.raise_for_status()
            return resp.json()

    async def get_stop_lists(self, org_ids: List[str]) -> Dict[str, Any]:
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{IIKO_CLOUD_BASE}/api/1/stop_lists",
                headers={"Authorization": f"Bearer {token}"},
                json={"organizationIds": org_ids}
            )
            resp.raise_for_status()
            return resp.json()

    async def get_olap_columns(self, org_id: str, report_type: str = "SALES") -> List[str]:
        """Получает список доступных OLAP-полей для организации."""
        cache_key = f"{org_id}:{report_type}"
        if cache_key in self._columns_cache:
            return self._columns_cache[cache_key]
        try:
            token = await self._ensure_token()
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{IIKO_CLOUD_BASE}/api/1/reports/olap/columns",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"organizationId": org_id, "reportType": report_type}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    columns = [c.get("name", "") for c in data.get("columnList", [])]
                    self._columns_cache[cache_key] = columns
                    return columns
        except Exception:
            pass
        return []  # если не удалось — не фильтруем

    def _filter_fields(self, fields: List[str], available: List[str]) -> List[str]:
        if not available:
            return fields
        return [f for f in fields if f in available]

    async def olap_report(
        self,
        org_id: str,
        date_from: str,
        date_to: str,
        group_by: List[str],
        aggregates: List[str]
    ) -> Dict[str, Any]:
        # Фильтруем поля по доступным для этой организации
        available = await self.get_olap_columns(org_id)
        if available:
            group_by = self._filter_fields(group_by, available)
            aggregates = self._filter_fields(aggregates, available)

        payload = {
            "organizationId": org_id,
            "settings": {
                "queryFilter": {
                    "dateFrom": _dt(date_from),
                    "dateTo": _dt(date_to, end=True)
                },
                "groupByRowFields": group_by,
                "aggregateFields": aggregates
            }
        }
        for attempt in range(2):
            token = await self._ensure_token()
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{IIKO_CLOUD_BASE}/api/1/reports/olap",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload
                )
                if resp.status_code == 401 and attempt == 0:
                    await self._invalidate_token(only_if=token)
                    continue
                resp.raise_for_status()
                return resp.json()
        raise Exception("OLAP 401: токен обновлён, но доступ отклонён.")

    async def get_orders_with_dishes(self, org_id: str, date_from: str, date_to: str) -> Dict[str, Any]:
        return await self.olap_report(
            org_id, date_from, date_to,
            ["OrderNum", "DishName"], ["DishCount"]
        )

    async def get_deliveries(self, org_id: str, date_from: str, date_to: str) -> List[Dict[str, Any]]:
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{IIKO_CLOUD_BASE}/api/1/deliveries/by_delivery_date_and_status",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "organizationIds": [org_id],
                    "deliveryDateFrom": _dt(date_from),
                    "deliveryDateTo": _dt(date_to, end=True)
                }
            )
            resp.raise_for_status()
            return resp.json().get("deliveries", [])

    async def get_invoices(self, org_ids: List[str], date_from: str, date_to: str) -> List[Dict[str, Any]]:
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{IIKO_CLOUD_BASE}/api/1/documents/export/invoice_incoming",
                headers={"Authorization": f"Bearer {token}"},
                json={"organizationIds": org_ids, "dateFrom": _dt(date_from), "dateTo": _dt(date_to, end=True)}
            )
            resp.raise_for_status()
            return resp.json()

    async def get_expense_orders(self, org_ids: List[str], date_from: str, date_to: str) -> List[Dict[str, Any]]:
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{IIKO_CLOUD_BASE}/api/1/documents/export/expense_invoice",
                headers={"Authorization": f"Bearer {token}"},
                json={"organizationIds": org_ids, "dateFrom": _dt(date_from), "dateTo": _dt(date_to, end=True)}
            )
            resp.raise_for_status()
            return resp.json()

    async def get_writeoffs(self, org_ids: List[str], date_from: str, date_to: str) -> Dict[str, Any]:
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{IIKO_CLOUD_BASE}/api/1/documents/export/write_off",
                headers={"Authorization": f"Bearer {token}"},
                json={"organizationIds": org_ids, "dateFrom": _dt(date_from), "dateTo": _dt(date_to, end=True)}
            )
            resp.raise_for_status()
            return resp.json()

    async def get_expense_acts(self, org_ids: List[str], date_from: str, date_to: str) -> Dict[str, Any]:
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{IIKO_CLOUD_BASE}/api/1/documents/export/expense",
                headers={"Authorization": f"Bearer {token}"},
                json={"organizationIds": org_ids, "dateFrom": _dt(date_from), "dateTo": _dt(date_to, end=True)}
            )
            resp.raise_for_status()
            return resp.json()

    # ============ SUPPLIERS / NOMENCLATURE / DOCUMENTS — invoice flow ============

    async def get_suppliers(self, org_id: str) -> List[Dict[str, Any]]:
        """Список поставщиков организации. Cloud API: POST /api/1/suppliers."""
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{IIKO_CLOUD_BASE}/api/1/suppliers",
                headers={"Authorization": f"Bearer {token}"},
                json={"organizationId": org_id}
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            # iiko возвращает либо {"employees": [...]}, либо {"suppliers": [...]} — поддерживаем оба
            return data.get("suppliers") or data.get("employees") or []

    async def search_nomenclature(self, org_id: str, query: str,
                                  limit: int = 30) -> List[Dict[str, Any]]:
        """Поиск товаров по имени. Загружает полную номенклатуру (кешируется на 30 мин),
        потом фильтрует локально."""
        cache = getattr(self, "_nomenclature_cache", None)
        if cache is None:
            self._nomenclature_cache: Dict[str, Tuple[datetime, List[Dict]]] = {}
            cache = self._nomenclature_cache

        cached = cache.get(org_id)
        if cached and (datetime.now() - cached[0]) < timedelta(minutes=30):
            products = cached[1]
        else:
            try:
                full = await self.get_nomenclature(org_id)
                products = full.get("products", []) or []
                cache[org_id] = (datetime.now(), products)
            except Exception:
                return []

        q = (query or "").strip().lower()
        if not q:
            return products[:limit]
        out = []
        for p in products:
            name = (p.get("name") or "").lower()
            num = (p.get("num") or "").lower()
            code = (p.get("code") or "").lower()
            if q in name or q in num or q in code:
                out.append(p)
                if len(out) >= limit:
                    break
        return out

    async def get_invoice_items_olap(
        self, org_ids: List[str], date_from: str, date_to: str
    ) -> List[Dict[str, Any]]:
        """Flat per-line-item rows from incoming invoices, used by /api/price-stats.
        Cloud-path: reuses invoice_incoming export and flattens (supplier, date, item) → row."""
        raw = await self.get_invoices(org_ids, date_from, date_to)
        invoices = raw if isinstance(raw, list) else raw.get("invoiceIncomings", []) if isinstance(raw, dict) else []
        out: List[Dict[str, Any]] = []
        for inv in invoices:
            sup = inv.get("supplier")
            if isinstance(sup, dict):
                supplier_name = sup.get("name") or "—"
                supplier_id = sup.get("id") or supplier_name
            else:
                supplier_name = sup or inv.get("supplierName") or "—"
                supplier_id = inv.get("supplierId") or supplier_name
            inv_date = (inv.get("dateIncoming") or inv.get("documentDate") or "")[:10]
            for it in (inv.get("items") or []):
                pid = it.get("productId") or it.get("product")
                if not pid:
                    continue
                amount = float(it.get("amount") or 0)
                if amount <= 0:
                    continue
                price = it.get("price")
                total = float(it.get("sum") or 0)
                if price is None:
                    price = total / amount if amount else 0
                price = float(price)
                if price <= 0:
                    continue
                out.append({
                    "product_id": pid,
                    "product_name": it.get("productName") or it.get("name") or "—",
                    "unit": it.get("amountUnit") or it.get("unit") or "",
                    "supplier_id": supplier_id,
                    "supplier_name": supplier_name,
                    "date": inv_date,
                    "price_per_unit": price,
                    "amount": amount,
                    "sum": total,
                })
        return out

    async def create_incoming_invoice(
        self, org_id: str, supplier_id: str, items: List[Dict[str, Any]],
        date: str, document_number: Optional[str] = None
    ) -> Dict[str, Any]:
        """Создать ВХОДЯЩУЮ накладную в iiko (черновик, status=NEW).
        Cloud API: POST /api/1/documents/create/incomingInvoice

        items[] — список словарей с полями:
            product (str, iiko product id), amount (float),
            sum (float, общая сумма по позиции), price (float, цена за единицу)
        """
        token = await self._ensure_token()
        body = {
            "organizationId": org_id,
            "supplier": supplier_id,
            "dateIncoming": _dt(date),
            "useDefaultDocumentTime": True,
            "items": items,
        }
        if document_number:
            body["documentNumber"] = document_number
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{IIKO_CLOUD_BASE}/api/1/documents/create/incomingInvoice",
                headers={"Authorization": f"Bearer {token}"},
                json=body
            )
            if resp.status_code != 200:
                import logging
                logging.getLogger(__name__).warning(
                    f"iiko create/incomingInvoice {resp.status_code}: "
                    f"body={resp.text[:1000]} | request={body}"
                )
                return {"ok": False, "error": f"HTTP {resp.status_code}", "body": resp.text[:500]}
            data = resp.json()
            return {"ok": True, "id": data.get("id") or data.get("documentId"),
                    "number": data.get("documentNumber") or data.get("number"),
                    "raw": data}

    async def set_document_status(self, org_id: str, document_id: str,
                                   status: str) -> Dict[str, Any]:
        """Изменить статус документа (NEW / PROCESSED / DELETED).
        Cloud API: POST /api/1/documents/setStatus
        Для проведения передать status="PROCESSED", для распроведения — "NEW".
        """
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{IIKO_CLOUD_BASE}/api/1/documents/setStatus",
                headers={"Authorization": f"Bearer {token}"},
                json={"organizationId": org_id, "documentId": document_id, "status": status}
            )
            if resp.status_code != 200:
                return {"ok": False, "error": f"HTTP {resp.status_code}", "body": resp.text[:500]}
            return {"ok": True, "raw": resp.json()}


# ============ iikoWEB CLIENT (self-hosted) ============

class IikoWebClient:
    """Клиент для самохостед iikoWeb 9.x через REST API /resto/api/v2/"""

    def __init__(self, base_url: str, login: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.login = login
        self.password = password
        self.token: Optional[str] = None
        self.token_expires: Optional[datetime] = None
        self._lock = asyncio.Lock()

    @staticmethod
    def _sha1(s: str) -> str:
        return hashlib.sha1(s.encode()).hexdigest()

    async def _ensure_token(self) -> str:
        async with self._lock:
            if self.token and self.token_expires and datetime.now() < self.token_expires:
                return self.token
            async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
                resp = await client.get(
                    f"{self.base_url}/api/auth",
                    params={"login": self.login, "pass": self._sha1(self.password)}
                )
                resp.raise_for_status()
                token = resp.text.strip().strip('"')
                if not token or len(token) < 10:
                    raise Exception(f"iikoWeb auth failed: {resp.text[:200]}")
                self.token = token
                self.token_expires = datetime.now() + timedelta(minutes=25)
                return self.token

    async def _invalidate_token(self):
        async with self._lock:
            self.token = None
            self.token_expires = None

    def _date_filter(self, date_from: str, date_to: str) -> Dict[str, Any]:
        d_from = date_from[:10]
        d_to = date_to[:10]
        include_high = "true"
        if d_from == d_to:
            # Сдвигаем to на +1 день, но делаем его НЕвключительным
            dt = datetime.strptime(d_to, "%Y-%m-%d") + timedelta(days=1)
            d_to = dt.strftime("%Y-%m-%d")
            include_high = "false"
        return {
            "filterType": "DateRange", "periodType": "CUSTOM",
            "from": d_from, "to": d_to,
            "includeLow": "true", "includeHigh": include_high
        }

    # Маппинг: поля облачного API → поля iikoWeb REST API
    # None = поле не существует в iikoWeb, пропускается
    _TO_WEB = {
        "DishAmountSum":        "DishSumInt",
        "OrdersCount":          "UniqOrderId",
        "DishCount":            "DishAmountInt",  # в iikoWeb = кол-во × 1000
        "ProductCategory.Name": "DishCategory",
        "OrderType.Name":       "OrderType",      # в iikoWeb без .Name
        "DishCostSumInt":       None,              # нет в iikoWeb — нужна отдельная лицензия
    }
    _FROM_WEB_EXTRA = {
        "OrderType":     "OrderType.Name",
        "DishAmountInt": "DishCount",
    }
    _FROM_WEB = {v: k for k, v in _TO_WEB.items() if v is not None}



    def _map_fields(self, fields: List[str]) -> List[str]:
        result = []
        for f in fields:
            mapped = self._TO_WEB.get(f, f)
            if mapped is not None:
                result.append(mapped)
        return result

    def _normalize_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        combined = {**self._FROM_WEB, **self._FROM_WEB_EXTRA}
        result = {}
        for k, v in row.items():
            new_key = combined.get(k, k)
            # DishAmountInt — кол-во порций (целое или дробное, не нужно делить)
            if k == "DishAmountInt" and isinstance(v, (int, float)):
                v = round(v, 2)
            result[new_key] = v
        return result

    async def olap_report(
        self,
        org_id: str,
        date_from: str,
        date_to: str,
        group_by: List[str],
        aggregates: List[str],
        deleted_only: bool = False
    ) -> Dict[str, Any]:
        """Выполняет OLAP через iikoWeb REST API, возвращает {"data": [...]} как облако."""
        if deleted_only:
            filters: Dict[str, Any] = {
                "OpenDate.Typed": self._date_filter(date_from, date_to),
                "OrderDeleted": {"filterType": "IncludeValues", "values": ["DELETED"]},
            }
        else:
            filters = {
                "OpenDate.Typed": self._date_filter(date_from, date_to),
                "OrderDeleted": {"filterType": "IncludeValues", "values": ["NOT_DELETED"]},
            }
        if org_id and org_id != "demo":
            filters["Department"] = {"filterType": "IncludeValues", "values": [org_id]}

        payload = {
            "reportType": "SALES",
            "buildSummary": "false",
            "groupByRowFields": self._map_fields(group_by),
            "aggregateFields": self._map_fields(aggregates),
            "filters": filters,
        }

        for attempt in range(2):
            token = await self._ensure_token()
            async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v2/reports/olap",
                    params={"key": token},
                    json=payload
                )
                if resp.status_code == 401 and attempt == 0:
                    await self._invalidate_token()
                    continue
                if not resp.is_success:
                    import logging
                    logging.getLogger(__name__).warning(f"iikoWeb OLAP 400: {resp.text[:300]} | payload={payload}")
                resp.raise_for_status()
                raw = resp.json()
                rows = raw if isinstance(raw, list) else raw.get("data", [])
                return {"data": [self._normalize_row(r) for r in rows]}

        raise Exception("iikoWeb OLAP: не удалось получить данные.")

    async def get_organizations(self) -> List[Dict[str, Any]]:
        """Список торговых точек (DEPARTMENT) из iikoWeb."""
        import xml.etree.ElementTree as ET
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            resp = await client.get(
                f"{self.base_url}/api/corporation/departments",
                params={"key": token}
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            return [
                {"id": e.find("id").text, "name": e.find("name").text}
                for e in root
                if e.find("type") is not None and e.find("type").text == "DEPARTMENT"
            ]

    async def get_stop_lists(self, org_ids: List[str]) -> Dict[str, Any]:
        return {"productionLocations": []}

    async def get_nomenclature(self, org_id: str) -> Dict[str, Any]:
        return {"products": []}

    async def get_expense_acts(self, org_ids: List[str], date_from: str, date_to: str) -> Dict[str, Any]:
        """Расходы через OLAP TRANSACTIONS — INCOME_EXPENSES счета."""
        filters: Dict[str, Any] = {
            "DateTime.OperDayFilter": self._tx_date_filter(date_from, date_to),
            "Account.Group": {"filterType": "IncludeValues", "values": ["INCOME_EXPENSES"]},
        }
        if org_ids and org_ids[0] and org_ids[0] != "demo":
            filters["Department"] = {"filterType": "IncludeValues", "values": org_ids}

        payload = {
            "reportType": "TRANSACTIONS",
            "buildSummary": "false",
            "groupByRowFields": ["Account.Name", "Department"],
            "aggregateFields": ["Sum.ResignedSum"],
            "filters": filters,
        }
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
            resp = await client.post(
                f"{self.base_url}/api/v2/reports/olap",
                params={"key": token},
                json=payload
            )
            resp.raise_for_status()
            raw = resp.json()
            rows = raw if isinstance(raw, list) else raw.get("data", [])
            # Формат для api.py: {"expenses": [{"items": [{"comment": name, "sum": amount, "category": {"name": cat}}], "dateIncoming": date, "paymentType": {"name": dept}}]}
            expenses = []
            for r in rows:
                amount = float(r.get("Sum.ResignedSum") or 0)
                if amount <= 0:
                    continue
                expenses.append({
                    "id": "",
                    "dateIncoming": f"{date_to}T00:00:00",
                    "paymentType": {"name": r.get("Department", "")},
                    "items": [{"comment": r.get("Account.Name", "Расход"), "sum": amount,
                               "category": {"name": r.get("Account.Name", "Прочее")}}],
                    "sum": amount,
                })
            return {"expenses": expenses}

    def _tx_date_filter(self, date_from: str, date_to: str) -> Dict[str, Any]:
        d_from = date_from[:10]
        d_to = date_to[:10]
        if d_from == d_to:
            dt = datetime.strptime(d_to, "%Y-%m-%d") + timedelta(days=1)
            d_to = dt.strftime("%Y-%m-%d")
        return {"filterType": "DateRange", "periodType": "CUSTOM", "from": d_from, "to": d_to}

    async def get_writeoffs(self, org_ids: List[str], date_from: str, date_to: str) -> Dict[str, Any]:
        """Списания через OLAP TRANSACTIONS — возвращает {"writeoffs": [{"items": [...]}]}"""
        filters: Dict[str, Any] = {
            "DateTime.OperDayFilter": self._tx_date_filter(date_from, date_to),
            "TransactionType": {"filterType": "IncludeValues", "values": ["SESSION_WRITEOFF", "WRITEOFF"]},
        }
        if org_ids and org_ids[0] and org_ids[0] != "demo":
            filters["Department"] = {"filterType": "IncludeValues", "values": org_ids}

        payload = {
            "reportType": "TRANSACTIONS",
            "buildSummary": "false",
            "groupByRowFields": ["Product.Category"],
            "aggregateFields": ["Sum.Outgoing"],
            "filters": filters,
        }
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
            resp = await client.post(
                f"{self.base_url}/api/v2/reports/olap",
                params={"key": token},
                json=payload
            )
            resp.raise_for_status()
            raw = resp.json()
            rows = raw if isinstance(raw, list) else raw.get("data", [])
            # Преобразуем в формат который ожидает api.py
            items = [
                {
                    "product": {"category": {"name": r.get("Product.Category") or "Прочее"}},
                    "sum": float(r.get("Sum.Outgoing") or 0)
                }
                for r in rows
            ]
            return {"writeoffs": [{"items": items}]}

    async def get_invoices(self, org_ids: List[str], date_from: str, date_to: str) -> Dict[str, Any]:
        """Накладные через OLAP TRANSACTIONS INVOICE — возвращает {"invoiceIncomings": [...]}"""
        filters: Dict[str, Any] = {
            "DateTime.OperDayFilter": self._tx_date_filter(date_from, date_to),
            "TransactionType": {"filterType": "IncludeValues", "values": ["INVOICE", "SESSION_ACCEPTANCE"]},
        }
        if org_ids and org_ids[0] and org_ids[0] != "demo":
            filters["Department"] = {"filterType": "IncludeValues", "values": org_ids}

        payload = {
            "reportType": "TRANSACTIONS",
            "buildSummary": "false",
            "groupByRowFields": ["Department", "TransactionType"],
            "aggregateFields": ["Sum.Incoming"],
            "filters": filters,
        }
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
            resp = await client.post(
                f"{self.base_url}/api/v2/reports/olap",
                params={"key": token},
                json=payload
            )
            resp.raise_for_status()
            raw = resp.json()
            rows = raw if isinstance(raw, list) else raw.get("data", [])
            # Преобразуем в формат {"invoiceIncomings": [...]}
            result = [
                {
                    "documentNumber": r.get("TransactionType", ""),
                    "status": "Processed",
                    "supplier": {"name": r.get("Department", "—")},
                    "dateIncoming": f"{date_to}T00:00:00",
                    "items": [],
                    "sum": float(r.get("Sum.Incoming") or 0)
                }
                for r in rows
                if float(r.get("Sum.Incoming") or 0) > 0
            ]
            return {"invoiceIncomings": result}

    async def get_olap_columns(self, report_type: str = "TRANSACTIONS") -> List[Dict[str, Any]]:
        """Список доступных OLAP-полей для report_type на этом iikoServer.
        Используется в диагностике при ошибках 'Unknown OLAP field'."""
        token = await self._ensure_token()
        try:
            async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v2/reports/olap/columns/{report_type}",
                    params={"key": token}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        return data
                    if isinstance(data, dict):
                        return data.get("columnList") or data.get("columns") or []
        except Exception:
            pass
        return []

    async def get_invoice_items_olap(
        self, org_ids: List[str], date_from: str, date_to: str
    ) -> List[Dict[str, Any]]:
        """Per-line-item invoice rows via OLAP TRANSACTIONS, grouped by product/supplier/day.
        Self-hosted iikoServer не отдаёт /documents/export/invoice_incoming, поэтому строим
        построчную картину через OLAP (это единственный способ для price-stats).

        Имена товаров/поставщиков НЕ запрашиваем в OLAP — поднимаем из локальных
        кешей (search_nomenclature, get_suppliers), чтобы не зависеть от
        непроверенных `.Name`-полей."""
        filters: Dict[str, Any] = {
            "DateTime.OperDayFilter": self._tx_date_filter(date_from, date_to),
            "TransactionType": {"filterType": "IncludeValues", "values": ["INVOICE", "SESSION_ACCEPTANCE"]},
        }
        if org_ids and org_ids[0] and org_ids[0] != "demo":
            filters["Department"] = {"filterType": "IncludeValues", "values": org_ids}

        payload = {
            "reportType": "TRANSACTIONS",
            "buildSummary": "false",
            "groupByRowFields": ["Counterparty", "Product"],
            "aggregateFields": ["Sum.Incoming", "Amount.Incoming"],
            "filters": filters,
        }
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
            resp = await client.post(
                f"{self.base_url}/api/v2/reports/olap",
                params={"key": token},
                json=payload
            )
            if resp.status_code >= 400:
                # iiko обычно возвращает JSON с описанием — отдаём в except-каскад.
                # Дополнительно тянем список валидных OLAP-полей для точечной диагностики.
                body = resp.text[:300]
                cols = await self.get_olap_columns("TRANSACTIONS")
                names = []
                for c in cols:
                    if isinstance(c, dict):
                        n = c.get("name") or c.get("field") or c.get("id")
                        if n:
                            names.append(str(n))
                    elif isinstance(c, str):
                        names.append(c)
                fields_preview = ", ".join(names[:120]) if names else "<columns endpoint empty/404>"
                raise Exception(f"OLAP {resp.status_code}: {body} | fields: {fields_preview}")
            raw = resp.json()
            rows = raw if isinstance(raw, list) else raw.get("data", [])

        names_by_id: Dict[str, str] = {}
        units_by_id: Dict[str, str] = {}
        suppliers_by_id: Dict[str, str] = {}
        if rows and org_ids and org_ids[0] and org_ids[0] != "demo":
            try:
                products = await self.search_nomenclature(org_ids[0], "", limit=10000)
                for p in products:
                    pid = p.get("id")
                    if pid:
                        names_by_id[pid] = p.get("name") or ""
                        units_by_id[pid] = p.get("unit") or ""
            except Exception:
                pass
            try:
                suppliers = await self.get_suppliers(org_ids[0])
                for s in suppliers:
                    sid = s.get("id")
                    if sid:
                        suppliers_by_id[sid] = s.get("name") or sid
            except Exception:
                pass

        out: List[Dict[str, Any]] = []
        for r in rows:
            pid = r.get("Product") or ""
            if not pid:
                continue
            amount = float(r.get("Amount.Incoming") or 0)
            total = float(r.get("Sum.Incoming") or 0)
            if amount <= 0 or total <= 0:
                continue
            price = total / amount
            cid = r.get("Counterparty") or ""
            out.append({
                "product_id": pid,
                "product_name": names_by_id.get(pid) or "—",
                "unit": units_by_id.get(pid, ""),
                "supplier_id": cid or suppliers_by_id.get(cid, "") or "—",
                "supplier_name": suppliers_by_id.get(cid) or cid or "—",
                "date": "",
                "price_per_unit": price,
                "amount": amount,
                "sum": total,
            })
        return out

    # ============ SUPPLIERS / NOMENCLATURE / DOCUMENTS — self-hosted iikoServer 9.x ============
    # iikoServer возвращает XML по умолчанию. Auth: ?key=<token> в query.
    # Кеш номенклатуры/складов хранится на инстансе на 30 минут.

    def _ensure_caches(self):
        if not hasattr(self, "_nomenclature_cache"):
            self._nomenclature_cache: Dict[str, Tuple[datetime, List[Dict]]] = {}
        if not hasattr(self, "_stores_cache"):
            self._stores_cache: Dict[str, Tuple[datetime, List[Dict]]] = {}
        if not hasattr(self, "_suppliers_cache"):
            self._suppliers_cache: Dict[str, Tuple[datetime, List[Dict]]] = {}

    @staticmethod
    def _xml_to_list_of_dicts(xml_text: str, item_tag: str) -> List[Dict[str, Any]]:
        """Парсит XML вида <list><item>...</item><item>...</item></list> в список dict'ов
        с строковыми значениями. item_tag — имя дочернего тега (e.g. 'employee', 'product')."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []
        # Корень может быть list-like; ищем все item_tag на любой глубине первого уровня
        items = []
        # Сначала ищем напрямую как дети корня
        children = root.findall(item_tag) or root.findall(f".//{item_tag}")
        for el in children:
            d: Dict[str, Any] = {}
            for child in el:
                tag = child.tag
                # учитываем namespace при наличии
                if "}" in tag:
                    tag = tag.split("}", 1)[1]
                d[tag] = (child.text or "").strip() if (child.text is not None) else ""
            items.append(d)
        return items

    async def get_suppliers(self, org_id: str) -> List[Dict[str, Any]]:
        """Список поставщиков. iikoServer: GET /resto/api/suppliers — возвращает XML
        с элементами <employee> (поставщик — это employee со специальной ролью)."""
        self._ensure_caches()
        cached = self._suppliers_cache.get(org_id)
        if cached and (datetime.now() - cached[0]) < timedelta(minutes=30):
            return cached[1]
        token = await self._ensure_token()
        try:
            async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
                resp = await client.get(
                    f"{self.base_url}/api/suppliers",
                    params={"key": token}
                )
                if resp.status_code != 200:
                    return []
                raw = resp.text
                items = self._xml_to_list_of_dicts(raw, "employee")
                if not items:
                    # запасной вариант — попробовать <supplier>
                    items = self._xml_to_list_of_dicts(raw, "supplier")
                # Нормализуем под формат Cloud-варианта: {id, name}
                out = []
                for it in items:
                    sid = it.get("id") or it.get("supplierId") or ""
                    name_parts = [it.get(k, "") for k in ("name", "firstName", "lastName") if it.get(k)]
                    name = " ".join(name_parts).strip() or sid
                    if sid:
                        out.append({"id": sid, "name": name, "_raw": it})
                self._suppliers_cache[org_id] = (datetime.now(), out)
                return out
        except Exception:
            return []

    async def _get_default_store(self, org_id: str) -> Optional[str]:
        """Берёт первый склад из corporation/stores (нужно для incomingInvoice)."""
        self._ensure_caches()
        cached = self._stores_cache.get(org_id)
        if cached and (datetime.now() - cached[0]) < timedelta(minutes=30):
            stores = cached[1]
            return stores[0]["id"] if stores else None
        token = await self._ensure_token()
        try:
            async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
                resp = await client.get(
                    f"{self.base_url}/api/corporation/stores",
                    params={"key": token}
                )
                if resp.status_code != 200:
                    return None
                items = self._xml_to_list_of_dicts(resp.text, "corporateItemDto")
                if not items:
                    items = self._xml_to_list_of_dicts(resp.text, "store")
                stores = [{"id": it.get("id", ""), "name": it.get("name", "")}
                          for it in items if it.get("id")]
                self._stores_cache[org_id] = (datetime.now(), stores)
                return stores[0]["id"] if stores else None
        except Exception:
            return None

    async def search_nomenclature(self, org_id: str, query: str,
                                  limit: int = 30) -> List[Dict[str, Any]]:
        """Поиск товаров. iikoServer: GET /resto/api/v2/entities/products/list — JSON,
        либо /resto/api/products — XML. Кеш на 30 минут, фильтрация локальная."""
        self._ensure_caches()
        cached = self._nomenclature_cache.get(org_id)
        if cached and (datetime.now() - cached[0]) < timedelta(minutes=30):
            products = cached[1]
        else:
            token = await self._ensure_token()
            products = []
            try:
                async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
                    resp = await client.get(
                        f"{self.base_url}/api/v2/entities/products/list",
                        params={"key": token, "includeDeleted": "false"}
                    )
                    if resp.status_code == 200:
                        try:
                            data = resp.json()
                            if isinstance(data, list):
                                products = [
                                    {"id": p.get("id"),
                                     "name": p.get("name"),
                                     "num": p.get("num"),
                                     "code": p.get("code"),
                                     "unit": (p.get("mainUnit") or {}).get("name") if isinstance(p.get("mainUnit"), dict) else p.get("mainUnit")}
                                    for p in data
                                    if p.get("id") and p.get("name")
                                ]
                        except Exception:
                            pass
                    # Fallback: XML на /api/products
                    if not products:
                        resp = await client.get(
                            f"{self.base_url}/api/products",
                            params={"key": token}
                        )
                        if resp.status_code == 200:
                            items = self._xml_to_list_of_dicts(resp.text, "productDto")
                            if not items:
                                items = self._xml_to_list_of_dicts(resp.text, "product")
                            products = [
                                {"id": it.get("id"), "name": it.get("name"),
                                 "num": it.get("num"), "code": it.get("code"),
                                 "unit": it.get("mainUnit")}
                                for it in items
                                if it.get("id") and it.get("name")
                            ]
            except Exception:
                products = []
            self._nomenclature_cache[org_id] = (datetime.now(), products)

        q = (query or "").strip().lower()
        if not q:
            return products[:limit]
        out = []
        for p in products:
            name = (p.get("name") or "").lower()
            num = (p.get("num") or "").lower()
            code = (p.get("code") or "").lower()
            if q in name or q in num or q in code:
                out.append(p)
                if len(out) >= limit:
                    break
        return out

    async def create_incoming_invoice(self, org_id: str, supplier_id: str,
                                       items: List[Dict[str, Any]], date: str,
                                       document_number: Optional[str] = None) -> Dict[str, Any]:
        """Создаёт входящую накладную в iikoServer 9.x как ЧЕРНОВИК (status=NEW).
        Endpoint: POST /resto/api/documents/import/incomingInvoice (тело — XML).

        items[] — список словарей с productId, amount, price, sum (как в Cloud-варианте).
        """
        store_id = await self._get_default_store(org_id)
        if not store_id:
            return {"ok": False, "error": "Не найден склад (defaultStore) — настрой в iikoOffice"}

        dt_iso = date if "T" in date else f"{date}T10:00:00"
        doc_num = document_number or (
            datetime.now().strftime("BOT-%y%m%d-%H%M%S-") + secrets.token_hex(2)
        )

        # Строим XML
        root = ET.Element("document")
        ET.SubElement(root, "documentNumber").text = str(doc_num)
        ET.SubElement(root, "dateIncoming").text = dt_iso
        ET.SubElement(root, "supplier").text = str(supplier_id)
        ET.SubElement(root, "defaultStore").text = str(store_id)
        ET.SubElement(root, "status").text = "NEW"
        items_el = ET.SubElement(root, "items")
        for idx, it in enumerate(items or [], start=1):
            ie = ET.SubElement(items_el, "item")
            ET.SubElement(ie, "num").text = str(idx)
            ET.SubElement(ie, "productId").text = str(it.get("productId") or "")
            ET.SubElement(ie, "amount").text = str(it.get("amount") or 0)
            ET.SubElement(ie, "price").text = str(it.get("price") or 0)
            ET.SubElement(ie, "sum").text = str(it.get("sum") or 0)
            ET.SubElement(ie, "storeId").text = str(store_id)

        xml_body = b'<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(root, encoding="utf-8")

        token = await self._ensure_token()
        try:
            async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
                resp = await client.post(
                    f"{self.base_url}/api/documents/import/incomingInvoice",
                    params={"key": token},
                    headers={"Content-Type": "application/xml"},
                    content=xml_body
                )
                if resp.status_code != 200:
                    import logging
                    logging.getLogger(__name__).warning(
                        f"iikoWeb import/incomingInvoice {resp.status_code}: "
                        f"body={resp.text[:1000]} | xml={xml_body[:1000]!r}"
                    )
                    return {"ok": False,
                            "error": f"HTTP {resp.status_code}",
                            "body": resp.text[:500]}
                # Ответ обычно XML вида <documentValidationResult> с id созданного документа
                try:
                    rroot = ET.fromstring(resp.text)
                    doc_id = ""
                    num_out = doc_num
                    for el in rroot.iter():
                        tag = el.tag.split("}", 1)[-1]
                        if tag in ("documentId", "id") and el.text:
                            doc_id = el.text.strip()
                        if tag == "documentNumber" and el.text:
                            num_out = el.text.strip()
                    return {"ok": True, "id": doc_id, "number": num_out, "raw": resp.text[:500]}
                except Exception:
                    return {"ok": True, "id": "", "number": doc_num, "raw": resp.text[:500]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def set_document_status(self, org_id: str, document_id: str,
                                   status: str) -> Dict[str, Any]:
        """Проводка/распроведение документа в iikoServer.
        Cloud-статусы: NEW (черновик), PROCESSED (проведена). Здесь маппим как есть.

        Точный путь зависит от версии iikoServer. Пробуем два:
          1) POST /api/documents/{id}/setStatus?status=...
          2) PUT  /api/documents/{id}/status?status=...
        """
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            # Попытка 1: POST setStatus
            try:
                resp = await client.post(
                    f"{self.base_url}/api/documents/{document_id}/setStatus",
                    params={"key": token, "status": status}
                )
                if resp.status_code == 200:
                    return {"ok": True, "raw": resp.text[:300]}
            except Exception:
                pass
            # Попытка 2: PUT /status
            try:
                resp = await client.put(
                    f"{self.base_url}/api/documents/{document_id}/status",
                    params={"key": token, "status": status}
                )
                if resp.status_code == 200:
                    return {"ok": True, "raw": resp.text[:300]}
            except Exception:
                pass
            return {"ok": False,
                    "error": "iikoServer не принял setStatus ни на одном из путей "
                             "(/setStatus, /status). Возможно для проводки в твоей версии нужен "
                             "другой эндпоинт — пришли точный URL из iiko-докуменации."}
