# Preview Rescue Flow — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Реализовать rescue-flow после показа превью: кнопка «Все 3 не подходят», один бесплатный reroll сета, экраны причин отказа и переходы (другое фото / другой тренд).

**Architecture:** Клавиатура первого/второго круга формируется в воркере `generate_take` по флагу `take.is_reroll`. В боте — новые callback-хендлеры для rescue:*; при «Хочу еще варианты» создаётся новый Take с `is_reroll=True` и теми же trend_id/session_id/input; `use_take` для reroll не вызывается. Экраны C1, E, F, G, H, I — ответы с текстом и inline-кнопками.

**Tech Stack:** aiogram FSM, Celery, SQLAlchemy, существующие Take/Session/Favorite сервисы.

---

## Task 1: Reroll не тратит квоту и клавиатура по раунду в generate_take

**Files:**
- Modify: `app/workers/tasks/generate_take.py` (use_take и блок с keyboard)

**Step 1:** В `generate_take.py` после `take_svc.set_status(...)` и перед `if take.session_id:` найти блок:
```python
if take.session_id:
    session = session_svc.get_session(take.session_id)
    if session:
        session_svc.use_take(session)
```
Заменить на: вызывать `use_take(session)` только если `not getattr(take, 'is_reroll', False)`.

**Step 2:** В том же файле, блок с `buttons_row` и `keyboard` (после send_media_group): ввести переменную `is_reroll = getattr(take, 'is_reroll', False)`. Для round 1 (`not is_reroll`): текст «Выберите вариант или обновите все 3:», в inline_keyboard добавить строку с одной кнопкой `{"text": "🔁 Все 3 не подходят", "callback_data": f"rescue:reject_set:{take_id}"}`. Для round 2 (`is_reroll`): текст «Выберите вариант:», добавить ту же кнопку «🔁 Все 3 не подходят». В обоих случаях сохранить кнопки «📸 Ещё фото» и «📋 Избранное» (или «📋 Избранное» только во втором круге по ТЗ — во втором круге ТЗ: «⭐ A | ⭐ B | ⭐ C, 📋 Избранное»; значит во втором круге можно не показывать «Ещё фото» или оставить для консистентности; по ТЗ для C2 только A, B, C, Избранное — без «Ещё фото»). Уточнение: для C2 в ТЗ только «⭐ A | ⭐ B | ⭐ C» и «📋 Избранное», но также при отказе от всего сета во 2-м круге показываем E — значит кнопка «Все 3 не подходят» на C2 нужна. Итого: round 2 клавиатура: A, B, C; «🔁 Все 3 не подходят»; «📋 Избранное». Без «Ещё фото» на round 2.

**Step 3:** Запустить воркер и один раз прогнать генерацию (ручная проверка). Commit: `feat(rescue): reroll does not consume quota; round-specific preview keyboard`.

---

## Task 2: SessionService — проверка наличия reroll по (session_id, trend_id)

**Files:**
- Modify: `app/services/sessions/service.py`

**Step 1:** Добавить метод:
```python
def has_reroll_for_trend(self, session_id: str, trend_id: str) -> bool:
    """True если в сессии уже есть take с is_reroll=True для данного trend_id."""
    from app.models.take import Take
    return (
        self.db.query(Take.id)
        .filter(
            Take.session_id == session_id,
            Take.trend_id == trend_id,
            Take.is_reroll == True,
        )
        .limit(1)
        .first()
        is not None
    )
```

**Step 2:** Commit: `feat(sessions): has_reroll_for_trend helper`.

---

## Task 3: TakeService — создание Take с is_reroll

**Files:**
- Modify: `app/services/takes/service.py`

**Step 1:** В `create_take` после `self.db.add(take)` и `self.db.flush()` не устанавливается `is_reroll`. Модель Take уже имеет поле `is_reroll`. Добавить в `create_take` опциональный аргумент `is_reroll: bool = False` и присваивать `take.is_reroll = is_reroll` перед add/flush (или после flush). Commit: `feat(takes): create_take accepts is_reroll`.

---

## Task 4: Хендлер «Все 3 не подходят» (rescue:reject_set) и экраны C1 / E

**Files:**
- Modify: `app/bot/main.py`

