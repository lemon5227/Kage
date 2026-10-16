"""Render the W6-4 demo video without screen recording.

  python scripts/demo/render_video.py [--out artifacts/demo/kage-demo.mp4]

Runs scripts/demo/replay_demo.py (real recorded run, no model), records its terminal output with
timestamps, draws each screen state with a small ANSI renderer (clear screen, colours, bold/dim,
CJK double width), appends the growth curve, and encodes an H.264 MP4 with ffmpeg.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
W, H = 1600, 1000
PAD_X, PAD_Y, LINE_H, CELL_W = 48, 56, 34, 13
BG = (24, 26, 31)
FG = (220, 222, 228)
COLORS = {31: (240, 98, 98), 32: (110, 210, 130), 33: (238, 200, 110), 35: (200, 140, 240), 36: (110, 200, 230)}
MONO = ImageFont.truetype('/System/Library/Fonts/Menlo.ttc', 22)
MONO_B = ImageFont.truetype('/System/Library/Fonts/Menlo.ttc', 22, index=1)
CJK = ImageFont.truetype('/System/Library/Fonts/Hiragino Sans GB.ttc', 22)
CJK_B = ImageFont.truetype('/System/Library/Fonts/Hiragino Sans GB.ttc', 22, index=1)
TOKEN = re.compile(r'\x1b\[([0-9;]*)([A-Za-z])|\n|[^\x1b\n]')


def wide(ch: str) -> bool:
    return ord(ch) > 0x2E7F


class Screen:
    def __init__(self):
        self.lines = [[]]            # each line: list of (char, style)
        self.style = {'fg': FG, 'bold': False, 'dim': False}
        self.pending = ''

    def feed(self, text: str) -> None:
        # Typed output arrives one character at a time, so an escape sequence can span chunks.
        text = self.pending + text
        cut = text.rfind('\x1b')
        if cut != -1 and not re.match(r'\x1b\[[0-9;]*[A-Za-z]', text[cut:]):
            text, self.pending = text[:cut], text[cut:]
        else:
            self.pending = ''
        for m in TOKEN.finditer(text):
            tok = m.group(0)
            if m.group(2):
                params, cmd = m.group(1), m.group(2)
                if cmd == 'J':
                    self.lines = [[]]
                elif cmd == 'm':
                    for code in (int(c) for c in (params or '0').split(';') if c):
                        if code == 0:
                            self.style = {'fg': FG, 'bold': False, 'dim': False}
                        elif code == 1:
                            self.style = {**self.style, 'bold': True}
                        elif code == 2:
                            self.style = {**self.style, 'dim': True}
                        elif code in COLORS:
                            self.style = {**self.style, 'fg': COLORS[code]}
            elif tok == '\n':
                self.lines.append([])
            else:
                self.lines[-1].append((tok, dict(self.style)))

    def render(self) -> Image.Image:
        img = Image.new('RGB', (W, H), BG)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([18, 14, W - 18, 44], 8, fill=(38, 41, 48))
        for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse([34 + i * 22, 22, 48 + i * 22, 36], fill=c)
        d.text((W // 2 - 150, 18), 'Kage · 学习流回放（真实记录）', font=CJK, fill=(150, 154, 165))
        visible = self.lines[-((H - PAD_Y - 20) // LINE_H):]
        for row, line in enumerate(visible):
            x, y = PAD_X, PAD_Y + row * LINE_H
            for ch, st in line:
                bold = st['bold'] and not 0x2500 <= ord(ch) <= 0x257F    # Menlo Bold has no box drawing
                font = (CJK_B if bold else CJK) if wide(ch) else (MONO_B if bold else MONO)
                fill = tuple(int(v * 0.55 + BG[i] * 0.45) for i, v in enumerate(st['fg'])) if st['dim'] else st['fg']
                d.text((x, y), ch, font=font, fill=fill)
                x += CELL_W * (2 if wide(ch) else 1)
        return img


def record(speed: float) -> list[tuple[float, str]]:
    env = {**os.environ, 'PYTHONUNBUFFERED': '1'}
    proc = subprocess.Popen([sys.executable, str(ROOT / 'scripts/demo/replay_demo.py'), '--speed', str(speed)],
                            stdout=subprocess.PIPE, env=env, cwd=ROOT)
    events, start = [], time.monotonic()
    raw = b''
    while True:
        chunk = proc.stdout.read1(4096)
        if not chunk:
            break
        raw += chunk
        try:                                   # keep multi-byte characters whole
            text, raw = raw.decode('utf-8'), b''
        except UnicodeDecodeError:
            continue
        events.append((time.monotonic() - start, text))
    proc.wait()
    events.append((time.monotonic() - start, ''))    # the replay's final pause is part of the video
    return events


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, default=ROOT / 'artifacts' / 'demo' / 'kage-demo.mp4')
    p.add_argument('--fps', type=int, default=15)
    p.add_argument('--curve-seconds', type=float, default=8)
    args = p.parse_args(argv)
    events = record(1.0)
    total = events[-1][0]
    work = Path(tempfile.mkdtemp(prefix='kage-demo-'))
    screen, idx, last, frame_files = Screen(), 0, None, []
    n = int(total * args.fps)
    for f in range(n):
        t = f / args.fps
        changed = False
        while idx < len(events) and events[idx][0] <= t:
            screen.feed(events[idx][1])
            idx += 1
            changed = True
        if changed or last is None:
            last = work / f'{f:05d}.png'
            screen.render().save(last)
        frame_files.append(last)
    curve = Image.open(ROOT / 'docs/assets/readme/growth-curve.png').convert('RGB')
    canvas = Image.new('RGB', (W, H), (255, 255, 255))
    curve.thumbnail((W - 80, H - 80))
    canvas.paste(curve, ((W - curve.width) // 2, (H - curve.height) // 2))
    curve_png = work / 'curve.png'
    canvas.save(curve_png)
    frame_files += [curve_png] * int(args.curve_seconds * args.fps)
    listing = work / 'frames.txt'
    listing.write_text(''.join(f"file '{fp}'\nduration {1 / args.fps}\n" for fp in frame_files)
                       + f"file '{frame_files[-1]}'\n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing),
                    '-vf', f'fps={args.fps},format=yuv420p', '-c:v', 'libx264', '-crf', '20', '-preset', 'medium',
                    '-movflags', '+faststart', str(args.out)], check=True)
    shutil.rmtree(work)
    print(args.out, f'{len(frame_files) / args.fps:.1f}s')


if __name__ == '__main__':
    main()
