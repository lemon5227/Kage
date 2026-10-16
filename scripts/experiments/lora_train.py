"""P4-L3: LoRA on Agents-A1-4B from student-format teacher demonstrations (Kaggle T4).

  python scripts/experiments/lora_train.py --data sft.jsonl --model DIR --out ADAPTER_DIR
      [--epochs 3 --lr 1e-4 --rank 16 --max-tokens 6144 --targets full|safe] [--smoke]

Each example is the request the student would send at one step (system prompt, task, earlier tool
calls and results, tool list) and the teacher's next response. The chat template renders both;
loss is applied only to the response tokens (after the longest common prefix of the prompt with
generation header and the full conversation). T4 has no bf16: base weights in fp16, LoRA weights
in fp32 with autocast and gradient checkpointing.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import random
import time

TARGETS = {
    # full: every language-model projection; safe: ones llama.cpp's LoRA converter maps 1:1.
    'full': r'.*language_model.*\.(q_proj|k_proj|v_proj|o_proj|in_proj_qkv|in_proj_z|out_proj|gate_proj|up_proj|down_proj)',
    'safe': r'.*language_model.*\.(o_proj|out_proj|gate_proj|up_proj|down_proj)',
}


def load_model(model_dir: str):
    import torch
    import transformers
    for name in ('AutoModelForCausalLM', 'AutoModelForImageTextToText'):
        try:
            model = getattr(transformers, name).from_pretrained(model_dir, torch_dtype=torch.float16,
                                                               device_map={'': 0}, low_cpu_mem_usage=True)
            return model, name
        except (ValueError, KeyError) as exc:
            last = exc
    raise last


def encode(tok, ex: dict, max_tokens: int):
    kw = dict(tools=ex['tools'] or None, enable_thinking=False, tokenize=False)
    prompt = tok.apply_chat_template(ex['messages'], add_generation_prompt=True, **kw)
    full = tok.apply_chat_template(ex['messages'] + [ex['target']], **kw)
    n = 0
    while n < min(len(prompt), len(full)) and prompt[n] == full[n]:
        n += 1
    head, tail = tok(full[:n], add_special_tokens=False)['input_ids'], tok(full[n:], add_special_tokens=False)['input_ids']
    if len(head) + len(tail) > max_tokens:
        return None
    return head + tail, [-100] * len(head) + tail, full[n:]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--epochs', type=float, default=3)
    p.add_argument('--lr', type=float, default=1e-4)
    p.add_argument('--rank', type=int, default=16)
    p.add_argument('--accum', type=int, default=8)
    p.add_argument('--max-tokens', type=int, default=6144)
    p.add_argument('--targets', choices=sorted(TARGETS), default='full')
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--smoke', action='store_true', help='2 optimizer steps on 4 examples, then save')
    args = p.parse_args(argv)

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoTokenizer
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    tok = AutoTokenizer.from_pretrained(args.model)
    rows = [json.loads(l) for l in args.data.read_text().splitlines() if l.strip()]
    data, skipped = [], 0
    for ex in rows:
        enc = encode(tok, ex, args.max_tokens)
        if enc is None:
            skipped += 1
        else:
            data.append(enc)
    if args.smoke:
        data = data[:4]
    print(json.dumps({'examples': len(data), 'skipped_too_long': skipped,
                      'max_len': max(len(d[0]) for d in data), 'sample_target': data[0][2][:300]}), flush=True)

    model, loader = load_model(args.model)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    model.enable_input_require_grads()
    config = LoraConfig(r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.05, target_modules=TARGETS[args.targets],
                        task_type='CAUSAL_LM')
    model = get_peft_model(model, config)
    for p_ in model.parameters():
        if p_.requires_grad:
            p_.data = p_.data.float()
    trainable = sum(p_.numel() for p_ in model.parameters() if p_.requires_grad)
    print(json.dumps({'loader': loader, 'trainable_params': trainable, 'targets': args.targets}), flush=True)

    params = [p_ for p_ in model.parameters() if p_.requires_grad]
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.0)
    steps_total = 2 if args.smoke else math.ceil(len(data) * args.epochs / args.accum)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / max(1, steps_total // 10)) * max(0.0, 1 - s / steps_total))
    scaler = torch.amp.GradScaler('cuda')
    model.train()
    order, step, micro, t0, losses = [], 0, 0, time.time(), []
    while step < steps_total:
        if not order:
            order = list(range(len(data)))
            random.shuffle(order)
        ids, labels, _ = data[order.pop()]
        x = torch.tensor([ids], device='cuda')
        y = torch.tensor([labels], device='cuda')
        with torch.autocast('cuda', dtype=torch.float16):
            loss = model(input_ids=x, labels=y).loss / args.accum
        scaler.scale(loss).backward()
        losses.append(loss.item() * args.accum)
        micro += 1
        if micro % args.accum == 0:
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            scaler.step(opt)
            scaler.update()
            opt.zero_grad(set_to_none=True)
            sched.step()
            step += 1
            print(json.dumps({'step': step, 'of': steps_total, 'loss': round(sum(losses) / len(losses), 4),
                              'lr': sched.get_last_lr()[0], 'seconds': round(time.time() - t0, 1),
                              'gpu_mb': torch.cuda.max_memory_allocated() // 2**20}), flush=True)
            losses = []
    args.out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.out)
    (args.out / 'train-config.json').write_text(json.dumps(vars(args) | {'data': str(args.data), 'out': str(args.out),
                                                         'examples': len(data), 'steps': steps_total}, default=str))
    print(json.dumps({'saved': str(args.out)}), flush=True)


if __name__ == '__main__':
    main()
