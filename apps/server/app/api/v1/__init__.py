from fastapi import APIRouter

from app.api.v1 import (
    audit,
    auth,
    customers,
    employees,
    health,
    inventory,
    payments,
    products,
    purchases,
    reports,
    sales,
    scales,
    settings,
    shifts,
    sync,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(products.router)
api_router.include_router(payments.router)
api_router.include_router(inventory.router)
api_router.include_router(customers.router)
api_router.include_router(sales.router)
api_router.include_router(scales.router)
api_router.include_router(purchases.router)
api_router.include_router(shifts.router)
api_router.include_router(reports.router)
api_router.include_router(settings.router)
api_router.include_router(employees.router)
api_router.include_router(audit.router)
api_router.include_router(sync.router)
