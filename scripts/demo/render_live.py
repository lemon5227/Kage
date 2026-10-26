"""Post-process a live-demo screen recording (D6): blur private regions, add smooth zooms, trim.

  python scripts/demo/render_live.py RECORDING.mp4 OUT.mp4 --plan PLAN.json

The plan lists blur rectangles (recording pixels) and zoom keyframes. The demo is typed, so the cursor-following
auto-zoom of the recorder has nothing to follow; zooms are placed at the moments Kage answers (times from the
usage log). Rectangles are blurred *before* zooming, so a zoom never reveals them.

PLAN.json: {"trim": [start, end], "fps": 30, "blur": [[x, y, w, h], ...],
            "views": {"full": [1, 0, 0], "term": [z, x, y], ...},
            "timeline": [[t, "view"], ...]}   # hold a view from t; move to the next one over `ease` seconds
"""
import argparse
import json
import subprocess


def smooth_expr(timeline: list, views: dict, index: int, ease: float) -> str:
    """Piecewise expression of zoompan variable `index` (0 zoom, 1 x, 2 y) over input time `it`."""
    parts = []
    for (t0, a), (t1, b) in zip(timeline, timeline[1:]):
        va, vb = views[a][index], views[b][index]
        start = max(t0, t1 - ease)
        p = f'((it-{start})/{t1 - start})'
        parts.append((t1, f'if(lt(it,{start}),{va},{va}+({vb}-{va})*{p}*{p}*(3-2*{p}))'))
    expr = str(views[timeline[-1][1]][index])
    for t1, piece in reversed(parts):
        expr = f'if(lt(it,{t1}),{piece},{expr})'
    return expr


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('src')
    parser.add_argument('out')
    parser.add_argument('--plan', required=True)
    parser.add_argument('--ease', type=float, default=1.2)
    args = parser.parse_args()
    plan = json.load(open(args.plan, encoding='utf-8'))
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
                            '-of', 'csv=p=0', args.src], capture_output=True, text=True, check=True).stdout
    width, height = (int(v) for v in probe.strip().split(','))
    fps = plan.get('fps', 30)
    chain, last = [f'[0:v]fps={fps}[v0]'], 'v0'
    for i, (x, y, w, h) in enumerate(plan['blur']):
        chain.append(f'[{last}]split[a{i}][b{i}];[b{i}]crop={w}:{h}:{x}:{y},boxblur=24:3[c{i}];'
                     f'[a{i}][c{i}]overlay={x}:{y}[v{i + 1}]')
        last = f'v{i + 1}'
    timeline, views = plan['timeline'], plan['views']
    z, x, y = (smooth_expr(timeline, views, k, args.ease) for k in range(3))
    chain.append(f"[{last}]zoompan=z='{z}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps},"
                 f"scale={plan.get('scale_width', width)}:-2:flags=lanczos[out]")
    start, end = plan['trim']
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', args.src, '-filter_complex', ';'.join(chain), '-map', '[out]',
                    '-ss', str(start), '-to', str(end), '-c:v', 'libx264', '-crf', str(plan.get('crf', 20)), '-preset', 'slow', '-pix_fmt', 'yuv420p',
                    '-movflags', '+faststart', args.out], check=True)


if __name__ == '__main__':
    main()
