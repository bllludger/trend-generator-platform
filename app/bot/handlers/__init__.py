"""Bot handler modules — ordered list of all routers.

IMPORTANT: The order in all_routers determines handler matching priority.
fallback_router MUST be last (it contains the catch-all unknown_message handler).
"""
from app.bot.handlers.start import start_router
from app.bot.handlers.commands import commands_router
from app.bot.handlers.profile import profile_router
from app.bot.handlers.photo_upload import photo_upload_router
from app.bot.handlers.themes import themes_router
from app.bot.handlers.generation import generation_router
from app.bot.handlers.copy_style import copy_style_router
from app.bot.handlers.merge import merge_router
from app.bot.handlers.payments import payments_router
from app.bot.handlers.bank_transfer import bank_transfer_router
from app.bot.handlers.trial import trial_router
from app.bot.handlers.results import results_router
from app.bot.handlers.rescue import rescue_router
from app.bot.handlers.favorites import favorites_router
from app.bot.handlers.session import session_router
from app.bot.handlers.fallback import fallback_router

all_routers = [
    start_router,
    commands_router,
    profile_router,
    photo_upload_router,
    themes_router,
    generation_router,
    copy_style_router,
    merge_router,
    payments_router,
    bank_transfer_router,
    trial_router,
    results_router,
    rescue_router,
    favorites_router,
    session_router,
    fallback_router,  # MUST be last — contains catch-all handler
]
