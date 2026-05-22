import asyncio
import logging
import httpx
import os
import hmac
import hashlib
import html
import json
from datetime import datetime, timedelta, date
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple
from uuid import uuid4
from fastapi import FastAPI, Header, HTTPException, Request, Depends, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import uvicorn

from database import (
    init_db, get_user, create_user, set_demo_mode,
    get_restaurants, add_restaurant, delete_restaurant, delete_all_restaurants,
    add_manual_expense, get_manual_expenses, delete_manual_expense,
    save_bot_invoice, get_bot_invoices, get_bot_invoice,
    update_bot_invoice, find_invoice_by_dedup, get_price_history,
    get_db, decrypt_password,
)
from iiko import IikoClient, get_client
from claude_api import analyze_with_claude, analyze_invoice_photos, analyze_invoice_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

IS_PROD = os.getenv("ENVIRONMENT") == "production"

# Swagger отключён в production
app = FastAPI(
    title="iikoBoss Analytics",
    version="1.0.0",
    docs_url=None if IS_PROD else "/docs",
    redoc_url=None if IS_PROD else "/redoc",
)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security headers
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        if IS_PROD:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# CORS — только Telegram origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://web.telegram.org",
        "https://webk.telegram.org",
        "https://webz.telegram.org",
        "null",  # Telegram Mini App webview
    ] if IS_PROD else ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-Telegram-Init-Data", "Content-Type"],
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MINIAPP_URL = os.getenv("MINIAPP_URL", "https://iiko.onrender.com")
DEMO_API_LOGIN = os.getenv("DEMO_API_LOGIN", "demo")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET")


class PeriodEnum(str, Enum):
    today = "today"
    yesterday = "yesterday"
    day_before_yesterday = "day_before_yesterday"
    week = "week"
    month = "month"

# In-memory cache for iiko responses (изолирован по user_id)
_cache: Dict[str, Any] = {}
_cache_time: Dict[str, datetime] = {}


def _cache_key(user_id: int, endpoint: str, org_id: str, period: str) -> str:
    return f"{user_id}:{endpoint}:{org_id}:{period}"


def _get_cached(key: str) -> Optional[Any]:
    if key in _cache and key in _cache_time:
        if datetime.now() - _cache_time[key] < timedelta(minutes=1):
            return _cache[key]
    return None


def _set_cached(key: str, value: Any):
    _cache[key] = value
    _cache_time[key] = datetime.now()


def validate_telegram_init_data(init_data: str) -> Dict[str, Any]:
    if not BOT_TOKEN:
        return {"id": 0, "username": "dev", "first_name": "Developer"}

    from urllib.parse import unquote, parse_qsl
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        if not parsed:
            parsed = dict(x.split("=", 1) for x in init_data.split("&") if "=" in x)

        hash_ = parsed.pop("hash", "")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if calculated_hash != hash_:
            raise HTTPException(status_code=403, detail="Invalid Telegram init data")

        user_raw = unquote(parsed.get("user", "{}"))
        user = json.loads(user_raw)
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Auth validation error: {e}")
        raise HTTPException(status_code=403, detail="Invalid Telegram init data")


