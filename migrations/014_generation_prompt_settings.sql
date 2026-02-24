-- Промпт генерации: единственный источник правды — БД (админка). Каждый блок можно включать/выключать и редактировать.
CREATE TABLE IF NOT EXISTS generation_prompt_settings (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    -- Блоки (вкл/выкл + контент)
    system_prompt_prefix TEXT NOT NULL DEFAULT '',
    system_prompt_prefix_enabled BOOLEAN NOT NULL DEFAULT true,
    negative_prompt_prefix TEXT NOT NULL DEFAULT 'negative_prompt: ',
    negative_prompt_prefix_enabled BOOLEAN NOT NULL DEFAULT true,
    safety_constraints TEXT NOT NULL DEFAULT 'no text generation, no chat.',
    safety_constraints_enabled BOOLEAN NOT NULL DEFAULT true,
    image_constraints_template TEXT NOT NULL DEFAULT 'size={size}, format={format}',
    image_constraints_template_enabled BOOLEAN NOT NULL DEFAULT true,
    -- Дефолты модели (используются, если job/тренд не переопределяют)
    default_model VARCHAR(128) NOT NULL DEFAULT 'gemini-2.5-flash-image',
    default_size VARCHAR(32) NOT NULL DEFAULT '1024x1024',
    default_format VARCHAR(16) NOT NULL DEFAULT 'png',
    default_temperature REAL NOT NULL DEFAULT 0.7,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

INSERT INTO generation_prompt_settings (
    id,
    system_prompt_prefix,
    system_prompt_prefix_enabled,
    negative_prompt_prefix,
    negative_prompt_prefix_enabled,
    safety_constraints,
    safety_constraints_enabled,
    image_constraints_template,
    image_constraints_template_enabled,
    default_model,
    default_size,
    default_format,
    default_temperature
) VALUES (
    1,
    'You are an image generation system. Follow the trend instructions precisely.',
    true,
    'negative_prompt: ',
    true,
    'no text generation, no chat.',
    true,
    'size={size}, format={format}',
    true,
    'gemini-2.5-flash-image',
    '1024x1024',
    'png',
    0.7
)
ON CONFLICT (id) DO NOTHING;
