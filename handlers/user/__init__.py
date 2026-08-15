from aiogram import Router

from handlers.user import start, shop, wallet, account, support


def get_user_router() -> Router:
    router = Router(name="user")
    router.include_router(start.router)
    router.include_router(shop.router)
    router.include_router(wallet.router)
    router.include_router(account.router)
    router.include_router(support.router)
    return router
