"""FSM States for the bot (2026 flow: photo -> trend/idea -> format -> generate)."""

from aiogram.fsm.state import State, StatesGroup


class BotStates(StatesGroup):
    waiting_for_audience = State()        # Step 0: выбор ЦА (Женщина/Мужчина/Пара)
    waiting_for_photo = State()           # Step 1: upload photo
    waiting_for_trend = State()           # Step 2: select trend or "Своя идея"
    waiting_for_prompt = State()          # Step 2b: if "Своя идея" — user's text prompt
    waiting_for_format = State()          # Step 3: select aspect ratio
    # "Сделать такую же" flow
    waiting_for_reference_photo = State()  # Шаг 1: референс для копирования
    waiting_for_self_photo = State()       # Шаг 2: своё фото (identity)
    # Оплата переводом на карту
    bank_transfer_waiting_receipt = State()  # Ждём чек (скриншот/фото)
    # Session-based flow (MVP)
    session_active = State()
    viewing_take_result = State()
    viewing_favorites = State()
    rescue_waiting_photo = State()
    # «Соединить фото» flow
    merge_waiting_count = State()          # Шаг 1: выбор 2 или 3 человек
    merge_waiting_photo_1 = State()        # Шаг 2: фото 1
    merge_waiting_photo_2 = State()        # Шаг 3: фото 2
    merge_waiting_photo_3 = State()        # Шаг 4: фото 3 (если выбрано 3)