**Step 1:** Зарегистрировать callback `F.data.startswith("rescue:reject_set:")`. Разобрать `take_id`. Загрузить Take, проверить существование и что take принадлежит пользователю (user_id по сессии или take.user_id). Если `take.is_reroll` — показать экран E: текст «Не нашли удачный вариант?», кнопки «🙂 Лицо не похоже» (`rescue:reason:face:{take_id}`), «📷 Попробовать другое фото» (`rescue:other_photo:{take_id}`), «🎭 Попробовать другой тренд» (`rescue:other_trend:{take_id}`). Если не is_reroll — показать C1: текст «Что именно не так?», кнопки «🙂 Лицо не похоже», «🎭 Не зашел образ», «🔁 Хочу еще варианты» с callback_data `rescue:reason:face:{take_id}`, `rescue:reason:style:{take_id}`, `rescue:reason:more:{take_id}`. Ответить на callback, отредактировать или отправить новое сообщение с клавиатурой.

**Step 2:** Commit: `feat(rescue): reject_set handler and C1/E screens`.

---

## Task 5: Хендлер «Хочу еще варианты» — создание reroll Take и постановка в очередь

**Files:**
- Modify: `app/bot/main.py`

**Step 1:** Callback `F.data.startswith("rescue:reason:more:")` → take_id. Проверить: сессия и тренд есть; вызвать `session_svc.has_reroll_for_trend(session.id, take.trend_id)` — если True, не создавать второй reroll, показать экран E (тот же текст и кнопки, что в Task 4). Если False: создать новый Take через take_svc.create_take(..., session_id=take.session_id, trend_id=take.trend_id, input_local_paths=take.input_local_paths, input_file_ids=take.input_file_ids, image_size=take.image_size, is_reroll=True). Присвоить take.is_reroll = True если create_take не принимает is_reroll (если принял — не дублировать). attach_take_to_session(new_take, session). Поставить задачу generate_take с new_take.id и status_chat_id/status_message_id (в rescue контексте можно отправить сообщение «⏳ Генерируем новый набор из 3 вариантов…» и передать chat_id и message_id). Ответить callback.answer.

**Step 2:** Убедиться, что Take создаётся с теми же input_local_paths (файлы ещё должны существовать). Commit: `feat(rescue): reason more_variants creates reroll take`.

---

## Task 6: Экраны F, G и кнопка «Загрузить другое фото» (rescue:reason:face, rescue:photo_tip)

**Files:**
- Modify: `app/bot/main.py`

**Step 1:** `rescue:reason:face:{take_id}`: отправить сообщение с текстом «Иногда результат зависит от исходного фото. Лучше всего работают фото, где лицо видно четко, без сильных теней и перекрытий.» и кнопками «📷 Загрузить другое фото» (`rescue:other_photo:{take_id}`), «💡 Какое фото подойдет» (`rescue:photo_tip:{take_id}`).

**Step 2:** `rescue:photo_tip:{take_id}` (или без take_id для G): отправить текст-памятку «Лучше всего работают фото, где: лицо видно прямо или почти прямо; нет сильных теней; глаза и контуры лица не закрыты; фото четкое» и кнопку «📷 Загрузить другое фото» с тем же callback_data `rescue:other_photo:{take_id}`.

**Step 3:** Commit: `feat(rescue): face reason F and photo tip G screens`.

---

## Task 7: Состояние rescue_waiting_photo и хендлер «Загрузить другое фото»

**Files:**
- Modify: `app/bot/main.py` (BotStates, callback rescue:other_photo, handler фото в rescue state)

**Step 1:** В BotStates добавить `rescue_waiting_photo = State()`.

**Step 2:** В callback `rescue:other_photo:{take_id}`: загрузить take, session, trend_id; проверить лимит «1 замена на тренд» — в state сохранить ключ `rescue_photo_trend_id` / `rescue_session_id` / `rescue_take_id` (контекст для возврата). Установить state = rescue_waiting_photo, data = rescue_trend_id, rescue_session_id, rescue_take_id (или rescue_from_take_id). Отправить сообщение «📷 Отправьте новое фото для этого тренда.» Ответить callback.answer.

