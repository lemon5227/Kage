"""R3c: choose replay rows with LESS-style gradient influence (Xia et al., ICML 2024, arXiv:2402.04333).

A candidate row is worth training on when the update it would cause points the same way as the gradients of the
rows we care about. Following LESS:
- a short warmup LoRA (lora_train.py --save-optimizer) gives meaningful gradients and the AdamW moments;
- candidate feature = the Adam update direction m'/(sqrt(v')+eps) after one step on that row (moments from the
  warmup), target feature = the plain gradient of a target row, both on the LoRA parameters only;
- features are compressed by a count-sketch random projection (each coordinate hashed to one of `dims` buckets
  with a random sign; an unbiased JL-type sketch that is linear in the parameter count, unlike a dense projection
  of 19M parameters) and L2-normalised;
- score = max over target sets of the mean cosine to that set (LESS takes the max over target tasks).
Then a diversity constraint the paper does not have: k-means on the candidate features, and selection walks the
score order while no cluster exceeds its share, so the top scores cannot all be near-duplicates.

Target sets (never eval tasks or transfer families): `own` = the base student's unguided successes (its normal
reason-then-act behaviour that R3 lost), `task` = the R2 validation rows.

  python less_select.py --model HF_DIR --warmup ADAPTER_DIR --candidates pool.jsonl \
      --target own=control.jsonl --target task=val.jsonl --n 1400 --out DIR
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lora_train                                          # noqa: E402

DIMS = 8192
SEED = 0


def count_sketch(dim_in: int, dims: int, seed: int = SEED, device='cpu'):
    import torch
    g = torch.Generator().manual_seed(seed)
    index = torch.randint(0, dims, (dim_in,), generator=g)
    sign = torch.randint(0, 2, (dim_in,), generator=g).float() * 2 - 1
    return index.to(device), sign.to(device)


def project(vec, sketch, dims: int):
    import torch
    index, sign = sketch
    out = torch.zeros(dims, device=vec.device, dtype=torch.float32)
    out.index_add_(0, index, vec.float() * sign)
    return out / out.norm().clamp_min(1e-12)


def diverse_top(scores: list[float], clusters: list[int], n: int, n_clusters: int) -> list[int]:
    """Highest scores first, but no cluster may take more than twice its even share of the n slots."""
    cap = max(1, -(-2 * n // n_clusters))
    taken: dict[int, int] = {}
    chosen = []
    for i in sorted(range(len(scores)), key=lambda j: -scores[j]):
        c = clusters[i]
        if taken.get(c, 0) < cap:
            chosen.append(i)
            taken[c] = taken.get(c, 0) + 1
            if len(chosen) == n:
                break
    return chosen


def kmeans(x, k: int, iters: int = 20, seed: int = SEED):
    import torch
    g = torch.Generator().manual_seed(seed)
    centers = x[torch.randperm(len(x), generator=g)[:k]].clone()
    for _ in range(iters):
        assign = (x @ centers.T).argmax(1)               # features are unit vectors: cosine k-means
        for c in range(k):
            members = x[assign == c]
            if len(members):
                centers[c] = members.mean(0)
                centers[c] /= centers[c].norm().clamp_min(1e-12)
    return assign.tolist()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open() if line.strip()]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--model', required=True)
    p.add_argument('--warmup', type=Path, required=True, help='adapter dir with optimizer.pt')
    p.add_argument('--candidates', type=Path, required=True)
    p.add_argument('--target', action='append', required=True, help='NAME=FILE.jsonl')
    p.add_argument('--n', type=int, default=1400)
    p.add_argument('--clusters', type=int, default=40)
    p.add_argument('--max-tokens', type=int, default=8192)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args(argv)
    started = time.time()

    import torch
    from peft import PeftModel
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.model)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    if device == 'cuda':
        base, _ = lora_train.load_model(args.model, torch.bfloat16)
    else:                                                  # tiny-model check on a laptop
        from transformers import AutoModelForCausalLM
        base = AutoModelForCausalLM.from_pretrained(args.model, dtype=torch.float32)
    model = PeftModel.from_pretrained(base, str(args.warmup), is_trainable=True)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    model.enable_input_require_grads()
    model.train()
    named = [(n, q) for n, q in model.named_parameters() if q.requires_grad]
    opt = torch.load(args.warmup / 'optimizer.pt', map_location=device)
    by_name = dict(zip(opt['names'], range(len(opt['names']))))
    beta1, beta2 = opt['betas']
    eps = opt['eps']
    m = torch.cat([opt['state']['state'][by_name[n]]['exp_avg'].flatten() for n, _ in named]).float()
    v = torch.cat([opt['state']['state'][by_name[n]]['exp_avg_sq'].flatten() for n, _ in named]).float()
    sketch = count_sketch(m.numel(), DIMS, device=device)

    def feature(row: dict, adam: bool):
        enc = lora_train.encode(tok, row, args.max_tokens)
        if enc is None:
            return None
        ids, labels, _ = enc
        model.zero_grad(set_to_none=True)
        with torch.autocast(device, dtype=torch.bfloat16, enabled=device == 'cuda'):
            loss = lora_train.response_loss(model, ids, labels)
        loss.backward()
        g = torch.cat([q.grad.flatten() for _, q in named]).float()
        if adam:
            m2 = beta1 * m + (1 - beta1) * g
            v2 = beta2 * v + (1 - beta2) * g * g
            g = m2 / (v2.sqrt() + eps)
        return project(g, sketch, DIMS)

    targets = {}
    for spec in args.target:
        name, path = spec.split('=', 1)
        feats = [f for f in (feature(r, adam=False) for r in read_jsonl(Path(path))) if f is not None]
        targets[name] = torch.stack(feats)
        print(json.dumps({'target': name, 'rows': len(feats), 'seconds': round(time.time() - started)}), flush=True)

    rows = read_jsonl(args.candidates)
    kept, feats = [], []
    for i, row in enumerate(rows):
        f = feature(row, adam=True)
        if f is not None:
            kept.append(row)
            feats.append(f)
        if i % 500 == 0:
            print(json.dumps({'candidates_done': i, 'of': len(rows), 'seconds': round(time.time() - started)}),
                  flush=True)
    x = torch.stack(feats)
    per_target = {name: (x @ t.T).mean(1) for name, t in targets.items()}
    score = torch.stack(list(per_target.values())).max(0).values
    clusters = kmeans(x, args.clusters)
    chosen = diverse_top(score.tolist(), clusters, args.n, args.clusters)

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / 'replay.jsonl').open('w') as f:
        for i in chosen:
            f.write(json.dumps(kept[i], ensure_ascii=False) + '\n')
    src = lambda idx: {s: sum(kept[i]['source'] == s for i in idx) for s in sorted({r['source'] for r in kept})}
    stats = {'method': 'LESS (Adam-direction candidates, gradient targets, count-sketch %d dims) + cluster cap' % DIMS,
             'candidates': len(rows), 'scored': len(kept), 'selected': len(chosen), 'clusters': args.clusters,
             'by_source_pool': src(range(len(kept))), 'by_source_selected': src(chosen),
             'score_selected_mean': float(score[chosen].mean()), 'score_all_mean': float(score.mean()),
             'per_target_mean_selected': {k: float(v[chosen].mean()) for k, v in per_target.items()},
             'per_target_mean_all': {k: float(v.mean()) for k, v in per_target.items()},
             'seconds': round(time.time() - started)}
    (args.out / 'replay-stats.json').write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats), flush=True)


if __name__ == '__main__':
    main()
