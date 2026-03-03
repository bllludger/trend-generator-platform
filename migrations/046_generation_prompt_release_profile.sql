-- Профиль "На релиз" (id=2): второй набор дефолтов для мастер-промпта. id=1 = Превью, id=2 = На релиз.
-- Разрешаем id=2 и копируем строку id=1 в id=2.

ALTER TABLE generation_prompt_settings DROP CONSTRAINT IF EXISTS generation_prompt_settings_id_check;

INSERT INTO generation_prompt_settings (
    id,
    prompt_input,
    prompt_input_enabled,
    prompt_task,
    prompt_task_enabled,
    prompt_identity_transfer,
    prompt_identity_transfer_enabled,
    safety_constraints,
    safety_constraints_enabled,
    default_model,
    default_size,
    default_format,
    default_temperature,
    default_image_size_tier,
    default_aspect_ratio,
    updated_at
)
SELECT
    2,
    prompt_input,
    prompt_input_enabled,
    prompt_task,
    prompt_task_enabled,
    prompt_identity_transfer,
    prompt_identity_transfer_enabled,
    safety_constraints,
    safety_constraints_enabled,
    default_model,
    default_size,
    default_format,
    default_temperature,
    COALESCE(default_image_size_tier, '1K'),
    COALESCE(default_aspect_ratio, '1:1'),
    NOW()
FROM generation_prompt_settings
WHERE id = 1
ON CONFLICT (id) DO NOTHING;