async def get_current_user(x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data")):
    if not x_telegram_init_data:
        if not BOT_TOKEN:
            return {"id": 0, "username": "dev", "first_name": "Developer"}
        raise HTTPException(status_code=401, detail="Missing init data")
    user = validate_telegram_init_data(x_telegram_init_data)
    return user


def get_period_dates(period: str, custom_from: Optional[str] = None,
                     custom_to: Optional[str] = None) -> tuple:
    today = datetime.now().date()
    if period == "custom":
        if not custom_from or not custom_to:
            raise HTTPException(status_code=400, detail="custom period requires from/to")
        try:
            df = date.fromisoformat(custom_from)
            dt = date.fromisoformat(custom_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")
        if df > dt:
            raise HTTPException(status_code=400, detail="from must be <= to")
        if (dt - df).days > 366:
            raise HTTPException(status_code=400, detail="Range too large (max 366 days)")
        return df.isoformat(), dt.isoformat()
    if period == "today":
        return today.isoformat(), today.isoformat()
    elif period == "yesterday":
        y = today - timedelta(days=1)
        return y.isoformat(), y.isoformat()
    elif period == "day_before_yesterday":
        y = today - timedelta(days=2)
        return y.isoformat(), y.isoformat()
    elif period == "week":
        start = today - timedelta(days=6)
        return start.isoformat(), today.isoformat()
    elif period == "month":
        start = today.replace(day=1)
        return start.isoformat(), today.isoformat()
    else:
        return today.isoformat(), today.isoformat()


def format_money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ") + " ₸"


# ============ DEMO DATA ============
DEMO_RESTAURANT = {
    "id": 1,
    "organization_id": "demo-org-1",
    "organization_name": "Демо Ресторан",
    "api_login": "demo"
}

DEMO_DASHBOARD = {
    "revenue_today": 944617,
    "revenue_change": 21.4,
    "avg_check": 14759,
    "avg_check_change": 21.4,
    "guests": 85,
    "guests_change": 11.8,
    "open_orders": 8,
    "revenue_yesterday": 0,
    "forecast": 1322464,
    "chart_7days": {
        "labels": ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"],
        "data": [750000, 690000, 330000, 330000, 330000, 778267, 950000]
    }
}

DEMO_SALES = {
    "channels": [
        {"name": "Зал", "revenue": 18720000, "guests": 2340, "avg_check": 8000, "top": True},
        {"name": "Доставка", "revenue": 4180000, "guests": 385, "avg_check": 10857, "top": True},
        {"name": "Самовывоз", "revenue": 2950000, "guests": 410, "avg_check": 7195, "top": True},
        {"name": "Банкеты", "revenue": 1680000, "guests": 125, "avg_check": 13440, "top": False},
        {"name": "Кейтеринг", "revenue": 720000, "guests": 42, "avg_check": 17143, "top": False},
        {"name": "Стафф", "revenue": 400000, "guests": 180, "avg_check": 2222, "top": False},
    ],
    "top_dishes": [
        {"name": "Стейк Рибай", "revenue": 2100000, "count": 420},
        {"name": "Паста с морепродуктами", "revenue": 1800000, "count": 360},
        {"name": "Пицца 4 сыра", "revenue": 2100000, "count": 525},
        {"name": "Лосось гриль", "revenue": 2600000, "count": 400},
        {"name": "Стейк Мачете", "revenue": 3100000, "count": 310},
        {"name": "Тёплый салат с говядиной", "revenue": 1900000, "count": 380},
        {"name": "Вино Prosecco", "revenue": 1200000, "count": 480},
        {"name": "Coca-Cola 0.25", "revenue": 950000, "count": 1900},
        {"name": "Свежевыжатый апельсиновый", "revenue": 1100000, "count": 550},
        {"name": "Доп. пармезан", "revenue": 85000, "count": 340},
    ],
    "categories": [
        {"name": "Основные блюда", "value": 35, "color": "#4A90E2"},
        {"name": "Паста", "value": 15, "color": "#34C759"},
        {"name": "Пицца", "value": 12, "color": "#FF9500"},
        {"name": "Салаты", "value": 10, "color": "#AF52DE"},
        {"name": "Напитки", "value": 8, "color": "#FF2D55"},
        {"name": "Вино", "value": 7, "color": "#5AC8FA"},
        {"name": "Десерты", "value": 5, "color": "#FFD60A"},
        {"name": "Соусы/допы", "value": 8, "color": "#FF3B30"},
    ]
}

DEMO_STAFF = {
    "total_revenue": 18850000,
    "orders": 897,
    "guests": 1656,
    "staff": [
        {"name": "Виктория Ким", "revenue": 3850000, "orders": 172, "guests": 318},
        {"name": "Артём Волков", "revenue": 3420000, "orders": 158, "guests": 285},
        {"name": "Камила Ахметова", "revenue": 2780000, "orders": 135, "guests": 248},
        {"name": "Данияр Оспанов", "revenue": 2350000, "orders": 112, "guests": 208},
        {"name": "Алина Морозова", "revenue": 2010000, "orders": 98, "guests": 182},
        {"name": "Тимур Касымов", "revenue": 1740000, "orders": 86, "guests": 162},
    ]
}

DEMO_FOODCOST = {
    "norm_pct": 30,
    "fact_pct": 36,
    "diff_pct": 6,
    "norm_sum": 14272282,
    "fact_sum": 17126739,
    "warning": "Себестоимость не заполнена у 2 из 30 блюд",
    "trend": [
        {"month": "Фев", "fact": 32, "norm": 30},
        {"month": "Мар", "fact": 34, "norm": 30},
        {"month": "Апр", "fact": 35, "norm": 30},
        {"month": "Май", "fact": 36, "norm": 30},
    ],
    "dishes": [
        {"name": "Доп. пармезан", "category": "Доп. прочее", "revenue": 85000, "count": 340, "cost_pct": 72.0},
        {"name": "Доп. соус цезарь", "category": "Доп. соусы", "revenue": 120000, "count": 600, "cost_pct": 70.0},
        {"name": "Стейк рибай", "category": "Основные блюда", "revenue": 4200000, "count": 420, "cost_pct": 52.0},
        {"name": "Лосось гриль", "category": "Основные блюда", "revenue": 2600000, "count": 400, "cost_pct": 39.4},
        {"name": "Стейк мачете с соусом", "category": "Осн. блюда", "revenue": 3100000, "count": 310, "cost_pct": 34.0},
        {"name": "Свежевыжатый апельсиновый", "category": "Напитки", "revenue": 1100000, "count": 550,
         "cost_pct": 34.0},
        {"name": "Тёплый салат из говядины", "category": "Салаты", "revenue": 1900000, "count": 380, "cost_pct": 30.0},
        {"name": "Coca-Cola 0.25", "category": "Напитки", "revenue": 950000, "count": 1900, "cost_pct": 30.0},
        {"name": "Паста с морепродуктами", "category": "Паста", "revenue": 1800000, "count": 360, "cost_pct": 29.0},
        {"name": "Вино Prosecco (бокал)", "category": "Вино", "revenue": 1200000, "count": 480, "cost_pct": 24.8},
        {"name": "Пицца 4 сыра", "category": "Пицца", "revenue": 2100000, "count": 525, "cost_pct": 23.8},
    ]
}

DEMO_EXPENSES = {
    "total": 674420,
    "operations": [
        {"name": "Маркетинг", "cat": "маркетинг", "date": "25.03.2026", "kassa": "Основная касса", "amount": 20000},
        {"name": "Услуги специалистов", "cat": "Заплатили охраннику", "date": "23.03.2026",
         "kassa": "Касса руководства", "amount": 70000},
        {"name": "Услуги специалистов", "cat": "Зп официантам", "date": "20.03.2026", "kassa": "Касса руководства",
         "amount": 200000},
    ],
    "categories": [
        {"name": "Услуги специалистов", "amount": 270000},
        {"name": "Хозяйственные расходы", "amount": 150000},
        {"name": "Маркетинг", "amount": 20000},
        {"name": "Аренда", "amount": 234420},
    ]
}

DEMO_INVOICES = [
    {"id": "0013", "status": "Проведена", "supplier": "ТОО АгроПром", "date": "08.03.2026", "items": 3,
     "amount": 279850},
    {"id": "0014", "status": "Проведена", "supplier": "ТОО МясоОпт", "date": "09.03.2026", "items": 2,
     "amount": 185000},
    {"id": "0015", "status": "Проведена", "supplier": "ИП Фермер", "date": "10.03.2026", "items": 2, "amount": 92500},
    {"id": "0016", "status": "Новая", "supplier": "ТОО АгроПром", "date": "12.03.2026", "items": 1, "amount": 312400},
]

DEMO_WRITEOFFS = {
    "total_written": 245800,
    "purchases": 1500000,
    "loss_pct": 16.4,
    "categories": [
        {"name": "Мясо и птица", "written": 85000, "purchases": 450000, "pct": 18.9, "alert": True},
        {"name": "Овощи и зелень", "written": 52000, "purchases": 180000, "pct": 28.9, "alert": True},
        {"name": "Молочные продукты", "written": 38000, "purchases": 120000, "pct": 31.7, "alert": True},
        {"name": "Хозтовары", "written": 15000, "purchases": 45000, "pct": 33.7, "alert": True},
        {"name": "Бакалея", "written": 12000, "purchases": 187500, "pct": 6.4, "alert": False},
        {"name": "Напитки", "written": 18000, "purchases": 295000, "pct": 6.1, "alert": False},
        {"name": "Рыба и морепродукты", "written": 25800, "purchases": 537500, "pct": 4.8, "alert": False},
    ]
}

DEMO_STOPLIST = {
    "items": [
        {"name": "Стейк Рибай", "sku": "ST-001", "balance": 0, "category": "Основные блюда", "status": "stop"},
        {"name": "Лосось гриль", "sku": "LS-007", "balance": 0, "category": "Рыба", "status": "stop"},
        {"name": "Паста карбонара", "sku": "PS-003", "balance": 1, "category": "Паста", "status": "low"},
    ],
    "total": 3,
    "updated_at": "14:30"
}

DEMO_RETENTION = {
    "clients": 1847,
    "orders": 5231,
    "cohorts": [
        {"name": "Янв", "size": 620, "jan": 16, "feb": 7, "mar": 5},
        {"name": "Фев", "size": 580, "jan": None, "feb": 17, "mar": 7},
        {"name": "Мар", "size": 647, "jan": None, "feb": None, "mar": 15},
    ],
    "frequency": [1120, 412, 185, 78, 52]
}

MONTH_NAMES_RU = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]


def _fmt_date(dt_str: str) -> str:
    """'2024-01-15T...' → '15.01.2024'"""
    d = (dt_str or "")[:10]
    if len(d) == 10 and "-" in d:
        return f"{d[8:10]}.{d[5:7]}.{d[0:4]}"
    return d


async def _foodcost_month(client, org_id: str, date_from: str, date_to: str):
    result = await client.olap_report(
        org_id, date_from, date_to,
        ["DishName", "ProductCategory.Name"],
        ["DishAmountSum", "DishCostSumInt", "DishCount"]
    )
    dishes, total_rev, total_cost = [], 0.0, 0.0
    for row in result.get("data", []):
        name = row.get("DishName", "")
        if not name:
            continue
        rev = float(row.get("DishAmountSum", 0) or 0)
        cost = float(row.get("DishCostSumInt", 0) or 0)
        count = int(row.get("DishCount", 0) or 0)
        cat = row.get("ProductCategory.Name") or row.get("ProductCategoryName", "")
        total_rev += rev
        total_cost += cost
        dishes.append({
            "name": name, "category": cat, "revenue": rev, "count": count,
            "cost_pct": round(cost / rev * 100, 1) if rev else 0.0
        })
    return dishes, total_rev, total_cost


# ============ MODELS ============
class SetupValidate(BaseModel):
    api_login: str
    iiko_server: Optional[str] = None
    api_password: Optional[str] = None


class SetupSave(BaseModel):
    api_login: str
    organization_id: str
    organization_name: str
    iiko_server: Optional[str] = None
    api_password: Optional[str] = None


class AIAnalyze(BaseModel):
    question: str
    context: Dict[str, Any]


class ExpenseCreate(BaseModel):
    name: str
    category: str
    amount: float
    kassa: str
    date: str


class ExportSendPayload(BaseModel):
    filename: str = Field(..., max_length=200)
    content: str = Field(..., max_length=5_000_000)
    caption: Optional[str] = None


# ============ ENDPOINTS ============
@app.on_event("startup")
async def startup():
    init_db()


@app.get("/")
async def root():
    return FileResponse("index.html")


@app.post("/api/setup/validate")
@limiter.limit("5/15 minutes")
async def setup_validate(request: Request, payload: SetupValidate, user: Dict = Depends(get_current_user)):
    if payload.api_login == "demo" or payload.api_login == DEMO_API_LOGIN:
        return {"valid": True, "organizations": [{"id": "demo-org-1", "name": "Демо Ресторан"}]}
    try:
        client = get_client(payload.api_login, payload.iiko_server, payload.api_password)
        orgs = await client.get_organizations()
        return {
            "valid": True,
            "organizations": [{"id": o["id"], "name": o["name"]} for o in orgs]
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


@app.post("/api/setup/save")
async def setup_save(payload: SetupSave, user: Dict = Depends(get_current_user)):
    tid = user.get("id", 0)
    create_user(tid, user.get("username"), user.get("first_name"))
    add_restaurant(tid, payload.api_login, payload.organization_id, payload.organization_name,
                   payload.iiko_server, payload.api_password)
    set_demo_mode(tid, 0)
    return {"success": True}


@app.get("/api/restaurants")
async def list_restaurants(user: Dict = Depends(get_current_user)):
    tid = user.get("id", 0)
    create_user(tid, user.get("username"), user.get("first_name"))
    rests = get_restaurants(tid)
    if not rests:
        # Не меняем is_demo флаг автоматически — только явный /api/demo его ставит
        return [DEMO_RESTAURANT]
    # Если есть реальные рестораны — сбрасываем demo флаг на всякий случай
    set_demo_mode(tid, 0)
    return rests


@app.delete("/api/restaurants/{rest_id}")
async def remove_restaurant(rest_id: int, user: Dict = Depends(get_current_user)):
    delete_restaurant(rest_id, user.get("id", 0))
    return {"success": True}


@app.post("/api/demo")
async def enable_demo(user: Dict = Depends(get_current_user)):
    tid = user.get("id", 0)
    create_user(tid, user.get("username"), user.get("first_name"))
    set_demo_mode(tid, 1)
    return {"success": True}


@app.post("/api/logout")
async def logout(user: Dict = Depends(get_current_user)):
    """Полный логаут: удаляем все рестораны юзера + сбрасываем демо-флаг."""
    tid = user.get("id", 0)
    create_user(tid, user.get("username"), user.get("first_name"))
    n = delete_all_restaurants(tid)
    set_demo_mode(tid, 0)
    return {"success": True, "deleted": n}


def _is_demo_user(user: Dict) -> bool:
    tid = user.get("id", 0)
    u = get_user(tid)
    if u is None or u.get("is_demo", 0) == 0:
        return False
    # Флаг is_demo=1, но если есть реальные рестораны — не демо
    rests = get_restaurants(tid)
    if rests:
        set_demo_mode(tid, 0)  # сбрасываем зависший флаг
        return False
    return True


def _get_org_id(org_id: str, user: Dict) -> str:
    if org_id == "demo-org-1" or _is_demo_user(user):
        return "demo"
    rests = get_restaurants(user.get("id", 0))
    for r in rests:
        if r["organization_id"] == org_id:
            return r["organization_id"]
    raise HTTPException(status_code=404, detail="Restaurant not found")


def _get_restaurant_info(org_id: str, user: Dict) -> Dict[str, Any]:
    """Возвращает api_login, iiko_server, api_password, org_name для ресторана."""
    if org_id == "demo" or _is_demo_user(user):
        return {"api_login": "demo", "iiko_server": None, "api_password": None, "org_name": ""}
    rests = get_restaurants(user.get("id", 0))
    for r in rests:
        if r["organization_id"] == org_id:
            return {
                "api_login": r["api_login"],
                "iiko_server": r.get("iiko_server"),
                "api_password": r.get("api_password"),
                "org_name": r.get("organization_name", ""),
            }
    return {"api_login": "demo", "iiko_server": None, "api_password": None, "org_name": ""}


def _olap_dept(real_org: str, info: Dict) -> str:
    """iikoWeb OLAP Department фильтр принимает название, облако — UUID."""
    if info.get("iiko_server") and info.get("org_name"):
        return info["org_name"]
    return real_org


def _parse_org_ids(org_ids_csv: Optional[str], path_org_id: str,
                   user: Dict) -> List[str]:
    """Список валидных org_id. Если org_ids_csv пуст — fallback на path_org_id."""
    if not org_ids_csv:
        return [_get_org_id(path_org_id, user)]
    ids = [x.strip() for x in org_ids_csv.split(",") if x.strip()]
    if not ids:
        return [_get_org_id(path_org_id, user)]
    valid = []
    for oid in ids:
        try:
            valid.append(_get_org_id(oid, user))
        except HTTPException:
            continue
    if not valid:
        raise HTTPException(status_code=404, detail="No accessible restaurants")
    return valid


def _cache_period_part(period: str, custom_from: Optional[str], custom_to: Optional[str]) -> str:
    if period == "custom":
        return f"custom:{custom_from}:{custom_to}"
    return period


def _get_api_login(org_id: str, user: Dict) -> str:
    return _get_restaurant_info(org_id, user)["api_login"]


@app.get("/api/dashboard/{org_id}")
async def dashboard(org_id: str, period: str = "today",
                    from_: Optional[str] = Query(None, alias="from"),
                    to: Optional[str] = Query(None),
                    org_ids: Optional[str] = Query(None),
                    user: Dict = Depends(get_current_user)):
    if _is_demo_user(user) or org_id == "demo-org-1":
        return DEMO_DASHBOARD

    orgs = _parse_org_ids(org_ids, org_id, user)
    date_from, date_to = get_period_dates(period, from_, to)
    branches_key = ",".join(sorted(orgs))
    cache_period_key = _cache_period_part(period, from_, to) + ":" + branches_key
    key = _cache_key(user.get("id", 0), "dashboard", branches_key, cache_period_key)
    cached = _get_cached(key)
    if cached:
        return cached

    async def fetch_one(real_org: str):
        info = _get_restaurant_info(real_org, user)
        client = get_client(info["api_login"], info.get("iiko_server"), info.get("api_password"))
        try:
            r = await client.olap_report(
                _olap_dept(real_org, info), date_from, date_to,
                ["OpenDate.Typed"], ["GuestNum", "DishAmountSum", "OrdersCount"]
            )
            return r.get("data", [])
        except Exception as e:
            logger.warning(f"[dashboard] {real_org}: {e}")
            return []

    try:
        results = await asyncio.gather(*(fetch_one(o) for o in orgs))
        all_rows = [row for batch in results for row in batch]
        total = sum(r.get("DishAmountSum", 0) for r in all_rows)
        guests = sum(r.get("GuestNum", 0) for r in all_rows)
        orders = sum(r.get("OrdersCount", 0) for r in all_rows)
        avg_check = total / guests if guests else 0

        resp = {
            "revenue_today": total,
            "revenue_change": 0,
            "avg_check": avg_check,
            "avg_check_change": 0,
            "guests": guests,
            "guests_change": 0,
            "open_orders": orders,
            "revenue_yesterday": 0,
            "forecast": total * 1.4,
            "chart_7days": DEMO_DASHBOARD["chart_7days"],
            "branches_count": len(orgs),
        }
        _set_cached(key, resp)
        return resp
    except Exception as e:
        print(f"[dashboard] {e}")
        return dict(DEMO_DASHBOARD)


@app.get("/api/sales/{org_id}")
async def sales(org_id: str, period: str = "today",
                from_: Optional[str] = Query(None, alias="from"),
                to: Optional[str] = Query(None),
                org_ids: Optional[str] = Query(None),
                user: Dict = Depends(get_current_user)):
    if _is_demo_user(user) or org_id == "demo-org-1":
        return DEMO_SALES

    orgs = _parse_org_ids(org_ids, org_id, user)
    date_from, date_to = get_period_dates(period, from_, to)
    branches_key = ",".join(sorted(orgs))
    cache_period_key = _cache_period_part(period, from_, to) + ":" + branches_key
    key = _cache_key(user.get("id", 0), "sales", branches_key, cache_period_key)
    cached = _get_cached(key)
    if cached:
        return cached

    async def fetch_one(real_org: str):
        info = _get_restaurant_info(real_org, user)
        client = get_client(info["api_login"], info.get("iiko_server"), info.get("api_password"))
        async def safe_olap(*args, **kwargs):
            try:
                return await client.olap_report(*args, **kwargs)
            except Exception as e:
                logger.warning(f"[sales] iiko olap failed for org={real_org}: {e} | group_by={args[3] if len(args) > 3 else kwargs.get('group_by')}")
                return {"data": []}
        dept = _olap_dept(real_org, info)
        return await asyncio.gather(
            safe_olap(dept, date_from, date_to, ["OrderType.Name"], ["DishAmountSum", "GuestNum"]),
            safe_olap(dept, date_from, date_to, ["DishName"], ["DishAmountSum", "DishCount"]),
            safe_olap(dept, date_from, date_to, ["ProductCategory.Name"], ["DishAmountSum"]),
        )

    try:
        per_org = await asyncio.gather(*(fetch_one(o) for o in orgs))
        channels_rows = [r for t in per_org for r in t[0].get("data", [])]
        dishes_rows   = [r for t in per_org for r in t[1].get("data", [])]
        cats_rows     = [r for t in per_org for r in t[2].get("data", [])]

        # Дедупликация по имени для каналов (несколько филиалов могут вернуть один и тот же канал)
        ch_agg: Dict[str, Dict[str, float]] = {}
        for row in channels_rows:
            name = row.get("OrderType.Name") or row.get("OrderTypeName", "")
            if not name:
                continue
            if name not in ch_agg:
                ch_agg[name] = {"revenue": 0.0, "guests": 0}
            ch_agg[name]["revenue"] += float(row.get("DishAmountSum", 0) or 0)
            ch_agg[name]["guests"]  += int(row.get("GuestNum", 0) or 0)
        channels = [{
            "name": n, "revenue": v["revenue"], "guests": int(v["guests"]),
            "avg_check": v["revenue"] / v["guests"] if v["guests"] else 0, "top": True
        } for n, v in ch_agg.items()]
        channels.sort(key=lambda x: x["revenue"], reverse=True)

        # Дедупликация по названию блюда
        di_agg: Dict[str, Dict[str, float]] = {}
        for row in dishes_rows:
            name = row.get("DishName", "")
            if not name:
                continue
            if name not in di_agg:
                di_agg[name] = {"revenue": 0.0, "count": 0}
            di_agg[name]["revenue"] += float(row.get("DishAmountSum", 0) or 0)
            di_agg[name]["count"]   += int(row.get("DishCount", 0) or 0)
        dishes = [{"name": n, "revenue": v["revenue"], "count": int(v["count"])} for n, v in di_agg.items()]
        dishes.sort(key=lambda x: x["revenue"], reverse=True)

        # Дедупликация по категории
        cat_agg: Dict[str, float] = {}
        for row in cats_rows:
            name = row.get("ProductCategory.Name") or row.get("ProductCategoryName", "")
            if not name:
                continue
            cat_agg[name] = cat_agg.get(name, 0.0) + float(row.get("DishAmountSum", 0) or 0)
        COLORS = ["#4A90E2", "#34C759", "#FF9500", "#AF52DE", "#FF2D55", "#5AC8FA", "#FFD60A", "#FF3B30"]
        cats_sorted = sorted(cat_agg.items(), key=lambda kv: kv[1], reverse=True)
        total_rev = sum(v for _, v in cats_sorted)
        categories = [{
            "name": name,
            "value": round(amount / total_rev * 100, 1) if total_rev else 0,
            "color": COLORS[i % len(COLORS)]
        } for i, (name, amount) in enumerate(cats_sorted)]

        result = {"channels": channels, "top_dishes": dishes[:10], "categories": categories,
                  "branches_count": len(orgs)}
        _set_cached(key, result)
        return result
    except Exception as e:
        print(f"[sales] {e}")
        return dict(DEMO_SALES)


@app.get("/api/shifts/{org_id}")
async def shifts(org_id: str, user: Dict = Depends(get_current_user)):
    """Сотрудники на смене сегодня с временем начала."""
    if _is_demo_user(user) or org_id == "demo-org-1":
        return {"staff": [
            {"name": "Виктория Ким", "since": "10:00", "revenue": 1250000, "orders": 48},
            {"name": "Артём Волков",  "since": "10:00", "revenue": 980000,  "orders": 38},
            {"name": "Камила Ахметова", "since": "14:00", "revenue": 620000, "orders": 24},
        ]}
    real_org = _get_org_id(org_id, user)
    info = _get_restaurant_info(real_org, user)
    today = datetime.now().date()
    tomorrow = (today + timedelta(days=1)).isoformat()
    client = get_client(info["api_login"], info.get("iiko_server"), info.get("api_password"))
    try:
        result = await client.olap_report(
            _olap_dept(real_org, info),
            today.isoformat(), today.isoformat(),
            group_by=["WaiterName", "HourOpen"],
            aggregates=["DishAmountSum", "OrdersCount"]
        )
        rows = result.get("data", [])
        waiters: Dict[str, Any] = {}
        for row in rows:
            name = row.get("WaiterName", "")
            if not name:
                continue
            h_raw = row.get("HourOpen", 99)
            try:
                h_int = int(str(h_raw).split(":")[0])
            except Exception:
                h_int = 99
            rev = float(row.get("DishAmountSum", 0) or 0)
            orders = int(row.get("OrdersCount", 0) or 0)
            if name not in waiters:
                waiters[name] = {"min_hour": h_int, "revenue": 0.0, "orders": 0}
            if h_int < waiters[name]["min_hour"]:
                waiters[name]["min_hour"] = h_int
            waiters[name]["revenue"] += rev
            waiters[name]["orders"] += orders

        staff_list = sorted(
            [{"name": n, "since": f"{d['min_hour']:02d}:00",
              "revenue": round(d["revenue"]), "orders": d["orders"]}
             for n, d in waiters.items() if d["revenue"] > 0],
            key=lambda x: x["since"]
        )
        return {"staff": staff_list}
    except Exception as e:
        logger.warning(f"[shifts] {e}")
        return {"staff": []}


@app.get("/api/staff/{org_id}")
async def staff(org_id: str, period: str = "week", user: Dict = Depends(get_current_user)):
    if _is_demo_user(user) or org_id == "demo-org-1":
        return DEMO_STAFF

    real_org = _get_org_id(org_id, user)
    info = _get_restaurant_info(real_org, user)
    login = info["api_login"]
    key = _cache_key(user.get("id", 0), "staff", real_org, period)
    cached = _get_cached(key)
    if cached:
        return cached

    date_from, date_to = get_period_dates(period)
    client = get_client(login, info.get("iiko_server"), info.get("api_password"))
    try:
        result = await client.olap_report(
            _olap_dept(real_org, info), date_from, date_to,
            ["WaiterName"],
            ["DishAmountSum", "GuestNum", "OrdersCount"]
        )
        staff_list = []
        total_rev = total_orders = total_guests = 0
        for row in result.get("data", []):
            name = row.get("WaiterName", "")
            if not name:
                continue
            revenue = float(row.get("DishAmountSum", 0) or 0)
            orders = int(row.get("OrdersCount", 0) or 0)
            guests = int(row.get("GuestNum", 0) or 0)
            staff_list.append({"name": name, "revenue": revenue, "orders": orders, "guests": guests})
            total_rev += revenue
            total_orders += orders
            total_guests += guests
        staff_list.sort(key=lambda x: x["revenue"], reverse=True)
        resp = {"total_revenue": total_rev, "orders": total_orders, "guests": total_guests, "staff": staff_list}
        _set_cached(key, resp)
        return resp
    except Exception as e:
        print(f"[staff] {e}")
        demo = dict(DEMO_STAFF)
        return demo


@app.get("/api/foodcost/{org_id}")
async def foodcost(org_id: str, period: str = "month", user: Dict = Depends(get_current_user)):
    if _is_demo_user(user) or org_id == "demo-org-1":
        return DEMO_FOODCOST

    real_org = _get_org_id(org_id, user)
    info = _get_restaurant_info(real_org, user)
    login = info["api_login"]
    key = _cache_key(user.get("id", 0), "foodcost", real_org, period)
    cached = _get_cached(key)
    if cached:
        return cached

    date_from, date_to = get_period_dates(period)
    client = get_client(login, info.get("iiko_server"), info.get("api_password"))
    try:
        today = datetime.now().date()
        trend_periods = []
        for i in range(3, -1, -1):
            m, y = today.month - i, today.year
            while m <= 0:
                m += 12
                y -= 1
            first = datetime(y, m, 1).date()
            last = (datetime(y, m + 1, 1).date() if m < 12 else datetime(y + 1, 1, 1).date()) - timedelta(days=1)
            trend_periods.append((MONTH_NAMES_RU[m - 1], first.isoformat(), min(last, today).isoformat()))

        tasks = [_foodcost_month(client, _olap_dept(real_org, info), date_from, date_to)]
        for _, mf, mt in trend_periods:
            tasks.append(_foodcost_month(client, _olap_dept(real_org, info), mf, mt))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        if isinstance(results[0], Exception):
            raise results[0]
        dishes, total_rev, total_cost = results[0]

        NORM_PCT = 30
        fact_pct = round(total_cost / total_rev * 100, 1) if total_rev else 0.0
        dishes.sort(key=lambda x: x["cost_pct"], reverse=True)

        trend = []
        for idx, (month_name, _, _) in enumerate(trend_periods):
            r = results[idx + 1]
            if isinstance(r, Exception):
                m_fact = 0.0
            else:
                _, m_rev, m_cost = r
                m_fact = round(m_cost / m_rev * 100, 1) if m_rev else 0.0
            trend.append({"month": month_name, "fact": m_fact, "norm": NORM_PCT})

        resp = {
            "norm_pct": NORM_PCT,
            "fact_pct": fact_pct,
            "diff_pct": round(fact_pct - NORM_PCT, 1),
            "norm_sum": round(total_rev * NORM_PCT / 100),
            "fact_sum": round(total_cost),
            "warning": None,
            "trend": trend,
            "dishes": dishes[:20]
        }
        _set_cached(key, resp)
        return resp
    except Exception as e:
        print(f"[foodcost] {e}")
        demo = dict(DEMO_FOODCOST)
        return demo


@app.get("/api/expenses/{org_id}")
async def expenses(org_id: str, period: str = "week", user: Dict = Depends(get_current_user)):
    if _is_demo_user(user) or org_id == "demo-org-1":
        return DEMO_EXPENSES

    real_org = _get_org_id(org_id, user)
    info = _get_restaurant_info(real_org, user)
    login = info["api_login"]
    date_from, date_to = get_period_dates(period)
    client = get_client(login, info.get("iiko_server"), info.get("api_password"))
    operations = []

    try:
        iiko_data = await client.get_expense_acts([_olap_dept(real_org, info)], date_from, date_to)
        docs = iiko_data.get("expenses") or iiko_data.get("expenseDocuments") or []
        for doc in docs:
            doc_date = _fmt_date(doc.get("dateIncoming", ""))
            kassa = (doc.get("paymentType", {}) or {}).get("name", "")
            items = doc.get("items") or []
            if items:
                for item in items:
                    cat = (item.get("category", {}) or {}).get("name", "")
                    comment = item.get("comment", "") or ""
                    amount = float(item.get("sum", 0) or 0)
                    if amount <= 0:
                        continue
                    operations.append({
                        "id": doc.get("id", ""), "name": comment or cat or "Расход",
                        "cat": cat, "date": doc_date, "kassa": kassa,
                        "amount": amount, "type": "iiko"
                    })
            else:
                amount = float(doc.get("sum", 0) or 0)
                if amount > 0:
                    name = doc.get("comment", "") or doc.get("documentNumber", "Расход")
                    operations.append({
                        "id": doc.get("id", ""), "name": name,
                        "cat": "", "date": doc_date, "kassa": kassa,
                        "amount": amount, "type": "iiko"
                    })
    except Exception as e:
        print(f"[expenses/iiko] {e}")

    try:
        for m in get_manual_expenses(real_org, date_from, date_to):
            operations.append({
                "id": str(m["id"]), "name": m["name"], "cat": m["category"],
                "date": m["date"], "kassa": m.get("kassa", ""),
                "amount": float(m["amount"]), "type": "manual"
            })
    except Exception as e:
        print(f"[expenses/manual] {e}")

    cat_totals: Dict[str, float] = {}
    for op in operations:
        cat = op["cat"] or "Прочее"
        cat_totals[cat] = cat_totals.get(cat, 0.0) + op["amount"]

    operations.sort(key=lambda x: x["date"], reverse=True)
    categories = [{"name": c, "amount": round(a)} for c, a in sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)]
    return {"total": round(sum(op["amount"] for op in operations)), "operations": operations, "categories": categories}


@app.get("/api/invoices/{org_id}")
async def invoices(org_id: str, period: str = "week", user: Dict = Depends(get_current_user)):
    if _is_demo_user(user) or org_id == "demo-org-1":
        return {"invoices": DEMO_INVOICES}

    real_org = _get_org_id(org_id, user)
    info = _get_restaurant_info(real_org, user)
    login = info["api_login"]
    key = _cache_key(user.get("id", 0), "invoices", real_org, period)
    cached = _get_cached(key)
    if cached:
        return cached

    date_from, date_to = get_period_dates(period)
    client = get_client(login, info.get("iiko_server"), info.get("api_password"))
    try:
        data = await client.get_invoices([_olap_dept(real_org, info)], date_from, date_to)
        STATUS_MAP = {
            "New": "Новая", "Processed": "Проведена", "Deleted": "Удалена",
            "InProgress": "В работе", "Accepted": "Проведена",
        }
        result_list = []
        for inv in data.get("invoiceIncomings", []):
            supplier = inv.get("supplier", {}) or {}
            items = inv.get("items", []) or []
            result_list.append({
                "id": (inv.get("documentNumber", "") or (inv.get("id", "") or "")[:8])[:8],
                "status": STATUS_MAP.get(inv.get("status", ""), inv.get("status", "")),
                "supplier": supplier.get("name", "—"),
                "date": _fmt_date(inv.get("dateIncoming", "")),
                "items": len(items),
                "amount": float(inv.get("sum", 0) or 0)
            })
        # Добавляем накладные из Telegram бота
        BOT_STATUS_MAP = {
            "draft": "Черновик",
            "draft_in_iiko": "Создан в iiko",
            "posted": "Проведена",
            "needs_mapping": "Нужно сопоставление",
            "iiko_error": "Ошибка iiko",
            "pending": "В обработке",
        }
        bot_invs = get_bot_invoices(limit=200, organization_id=real_org)
        for b in bot_invs:
            raw_status = b.get("status") or "draft"
            if raw_status == "pending":
                continue  # ещё в работе бота
            result_list.append({
                "id": f"BOT-{b['id']}",
                "bot_id": b["id"],
                "status": BOT_STATUS_MAP.get(raw_status, raw_status),
                "raw_status": raw_status,
                "supplier": b.get("supplier") or "—",
                "date": (b.get("date") or "")[:10] or (b.get("created_at") or "")[:10],
                "items": len(json.loads(b.get("items") or "[]")),
                "amount": float(b.get("total_amount") or 0),
                "vat_amount": float(b.get("vat_amount") or 0),
                "iiko_doc_id": b.get("iiko_doc_id") or "",
                "iiko_doc_number": b.get("iiko_doc_number") or "",
                "source": "bot",
                "branch": b.get("branch") or "",
                "by": b.get("telegram_user") or "",
            })

        result_list.sort(key=lambda x: x["date"], reverse=True)
        result = {"invoices": result_list}
        _set_cached(key, result)
        return result
    except Exception as e:
        print(f"[invoices] {e}")
        return {"invoices": DEMO_INVOICES}


# ============ PRICE STATS (Mini App «📊 Цены») ============
# Cache of iiko invoice exports per (org_id, days) → (timestamp, raw_payload).
# TTL 1 hour. Avoids hitting iiko on every nomenclature pick.
_price_stats_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_PRICE_STATS_TTL_SECONDS = 3600


@app.get("/api/price-stats/{org_id}")
async def price_stats(org_id: str, product_id: str = Query(..., min_length=1),
                       days: int = Query(60, ge=1, le=365),
                       user: Dict = Depends(get_current_user)):
    """Агрегат цен товара по поставщикам за `days` дней.
    Источник: iiko export invoice_incoming + локальные bot_invoices.
    """
    import time
    if _is_demo_user(user) or org_id == "demo-org-1":
        return {"product": {"id": product_id, "name": "—", "unit": ""},
                "best": None, "suppliers": [], "stats": {"purchases": 0, "days": days}}

    real_org = _get_org_id(org_id, user)
    info = _get_restaurant_info(real_org, user)
    client = get_client(info["api_login"], info.get("iiko_server"), info.get("api_password"))

    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    cache_key = f"{real_org}|{days}"
    now_ts = time.time()
    cached = _price_stats_cache.get(cache_key)
    iiko_ok = True
    if cached and (now_ts - cached[0]) < _PRICE_STATS_TTL_SECONDS:
        rows = cached[1]
    else:
        try:
            rows = await client.get_invoice_items_olap([_olap_dept(real_org, info)], date_from, date_to)
            _price_stats_cache[cache_key] = (now_ts, rows)
        except Exception as e:
            logger.warning(f"[price_stats] iiko fetch failed: {e}")
            rows = []
            iiko_ok = False

    product_name = "—"
    product_unit = ""

    by_supplier: Dict[str, Dict[str, Any]] = {}
    purchases_count = 0
    for r in rows:
        if r.get("product_id") != product_id:
            continue
        price = float(r.get("price_per_unit") or 0)
        if price <= 0:
            continue
        supplier_id = r.get("supplier_id") or r.get("supplier_name") or "—"
        supplier_name = r.get("supplier_name") or "—"
        unit = r.get("unit") or ""
        purchases_count += 1
        if not product_name or product_name == "—":
            product_name = r.get("product_name") or product_name
            product_unit = unit
        cur = by_supplier.get(supplier_id)
        if cur is None or price < cur["price_per_unit"]:
            by_supplier[supplier_id] = {
                "supplier_id": supplier_id,
                "supplier_name": supplier_name,
                "price_per_unit": price,
                "date": r.get("date") or "",
                "unit": unit,
            }

    try:
        local = get_price_history(user.get("id") or 0, days=days)
    except Exception:
        local = []
    for h in local:
        if h["key"] != product_id:
            continue
        sid = f"local:{h['supplier']}"
        purchases_count += 1
        cur = by_supplier.get(sid)
        if cur is None or h["price_per_unit"] < cur["price_per_unit"]:
            by_supplier[sid] = {
                "supplier_id": sid,
                "supplier_name": h["supplier"],
                "price_per_unit": h["price_per_unit"],
                "date": h["date"],
                "unit": h["unit"] or product_unit,
            }

    suppliers = sorted(by_supplier.values(), key=lambda r: r["price_per_unit"])
    best = suppliers[0] if suppliers else None
    if best:
        for s in suppliers:
            s["delta_pct"] = ((s["price_per_unit"] - best["price_per_unit"]) /
                              best["price_per_unit"] * 100) if best["price_per_unit"] > 0 else 0.0

    return {
        "product": {"id": product_id, "name": product_name, "unit": product_unit},
        "best": best,
        "suppliers": suppliers,
        "stats": {"purchases": purchases_count, "days": days},
        "iiko_ok": iiko_ok,
    }


@app.get("/api/writeoffs/{org_id}")
async def writeoffs(org_id: str, period: str = "week", user: Dict = Depends(get_current_user)):
    if _is_demo_user(user) or org_id == "demo-org-1":
        return DEMO_WRITEOFFS

    real_org = _get_org_id(org_id, user)
    info = _get_restaurant_info(real_org, user)
    login = info["api_login"]
    key = _cache_key(user.get("id", 0), "writeoffs", real_org, period)
    cached = _get_cached(key)
    if cached:
        return cached

    date_from, date_to = get_period_dates(period)
    client = get_client(login, info.get("iiko_server"), info.get("api_password"))
    try:
        data = await client.get_writeoffs([_olap_dept(real_org, info)], date_from, date_to)
        cat_totals: Dict[str, float] = {}
        total_written = 0.0
        for doc in data.get("writeoffs", []):
            for item in doc.get("items", []):
                product = item.get("product", {}) or {}
                cat = (product.get("category", {}) or {}).get("name", "Прочее") or "Прочее"
                amount = float(item.get("sum", 0) or 0)
                cat_totals[cat] = cat_totals.get(cat, 0.0) + amount
                total_written += amount
        categories = []
        for cat_name, written in sorted(cat_totals.items(), key=lambda x: x[1], reverse=True):
            pct = round(written / total_written * 100, 1) if total_written else 0
            categories.append({
                "name": cat_name, "written": round(written),
                "purchases": 0, "pct": pct, "alert": pct > 20
            })
        result = {"total_written": round(total_written), "purchases": 0, "loss_pct": 0, "categories": categories}
        _set_cached(key, result)
        return result
    except Exception as e:
        print(f"[writeoffs] {e}")
        return DEMO_WRITEOFFS


@app.get("/api/cancels/{org_id}")
async def cancels(org_id: str, period: str = "today", user: Dict = Depends(get_current_user)):
    if _is_demo_user(user) or org_id == "demo-org-1":
        return {"items": [], "total_amount": 0, "total_orders": 0}

    real_org = _get_org_id(org_id, user)
    info = _get_restaurant_info(real_org, user)
    date_from, date_to = get_period_dates(period)
    client = get_client(info["api_login"], info.get("iiko_server"), info.get("api_password"))
    try:
        result = await client.olap_report(
            _olap_dept(real_org, info), date_from, date_to,
            group_by=["DishName"],
            aggregates=["DishAmountSum", "OrdersCount"],
            deleted_only=True
        )
        rows = result.get("data", [])
        items = [
            {"name": r.get("DishName", ""), "amount": float(r.get("DishAmountSum", 0) or 0)}
            for r in rows if r.get("DishName") and float(r.get("DishAmountSum", 0) or 0) > 0
        ]
        items.sort(key=lambda x: x["amount"], reverse=True)
        total_amount = sum(i["amount"] for i in items)
        total_orders = int(sum(float(r.get("OrdersCount", 0) or 0) for r in rows))
        return {"items": items[:15], "total_amount": total_amount, "total_orders": total_orders}
    except Exception as e:
        logger.warning(f"[cancels] {e}")
        return {"items": [], "total_amount": 0, "total_orders": 0}


@app.get("/api/companions/{org_id}")
async def companions(org_id: str, period: str = "week", user: Dict = Depends(get_current_user)):
    """Анализ компаньонов — блюда которые покупают вместе."""
    if _is_demo_user(user) or org_id == "demo-org-1":
        return {"pairs": [], "companions": {}}

    real_org = _get_org_id(org_id, user)
    info = _get_restaurant_info(real_org, user)
    date_from, date_to = get_period_dates(period)
    client = get_client(info["api_login"], info.get("iiko_server"), info.get("api_password"))
    try:
        result = await client.olap_report(
            _olap_dept(real_org, info), date_from, date_to,
            group_by=["OpenDate.Typed", "OrderNum", "DishName"],
            aggregates=["DishAmountSum"]
        )
        rows = result.get("data", [])
        # Строим словарь order → [dishes], ключ = дата+номер для уникальности
        order_dishes: Dict[str, List[str]] = {}
        for r in rows:
            date_key = str(r.get("OpenDate.Typed", ""))[:10]
            order = f"{date_key}_{r.get('OrderNum', '')}"
            dish = r.get("DishName", "")
            if not order or not dish:
                continue
            if order not in order_dishes:
                order_dishes[order] = []
            if dish not in order_dishes[order]:
                order_dishes[order].append(dish)

        # Считаем пары
        pair_count: Dict[str, int] = {}
        companion_count: Dict[str, Dict[str, int]] = {}
        for dishes in order_dishes.values():
            if len(dishes) < 2:
                continue
            for i in range(len(dishes)):
                for j in range(i + 1, len(dishes)):
                    a, b = sorted([dishes[i], dishes[j]])
                    key = f"{a}|||{b}"
                    pair_count[key] = pair_count.get(key, 0) + 1
                    # Компаньоны для каждого блюда
                    companion_count.setdefault(dishes[i], {})[dishes[j]] = \
                        companion_count.get(dishes[i], {}).get(dishes[j], 0) + 1
                    companion_count.setdefault(dishes[j], {})[dishes[i]] = \
                        companion_count.get(dishes[j], {}).get(dishes[i], 0) + 1

        # Топ пар
        top_pairs = sorted(pair_count.items(), key=lambda x: x[1], reverse=True)[:10]
        pairs = [{"a": k.split("|||")[0], "b": k.split("|||")[1], "count": v} for k, v in top_pairs]

        # Топ компаньоны для топ-блюд
        top_companions = {}
        for dish, comp in sorted(companion_count.items(), key=lambda x: sum(x[1].values()), reverse=True)[:8]:
            top = sorted(comp.items(), key=lambda x: x[1], reverse=True)[:3]
            top_companions[dish] = [{"name": n, "count": c} for n, c in top]

        return {"pairs": pairs, "companions": top_companions}
    except Exception as e:
        logger.warning(f"[companions] {e}")
        return {"pairs": [], "companions": {}}


@app.get("/api/retention/{org_id}")
async def retention(org_id: str, user: Dict = Depends(get_current_user)):
    if _is_demo_user(user) or org_id == "demo-org-1":
        return DEMO_RETENTION
    return {"clients": 0, "orders": 0, "cohorts": [], "frequency": []}


@app.get("/api/comparison/{org_id}")
async def comparison(org_id: str,
                     org_ids: Optional[str] = Query(None),
                     user: Dict = Depends(get_current_user)):
    """YoY сравнение по неделям и месяцам с разбивкой по каналам."""
    if _is_demo_user(user) or org_id == "demo-org-1":
        return {"weeks": [], "months": [], "channels": []}

    orgs = _parse_org_ids(org_ids, org_id, user)

    from datetime import date as date_cls

    async def fetch_year_for_org(real_org: str, year: int):
        info = _get_restaurant_info(real_org, user)
        client = get_client(info["api_login"], info.get("iiko_server"), info.get("api_password"))
        start = f"{year}-01-01"
        end = f"{year}-12-31"
        try:
            result = await client.olap_report(
                _olap_dept(real_org, info), start, end,
                group_by=["OpenDate.Typed", "OrderType.Name"],
                aggregates=["DishAmountSum", "OrdersCount"]
            )
            return result.get("data", [])
        except Exception as e:
            logger.warning(f"[comparison] {real_org}/{year}: {e}")
            return []

    cur_year = datetime.now().year
    cur_batches, prev_batches = await asyncio.gather(
        asyncio.gather(*(fetch_year_for_org(o, cur_year) for o in orgs)),
        asyncio.gather(*(fetch_year_for_org(o, cur_year - 1) for o in orgs)),
    )
    cur_rows  = [r for batch in cur_batches  for r in batch]
    prev_rows = [r for batch in prev_batches for r in batch]

    def aggregate(rows, by: str):
        result = {}
        for row in rows:
            dt_str = (row.get("OpenDate.Typed") or "")[:10]
            if not dt_str or len(dt_str) < 10:
                continue
            try:
                dt = date_cls.fromisoformat(dt_str)
            except Exception:
                continue
            channel = row.get("OrderType.Name", "Прочее") or "Прочее"
            rev = float(row.get("DishAmountSum", 0) or 0)
            orders = int(row.get("OrdersCount", 0) or 0)

            if by == "week":
                iso = dt.isocalendar()
                key = f"{iso.year}-W{iso.week:02d}"
                label = f"Нед {iso.week}"
            else:
                key = f"{dt.year}-{dt.month:02d}"
                label = ['Янв','Фев','Мар','Апр','Май','Июн','Июл','Авг','Сен','Окт','Ноя','Дек'][dt.month-1]

            if key not in result:
                result[key] = {"key": key, "label": label, "year": dt.year,
                               "total_rev": 0, "total_orders": 0, "channels": {}}
            result[key]["total_rev"] += rev
            result[key]["total_orders"] += orders
            if channel not in result[key]["channels"]:
                result[key]["channels"][channel] = {"rev": 0, "orders": 0}
            result[key]["channels"][channel]["rev"] += rev
            result[key]["channels"][channel]["orders"] += orders
        return sorted(result.values(), key=lambda x: x["key"])

    cur_weeks = aggregate(cur_rows, "week")
    prev_weeks = aggregate(prev_rows, "week")
    cur_months = aggregate(cur_rows, "month")
    prev_months = aggregate(prev_rows, "month")

    # Список всех каналов
    all_channels = set()
    for row in cur_rows + prev_rows:
        ch = row.get("OrderType.Name", "")
        if ch:
            all_channels.add(ch)

    return {
        "weeks":    {"current": cur_weeks,  "previous": prev_weeks},
        "months":   {"current": cur_months, "previous": prev_months},
        "channels": sorted(all_channels),
        "cur_year": cur_year,
        "prev_year": cur_year - 1,
    }


@app.get("/api/olap/{org_id}")
async def olap_raw(org_id: str, period: str = "today",
                   from_: Optional[str] = Query(None, alias="from"),
                   to: Optional[str] = Query(None),
                   org_ids: Optional[str] = Query(None),
                   user: Dict = Depends(get_current_user)):
    """Один большой OLAP-запрос — фронтенд сам фильтрует."""
    if _is_demo_user(user) or org_id == "demo-org-1":
        return {"data": [], "demo": True}

    orgs = _parse_org_ids(org_ids, org_id, user)
    date_from, date_to = get_period_dates(period, from_, to)
    branches_key = ",".join(sorted(orgs))
    cache_period_key = _cache_period_part(period, from_, to) + ":" + branches_key
    key = _cache_key(user.get("id", 0), "olap_raw", branches_key, cache_period_key)
    cached = _get_cached(key)
    if cached:
        return cached

    async def fetch_one(real_org: str):
        info = _get_restaurant_info(real_org, user)
        client = get_client(info["api_login"], info.get("iiko_server"), info.get("api_password"))
        try:
            r = await client.olap_report(
                _olap_dept(real_org, info), date_from, date_to,
                group_by=["OpenDate.Typed", "DishName", "ProductCategory.Name",
                          "WaiterName", "OrderType.Name"],
                aggregates=["DishAmountSum", "GuestNum", "OrdersCount", "DishCount"]
            )
            return r.get("data", [])
        except Exception as e:
            logger.warning(f"[olap_raw] {real_org}: {e}")
            return []

    results = await asyncio.gather(*(fetch_one(o) for o in orgs))
    merged = [row for batch in results for row in batch]
    resp = {"data": merged, "demo": False, "date_from": date_from, "date_to": date_to,
            "branches_count": len(orgs)}
    _set_cached(key, resp)
    return resp


@app.get("/api/stoplist/{org_id}")
async def get_stoplist(org_id: str, user: Dict = Depends(get_current_user)):
    if _is_demo_user(user) or org_id == "demo-org-1":
        demo = dict(DEMO_STOPLIST)
        demo["updated_at"] = datetime.now().strftime("%H:%M")
        return demo

    real_org = _get_org_id(org_id, user)
    info = _get_restaurant_info(real_org, user)
    login = info["api_login"]
    try:
        client = get_client(login, info.get("iiko_server"), info.get("api_password"))
        stop_data, nomen_data = await asyncio.gather(
            client.get_stop_lists([_olap_dept(real_org, info)]),
            client.get_nomenclature(real_org),
            return_exceptions=True
        )
        if isinstance(stop_data, Exception) or isinstance(nomen_data, Exception):
            return DEMO_STOPLIST

        id_to_product = {p["id"]: p for p in nomen_data.get("products", [])}
        stopped = []
        for loc in stop_data.get("productionLocations", []):
            for item in loc.get("stopList", {}).get("items", []):
                pid = item.get("productId", "")
                product = id_to_product.get(pid, {})
                balance = item.get("balance", 0)
                stopped.append({
                    "name": product.get("name", pid),
                    "sku": product.get("code", ""),
                    "balance": balance,
                    "category": product.get("productCategoryId", ""),
                    "status": "stop" if balance == 0 else "low"
                })

        return {"items": stopped, "total": len(stopped), "updated_at": datetime.now().strftime("%H:%M")}
    except Exception:
        return DEMO_STOPLIST


@app.post("/api/ai/analyze")
@limiter.limit("20/minute")
async def ai_analyze(request: Request, payload: AIAnalyze, user: Dict = Depends(get_current_user)):
    org_id = payload.context.get("org_id", "demo")
    response = await analyze_with_claude(payload.question, payload.context, org_id)
    return {"response": response}


@app.post("/api/expenses/manual")
async def create_manual_expense(org_id: str, payload: ExpenseCreate, user: Dict = Depends(get_current_user)):
    _get_org_id(org_id, user)  # проверка доступа
    add_manual_expense(org_id, payload.name, payload.category, payload.amount, payload.kassa, payload.date)
    return {"success": True}


@app.get("/api/expenses/manual")
async def list_manual_expenses(org_id: str, date_from: str, date_to: str, user: Dict = Depends(get_current_user)):
    _get_org_id(org_id, user)  # проверка доступа
    items = get_manual_expenses(org_id, date_from, date_to)
    return {"items": items}


@app.delete("/api/expenses/manual/{exp_id}")
async def remove_manual_expense(exp_id: int, org_id: str, user: Dict = Depends(get_current_user)):
    _get_org_id(org_id, user)  # проверка доступа
    delete_manual_expense(exp_id, org_id)
    return {"success": True}


@app.get("/api/export/{report_type}")
async def export_report(report_type: str, org_id: str = "demo-org-1", period: str = "today",
                        user: Dict = Depends(get_current_user)):
    """Генерирует CSV файл для скачивания"""
    from fastapi.responses import StreamingResponse
    import io

    rows = []
    filename = f"{report_type}-{datetime.now().strftime('%Y-%m-%d')}.csv"

    if report_type == "channels":
        rows = [["Канал", "Выручка", "Гостей", "Ср. чек"]]
        data = DEMO_SALES.get("channels", [])
        for c in data:
            rows.append([c.get("name",""), c.get("revenue",0), c.get("guests",0), round(c.get("avg_check",0))])
    elif report_type == "staff":
        rows = [["Имя", "Выручка", "Заказы", "Гости"]]
        data = DEMO_STAFF.get("staff", [])
        for s in data:
            rows.append([s.get("name",""), s.get("revenue",0), s.get("orders",0), s.get("guests",0)])
    elif report_type == "abc":
        rows = [["Блюдо", "Категория", "Выручка", "%", "Накоп.%", "ABC"]]
        # Берём демо данные ABC
        dishes = sorted(DEMO_SALES.get("top_dishes", []), key=lambda x: x.get("revenue", 0), reverse=True)
        total = sum(d.get("revenue", 0) for d in dishes)
        cum = 0
        for d in dishes:
            pct = round(d.get("revenue", 0) / total * 100, 1) if total else 0
            cum += pct
            abc = "A" if cum <= 80 else ("B" if cum <= 95 else "C")
            rows.append([d.get("name",""), "", d.get("revenue",0), pct, round(cum,1), abc])
    elif report_type == "engineering":
        rows = [["Блюдо", "Категория", "Выручка", "Маржа%", "Кол-во"]]
        for d in DEMO_SALES.get("top_dishes", []):
            rows.append([d.get("name",""), "", d.get("revenue",0), "—", d.get("count",0)])
    elif report_type == "expenses":
        rows = [["Название", "Категория", "Сумма", "Дата"]]
        for e in DEMO_EXPENSES.get("operations", []):
            rows.append([e.get("name",""), e.get("category",""), e.get("amount",0), e.get("date","")])
    elif report_type == "writeoffs":
        rows = [["Позиция", "Категория", "Сумма", "Дата"]]
        for w in DEMO_WRITEOFFS.get("categories", []):
            rows.append([w.get("name",""), w.get("category",""), w.get("amount",0), ""])
    else:
        rows = [["Нет данных"]]

    csv_content = '\uFEFF' + '\n'.join(';'.join(str(c) for c in row) for row in rows)
    output = io.BytesIO(csv_content.encode('utf-8-sig'))

    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.post("/api/export-send")
@limiter.limit("10/minute")
async def export_send(request: Request, payload: ExportSendPayload,
                      user: Dict = Depends(get_current_user)):
    """Отправляет CSV/текстовый файл в чат с пользователем через бота."""
    chat_id = user.get("id")
    if not chat_id:
        raise HTTPException(status_code=400, detail="no chat_id")
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail="bot not configured")

    safe_name = "".join(c for c in payload.filename if c.isalnum() or c in "._- ") or "export.csv"
    if not safe_name.lower().endswith((".csv", ".txt")):
        safe_name += ".csv"

    content_bytes = payload.content.encode("utf-8")
    if not content_bytes.startswith(b"\xef\xbb\xbf"):
        content_bytes = b"\xef\xbb\xbf" + content_bytes

    files = {"document": (safe_name, content_bytes, "text/csv")}
    data = {"chat_id": str(chat_id)}
    if payload.caption:
        data["caption"] = payload.caption[:1000]

    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                             data=data, files=files)
        result = r.json()
        if not result.get("ok"):
            desc = result.get("description", "send failed")
            if "chat not found" in desc.lower() or "bot was blocked" in desc.lower():
                raise HTTPException(status_code=409,
                    detail="Откройте чат с ботом и нажмите Start, потом повторите.")
            raise HTTPException(status_code=502, detail=f"Telegram: {desc}")
        return {"ok": True}
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Telegram request failed: {e}")


