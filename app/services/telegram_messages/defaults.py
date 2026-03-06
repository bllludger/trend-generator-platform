DEFAULT_TELEGRAM_TEMPLATES: dict[str, dict[str, str]] = {
    "start.welcome_text": {
        "value": (
            "👋 Nano Banana — ИИ фотостудия\n\n"
            "Это просто фото.\n"
            "Но оно может стать сценой.\n\n"
            "Загрузи кадр — выбери стиль —\n"
            "получи результат как после съёмки.\n\n"
            "👇 Попробовать бесплатно"
        ),
        "category": "start",
        "description": "Текст приветствия (/start).",
    },
    "start.deeplink_trend": {
        "value": "Отправьте фото — применим тренд «{name}»",
        "category": "start",
        "description": "Сообщение при входе по deep link (выбран тренд, ждём фото).",
    },
    "help.main_text": {
        "value": (
            "🎨 *NanoBanan — ИИ фотостудия*\n\n"
            "*Как использовать:*\n"
            "1. «🔥 Создать фото» — отправьте фото, выберите тренд, формат — результат!\n"
            "2. «🔄 Сделать такую же» — загрузите образец, затем своё фото — копия стиля 1:1\n"
            "3. «🛒 Купить генерации» — пакеты фото за Telegram Stars (без watermark)\n"
            "4. «👤 Мой профиль» — баланс и статистика\n\n"
            "*Как работает оплата:*\n"
            "— 3 бесплатных превью (с watermark)\n"
            "— Купите пакет за Stars — получайте фото в полном качестве\n"
            "— Можно разблокировать отдельное фото\n\n"
            "*Команды:*\n"
            "/start — Начать\n"
            "/help — Помощь\n"
            "/cancel — Отменить выбор\n"
            "/terms — Условия использования\n"
            "/paysupport — Поддержка по платежам"
        ),
        "category": "help",
        "description": "Текст команды /help.",
    },
    "flow.request_photo": {
        "value": (
            "📸 Загрузи своё фото\n"
            "и получи съёмку как из дорогой студии — за 30 секунд\n\n"
            "✨ Превью бесплатно\n\n"
            "Чтобы получилось идеально:\n"
            "— лицо крупно в кадре\n"
            "— без очков\n"
            "— фото чёткое\n\n"
            "👇 Попробовать"
        ),
        "category": "flow",
        "description": "Запрос фото перед созданием.",
    },
    "flow.reference_note": {
        "value": "📎 Фото пользователя закреплены как Image B (REFERENCE) и будут участвовать в генерации.",
        "category": "flow",
        "description": "Нотификация о закрепленном референсе.",
    },
    "flow.photo_accepted_choose_theme": {
        "value": "✅ Фото принято\n\nМы используем его, чтобы сохранить вашу внешность и стиль.\nВыберите тематику или придумайте свой образ 👇",
        "category": "flow",
        "description": "После загрузки фото: приглашение выбрать тематику.",
    },
    "flow.theme_page_caption": {
        "value": "Тематика: {theme_name} — стр. {current} из {total}",
        "category": "flow",
        "description": "Заголовок страницы трендов внутри тематики (пагинация).",
    },
    "menu.btn.create_photo": {"value": "🔥 Создать фото", "category": "buttons", "description": "Главная кнопка создания."},
    "menu.btn.copy_style": {"value": "🔄 Сделать такую же", "category": "buttons", "description": "Главная кнопка copy style."},
    "menu.btn.merge_photos": {"value": "🧩 Соединить фото", "category": "buttons", "description": "Кнопка сервиса склейки фото."},
    "menu.btn.profile": {"value": "👤 Мой профиль", "category": "buttons", "description": "Главная кнопка профиля."},
    "menu.btn.help": {"value": "❓ Помощь", "category": "buttons", "description": "Главная кнопка помощи."},
    "menu.btn.shop": {"value": "🛒 Купить генерации", "category": "buttons", "description": "Главная кнопка магазина."},
    "menu.btn.custom_idea": {"value": "💡 Своя идея", "category": "buttons", "description": "Кнопка выбора своей идеи."},
    "copy.btn.one_photo": {"value": "1 фотография", "category": "buttons", "description": "Copy-style: один портрет."},
    "copy.btn.two_photos": {"value": "2 фотографии", "category": "buttons", "description": "Copy-style: два портрета."},
    "format.btn.1_1": {"value": "1:1 Квадрат", "category": "buttons", "description": "Формат 1:1."},
    "format.btn.16_9": {"value": "16:9 Широкий", "category": "buttons", "description": "Формат 16:9."},
    "format.btn.4_3": {"value": "4:3 Классика 🔥", "category": "buttons", "description": "Формат 4:3."},
    "format.btn.9_16": {"value": "9:16 Портрет", "category": "buttons", "description": "Формат 9:16."},
    "format.btn.3_4": {"value": "3:4 Вертикальный", "category": "buttons", "description": "Формат 3:4."},
    "nav.btn.back_to_trends": {"value": "⬅️ Назад к трендам", "category": "buttons", "description": "Навигация назад к списку трендов (с экрана формата)."},
    "nav.btn.back_to_themes": {"value": "⬅️ Назад к тематикам", "category": "buttons", "description": "Навигация назад к списку тематик (из экрана трендов темы)."},
    "nav.btn.menu": {"value": "📋 В меню", "category": "buttons", "description": "Навигация в главное меню."},
    "profile.btn.top_up": {"value": "🛒 Пополнить баланс", "category": "buttons", "description": "Кнопка пополнения баланса."},
    "progress.preparing": {"value": "⏳ Подготавливаем кадр", "category": "progress", "description": "Этап прогресса 1."},
    "progress.generating": {"value": "🎨 Генерируем стиль", "category": "progress", "description": "Этап прогресса 2."},
    "progress.finalizing": {"value": "✨ Финализируем результат", "category": "progress", "description": "Этап прогресса 3."},
    "progress.take_step_1": {"value": "⏳ Генерация снимка [🟩⬜⬜] 1/3", "category": "progress", "description": "Прогресс снимка: шаг 1/3 (полоска из 3 сегментов)."},
    "progress.take_step_2": {"value": "⏳ Генерация снимка [🟩🟩⬜] 2/3", "category": "progress", "description": "Прогресс снимка: шаг 2/3."},
    "progress.take_step_3": {"value": "⏳ Генерация снимка [🟩🟩🟩] 3/3", "category": "progress", "description": "Прогресс снимка: шаг 3/3."},
    "progress.take_final": {"value": "⏳ Генерация снимка [🟩🟩🟩] Почти готово…", "category": "progress", "description": "Прогресс снимка: последний шаг перед отправкой фото."},
    "progress.take_parallel": {"value": "⏳ Генерация снимка [⬜⬜⬜] Генерируем 3 варианта… 0/3", "category": "progress", "description": "Начальное состояние прогресс-бара при параллельной генерации (далее обновляется воркером: 1/3, 2/3, 3/3)."},
    "progress.suffix": {
        "value": "\n\nОбычно это занимает до 30 секунд.",
        "category": "progress",
        "description": "Общий хвост текста прогресса.",
    },
    "errors.common_generation": {
        "value": (
            "Упс, что-то пошло не так.\n\n"
            "Почему это могло случиться:\n"
            "1) Запрос попал под ограничения модели (контент/safety).\n"
            "2) Фото или формулировка запроса оказались слишком сложными для текущего шага.\n"
            "3) Временный сбой на стороне провайдера генерации."
        ),
        "category": "errors",
        "description": "Универсальная ошибка генерации (карточка с кнопками).",
    },
    "errors.btn.retry": {"value": "🔄 Попробовать ещё раз", "category": "buttons", "description": "Кнопка повтора после ошибки."},
    "errors.btn.change_trend": {
        "value": "🎨 Выбрать другой тренд",
        "category": "buttons",
        "description": "Кнопка выбора другого тренда.",
    },
    "errors.btn.replace_photo": {
        "value": "🖼️ Заменить исходное фото",
        "category": "buttons",
        "description": "Кнопка замены исходного фото.",
    },
    # --- Мой профиль (личный кабинет) ---
    "profile.title": {
        "value": "👤 *Мой профиль*",
        "category": "profile",
        "description": "Заголовок блока «Мой профиль».",
    },
    "profile.body": {
        "value": (
            "🆓 *Бесплатные превью:* {free_left} из {free_limit}\n"
            "🔄 *«Сделать такую же»:* {copy_left} из {copy_limit}\n"
            "💰 *Баланс генераций:* {token_balance}\n"
            "📊 *Всего куплено:* {total_purchased}\n\n"
            "Бесплатные генерации дают превью с watermark.\n"
            "Купите пакет — получайте фото в полном качестве!"
        ),
        "category": "profile",
        "description": "Текст профиля (переменные: free_left, free_limit, copy_left, copy_limit, token_balance, total_purchased).",
    },
    # --- Магазин и оплата ---
    "shop.unavailable": {
        "value": "Магазин временно недоступен.",
        "category": "payments",
        "description": "Когда нет пакетов в магазине.",
    },
    "shop.load_error": {
        "value": "Ошибка загрузки магазина.",
        "category": "payments",
        "description": "Ошибка при открытии магазина.",
    },
    "shop.header": {
        "value": "🛒 *Магазин генераций*\n\nКупите пакет — получайте фото в полном качестве, без watermark!\n\n",
        "category": "payments",
        "description": "Заголовок экрана магазина.",
    },
    "shop.how_buy_stars": {
        "value": (
            "📘 *Как купить Telegram Stars*\n\n"
            "1. Откройте любой тариф в боте и нажмите на него.\n"
            "2. В открывшемся окне оплаты выберите способ — *Stars* (звёзды).\n"
            "3. Если Stars нет в списке — пополните баланс Stars в настройках Telegram: "
            "Настройки → Telegram Stars (или через оплату в другом боте).\n"
            "4. Подтвердите оплату — генерации зачислятся автоматически.\n\n"
            "Не получается оплатить Stars? Можно оплатить *переводом на карту* — нажмите кнопку ниже."
        ),
        "category": "payments",
        "description": "Инструкция «Как купить Stars» в экране выбора тарифа.",
    },
    "pay.pack_unavailable": {
        "value": "Пакет недоступен.",
        "category": "payments",
        "description": "Пакет отключён или не найден при нажатии.",
    },
    "pay.create_error": {
        "value": "Ошибка при создании платежа.",
        "category": "payments",
        "description": "Не удалось создать invoice.",
    },
    "pay.user_not_found": {
        "value": "Пользователь не найден.",
        "category": "payments",
        "description": "Unlock: пользователь не в БД.",
    },
    "pay.photo_not_found": {
        "value": "Фото не найдено.",
        "category": "payments",
        "description": "Unlock: job не найден.",
    },
    "pay.already_full": {
        "value": "Это фото уже в полном качестве.",
        "category": "payments",
        "description": "Unlock: фото уже без watermark.",
    },
    "unlock.invoice_title": {
        "value": "🔓 Разблокировать фото",
        "category": "payments",
        "description": "Заголовок invoice разблокировки.",
    },
    "unlock.invoice_description": {
        "value": "Получить фото без watermark в полном качестве ({cost}⭐)",
        "category": "payments",
        "description": "Описание invoice (переменная: cost).",
    },
    "unlock.invoice_label": {
        "value": "Разблокировка",
        "category": "payments",
        "description": "Label в invoice.",
    },
    "payment.unknown_order": {
        "value": "Не удалось определить заказ по платежу. Напишите в /paysupport и укажите время платежа — разберём вручную.",
        "category": "payments",
        "description": "Неверный payload успешного платежа.",
    },
    "payment.unlock_send_error": {
        "value": "Оплата прошла, но не удалось отправить фото. Напишите в /paysupport с описанием — мы вышлем кадр вручную.",
        "category": "payments",
        "description": "Unlock оплачен, но отправить файл не удалось.",
    },
    "payment.pack_not_found": {
        "value": "Ошибка: пакет не найден. Обратитесь в /paysupport.",
        "category": "payments",
        "description": "После оплаты пакет не найден в БД.",
    },
    "payment.pack_success": {
        "value": "✅ Пакет *{emoji} {name}* активирован!\n\nНачислено: *{tokens}* генераций\nВаш баланс: *{balance}* генераций\n\nТеперь ваши фото будут без watermark!",
        "category": "payments",
        "description": "После успешной покупки пакета (emoji, name, tokens, balance).",
    },
    "payment.credit_error": {
        "value": "⚠️ Оплата получена, но произошла ошибка начисления.\nОбратитесь в /paysupport — мы решим вопрос.",
        "category": "payments",
        "description": "Платёж прошёл, credit_tokens вернул False.",
    },
    "payment.generic_error": {
        "value": "⚠️ Произошла ошибка при обработке платежа.\nОбратитесь в /paysupport.",
        "category": "payments",
        "description": "Исключение в successful_payment.",
    },
    "success.unlock_caption": {
        "value": "🔓 Фото разблокировано! Вот ваш кадр в полном качестве (без сжатия).",
        "category": "payments",
        "description": "Подпись к фото при отправке после unlock.",
    },
    "success.btn.menu": {"value": "📋 В меню", "category": "buttons", "description": "После успеха/ошибки: в меню."},
    "success.btn.more": {"value": "🔄 Сделать ещё", "category": "buttons", "description": "После успеха: сгенерировать ещё."},
    "success.btn.try_trend": {"value": "Попробовать этот тренд", "category": "buttons", "description": "Кнопка deep link на тот же тренд (результат генерации)."},
    "success.btn.channel": {"value": "Канал", "category": "buttons", "description": "Кнопка перехода в канал (если задан telegram_channel_url)."},
    # --- Команды: paysupport, terms ---
    "cmd.paysupport": {
        "value": (
            "💬 *Поддержка по платежам*\n\n"
            "Если у вас возникли проблемы с оплатой или начислением генераций:\n\n"
            "1. Убедитесь, что у вас достаточно Telegram Stars\n"
            "2. Проверьте баланс в «👤 Мой профиль»\n"
            "3. Напишите нам в чат поддержки\n\n"
            "Мы обработаем ваш запрос в кратчайшие сроки.\n\n"
            "⚠️ Telegram support не рассматривает вопросы по покупкам в ботах."
        ),
        "category": "commands",
        "description": "Текст команды /paysupport.",
    },
    "cmd.terms": {
        "value": (
            "📄 *Условия использования NanoBanan*\n\n"
            "1. Генерации приобретаются за Telegram Stars.\n"
            "2. Бесплатные генерации дают результат с watermark (превью).\n"
            "3. Оплаченные генерации дают полное качество без watermark.\n"
            "4. Возврат Stars возможен до использования генераций.\n"
            "5. Администрация вправе отказать в обслуживании при нарушении правил.\n"
            "6. Все сгенерированные изображения — результат работы ИИ.\n\n"
            "Используя бота, вы соглашаетесь с этими условиями."
        ),
        "category": "commands",
        "description": "Текст команды /terms.",
    },
    # --- Действия после генерации (успех/ошибка) ---
    "action.choose": {
        "value": "Выберите действие:",
        "category": "flow",
        "description": "После нажатия «В меню» после генерации.",
    },
    "action.create_again": {
        "value": "Чтобы создать изображение заново, нажмите «🔥 Создать фото» и выберите тренд.",
        "category": "flow",
        "description": "После «Сделать ещё» / retry.",
    },
    # --- Разные подсказки и алерты ---
    "flow.session_expired_copy": {
        "value": "Сессия истекла. Начните заново: «🔄 Сделать такую же».",
        "category": "flow",
        "description": "Истекла сессия в copy-flow.",
    },
    "flow.start_over": {"value": "Начните заново:", "category": "flow", "description": "Сброс и призыв начать заново."},
    "flow.choose_other_trend": {
        "value": "Выберите другой тренд для этого же фото:",
        "category": "flow",
        "description": "После ошибки: выбор другого тренда.",
    },
    "flow.only_images": {
        "value": "Поддерживаются только изображения: JPG, PNG, WEBP. Отправьте файл с фото.",
        "category": "flow",
        "description": "Неверный тип файла.",
    },
    "flow.save_photo_error": {
        "value": "Не удалось сохранить фото. Попробуйте ещё раз.",
        "category": "errors",
        "description": "Ошибка сохранения загруженного фото.",
    },
    "flow.save_file_error": {
        "value": "Не удалось сохранить файл. Попробуйте ещё раз.",
        "category": "errors",
        "description": "Ошибка сохранения загруженного файла.",
    },
    "flow.analyzing": {
        "value": "⏳ Анализирую дизайн...",
        "category": "flow",
        "description": "Сообщение во время анализа референса.",
    },
    "errors.no_trends": {
        "value": "Нет доступных трендов. Попробуйте позже.",
        "category": "errors",
        "description": "Список трендов пуст.",
    },
    "errors.no_trends_short": {
        "value": "Нет доступных трендов.",
        "category": "errors",
        "description": "Тренды недоступны (короткий alert).",
    },
    "errors.choose_new_photo": {
        "value": "Для этого сценария выберите новое фото.",
        "category": "errors",
        "description": "Copy-flow: нужен новый снимок.",
    },
    "errors.no_source_photo": {
        "value": "Нет исходного фото. Загрузите новое.",
        "category": "errors",
        "description": "Нет фото для повтора.",
    },
    "errors.upload_photo": {
        "value": "Ошибка при загрузке фото. Попробуйте ещё раз.",
        "category": "errors",
        "description": "Ошибка загрузки фото.",
    },
    "errors.upload_file": {
        "value": "Ошибка при загрузке файла. Попробуйте ещё раз.",
        "category": "errors",
        "description": "Ошибка загрузки файла.",
    },
    "errors.trend_unavailable": {
        "value": "Тренд недоступен",
        "category": "errors",
        "description": "Тренд отключён или не найден.",
    },
    "errors.try_later_short": {
        "value": "Ошибка. Попробуйте позже.",
        "category": "errors",
        "description": "Краткое сообщение об ошибке.",
    },
    "errors.try_again": {"value": "Ошибка. Попробуйте ещё раз.", "category": "errors", "description": "Повторить действие."},
    "errors.try_again_alert": {"value": "Ошибка. Попробуйте снова.", "category": "errors", "description": "Alert в callback."},
    "errors.session_expired_photo": {
        "value": "Сессия истекла. Отправьте фото заново.",
        "category": "errors",
        "description": "Истекла сессия при выборе тренда.",
    },
    "errors.send_photo_first": {"value": "Сначала отправьте фото.", "category": "errors", "description": "Callback: тренд без фото."},
    "errors.idea_min_length": {
        "value": "Опишите идею подробнее (минимум 3 символа).",
        "category": "flow",
        "description": "Своя идея: слишком короткий текст.",
    },
    "errors.idea_max_length": {
        "value": "Текст слишком длинный. Сократите до 2000 символов.",
        "category": "flow",
        "description": "Своя идея: превышен лимит.",
    },
    "errors.unknown_format": {"value": "Неизвестный формат", "category": "errors", "description": "Формат изображения."},
    "errors.choose_trend_or_idea": {
        "value": "Выберите тренд или введите свою идею.",
        "category": "errors",
        "description": "Некорректный ввод на шаге тренда.",
    },
    "errors.enter_idea": {"value": "Введите описание своей идеи.", "category": "flow", "description": "Нужен текст для «Своя идея»."},
    "errors.request_processing": {"value": "⏳ Запрос уже обрабатывается.", "category": "flow", "description": "Двойное нажатие на тренд."},
    "errors.reserve_tokens_failed": {
        "value": "Не удалось зарезервировать токены.",
        "category": "errors",
        "description": "Нет токенов/лимитов для генерации.",
    },
    "errors.regenerate_launched": {"value": "Генерация запущена!", "category": "flow", "description": "После нажатия «Попробовать ещё раз»."},
    "errors.start_first": {"value": "Сначала нажмите /start.", "category": "errors", "description": "Пользователь не в БД."},
    "errors.job_not_found": {"value": "Кадр не найден.", "category": "errors", "description": "Job не найден."},
    "errors.wait_current_generation": {
        "value": "Подождите завершения текущей генерации.",
        "category": "errors",
        "description": "Повторный запрос во время генерации.",
    },
    "errors.no_source_photos": {"value": "Нет исходных фото для повтора.", "category": "errors", "description": "Regenerate без фото."},
    "errors.trend_no_longer": {"value": "Тренд больше недоступен.", "category": "errors", "description": "Тренд отключили."},
    "errors.general_short": {"value": "Ошибка.", "category": "errors", "description": "Краткий alert."},
    "errors.start_again": {"value": "Ошибка. Нажмите /start.", "category": "errors", "description": "Критическая ошибка."},
    "errors.file_too_large": {
        "value": "Файл слишком большой ({size_mb:.1f} МБ). Загрузите другое фото.",
        "category": "errors",
        "description": "Размер файла (переменная size_mb).",
    },
    "errors.file_too_large_max": {
        "value": "Файл слишком большой ({size_mb:.1f} МБ). Максимум {max_mb} МБ.",
        "category": "errors",
        "description": "Превышен размер при загрузке (size_mb, max_mb).",
    },
    "errors.file_too_large_max_only": {
        "value": "Файл слишком большой. Максимум {max_mb} МБ.",
        "category": "errors",
        "description": "Превышен размер (только max_mb).",
    },
    "copy.choose_one_two": {"value": "Выбери 1 или 2.", "category": "flow", "description": "Copy: выбор числа фото."},
    "copy.wait_one_photo": {"value": "Жду одну фотографию.", "category": "flow", "description": "Copy: ожидание 1 фото."},
    "copy.wait_two_photos": {"value": "Жду две фотографии.", "category": "flow", "description": "Copy: ожидание 2 фото."},
    "flow.session_reset_copy": {
        "value": "Сессия сброшена. Начните заново: «🔄 Сделать такую же».",
        "category": "flow",
        "description": "Сброс сессии copy.",
    },
    "flow.send_second_photo": {
        "value": "Отправьте вторую фотографию (фото или файл изображения).",
        "category": "flow",
        "description": "Copy: запрос второго фото.",
    },
    "flow.send_reference": {"value": "Отправьте картинку-образец (фото).", "category": "flow", "description": "Copy: запрос референса."},
    "flow.send_your_photo": {"value": "Отправьте свою фотографию.", "category": "flow", "description": "Запрос своего фото."},
    "flow.only_jpg_png_webp": {"value": "Поддерживаются только JPG, PNG, WEBP.", "category": "flow", "description": "Формат файла."},
    "flow.prompt_placeholder": {
        "value": "Опишите свою идею текстом. Например: «Сделай в стиле аниме»",
        "category": "flow",
        "description": "Подсказка в состоянии «Своя идея».",
    },
    "nav.upload_photo_or_btn": {
        "value": "Отправьте фото или нажмите «🔥 Создать фото».",
        "category": "flow",
        "description": "Неверный ввод в waiting_for_photo.",
    },
    "nav.main_hint": {
        "value": "Нажмите «🔥 Создать фото» или «🔄 Сделать такую же» — или /help для справки.",
        "category": "flow",
        "description": "Подсказка в неизвестном состоянии.",
    },
    "progress.regenerating": {
        "value": "⏳ Перегенерация с теми же настройками...",
        "category": "progress",
        "description": "Сообщение при перегенерации.",
    },
    "progress.regenerate_step1": {"value": "⏳ Генерация изображения…", "category": "progress", "description": "Промежуточный прогресс перегенерации (воркер)."},
    "progress.regenerate_step2": {"value": "⏳ Почти готово…", "category": "progress", "description": "Промежуточный прогресс перегенерации перед выдачей."},
    "errors.banned": {
        "value": "🚫 Ваш аккаунт заблокирован.\n\nПричина: {reason}",
        "category": "errors",
        "description": "Сообщение при бане (переменная: reason).",
    },
    "errors.suspended": {
        "value": "⏸ Ваш аккаунт временно приостановлен до {until}.\n\nПричина: {reason}",
        "category": "errors",
        "description": "Сообщение при подвеске (until, reason).",
    },
    "errors.rate_limit": {
        "value": "⚠️ Превышен лимит запросов ({rate_limit}/час).\n\nПопробуйте через несколько минут.",
        "category": "errors",
        "description": "Превышен rate limit (переменная: rate_limit).",
    },
    # --- Оплата переводом на карту ---
    "bank_transfer.btn.start": {
        "value": "💳 Не знаю как купить Stars",
        "category": "bank_transfer",
        "description": "Кнопка в магазине для альтернативной оплаты переводом.",
    },
    "bank_transfer.step1_description": {
        "value": (
            "💳 *Оплата переводом на карту*\n\n"
            "Если вы не знаете, как купить Telegram Stars — можно оплатить переводом "
            "на карту Озон Банка. Мы проверим чек и зачислим генерации автоматически.\n\n"
            "Выберите тариф:"
        ),
        "category": "bank_transfer",
        "description": "Шаг 1: описание способа оплаты переводом + предложение выбрать тариф.",
    },
    "bank_transfer.step2_requisites": {
        "value": (
            "💳 *Оплата: {pack_name}*\n"
            "📦 Пакет: *{tokens}* генераций\n"
            "💰 Сумма к переводу: *{expected_rub} ₽*\n"
            "🏦 Номер карты: `{card}`\n\n"
            "⚠️ *После перевода отправьте чек (скриншот или фото).* "
            "Без чека оплата не засчитывается.\n\n"
            "Мы проверим сумму автоматически и зачислим генерации."
        ),
        "category": "bank_transfer",
        "description": "Шаг 2: реквизиты и сумма (переменные: pack_name, tokens, expected_rub, card).",
    },
    "bank_transfer.success": {
        "value": (
            "✅ *Оплата засчитана!*\n\n"
            "Пакет: *{pack_name}*\n"
            "Начислено: *{tokens}* генераций\n"
            "Ваш баланс: *{balance}* генераций\n\n"
            "Теперь ваши фото будут без watermark!"
        ),
        "category": "bank_transfer",
        "description": "Успешное зачисление после проверки чека (pack_name, tokens, balance).",
    },
    "bank_transfer.amount_mismatch": {
        "value": (
            "❌ *Не удалось подтвердить оплату.*\n\n"
            "Отправьте чек ещё раз (скриншот или фото перевода).\n"
            "Убедитесь, что на скриншоте видна сумма перевода."
        ),
        "category": "bank_transfer",
        "description": "Сумма на чеке не совпала или не распознана.",
    },
}
