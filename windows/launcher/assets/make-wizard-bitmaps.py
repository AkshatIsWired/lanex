#!/usr/bin/env python3
# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Generate Inno Setup wizard bitmaps from official LanEx brand assets:
- windows/launcher/assets/wizard.bmp (164x314, left banner on Welcome & Finished pages)
- windows/launcher/assets/wizard-small.bmp (55x55, top-right header icon on inner pages)
"""
from pathlib import Path
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
VENDOR = REPO_ROOT / "lanex" / "server" / "static" / "vendor"
ASSETS = Path(__file__).resolve().parent

MARK_PNG = VENDOR / "lanex-mark-light.png"
LOGO_PNG = VENDOR / "lanex-logo-light.png"

WIZARD_BMP = ASSETS / "wizard.bmp"
WIZARD_SMALL_BMP = ASSETS / "wizard-small.bmp"

def create_wizard_small():
    # 55x55 on pure white background
    bg = Image.new("RGB", (55, 55), (255, 255, 255))
    mark = Image.open(MARK_PNG).convert("RGBA")
    bbox = mark.getbbox()
    if bbox:
        mark = mark.crop(bbox)
    
    # Target size: 44x44
    target_size = 44
    aspect = mark.width / mark.height
    if aspect >= 1.0:
        w = target_size
        h = int(target_size / aspect)
    else:
        h = target_size
        w = int(target_size * aspect)
    
    mark_resized = mark.resize((w, h), Image.Resampling.LANCZOS)
    pos_x = (55 - w) // 2
    pos_y = (55 - h) // 2
    
    bg.paste(mark_resized, (pos_x, pos_y), mark_resized)
    bg.save(WIZARD_SMALL_BMP, "BMP")
    print(f"Generated {WIZARD_SMALL_BMP} (55x55)")

def create_wizard_banner():
    # 164x314 on LanEx dark navy background (14, 21, 36)
    W, H = 164, 314
    bg = Image.new("RGB", (W, H), (14, 21, 36))
    
    # Optional subtle gradient or clean dark tone
    # Mark in upper-middle
    mark = Image.open(MARK_PNG).convert("RGBA")
    m_bbox = mark.getbbox()
    if m_bbox:
        mark = mark.crop(m_bbox)
    
    mark_w = 86
    mark_h = int(mark_w * (mark.height / mark.width))
    mark_resized = mark.resize((mark_w, mark_h), Image.Resampling.LANCZOS)
    
    # Wordmark text from logo
    logo = Image.open(LOGO_PNG).convert("RGBA")
    l_bbox = logo.getbbox()
    if l_bbox:
        logo = logo.crop(l_bbox)
    # The text starts around column 308
    text_crop = logo.crop((308, 0, logo.width, logo.height))
    t_bbox = text_crop.getbbox()
    if t_bbox:
        text_crop = text_crop.crop(t_bbox)
    
    text_w = 110
    text_h = int(text_w * (text_crop.height / text_crop.width))
    text_resized = text_crop.resize((text_w, text_h), Image.Resampling.LANCZOS)
    
    # Vertical layout:
    # mark at y=85, text at y=185
    mark_x = (W - mark_w) // 2
    mark_y = 80
    
    text_x = (W - text_w) // 2
    text_y = mark_y + mark_h + 16
    
    bg.paste(mark_resized, (mark_x, mark_y), mark_resized)
    bg.paste(text_resized, (text_x, text_y), text_resized)
    
    bg.save(WIZARD_BMP, "BMP")
    print(f"Generated {WIZARD_BMP} (164x314)")

def main():
    create_wizard_small()
    create_wizard_banner()

if __name__ == "__main__":
    main()