# ============ INVOICE EDITOR (Mini App) + POST/UNPOST ============

class InvoiceEditPayload(BaseModel):
    items: List[Dict[str, Any]]
    supplier: Optional[str] = None
    date: Optional[str] = None
    total_amount: Optional[float] = None
    vat_amount: Optional[float] = None


@app.get("/api/invoice-edit/{pending_id}")
async def invoice_edit_get(pending_id: str, user: Dict = Depends(get_current_user)):
    """Возвращает данные pending-накладной для редактирования в Mini App.
    Доступ только владельцу (по telegram_id из initData)."""
    chat_id = _pending_by_id.get(pending_id)
    pending = _pending_invoices.get(chat_id) if chat_id else None
    if not pending:
        raise HTTPException(status_code=404, detail="Pending invoice not found or expired")
    if pending.get("telegram_id") != user.get("id"):
        raise HTTPException(status_code=403, detail="Not your invoice")
    result = pending.get("result") or {}
    rests = _get_user_orgs(pending["telegram_id"])
    org_id_for_search = rests[0]["organization_id"] if rests else None
    return {
        "pending_id": pending_id,
        "supplier": result.get("supplier"),
        "date": result.get("date"),
        "items": result.get("items", []),
        "total_amount": result.get("total_amount", 0),
        "vat_amount": result.get("vat_amount", 0),
        "vat_rate": result.get("vat_rate", 12.0),
        "currency": result.get("currency", "KZT"),
        "search_org_id": org_id_for_search,
    }


