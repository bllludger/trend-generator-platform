-- Transfer Policy: дефолтный список пунктов для блока [AVOID] (редактируемый в админке).
ALTER TABLE transfer_policy ADD COLUMN IF NOT EXISTS avoid_default_items TEXT NOT NULL DEFAULT 'watermarks
logos
text in image
chat or UI elements
blurry face
incorrect pose
cropped limbs
distorted proportions
unnatural lighting
painterly or illustrated look';
