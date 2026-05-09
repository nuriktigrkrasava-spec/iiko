import httpx
import asyncio
import hashlib
from datetime import datetime, timedelta, date
from typing import List, Dict, Any, Optional

IIKO_CLOUD_BASE = "https://api-ru.iiko.services"

_client_cache: Dict[str, Any] = {}


def get_client(api_login: str, iiko_server: str = None, api_password: str = None):
    if iiko_server:
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