@app.post("/api/invoice-edit/{pending_id}")
async def invoice_edit_post(pending_id: str, payload: InvoiceEditPayload,
                             user: Dict = Depends(get_current_user)):
    """Принимает обновлённую накладную из Mini App (fallback к WebApp.sendData).
    После обновления pending — бот сам перерисует превью при следующем callback'е,
    но для лучшего UX делаем edit прямо здесь."""
    chat_id = _pending_by_id.get(pending_id)
    pending = _pending_invoices.get(chat_id) if chat_id else None
    if not pending:
        raise HTTPException(status_code=404, detail="Pending invoice not found")
    if pending.get("telegram_id") != user.get("id"):
        raise HTTPException(status_code=403, detail="Not your invoice")
    r = pending.setdefault("result", {})
    r["items"] = payload.items
    if payload.supplier is not None: r["supplier"] = payload.supplier
    if payload.date is not None: r["date"] = payload.date
    if payload.total_amount is not None: r["total_amount"] = payload.total_amount
    if payload.vat_amount is not None: r["vat_amount"] = payload.vat_amount
    pending["state"] = "preview"
    # Перерисуем превью в боте
    if pending.get("message_id"):
        await _tg_edit(pending["chat_id"], pending["message_id"],
                       _format_invoice_v2(pending, "preview"),
                       _invoice_kb(pending["pending_id"]))
    return {"ok": True}


