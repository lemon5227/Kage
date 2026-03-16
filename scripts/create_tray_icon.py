#!/usr/bin/env python3
"""Extract smooth black lines from AI-generated image with true transparency"""
from PIL import Image
import numpy as np

# Load the smooth AI-generated line ghost
img = Image.open('/Users/wenbo/.gemini/antigravity/brain/f51ea465-b5e4-42c3-95b7-7dfa16be6ecc/kage_tray_line_1769628700808.png')
img = img.convert('RGBA')
arr = np.array(img)

# Find dark pixels (the black lines) - R,G,B all < 100
dark_mask = (arr[:,:,0] < 100) & (arr[:,:,1] < 100) & (arr[:,:,2] < 100)

# Create new image: keep black lines, make everything else transparent
new_arr = np.zeros_like(arr)
new_arr[dark_mask] = [0, 0, 0, 255]  # Black opaque
new_arr[~dark_mask] = [0, 0, 0, 0]   # Transparent

new_img = Image.fromarray(new_arr)

# Crop to content
bbox = new_img.getbbox()
if bbox:
    cropped = new_img.crop(bbox)
else:
    cropped = new_img

w, h = cropped.size
print(f'Cropped size: {w}x{h}')

# Keep aspect ratio, fit in target size
def resize_keep_aspect(img, target_size):
    w, h = img.size
    scale = min(target_size / w, target_size / h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    # Center in target canvas
    final = Image.new('RGBA', (target_size, target_size), (0, 0, 0, 0))
    offset = ((target_size - new_w) // 2, (target_size - new_h) // 2)
    final.paste(resized, offset)
    return final

# Save icons
resize_keep_aspect(cropped, 22).save('/Users/wenbo/Kage/assets/tray_icon.png')
resize_keep_aspect(cropped, 44).save('/Users/wenbo/Kage/assets/tray_icon@2x.png')

print('✅ Created smooth 22x22 and 44x44 icons from AI-generated image')
