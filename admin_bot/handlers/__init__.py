"""គ្រប់ Router របស់ Panel — លំដាប់ចុះបញ្ជីមានសារៈសំខាន់ (handler ដំបូងឈ្នះ)។"""
from __future__ import annotations

from admin_bot.handlers import (
    accounts,
    analytics,
    categories,
    customers,
    orders,
    products,
    prompt,
    qrcodes,
    settings,
    start,
)

# start មុនគេ (menu:main + noop), បន្ទាប់មកផ្នែកនីមួយៗ
all_routers = [
    start.router,
    products.router,
    categories.router,
    qrcodes.router,
    prompt.router,
    orders.router,
    customers.router,
    accounts.router,
    analytics.router,
    settings.router,
]

__all__ = ["all_routers"]