@app.get("/api/nomenclature/search/{org_id}")
async def nomenclature_search(org_id: str, q: str = Query("", max_length=100),
                               limit: int = Query(30, le=50),
                               user: Dict = Depends(get_current_user)):
    """Поиск товаров по имени в номенклатуре iiko (для редактора накладных)."""
    if _is_demo_user(user) or org_id == "demo-org-1":
        return {"products": []}
    real_org = _get_org_id(org_id, user)
    info = _get_restaurant_info(real_org, user)
    client = get_client(info["api_login"], info.get("iiko_server"), info.get("api_password"))
    try:
        products = await client.search_nomenclature(real_org, q, limit=limit)
    except Exception as e:
        logger.warning(f"[nomenclature_search] {e}")
        products = []
    return {"products": [
        {"id": p.get("id"), "name": p.get("name"), "num": p.get("num"),
         "code": p.get("code"), "unit": p.get("unit") or p.get("mainUnit")}
        for p in products
    ]}


@app.get("/api/debug/iiko-fields/{org_id}")
async def debug_iiko_fields(org_id: str, report_type: str = "TRANSACTIONS"):
    """Диагностика OLAP-полей: пробует несколько URL-схем columns-эндпоинта
    и возвращает статус+тело каждой попытки. Без auth, без данных юзера."""
    conn = get_db()
    if org_id == "auto":
        row = conn.execute(
            "SELECT organization_id, api_login, iiko_server, api_password "
            "FROM restaurants WHERE iiko_server IS NOT NULL LIMIT 1"
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT organization_id, api_login, iiko_server, api_password "
            "FROM restaurants WHERE organization_id = ? LIMIT 1", (org_id,)
        ).fetchone()
    conn.close()
    if not row:
        return {"error": "no restaurant found", "org_id": org_id}
    real_org = row["organization_id"]
    api_password = decrypt_password(row["api_password"]) if row["api_password"] else None
    client = get_client(row["api_login"], row["iiko_server"], api_password)
    base = getattr(client, "base_url", None)
    if not base:
        # Cloud-клиент — другая схема, не наш случай
        return {"error": "cloud client — debug not implemented", "org_id": real_org}
    try:
        token = await client._ensure_token()
    except Exception as e:
        return {"error": f"auth failed: {e}", "org_id": real_org}
    candidates = [
        f"{base}/api/v2/reports/olap/columns/{report_type}",
        f"{base}/api/v2/reports/olap/columns?reportType={report_type}",
        f"{base}/api/v2/reports/olap/columnsConfig",
        f"{base}/api/v2/reports/olap/columnsConfig?reportType={report_type}",
        f"{base}/api/reports/olap/columns/{report_type}",
    ]
    attempts: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0, verify=False) as cli:
        for url in candidates:
            try:
                sep = "&" if "?" in url else "?"
                resp = await cli.get(f"{url}{sep}key={token}")
                attempts.append({
                    "url": url,
                    "status": resp.status_code,
                    "body": resp.text[:1500],
                })
            except Exception as e:
                attempts.append({"url": url, "error": str(e)})
    return {"org_id": real_org, "report_type": report_type, "attempts": attempts}


@app.get("/api/suppliers/{org_id}")
async def suppliers_list(org_id: str, user: Dict = Depends(get_current_user)):
    """Список поставщиков из iiko (для редактора)."""
    if _is_demo_user(user) or org_id == "demo-org-1":
        return {"suppliers": []}
    real_org = _get_org_id(org_id, user)
    info = _get_restaurant_info(real_org, user)
    client = get_client(info["api_login"], info.get("iiko_server"), info.get("api_password"))
    try:
        suppliers = await client.get_suppliers(real_org)
    except Exception as e:
        logger.warning(f"[suppliers_list] {e}")
        suppliers = []
    return {"suppliers": suppliers}


