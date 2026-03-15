-- Унификация терминологии NeoBanana (обращение «вы», канонические формулировки).
-- Обновляет типовые ключи в telegram_message_templates. Кастомные правки админа перезаписываются.
-- При необходимости админ может вернуть тексты в разделе «Сообщения бота».

UPDATE telegram_message_templates SET value = '👋 NeoBanana — ИИ фотостудия

Это просто фото.
Но оно может стать сценой.

Загрузите фото — выберите стиль —
получите результат как после съёмки.

👇 Попробуйте бесплатно', updated_at = NOW() WHERE key = 'start.welcome_text';

UPDATE telegram_message_templates SET value = 'Ошибка. Попробуйте ещё раз.', updated_at = NOW() WHERE key = 'errors.try_again_alert';

UPDATE telegram_message_templates SET value = 'Недостаточно доступа. Купите пакет.', updated_at = NOW() WHERE key = 'errors.reserve_tokens_failed';

UPDATE telegram_message_templates SET value = 'Выберите 1 или 2.', updated_at = NOW() WHERE key = 'copy.choose_one_two';

UPDATE telegram_message_templates SET value = 'Опишите свою идею текстом. Например: «Сделайте в стиле аниме»', updated_at = NOW() WHERE key = 'flow.prompt_placeholder';

UPDATE telegram_message_templates SET value = 'Произошла ошибка. Попробуйте позже.', updated_at = NOW() WHERE key = 'errors.try_later';

-- Новые ключи (если записей ещё нет — не вставляем, используются fallback из кода)
UPDATE telegram_message_templates SET value = 'Ошибка загрузки профиля.', updated_at = NOW() WHERE key = 'errors.profile_load';

UPDATE telegram_message_templates SET value = 'Это фото уже оплачено. Если не получили файл — напишите в поддержку: @{support_username}.', updated_at = NOW() WHERE key = 'pay.unlock_already_paid';

UPDATE telegram_message_templates SET value = 'Пробный пакет уже был использован. Средства возвращены на ваш счёт Stars.', updated_at = NOW() WHERE key = 'payment.trial_refunded';

UPDATE telegram_message_templates SET value = 'Пробный пакет уже был использован. Обратитесь в поддержку: @{support_username} — мы вернём средства на карту.', updated_at = NOW() WHERE key = 'payment.trial_refunded_yoomoney';

UPDATE telegram_message_templates SET value = 'Файл ещё не готов. Средства возвращены на ваш счёт Stars. Попробуйте разблокировать позже или напишите @{support_username}.', updated_at = NOW() WHERE key = 'payment.unlock_file_not_ready_refunded';

UPDATE telegram_message_templates SET value = 'Оплата принята, но файл ещё не готов. Обратитесь в поддержку: @{support_username} — мы вернём средства вручную.', updated_at = NOW() WHERE key = 'payment.unlock_file_not_ready';
