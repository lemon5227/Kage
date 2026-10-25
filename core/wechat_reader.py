"""D4a: read the WeChat window by screenshot + on-device OCR (read-only feasibility).

WeChat 4.1 exposes six accessibility nodes (setting AXManualAccessibility/AXEnhancedUserInterface is refused),
so the accessibility route used elsewhere cannot see chats. This module captures the WeChat main window
(`screencapture -l`, works while the window is covered), runs macOS Vision text recognition on the Mac
(Chinese + English, nothing leaves the machine) and turns the chat-list column into rows:
name, last-message preview, time, unread badge. Screenshots are deleted after reading.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import tempfile
import uuid

TIME = re.compile(r'^(\d{1,2}:\d{2}|昨天|前天|星期[一二三四五六日天]|周[一二三四五六日]|\d{1,2}/\d{1,2}(/\d{2,4})?|'
                  r'\d{4}/\d{1,2}/\d{1,2}|\d{1,2}月\d{1,2}日)$')


def wechat_windows() -> list[dict]:
    import Quartz
    rows = []
    for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID):
        if w.get('kCGWindowOwnerName', '') in ('WeChat', '微信') and w.get('kCGWindowLayer') == 0:
            b = w.get('kCGWindowBounds', {})
            rows.append({'id': int(w['kCGWindowNumber']), 'title': str(w.get('kCGWindowName', '')),
                         'width': int(b.get('Width', 0)), 'height': int(b.get('Height', 0))})
    return sorted(rows, key=lambda r: -r['width'] * r['height'])


def capture(window_id: int) -> Path:
    path = Path(tempfile.gettempdir()) / f'kage-wx-{uuid.uuid4().hex}.png'
    subprocess.run(['screencapture', '-x', '-o', '-l', str(window_id), str(path)], check=True, timeout=20)
    return path


def ocr(image: Path) -> tuple[list[dict], int, int]:
    """[{text, x, y, w, h, conf}] in pixels from the top-left, plus the image size."""
    import Quartz
    import Vision
    from Foundation import NSURL
    source = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(image)), None)
    cg = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    width, height = Quartz.CGImageGetWidth(cg), Quartz.CGImageGetHeight(cg)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setRecognitionLanguages_(['zh-Hans', 'en-US'])
    request.setUsesLanguageCorrection_(True)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, None)
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f'text recognition failed: {error}')
    boxes = []
    for observation in request.results() or []:
        candidate = observation.topCandidates_(1)[0]
        box = observation.boundingBox()          # normalized, origin bottom-left
        boxes.append({'text': str(candidate.string()), 'conf': float(candidate.confidence()),
                      'x': box.origin.x * width, 'y': (1 - box.origin.y - box.size.height) * height,
                      'w': box.size.width * width, 'h': box.size.height * height})
    return boxes, width, height


def red_badge(image: Path, x0: float, y0: float, x1: float, y1: float) -> bool:
    """A red unread badge somewhere in the given pixel box (WeChat's badge is a saturated red)."""
    import Quartz
    from Foundation import NSURL
    source = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(image)), None)
    cg = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    width, height = Quartz.CGImageGetWidth(cg), Quartz.CGImageGetHeight(cg)
    data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(cg))
    per_row, bpp = Quartz.CGImageGetBytesPerRow(cg), Quartz.CGImageGetBitsPerPixel(cg) // 8
    reds = 0
    for y in range(max(0, int(y0)), min(height, int(y1)), 2):
        for x in range(max(0, int(x0)), min(width, int(x1)), 2):
            i = y * per_row + x * bpp
            b, g, r = data[i], data[i + 1], data[i + 2]       # BGRA on Apple silicon screenshots
            if r > 200 and g < 90 and b < 90:
                reds += 1
                if reds >= 6:
                    return True
    return False


def chat_list(image: Path) -> list[dict]:
    """Rows of the chat-list column: {name, preview, time, unread}. The list is the column whose lines pair a
    name with a time on the right; the open conversation pane on the right is ignored."""
    boxes, width, height = ocr(image)
    times = [b for b in boxes if TIME.match(b['text'].strip()) and b['x'] < width * 0.6]
    if not times:
        return []
    right_edge = max(t['x'] + t['w'] for t in times)          # times are right-aligned in the list column
    left_edge = min(b['x'] for b in boxes if b['x'] < right_edge and b['y'] > 40)
    rows = []
    for t in sorted(times, key=lambda b: b['y']):
        same_line = [b for b in boxes if abs(b['y'] - t['y']) < t['h'] * 0.8 and b['x'] < t['x'] and b['x'] > left_edge - 5]
        below = [b for b in boxes if 0 < b['y'] - t['y'] < t['h'] * 2.6 and left_edge - 5 < b['x'] < right_edge]
        name = ' '.join(b['text'] for b in sorted(same_line, key=lambda b: b['x'])).strip()
        if not name:
            continue
        name_box = min(same_line, key=lambda b: b['x'])
        preview = ' '.join(b['text'] for b in sorted(below, key=lambda b: b['x'])).strip()
        # Badge: on the avatar's top-right corner, left of the name.
        avatar_right = name_box['x'] - 4
        unread = red_badge(image, avatar_right - name_box['h'] * 1.6, t['y'] - name_box['h'] * 0.9,
                           avatar_right + 2, t['y'] + name_box['h'] * 0.6)
        count = re.match(r'^\[(\d+)条\]', preview)
        rows.append({'name': name, 'preview': preview, 'time': t['text'].strip(), 'unread': unread,
                     'unread_count': int(count.group(1)) if count else None})
    return rows


def read_chat_list() -> list[dict]:
    windows = [w for w in wechat_windows() if w['width'] >= 500]
    if not windows:
        raise RuntimeError('微信主窗口没有打开（可能还在登录页或已最小化）')
    image = capture(windows[0]['id'])
    try:
        return chat_list(image)
    finally:
        image.unlink(missing_ok=True)