@app.get("/api/invoice-saved/{invoice_id}")
async def invoice_saved_get(invoice_id: int, user: Dict = Depends(get_current_user)):
    """Загрузить сохранённую накладную (из БД) для редактирования в Mini App.
    Используется для накладных со статусом needs_mapping / iiko_error / draft."""
    inv = get_bot_invoice(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv.get("telegram_id") != user.get("id"):
        raise HTTPException(status_code=403, detail="Not your invoice")
    try:
        items = json.loads(inv.get("items") or "[]")
    except Exception:
        items = []
    return {
        "invoice_id": invoice_id,
        "supplier": inv.get("supplier"),
        "supplier_id": inv.get("supplier_id"),
        "organization_id": inv.get("organization_id"),
        "date": inv.get("date"),
        "items": items,
        "total_amount": inv.get("total_amount", 0),
        "vat_amount": inv.get("vat_amount", 0),
        "vat_rate": 12.0,
        "currency": "KZT",
        "search_org_id": inv.get("organization_id"),
        "status": inv.get("status"),
    }


class SavedInvoicePayload(BaseModel):
    items: List[Dict[str, Any]]
    supplier: Optional[str] = None
    date: Optional[str] = None
    total_amount: Optional[float] = None
    vat_amount: Optional[float] = None


@app.post("/api/invoice-saved/{invoice_id}/send")
async def invoice_saved_send(invoice_id: int, payload: SavedInvoicePayload,
                              user: Dict = Depends(get_current_user)):
    """После ручного маппинга в Mini App — обновить позиции и попробовать отправить в iiko."""
    inv = get_bot_invoice(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv.get("telegram_id") != user.get("id"):
        raise HTTPException(status_code=403, detail="Not your invoice")

    # Сохраняем обновлённые поля
    update_fields = {"items": json.dumps(payload.items, ensure_ascii=False)}
    if payload.supplier is not None: update_fields["supplier"] = payload.supplier
    if payload.date is not None: update_fields["date"] = payload.date
    if payload.total_amount is not None: update_fields["total_amount"] = payload.total_amount
    if payload.vat_amount is not None: update_fields["vat_amount"] = payload.vat_amount
    update_bot_invoice(invoice_id, **update_fields)

    # Готовим и шлём в iiko
    org_id = inv.get("organization_id")
    supplier_id = inv.get("supplier_id")
    if not org_id or not supplier_id:
        raise HTTPException(status_code=400, detail="Не указан филиал или поставщик")
    real_org = _get_org_id(org_id, user)
    info = _get_restaurant_info(real_org, user)
    client = get_client(info["api_login"], info.get("iiko_server"), info.get("api_password"))

    # Собираем sendable items — только те у кого есть iiko_product_id
    sendable, unmatched = [], []
    for it in payload.items:
        prod_id = it.get("iiko_product_id")
        if not prod_id:
            unmatched.append(it.get("name", "—"))
            continue
        qty = float(it.get("quantity") or 0)
        price = float(it.get("price_per_unit") or 0)
        total = float(it.get("total") or (qty * price))
        sendable.append({"productId": prod_id, "amount": qty, "price": price, "sum": total})

    if unmatched:
        update_bot_invoice(invoice_id, status="needs_mapping")
        return {"ok": False, "unmatched": unmatched,
                "error": f"Не сопоставлено {len(unmatched)} позиций — выбери товар iiko для каждой"}

    date_str = payload.date or inv.get("date") or datetime.now().strftime("%Y-%m-%d")
    try:
        resp = await client.create_incoming_invoice(
            org_id=real_org, supplier_id=supplier_id,
            items=sendable, date=date_str
        )
    except Exception as e:
        update_bot_invoice(invoice_id, status="iiko_error")
        raise HTTPException(status_code=502, detail=f"iiko: {e}")

    if not resp.get("ok"):
        update_bot_invoice(invoice_id, status="iiko_error")
        err = resp.get("error", "unknown")
        body_txt = resp.get("body") or ""
        if body_txt:
            err = f"{err}: {body_txt[:300]}"
        return {"ok": False, "error": err}

    update_bot_invoice(invoice_id,
        iiko_doc_id=resp.get("id") or "",
        iiko_doc_number=resp.get("number") or "",
        status="draft_in_iiko")
    return {"ok": True, "iiko_doc_id": resp.get("id"), "iiko_doc_number": resp.get("number")}


@app.post("/api/invoices/{invoice_id}/post")
async def invoice_post_doc(invoice_id: int, user: Dict = Depends(get_current_user)):
    """Провести накладную в iiko."""
    inv = get_bot_invoice(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv.get("telegram_id") != user.get("id"):
        raise HTTPException(status_code=403, detail="Not your invoice")
    if not inv.get("iiko_doc_id"):
        raise HTTPException(status_code=400, detail="Накладная не создана в iiko (нет doc_id)")
    real_org = _get_org_id(inv["organization_id"], user)
    info = _get_restaurant_info(real_org, user)
    client = get_client(info["api_login"], info.get("iiko_server"), info.get("api_password"))
    try:
        resp = await client.set_document_status(real_org, inv["iiko_doc_id"], "PROCESSED")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"iiko: {e}")
    if not resp.get("ok"):
        raise HTTPException(status_code=502, detail=resp.get("error") or "iiko error")
    update_bot_invoice(invoice_id, status="posted")
    return {"ok": True}


@app.post("/api/invoices/{invoice_id}/unpost")
async def invoice_unpost_doc(invoice_id: int, user: Dict = Depends(get_current_user)):
    """Распровести накладную в iiko."""
    inv = get_bot_invoice(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv.get("telegram_id") != user.get("id"):
        raise HTTPException(status_code=403, detail="Not your invoice")
    if not inv.get("iiko_doc_id"):
        raise HTTPException(status_code=400, detail="Нет doc_id")
    real_org = _get_org_id(inv["organization_id"], user)
    info = _get_restaurant_info(real_org, user)
    client = get_client(info["api_login"], info.get("iiko_server"), info.get("api_password"))
    try:
        resp = await client.set_document_status(real_org, inv["iiko_doc_id"], "NEW")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"iiko: {e}")
    if not resp.get("ok"):
        raise HTTPException(status_code=502, detail=resp.get("error") or "iiko error")
    update_bot_invoice(invoice_id, status="draft_in_iiko")
    return {"ok": True}


# ============ INVOICE BOT v2: state + helpers ============
# _pending_invoices: chat_id -> pending dict
# _pending_by_id:    pending_id -> chat_id (reverse index для Mini App, этап 5)
_pending_invoices: Dict[int, dict] = {}
_pending_by_id: Dict[str, int] = {}

def _invoice_kb(pending_id: str) -> dict:
    """Динамическая клавиатура превью — WebApp-кнопка редактирования с pending_id в URL."""
    return {
        "inline_keyboard": [
            [{"text": "📤 Отправить в iiko", "callback_data": "act:send"},
             {"text": "➕ Добавить фото",     "callback_data": "act:add"}],
            [{"text": "✏️ Редактировать",   "web_app": {"url": f"{MINIAPP_URL}/?edit={pending_id}"}},
             {"text": "❌ Отменить",         "callback_data": "act:cancel"}],
        ]
    }


# Backward-compat alias для мест где не нужна WebApp-кнопка
INVOICE_KB_FALLBACK = {
    "inline_keyboard": [
        [{"text": "📤 Отправить в iiko", "callback_data": "act:send"},
         {"text": "➕ Добавить фото",     "callback_data": "act:add"}],
        [{"text": "✏️ Редактировать",   "callback_data": "act:edit"},
         {"text": "❌ Отменить",         "callback_data": "act:cancel"}],
    ]
}

ADD_PHOTOS_KB = {
    "inline_keyboard": [
        [{"text": "✅ Готово",  "callback_data": "add:done"}],
        [{"text": "❌ Отмена", "callback_data": "act:cancel"}],
    ]
}


async def _tg_send(chat_id: int, text: str, reply_markup: dict = None) -> Optional[int]:
    """Шлёт сообщение, возвращает message_id (или None при ошибке)."""
    if not BOT_TOKEN:
        return None
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)
        return r.json().get("result", {}).get("message_id")
    except Exception as e:
        logger.warning(f"[tg_send] {e}")
        return None


async def _tg_edit(chat_id: int, message_id: int, text: str, reply_markup: dict = None):
    if not BOT_TOKEN or not message_id:
        return
    payload = {"chat_id": chat_id, "message_id": message_id,
               "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json=payload)
    except Exception as e:
        logger.warning(f"[tg_edit] {e}")


async def _tg_download_file(file_id: str) -> Optional[Tuple[bytes, str]]:
    """Скачивает файл по file_id. Возвращает (bytes, mime_type) или None."""
    if not BOT_TOKEN:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
                            params={"file_id": file_id})
            result = r.json().get("result")
            if not result:
                return None
            file_path = result.get("file_path", "")
            img_r = await c.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}")
            return img_r.content, "image/jpeg"
    except Exception as e:
        logger.warning(f"[tg_download] {e}")
        return None


def _pending_id() -> str:
    """Короткий UUID для Mini App URL."""
    return uuid4().hex[:16]


def _fmt_kzt(n: float) -> str:
    """12500.0 -> '12 500'."""
    try:
        return f"{int(round(float(n))):,}".replace(",", " ")
    except Exception:
        return str(n)


def _photo_count_text(n: int) -> str:
    return "1 фото" if n == 1 else f"{n} фото"


def _format_invoice_v2(p: dict, status: str = "preview") -> str:
    """Превью накладной: позиции + «Итого X ₸ (в т.ч. НДС Y ₸)»."""
    result = p.get("result", {}) or {}
    supplier = result.get("supplier") or "—"
    date_str = result.get("date") or "—"
    items = result.get("items", []) or []
    total = float(result.get("total_amount") or 0)
    vat = float(result.get("vat_amount") or 0)
    n_photos = len(p.get("images") or [])

    icon = {"preview": "📋", "adding": "📸", "recognizing": "🔍",
            "sent": "✅", "cancelled": "❌"}.get(status, "📋")

    lines = [f"{icon} <b>Накладная распознана</b>"]
    if n_photos > 1:
        lines.append(f"📎 {_photo_count_text(n_photos)} объединено")
    lines.append(f"🏭 Поставщик: {supplier}")
    lines.append(f"📅 Дата: {date_str}")

    if items:
        lines.append(f"\n<b>Позиции ({len(items)}):</b>")
        for it in items[:15]:
            nm = it.get("name", "—") or "—"
            qty = it.get("quantity")
            un = it.get("unit") or ""
            ppu = it.get("price_per_unit")
            tot = it.get("total")
            qty_s = "—" if qty is None else str(qty)
            ppu_s = "—" if ppu is None else _fmt_kzt(ppu)
            tot_s = "—" if tot is None else _fmt_kzt(tot)
            lines.append(f"• {nm}: {qty_s} {un} × {ppu_s} ₸ = {tot_s} ₸")
        if len(items) > 15:
            lines.append(f"  … ещё {len(items)-15} позиций")

    total_line = f"\n💰 <b>Итого: {_fmt_kzt(total)} ₸</b>"
    if vat and vat > 0:
        total_line += f"  <i>(в т.ч. НДС {_fmt_kzt(vat)} ₸)</i>"
    lines.append(total_line)

    if status == "preview":
        lines.append("\n⚠️ <i>Распознано ИИ — могут быть ошибки. Проверь перед отправкой.</i>")
        lines.append("<i>Выбери действие ниже:</i>")
    elif status == "adding":
        lines.append("\n<i>Пришли ещё фото или файлом, потом нажми «✅ Готово»</i>")
    elif status == "sent":
        lines.append("\n<b>✅ Отправлено в iiko</b>")
    elif status == "cancelled":
        lines.append("\n<i>Отменено</i>")

    return "\n".join(lines)


def _drop_pending(chat_id: int) -> None:
    p = _pending_invoices.pop(chat_id, None)
    if p:
        _pending_by_id.pop(p.get("pending_id", ""), None)


def _get_user_orgs(telegram_id: int) -> List[Dict[str, Any]]:
    """Все рестораны пользователя (org_id + creds). Дедупликация по organization_id уже в get_restaurants."""
    return get_restaurants(telegram_id) or []


def _bot_iiko_client(rest: Dict[str, Any]):
    """IikoClient/IikoWebClient для конкретной записи ресторана."""
    return get_client(rest["api_login"], rest.get("iiko_server"), rest.get("api_password"))


