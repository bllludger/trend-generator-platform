-- Trend: только сцена и стиль. Добавляем subject_mode, framing_hint, negative_scene.
-- subject_prompt и system_prompt остаются для legacy (скрыты в UI, используются только если scene_prompt пуст).
ALTER TABLE trends ADD COLUMN IF NOT EXISTS subject_mode VARCHAR(32) DEFAULT 'face';
ALTER TABLE trends ADD COLUMN IF NOT EXISTS framing_hint VARCHAR(32) DEFAULT 'portrait';
ALTER TABLE trends ADD COLUMN IF NOT EXISTS negative_scene TEXT;

-- negative_scene: при пустом — используем negative_prompt для обратной совместимости
UPDATE trends
SET negative_scene = negative_prompt
WHERE negative_scene IS NULL AND (negative_prompt IS NOT NULL AND negative_prompt <> '');

-- TransferPolicy: глобальная сущность (одна запись id=1)
CREATE TABLE IF NOT EXISTS transfer_policy (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    identity_lock_level VARCHAR(64) NOT NULL DEFAULT 'strict',
    identity_rules_text TEXT NOT NULL DEFAULT 'Preserve the face and identity from IMAGE_1 in the output. Do not alter facial features, skin tone, or distinguishing characteristics.',
    composition_rules_text TEXT NOT NULL DEFAULT 'Place the subject from IMAGE_1 naturally in the scene. Maintain proportions and perspective.',
    subject_reference_name VARCHAR(32) NOT NULL DEFAULT 'IMAGE_1',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO transfer_policy (id, identity_lock_level, identity_rules_text, composition_rules_text, subject_reference_name, updated_at)
VALUES (1, 'strict',
        'Preserve the face and identity from IMAGE_1 in the output. Do not alter facial features, skin tone, or distinguishing characteristics.',
        'Place the subject from IMAGE_1 naturally in the scene. Maintain proportions and perspective.',
        'IMAGE_1', NOW())
ON CONFLICT (id) DO NOTHING;
