"""Render a lineage.jsonl version tree as a dependency-free SVG.

  python scripts/experiments/lineage_plot.py --lineage <lineage.jsonl> --out tree.svg

Node colour = status, label = first 20 characters of the hypothesis + validation rate,
plus the subtree score used for parent selection.
"""
from __future__ import annotations

import argparse
from html import escape
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.evolution.lineage import Lineage

COLORS = {'active': '#2e7d32', 'rejected': '#c62828', 'retired': '#757575'}
W, H, DX, DY = 190, 46, 210, 80


def layout(lineage: Lineage) -> dict[str, tuple[float, float]]:
    pos, next_x = {}, [0]

    def place(node_id: str, depth: int) -> float:
        kids = sorted(lineage.children(node_id), key=lambda n: n.created)
        if not kids:
            x = next_x[0]
            next_x[0] += 1
        else:
            xs = [place(k.id, depth + 1) for k in kids]
            x = (xs[0] + xs[-1]) / 2
        pos[node_id] = (x, depth)
        return x

    for root in sorted(lineage.roots(), key=lambda n: n.created):
        place(root.id, 0)
    return pos


def render(lineage: Lineage) -> str:
    pos = layout(lineage)
    width = max([x for x, _ in pos.values()] + [0]) * DX + W + 20
    height = max([d for _, d in pos.values()] + [0]) * DY + H + 20
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
             'font-family="Helvetica, Arial, sans-serif" font-size="11">']
    for node_id, (x, d) in pos.items():
        node = lineage.nodes[node_id]
        if node.parent in pos:
            px, pd = pos[node.parent]
            parts.append(f'<line x1="{px * DX + 10 + W / 2:.0f}" y1="{pd * DY + 10 + H:.0f}" '
                         f'x2="{x * DX + 10 + W / 2:.0f}" y2="{d * DY + 10:.0f}" stroke="#999"/>')
    for node_id, (x, d) in pos.items():
        node = lineage.nodes[node_id]
        v = node.validation or {}
        rate = f"{v.get('passed', 0)}/{v.get('total', 0)}" if v else 'n/a'
        label = escape(node.hypothesis[:20] or node.id[:20])
        parts.append(f'<g class="node" data-id="{escape(node.id)}">'
                     f'<rect x="{x * DX + 10:.0f}" y="{d * DY + 10:.0f}" width="{W}" height="{H}" rx="6" '
                     f'fill="{COLORS.get(node.status, "#444")}"/>'
                     f'<text x="{x * DX + 18:.0f}" y="{d * DY + 28:.0f}" fill="#fff">{label}</text>'
                     f'<text x="{x * DX + 18:.0f}" y="{d * DY + 46:.0f}" fill="#fff">'
                     f'val {rate} · clade {lineage.subtree_score(node.id):.2f}</text></g>')
    parts.append('</svg>')
    return '\n'.join(parts) + '\n'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--lineage', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args(argv)
    args.out.write_text(render(Lineage(args.lineage)))
    print(args.out)


if __name__ == '__main__':
    main()
