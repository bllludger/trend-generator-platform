-- Унификация терминологии NeoBanana: обновление шаблонов сообщений бота.
-- Если в таблице есть запись по ключу, value перезаписывается новым текстом.
-- Админы, кастомизировавшие эти ключи в «Сообщения бота», могут вернуть свои формулировки вручную.

UPDATE telegram_message_templates SET value = '👋 NeoBanana — ИИ фотостудия

Это просто фото.
Но оно может стать сценой.

Загрузи фото — выбери стиль —
получи результат как после съёмки.

👇 Попробовать бесплатно', updated_at = NOW() WHERE key = 'start.welcome_text';

UPDATE telegram_message_templates SET value = '🛒 Купить пакет', updated_at = NOW() WHERE key = 'menu.btn.shop';

UPDATE telegram_message_templates SET value = '🛒 *Магазин*

Купите пакет — получайте фото в полном качестве, без водяного знака!

', updated_at = NOW() WHERE key = 'shop.header';

UPDATE telegram_message_templates SET value = 'Пакеты временно недоступны.', updated_at = NOW() WHERE key = 'shop.unavailable';

UPDATE telegram_message_templates SET value = 'Фото не найдено.', updated_at = NOW() WHERE key = 'errors.job_not_found';

UPDATE telegram_message_templates SET value = '🔓 Фото разблокировано! Вот ваше фото в полном качестве (без сжатия).', updated_at = NOW() WHERE key = 'success.unlock_caption';

UPDATE telegram_message_templates SET value = 'Получить фото без водяного знака в полном качестве ({cost}⭐)', updated_at = NOW() WHERE key = 'unlock.invoice_description';

UPDATE telegram_message_templates SET value = '✅ Пакет *{emoji} {name}* активирован!

Начислено: *{tokens}* фото
Ваш баланс: *{balance}* фото

Теперь ваши фото будут без водяного знака!', updated_at = NOW() WHERE key = 'payment.pack_success';

UPDATE telegram_message_templates SET value = '📄 *Условия использования NeoBanana*

1. Пакеты фото приобретаются за Telegram Stars.
2. Бесплатные превью — с водяным знаком.
3. Оплаченный пакет даёт фото в полном качестве без водяного знака.
4. Возврат Stars возможен до использования фото из пакета.
5. Администрация вправе отказать в обслуживании при нарушении правил.
6. Все сгенерированные изображения — результат работы ИИ.

Используя бота, вы соглашаетесь с этими условиями.', updated_at = NOW() WHERE key = 'cmd.terms';

UPDATE telegram_message_templates SET value = 'Для этого сценария выберите новое фото.', updated_at = NOW() WHERE key = 'errors.choose_new_photo';