**Step 3:** Добавить хендлер сообщения с фото в состоянии `BotStates.rescue_waiting_photo`: скачать файл, сохранить во временный путь (аналогично основному флоу), создать новый Take (trend_id/session_id из state; input_local_paths = [новый путь]; is_reroll=False — это замена фото, не reroll сета). Не вызывать use_take при создании Take для rescue photo replacement (или вызывать — по дизайну «1 замена» не тратим квоту: тогда в create_take не увеличивать takes_used; проще всего — создаём take, ставим generate_take; в generate_take для «rescue photo» не вызывать use_take. Чтобы не плодить флаги, можно считать: rescue photo replacement = новый take с теми же trend_id/session_id, но другими input_local_paths; квоту тратим (один раз пользователь получает смену фото, но лимит сессии всё равно ограничивает). По дизайну «Смена исходного фото внутри одного тренда должна быть ограничена» — ограничиваем числом раз (1), а не квотой. Решение: при первой замене фото для тренда не вызывать use_take (аналогично reroll). Для этого в Take можно ввести флаг is_rescue_photo_replace или проверять по какому-то правилу. Проще: хранить в Session или в FSM «rescue_photo_used_for_trends»; при создании Take после «загрузить другое фото» проверять — если для этого trend_id замена ещё не использовалась, не вызывать use_take в generate_take. Тогда нужен флаг на Take: is_rescue_photo_replace. Добавить в модель Take поле is_rescue_photo_replace (Boolean, default False). При создании Take из rescue:other_photo выставлять True. В generate_take: use_take только если not take.is_reroll and not getattr(take, 'is_rescue_photo_replace', False). Тогда лимит «1 замена»: при нажатии «Загрузить другое фото» проверять — если для этого тренда уже был take с is_rescue_photo_replace в этой сессии, не переходить в rescue_waiting_photo, а показать «Замена фото для этого тренда уже использована» или экран I. Реализация: в Task 7 при rescue:other_photo проверять has_rescue_photo_for_trend(session_id, trend_id) — метод в SessionService: есть ли Take с session_id, trend_id, is_rescue_photo_replace=True. Если да — показать экран I. Иначе — state rescue_waiting_photo. После получения фото — create_take(..., is_rescue_photo_replace=True), attach, send_task generate_take. В generate_take не вызывать use_take если is_rescue_photo_replace. Миграция: добавить колонку is_rescue_photo_replace BOOLEAN DEFAULT FALSE в takes.

**Step 4:** Добавить миграцию `migrations/059_take_rescue_photo_replace.sql`: `ALTER TABLE takes ADD COLUMN IF NOT EXISTS is_rescue_photo_replace BOOLEAN NOT NULL DEFAULT FALSE;`. В модели Take: `is_rescue_photo_replace = Column(Boolean, nullable=False, default=False)`. В TakeService.create_take добавить параметр is_rescue_photo_replace=False и присваивать take.is_rescue_photo_replace = is_rescue_photo_replace. В generate_take при use_take: вызывать только если not take.is_reroll and not getattr(take, 'is_rescue_photo_replace', False). SessionService: has_rescue_photo_for_trend(session_id, trend_id) — существует ли take с session_id, trend_id, is_rescue_photo_replace=True.

**Step 5:** Commit: `feat(rescue): rescue_waiting_photo and other_photo flow with is_rescue_photo_replace`.

---

## Task 8: «Попробовать другой тренд» и экран I

**Files:**
- Modify: `app/bot/main.py`

**Step 1:** Callback `rescue:other_trend:{take_id}`: показать экран I — текст «Можно попробовать другой тренд.» Кнопки: «🎭 Попробовать другой тренд» (переход к выбору трендов — nav:trends или вернуть в состояние выбора тренда с текущей сессией/фото), «💎 Открыть лучший вариант» (open_favorites). Для перехода к трендам: отправить сообщение с клавиатурой трендов (темы уже выбраны — из take/session можно взять theme_id; показать список трендов как после выбора темы) или callback_data `nav:trends` открывает экран выбора трендов. Проверить существующие обработчики nav:trends — куда ведут. Если nav:trends ведёт в меню, сделать отдельный callback `rescue:pick_trend:{take_id}` который устанавливает state waiting_for_trend и показывает клавиатуру трендов (нужны theme_id и список трендов из контекста take). Упрощение: отправить текст «Можно попробовать другой тренд.» и кнопки «🎭 К трендам» (callback_data `nav:themes` или восстановить контекст и показать тренды), «💎 Открыть лучший вариант» (open_favorites). Пользователь нажимает «К трендам» — переходим к выбору темы/тренда (state + данные из сессии). Реализация: rescue:other_trend — отправить экран I; кнопка «🎭 Попробовать другой тренд» с callback_data например `nav:menu` или вернуть к формату «Создать фото» (ожидание фото уже есть в сессии — тогда «Ещё фото» уже даёт загрузку). По ТЗ экран I: «Можно попробовать другой тренд.» Кнопки: «🎭 Попробовать другой тренд», «💎 Открыть лучший вариант». Второй — open_favorites. Первый — перейти к списку трендов. Самый простой способ: отправить ссылку на меню «🔥 Создать фото» и пользователь начинает заново; или показать inline-клавиатуру с темами. Выбрать: показываем те же темы, что при создании снимка (themes_keyboard), и при выборе темы — тренды (trends_keyboard). Для этого в state положить rescue_return_to_trends = True и theme_id при выборе темы перейти к трендам. Или один callback `nav:themes` который показывает темы — тогда пользователь идёт по обычному пути тема → тренд → формат. Показать сообщение с reply или inline «Выберите тематику» и themes_keyboard. Commit: `feat(rescue): other_trend screen I and nav to themes/trends`.

---

## Task 9: Унификация экрана после выбора A/B/C (B и D) — «Отлично. Можно открыть в HD»

**Files:**
- Modify: `app/bot/main.py` (choose_variant и при необходимости add_variant_to_favorites)

**Step 1:** В choose_variant после добавления в избранное и callback.answer: вместо текущего текста «{trend_label} · Вариант {variant} в избранном» и кнопок «Ещё фото»/«В избранное» + «Оцените результат» — отправить одно сообщение: текст «Отлично. Можно открыть этот вариант в HD без watermark.» и одну кнопку «💎 Открыть в HD» (callback_data `deliver_hd_one:{fav_id}`). Если бесплатный пакет — сначала показать paywall (как сейчас), после него или вместо второго сообщения — тот же текст «Отлично. Можно открыть…» и кнопку «💎 Открыть в HD» (после покупки). Убрать отправку «Оцените результат» с _feedback_keyboard из choose_variant сразу после выбора (по ТЗ не спрашивать «оставить?» и не перегружать). Оценку можно оставить в отдельном сообщении после «Открыть в HD» или не показывать до перехода в избранное. По ТЗ: «Не нужно задавать дополнительный вопрос» — убираем feedback keyboard из этого шага. Итого: после A/B/C отправить только «Отлично. Можно открыть этот вариант в HD без watermark.» и «💎 Открыть в HD». Для free — сначала paywall, затем то же. Commit: `feat(rescue): post-choose message B/D unified (Open in HD only)`.

---

## Task 10: Обработка «Не зашел образ» (rescue:reason:style)

**Files:**
- Modify: `app/bot/main.py`

**Step 1:** Callback `rescue:reason:style:{take_id}`: вести на тот же экран I или на экран с выбором «Попробовать другой тренд» / «Загрузить другое фото» (как в E). По ТЗ для C1 при «Не зашел образ» отдельный путь не расписан — направить на экран с кнопками как E: «🙂 Лицо не похоже», «📷 Попробовать другое фото», «🎭 Попробовать другой тренд». Или сразу экран I. Выбрать: показываем экран I («Можно попробовать другой тренд» + «🎭 Попробовать другой тренд», «💎 Открыть лучший вариант»). Commit: `feat(rescue): reason style leads to screen I`.

---

## Task 11: Тексты из defaults или константы

**Files:**
- Modify: `app/services/telegram_messages/defaults.py` (опционально) или оставить литералы в main.py

**Step 1:** Вынести тексты rescue-экранов в константы в main.py (RESCUE_MSG_*) или в defaults. Для первой итерации — литералы в хендлерах допустимы. Commit по необходимости.

---

## Task 12: Аналитика (опционально)

**Files:**
- Modify: `app/bot/main.py`, возможно ProductAnalyticsService

**Step 1:** В хендлерах rescue вызывать ProductAnalyticsService.track с событиями rescue_reject_set, rescue_reason_face/style/more, rescue_reroll_requested, rescue_photo_requested и т.д. Commit: `feat(rescue): analytics events`.

---

## Execution

После выполнения плана: ручное тестирование — первый круг превью → «Все 3 не подходят» → C1 → «Хочу еще варианты» → второй сет → выбор A/B/C → «Открыть в HD»; и сценарий второго круга «Все 3 не подходят» → E → Лицо не похоже → F → Загрузить другое фото → отправка фото → новый сет.