def _compute_dedup_hash(supplier: str, date_str: str, total: float,
                        items: List[Dict[str, Any]]) -> str:
    """Стабильный хеш накладной для защиты от дублей."""
    sig_items = sorted([
        (str(it.get("name", "")).strip().lower(),
         round(float(it.get("quantity") or 0), 3),
         round(float(it.get("price_per_unit") or 0), 2))
        for it in (items or [])
    ])
    payload = json.dumps({
        "s": (supplier or "").strip().lower(),
        "d": (date_str or "").strip(),
        "t": round(float(total or 0), 2),
        "i": sig_items,
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _auto_match_items(client, org_id: str,
                             items: List[Dict[str, Any]]) -> Tuple[List[Dict], List[str]]:
    """Сопоставляет позиции с номенклатурой iiko по имени.
    Возвращает (sendable_items, unmatched_names).
    sendable_items — формат для create_incoming_invoice (product, amount, price, sum).
    """
    sendable, unmatched = [], []
    for it in (items or []):
        # Если уже сопоставлено в редакторе — используем
        prod_id = it.get("iiko_product_id")
        if not prod_id:
            try:
                matches = await client.search_nomenclature(org_id, it.get("name", ""), limit=1)
            except Exception as e:
                logger.warning(f"[invoice-match] iiko search_nomenclature failed for org={org_id}, name='{it.get('name', '')}': {e}")
                matches = []
            if matches:
                prod_id = matches[0].get("id")
        if not prod_id:
            unmatched.append(it.get("name", "—"))
            continue
        qty = float(it.get("quantity") or 0)
        price = float(it.get("price_per_unit") or 0)
        total = float(it.get("total") or (qty * price))
        sendable.append({
            "productId": prod_id,
            "amount": qty,
            "price": price,
            "sum": total,
        })
    return sendable, unmatched


def _suppliers_kb(suppliers: List[Dict[str, Any]], page: int = 0) -> dict:
    """Клавиатура выбора поставщика (по 20 на страницу)."""
    PAGE = 20
    start = page * PAGE
    chunk = suppliers[start:start + PAGE]
    rows = []
    for s in chunk:
        sid = s.get("id") or s.get("supplierId")
        name = (s.get("name") or "—")[:35]
        if sid:
            rows.append([{"text": name, "callback_data": f"sup:{sid}"}])
    nav = []
    if page > 0:
        nav.append({"text": "← Назад", "callback_data": f"sup:page:{page-1}"})
    if start + PAGE < len(suppliers):
        nav.append({"text": "Ещё →", "callback_data": f"sup:page:{page+1}"})
    if nav:
        rows.append(nav)
    rows.append([{"text": "❌ Отмена", "callback_data": "act:cancel"}])
    return {"inline_keyboard": rows}


def _orgs_kb(orgs: List[Dict[str, Any]]) -> dict:
    """Клавиатура выбора филиала."""
    rows = []
    for o in orgs:
        oid = o.get("organization_id") or o.get("id")
        name = (o.get("organization_name") or o.get("name") or "—")[:35]
        if oid:
            rows.append([{"text": name, "callback_data": f"org:{oid}"}])
    rows.append([{"text": "❌ Отмена", "callback_data": "act:cancel"}])
    return {"inline_keyboard": rows}


def _dedup_kb() -> dict:
    return {
        "inline_keyboard": [[
            {"text": "✅ Да, создать копию", "callback_data": "dedup:yes"},
            {"text": "❌ Нет, отменить",     "callback_data": "dedup:no"},
        ]]
    }


async def _show_supplier_picker(chat_id: int, msg_id: int, pending: dict) -> bool:
    """Показывает список поставщиков. True если показано, False если ошибка."""
    rests = _get_user_orgs(pending["telegram_id"])
    if not rests:
        await _tg_edit(chat_id, msg_id,
            "⚠️ У тебя не настроен ни один ресторан в Mini App. Сначала добавь iiko-учётку.")
        return False
    first = rests[0]
    if first["api_login"] == "demo":
        await _tg_edit(chat_id, msg_id,
            "⚠️ Ты в demo-режиме. Отправка в iiko недоступна — добавь реальную учётку.")
        return False
    client = _bot_iiko_client(first)
    try:
        suppliers = await client.get_suppliers(first["organization_id"])
    except Exception as e:
        logger.warning(f"[suppliers] {e}")
        suppliers = []
    if not suppliers:
        await _tg_edit(chat_id, msg_id,
            "⚠️ Не удалось получить список поставщиков из iiko. Попробуй позже.")
        return False
    # сохраним в pending для пагинации/выбора по id
    pending["state"] = "choosing_supplier"
    pending["suppliers_cache"] = suppliers
    await _tg_edit(chat_id, msg_id,
        f"🏭 <b>Выбери поставщика</b> ({len(suppliers)}):",
        _suppliers_kb(suppliers, 0))
    return True


async def _show_supplier_picker_for_org(chat_id: int, msg_id: int, pending: dict, org_id: str) -> bool:
    """Показывает список поставщиков КОНКРЕТНОГО филиала. True если показано."""
    rests = _get_user_orgs(pending["telegram_id"])
    rest = next((r for r in rests if r.get("organization_id") == org_id), None)
    if not rest:
        await _tg_edit(chat_id, msg_id, "⚠️ Филиал не найден среди подключённых.")
        return False
    if rest["api_login"] == "demo":
        await _tg_edit(chat_id, msg_id,
            "⚠️ Ты в demo-режиме. Отправка в iiko недоступна — добавь реальную учётку.")
        return False
    client = _bot_iiko_client(rest)
    try:
        suppliers = await client.get_suppliers(org_id)
    except Exception as e:
        logger.warning(f"[suppliers for {org_id}] {e}")
        suppliers = []
    if not suppliers:
        await _tg_edit(chat_id, msg_id,
            "⚠️ Не удалось получить список поставщиков из iiko. Попробуй позже.")
        return False
    pending["state"] = "choosing_supplier"
    pending["suppliers_cache"] = suppliers
    await _tg_edit(chat_id, msg_id,
        f"🏭 <b>Выбери поставщика</b> ({len(suppliers)}):",
        _suppliers_kb(suppliers, 0))
    return True


async def _show_org_picker(chat_id: int, msg_id: int, pending: dict) -> bool:
    """Показывает список филиалов того же iiko-сервера."""
    rests = _get_user_orgs(pending["telegram_id"])
    if not rests:
        await _tg_edit(chat_id, msg_id, "⚠️ Нет филиалов в твоей учётке.")
        return False
    pending["state"] = "choosing_org"
    await _tg_edit(chat_id, msg_id,
        f"🏢 <b>Выбери филиал</b> ({len(rests)}):",
        _orgs_kb(rests))
    return True


def _compare_prices(telegram_id: int, current_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Для каждой позиции текущей накладной возвращает сравнение с историческим минимумом.

    Возвращает список dict'ов в том же порядке что current_items, каждый:
      {name, current_price, quantity, unit,
       min_price, min_supplier, min_date,  # None если нет истории
       status: 'new_min' | 'overpay' | 'normal' | 'no_history',
       delta_pct: float}
    """
    history = get_price_history(telegram_id, days=90)
    by_key: Dict[str, List[Dict[str, Any]]] = {}
    for h in history:
        by_key.setdefault(h["key"], []).append(h)

    rows: List[Dict[str, Any]] = []
    for it in current_items or []:
        name = (it.get("name") or "").strip()
        current_price = float(it.get("price_per_unit") or 0)
        quantity = float(it.get("quantity") or 0)
        unit = it.get("unit") or ""
        key = str(it.get("iiko_product_id") or name.lower())

        past = by_key.get(key, [])
        # Берём минимум среди прошлых закупок (НЕ включая текущую — она ещё не сохранена).
        if past:
            best = min(past, key=lambda r: r["price_per_unit"])
            min_price = best["price_per_unit"]
            min_supplier = best["supplier"]
            min_date = best["date"]
            if current_price <= min_price * 0.99:
                status = "new_min"
            elif current_price >= min_price * 1.1:
                status = "overpay"
            else:
                status = "normal"
            delta_pct = ((current_price - min_price) / min_price * 100) if min_price > 0 else 0.0
        else:
            min_price = None
            min_supplier = None
            min_date = None
            status = "no_history"
            delta_pct = 0.0

        rows.append({
            "name": name,
            "current_price": current_price,
            "quantity": quantity,
            "unit": unit,
            "min_price": min_price,
            "min_supplier": min_supplier,
            "min_date": min_date,
            "status": status,
            "delta_pct": delta_pct,
        })
    return rows


def _format_price_comparison(rows: List[Dict[str, Any]]) -> str:
    """HTML-сообщение для бота с построчным сравнением цен."""
    if not rows:
        return "📊 <b>Сравнение цен</b>\n\nВ накладной нет позиций с ценами для сравнения."

    if all(r["status"] == "no_history" for r in rows):
        return ("📊 <b>Сравнение цен</b>\n\n"
                "📭 Это первая накладная — истории закупок для сравнения пока нет. "
                "После нескольких отправленных накладных я смогу показывать где переплачиваешь, "
                "а где удалось купить дешевле обычного.")

    icons = {"new_min": "🟢", "overpay": "🔴", "normal": "⚪", "no_history": "🟡"}
    lines = ["📊 <b>Сравнение цен с историей (90 дней)</b>", ""]

    overpay_savings = 0.0
    for r in rows:
        icon = icons.get(r["status"], "⚪")
        name = html.escape(r["name"] or "—")
        cur = r["current_price"]
        unit = html.escape(r["unit"] or "ед")
        if r["status"] == "new_min":
            tail = f"новый минимум, было {r['min_price']:.0f} ₸"
        elif r["status"] == "overpay":
            supplier = html.escape(r["min_supplier"] or "—")
            tail = (f"+{r['delta_pct']:.0f}% к минимуму {r['min_price']:.0f} ₸ "
                    f"у \"{supplier}\", {r['min_date']}")
            overpay_savings += (cur - r["min_price"]) * (r["quantity"] or 0)
        elif r["status"] == "normal":
            sign = "+" if r["delta_pct"] >= 0 else ""
            tail = f"как обычно ({sign}{r['delta_pct']:.0f}%)"
        else:  # no_history
            tail = "нет истории"
        lines.append(f"{icon} <b>{name}</b> — {cur:.0f} ₸/{unit} <i>({tail})</i>")

    if overpay_savings > 0:
        lines.append("")
        lines.append(f"💡 <i>Потенциальная экономия если брать у дешёвых: "
                     f"{overpay_savings:,.0f} ₸</i>".replace(",", " "))
    return "\n".join(lines)


async def _finalize_send(chat_id: int, msg_id: int, pending: dict,
                          force: bool = False) -> None:
    """Финальный шаг: dedup-проверка + auto-match + create_incoming_invoice + сохранение в БД."""
    result = pending.get("result") or {}
    supplier_name = pending.get("supplier_name") or result.get("supplier") or "—"
    supplier_id = pending.get("supplier_id") or ""
    org_id = pending.get("organization_id") or ""
    items = result.get("items", []) or []
    total = float(result.get("total_amount") or 0)
    vat = float(result.get("vat_amount") or 0)
    date_str = result.get("date") or datetime.now().strftime("%Y-%m-%d")

    # ---- Dedup ----
    dedup_hash = _compute_dedup_hash(supplier_name, date_str, total, items)
    pending["dedup_hash"] = dedup_hash
    if not force:
        existing = find_invoice_by_dedup(dedup_hash, pending["telegram_id"], days=30)
        if existing:
            await _tg_edit(chat_id, msg_id,
                f"⚠️ Похоже эту накладную уже отправляли:\n"
                f"📅 {existing.get('created_at','')[:10]}, "
                f"🏭 {existing.get('supplier','')}, "
                f"💰 {_fmt_kzt(existing.get('total_amount') or 0)} ₸\n\n"
                f"<b>Создать копию?</b>",
                _dedup_kb())
            return

    # ---- Resolve restaurant credentials for the picked org ----
    rests = _get_user_orgs(pending["telegram_id"])
    rest = next((r for r in rests if r["organization_id"] == org_id), None) or (rests[0] if rests else None)
    if not rest:
        await _tg_edit(chat_id, msg_id, "❌ Филиал не найден. Отмена.")
        _drop_pending(chat_id)
        return
    client = _bot_iiko_client(rest)

    # ---- Auto-match items to iiko nomenclature ----
    await _tg_edit(chat_id, msg_id, "🔎 Сопоставляю позиции с номенклатурой iiko...")
    sendable, unmatched = await _auto_match_items(client, org_id, items)

    if unmatched:
        # Сохраняем как локальный черновик, просим открыть редактор для маппинга
        save_bot_invoice(
            telegram_id=pending["telegram_id"],
            telegram_user=pending.get("username") or "",
            raw_text="[ФОТО]",
            supplier=supplier_name, branch=rest.get("organization_name", ""),
            items_json=json.dumps(items, ensure_ascii=False),
            total_amount=total, date=date_str,
            vat_amount=vat, supplier_id=supplier_id,
            organization_id=org_id, dedup_hash=dedup_hash,
            status="needs_mapping",
        )
        names_preview = ", ".join(unmatched[:5])
        more = f" и ещё {len(unmatched)-5}" if len(unmatched) > 5 else ""
        await _tg_edit(chat_id, msg_id,
            f"⚠️ Не сопоставлено {len(unmatched)} позиций: {names_preview}{more}\n\n"
            f"📋 Накладная сохранена как черновик. Открой Mini App → Расходы → Накладные, "
            f"нажми ✏️ чтобы выбрать товары вручную и отправить.")
        _drop_pending(chat_id)
        return

    # ---- Send to iiko ----
    try:
        resp = await client.create_incoming_invoice(
            org_id=org_id, supplier_id=supplier_id,
            items=sendable, date=date_str
        )
    except Exception as e:
        logger.warning(f"[create_invoice] {e}")
        resp = {"ok": False, "error": str(e)}

    if not resp.get("ok"):
        # Сохраняем локальный черновик чтобы пользователь не потерял работу
        save_bot_invoice(
            telegram_id=pending["telegram_id"],
            telegram_user=pending.get("username") or "",
            raw_text="[ФОТО]",
            supplier=supplier_name, branch=rest.get("organization_name", ""),
            items_json=json.dumps(items, ensure_ascii=False),
            total_amount=total, date=date_str,
            vat_amount=vat, supplier_id=supplier_id,
            organization_id=org_id, dedup_hash=dedup_hash,
            status="iiko_error",
        )
        err = resp.get("error", "unknown")
        body_txt = (resp.get("body") or "")[:400]
        body_line = f"\n<code>{body_txt}</code>" if body_txt else ""
        if "409" in err:
            headline = "⚠️ Похоже эта накладная уже есть в iiko (конфликт по номеру или содержимому)."
        else:
            headline = f"❌ iiko вернул ошибку: <code>{err}</code>"
        await _tg_edit(chat_id, msg_id,
            f"{headline}{body_line}\n\n"
            f"📋 Накладная сохранена локально как черновик.")
        _drop_pending(chat_id)
        return

    iiko_doc_id = resp.get("id") or ""
    iiko_doc_number = resp.get("number") or ""
    inv_id = save_bot_invoice(
        telegram_id=pending["telegram_id"],
        telegram_user=pending.get("username") or "",
        raw_text="[ФОТО]",
        supplier=supplier_name, branch=rest.get("organization_name", ""),
        items_json=json.dumps(items, ensure_ascii=False),
        total_amount=total, date=date_str,
        vat_amount=vat, supplier_id=supplier_id,
        organization_id=org_id,
        iiko_doc_id=iiko_doc_id, iiko_doc_number=iiko_doc_number,
        dedup_hash=dedup_hash,
        status="draft_in_iiko",
    )
    num_str = f" #{iiko_doc_number}" if iiko_doc_number else ""
    await _tg_edit(chat_id, msg_id,
        f"✅ <b>Черновик создан в iiko{num_str}</b>\n\n"
        f"🏭 Поставщик: {supplier_name}\n"
        f"🏢 Филиал: {rest.get('organization_name','')}\n"
        f"💰 Итого: {_fmt_kzt(total)} ₸\n\n"
        f"Открой Mini App → Расходы → Накладные → нажми «▶️ Провести» когда проверишь.")
    _drop_pending(chat_id)


async def _recognize_invoice_and_create_pending(
    chat_id: int, telegram_id: int, username: str,
    file_id: str, image_bytes: bytes, mime: str
) -> None:
    """Распознаёт одно фото и создаёт pending invoice. Универсально для photo и document."""
    pending = _pending_invoices.get(chat_id)
    if pending and pending.get("state") == "adding_photos":
        pending["images"].append({"file_id": file_id, "bytes": image_bytes, "mime": mime})
        n = len(pending["images"])
        await _tg_send(chat_id,
            f"📸 Фото {n} добавлено. Нажми «✅ Готово» в верхнем сообщении когда все скинешь.")
        return

    status_msg_id = await _tg_send(chat_id, "🔍 Распознаю накладную...")
    result = await analyze_invoice_photos([(image_bytes, mime)])
    if "error" in result:
        msg = f"❌ Не удалось распознать: {result['error']}\n\nПопробуй сфотографировать чётче."
        if status_msg_id:
            await _tg_edit(chat_id, status_msg_id, msg)
        else:
            await _tg_send(chat_id, msg)
        return

    pid = _pending_id()
    pending = {
        "pending_id": pid,
        "telegram_id": telegram_id,
        "username": username,
        "chat_id": chat_id,
        "message_id": status_msg_id,
        "state": "preview",
        "images": [{"file_id": file_id, "bytes": image_bytes, "mime": mime}],
        "result": result,
        "supplier_id": None,
        "organization_id": None,
        "created_at": datetime.now().isoformat(),
    }
    _pending_invoices[chat_id] = pending
    _pending_by_id[pid] = chat_id

    if status_msg_id:
        await _tg_edit(chat_id, status_msg_id, _format_invoice_v2(pending, "preview"), _invoice_kb(pending["pending_id"]))
    else:
        new_id = await _tg_send(chat_id, _format_invoice_v2(pending, "preview"), _invoice_kb(pending["pending_id"]))
        pending["message_id"] = new_id


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Обработчик сообщений и callback_query Telegram бота."""
    if TELEGRAM_WEBHOOK_SECRET:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid webhook secret")
    try:
        data = await request.json()

        # === CALLBACK_QUERY ===
        if "callback_query" in data:
            cb = data["callback_query"]
            cb_id = cb["id"]
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]
            action = cb.get("data", "")

            async with httpx.AsyncClient(timeout=10.0) as c:
                try:
                    await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
                                 json={"callback_query_id": cb_id})
                except Exception:
                    pass

            pending = _pending_invoices.get(chat_id)

            # Отмена — работает даже если pending нет
            if action == "act:cancel":
                _drop_pending(chat_id)
                await _tg_edit(chat_id, msg_id, "❌ <i>Отменено</i>")
                return {"ok": True}

            if not pending:
                await _tg_edit(chat_id, msg_id,
                               "⚠️ Данные устарели. Пришли накладную (фото, файлом или текстом) заново.")
                return {"ok": True}

            if action == "act:add":
                pending["state"] = "adding_photos"
                await _tg_edit(chat_id, msg_id, _format_invoice_v2(pending, "adding"), ADD_PHOTOS_KB)
                return {"ok": True}

            if action == "act:compare":
                items = (pending.get("result") or {}).get("items") or []
                rows = _compare_prices(pending["telegram_id"], items)
                text = _format_price_comparison(rows)
                # Шлём НОВЫМ сообщением — превью с кнопками остаётся доступным
                await _tg_send(chat_id, text)
                return {"ok": True}

            if action == "add:done":
                images = pending.get("images") or []
                if not images:
                    _drop_pending(chat_id)
                    await _tg_edit(chat_id, msg_id, "⚠️ Ни одного фото нет. Отменено.")
                    return {"ok": True}
                await _tg_edit(chat_id, msg_id, f"🔍 Распознаю {_photo_count_text(len(images))}...")
                payload = [(img["bytes"], img["mime"]) for img in images]
                result = await analyze_invoice_photos(payload)
                if "error" in result:
                    await _tg_edit(chat_id, msg_id, f"❌ Не удалось распознать: {result['error']}")
                    _drop_pending(chat_id)
                    return {"ok": True}
                pending["result"] = result
                pending["state"] = "preview"
                await _tg_edit(chat_id, msg_id, _format_invoice_v2(pending, "preview"), _invoice_kb(pending["pending_id"]))
                return {"ok": True}

            if action == "act:send":
                rests = _get_user_orgs(pending["telegram_id"])
                if not rests:
                    await _tg_edit(chat_id, msg_id, "⚠️ У тебя не настроен ни один ресторан. Открой Mini App и подключи iiko-учётку.")
                    return {"ok": True}
                if rests[0]["api_login"] == "demo":
                    await _tg_edit(chat_id, msg_id, "⚠️ Ты в demo-режиме. Отправка в iiko недоступна — добавь реальную учётку.")
                    return {"ok": True}
                if len(rests) == 1:
                    pending["organization_id"] = rests[0]["organization_id"]
                    await _show_supplier_picker_for_org(chat_id, msg_id, pending, rests[0]["organization_id"])
                else:
                    await _show_org_picker(chat_id, msg_id, pending)
                return {"ok": True}

            if action == "act:edit":
                # act:edit теперь WebApp-кнопка, callback не приходит. Но если старый клиент:
                stub = (_format_invoice_v2(pending, "preview")
                        + "\n\n⏳ <i>Обнови Telegram для встроенного редактора.</i>")
                await _tg_edit(chat_id, msg_id, stub, _invoice_kb(pending["pending_id"]))
                return {"ok": True}

            # === Пагинация поставщиков ===
            if action.startswith("sup:page:"):
                page = int(action.rsplit(":", 1)[-1])
                suppliers = pending.get("suppliers_cache") or []
                await _tg_edit(chat_id, msg_id,
                    f"🏭 <b>Выбери поставщика</b> ({len(suppliers)}):",
                    _suppliers_kb(suppliers, page))
                return {"ok": True}

            # === Выбор поставщика ===
            if action.startswith("sup:"):
                supplier_id = action.split(":", 1)[1]
                suppliers = pending.get("suppliers_cache") or []
                supplier = next((s for s in suppliers if (s.get("id") or s.get("supplierId")) == supplier_id), None)
                pending["supplier_id"] = supplier_id
                pending["supplier_name"] = supplier.get("name") if supplier else "—"
                # Филиал уже выбран на предыдущем шаге (или это был единственный) — финализируем
                await _finalize_send(chat_id, msg_id, pending, force=False)
                return {"ok": True}

            # === Выбор филиала → показываем поставщиков этого филиала ===
            if action.startswith("org:"):
                org_id = action.split(":", 1)[1]
                pending["organization_id"] = org_id
                await _show_supplier_picker_for_org(chat_id, msg_id, pending, org_id)
                return {"ok": True}

            # === Подтверждение дубля ===
            if action == "dedup:yes":
                await _finalize_send(chat_id, msg_id, pending, force=True)
                return {"ok": True}
            if action == "dedup:no":
                _drop_pending(chat_id)
                await _tg_edit(chat_id, msg_id, "❌ <i>Отменено (дубль).</i>")
                return {"ok": True}

            # неизвестный callback — игнорируем
            return {"ok": True}

        # === MESSAGE ===
        message = data.get("message", {})
        if not message:
            return {"ok": True}

        chat_id = message.get("chat", {}).get("id")
        user_tg = message.get("from", {})
        telegram_id = user_tg.get("id", 0)
        username = user_tg.get("username") or user_tg.get("first_name", "user")

        # === WEB_APP_DATA (Mini App-редактор → бот) ===
        if message.get("web_app_data"):
            raw = message["web_app_data"].get("data", "")
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {}
            pid = payload.get("pending_id") or ""
            target_chat = _pending_by_id.get(pid)
            pending = _pending_invoices.get(target_chat) if target_chat else None
            if not pending:
                await _tg_send(chat_id, "⚠️ Сессия редактирования истекла. Пришли накладную заново.")
                return {"ok": True}
            # Обновляем поля result. WebApp шлёт обновлённые items/supplier/date/total/vat
            r = pending.setdefault("result", {})
            if "items" in payload:    r["items"] = payload["items"]
            if "supplier" in payload: r["supplier"] = payload["supplier"]
            if "date" in payload:     r["date"] = payload["date"]
            if "total_amount" in payload: r["total_amount"] = payload["total_amount"]
            if "vat_amount" in payload:   r["vat_amount"] = payload["vat_amount"]
            pending["state"] = "preview"
            # Перерисовываем превью (на том же сообщении если знаем message_id)
            if pending.get("message_id"):
                await _tg_edit(pending["chat_id"], pending["message_id"],
                               _format_invoice_v2(pending, "preview"),
                               _invoice_kb(pending["pending_id"]))
            else:
                new_id = await _tg_send(pending["chat_id"],
                                        _format_invoice_v2(pending, "preview"),
                                        _invoice_kb(pending["pending_id"]))
                pending["message_id"] = new_id
            return {"ok": True}

        # === DOCUMENT (image как файл) ===
        doc = message.get("document")
        if doc and (doc.get("mime_type") or "").startswith("image/"):
            file_id = doc["file_id"]
            file_data = await _tg_download_file(file_id)
            if not file_data:
                await _tg_send(chat_id, "❌ Не удалось скачать файл.")
                return {"ok": True}
            image_bytes, mime = file_data
            await _recognize_invoice_and_create_pending(chat_id, telegram_id, username, file_id, image_bytes, mime)
            return {"ok": True}

        # === DOCUMENT (не-image — PDF и пр.) ===
        if doc:
            await _tg_send(chat_id, "📎 Я принимаю только фото/картинки накладных (jpg/png/heic). PDF и другие форматы пока не поддерживаются.")
            return {"ok": True}

        # === PHOTO (сжатое) — принимаем самый большой размер ===
        if message.get("photo"):
            photo_sizes = message["photo"]
            biggest = photo_sizes[-1]
            file_id = biggest["file_id"]
            file_data = await _tg_download_file(file_id)
            if not file_data:
                await _tg_send(chat_id, "❌ Не удалось скачать фото.")
                return {"ok": True}
            image_bytes, mime = file_data
            if not mime:
                mime = "image/jpeg"
            await _recognize_invoice_and_create_pending(chat_id, telegram_id, username, file_id, image_bytes, mime)
            return {"ok": True}

        # === TEXT ===
        text = message.get("text") or ""
        if text == "/start":
            await _tg_send(chat_id,
                "👋 <b>Привет! Я бот ресторанной аналитики + распознавание накладных.</b>\n\n"
                "📊 Открой Mini App (кнопка меню слева внизу) — увидишь выручку, средний чек, расходы и лояльность гостей по своим филиалам.\n\n"
                "📎 Пришли мне накладную — фото, файлом или просто текстом — я её распознаю, ты подтвердишь, я отправлю в iiko.\n\n"
                "🔑 <b>Первый раз?</b> Открой Mini App → введи API-логин iiko (или URL сервера + пароль для самохостед iikoWeb).\n\n"
                "⚠️ <i>Распознавание делает ИИ — он может ошибаться, всегда проверяй перед отправкой.</i>")
            return {"ok": True}
        if text.startswith("/"):
            return {"ok": True}
        if text:
            # Короткие сообщения (приветствия и т.п.) — не пытаемся распознать
            if len(text.strip()) < 20:
                await _tg_send(chat_id,
                    "📎 Пришли накладную — фото, файлом или текстом (минимум 20 символов с позициями и ценами).")
                return {"ok": True}

            status_msg_id = await _tg_send(chat_id, "🔍 Распознаю накладную из текста...")
            result = await analyze_invoice_text(text)
            if "error" in result or not (result.get("items") or []):
                err = result.get("error") if "error" in result else "не нашёл позиций в тексте"
                await _tg_edit(chat_id, status_msg_id,
                    f"⚠️ Не получилось распознать накладную из текста: {err}.\n\n"
                    f"Попробуй прислать фото или файл — это надёжнее.")
                return {"ok": True}

            # Создаём pending как для фото
            pid = _pending_id()
            pending = {
                "pending_id": pid,
                "telegram_id": telegram_id,
                "username": username,
                "chat_id": chat_id,
                "message_id": status_msg_id,
                "state": "preview",
                "images": [],
                "result": result,
                "supplier_id": None,
                "organization_id": None,
                "created_at": datetime.now().isoformat(),
            }
            _pending_invoices[chat_id] = pending
            _pending_by_id[pid] = chat_id
            await _tg_edit(chat_id, status_msg_id,
                           _format_invoice_v2(pending, "preview"),
                           _invoice_kb(pending["pending_id"]))
            return {"ok": True}

    except Exception as e:
        logger.warning(f"[webhook] {e}")

    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
    
