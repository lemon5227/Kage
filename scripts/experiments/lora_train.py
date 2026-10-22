"""P4-L3: LoRA on Agents-A1-4B from student-format teacher demonstrations (Kaggle T4).

  python scripts/experiments/lora_train.py --data sft.jsonl --model DIR --out ADAPTER_DIR
      [--val val.jsonl] [--epochs 3 --lr 1e-4 --rank 16 --max-tokens 6144 --targets full|safe] [--smoke]

Each example is the request the student would send at one step (system prompt, task, earlier tool
calls and results, tool list) and the teacher's next response. The chat template renders both;
loss is applied only to the response tokens (after the longest common prefix of the prompt with
generation header and the full conversation). T4 has no bf16: base weights in fp16, LoRA weights
in fp32 with autocast and gradient checkpointing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import time

TARGETS = {
    # full: every language-model projection; safe: ones llama.cpp's LoRA converter maps 1:1.
    # Text decoder layers only: `model.language_model.layers.N` (image-text loader) or `model.layers.N`
    # (causal-LM loader); vision blocks are `model.visual.blocks.N` and never match.
    # `linear_attn.out_proj` is not safe: the converter reorders its V-head columns, which a LoRA pair
    # cannot do (convert_lora_to_gguf raises NotImplementedError; checked locally at b29c606e2).
    'full': r'(.*\.)?layers\.\d+\.(self_attn|linear_attn|mlp)\.(q_proj|k_proj|v_proj|o_proj|in_proj_qkv|in_proj_z|out_proj|gate_proj|up_proj|down_proj)',
    'safe': r'(.*\.)?layers\.\d+\.(self_attn\.o_proj|mlp\.(gate_proj|up_proj|down_proj))',
}


def load_examples(tok, path: Path, max_tokens: int) -> tuple[list, int]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    data, skipped = [], 0
    for ex in rows:
        enc = encode(tok, ex, max_tokens)
        if enc is None:
            skipped += 1
        else:
            data.append(enc)
    return data, skipped


def response_loss(model, ids: list, labels: list):
    """Mean cross-entropy over the response tokens. The response is the tail of the sequence, so only its
    logits are computed (`logits_to_keep`): with a 248k vocabulary, full-length fp32 logits alone take
    several GB at 6-8k tokens. Same value as `model(input_ids, labels=labels).loss`."""
    import torch
    n = sum(label != -100 for label in labels)
    x = torch.tensor([ids], device=model.device)
    logits = model(input_ids=x, logits_to_keep=n + 1).logits[0, :-1].float()
    return torch.nn.functional.cross_entropy(logits, torch.tensor(ids[-n:], device=model.device))


def validation_loss(model, data: list, dtype=None) -> float:
    """Mean response-token loss over the val set (weighted by each example's response tokens)."""
    import torch
    dtype = dtype or torch.float16
    total, tokens = 0.0, 0
    model.eval()
    with torch.no_grad():
        for ids, labels, _ in data:
            with torch.autocast('cuda', dtype=dtype):
                loss = response_loss(model, ids, labels)
            count = sum(label != -100 for label in labels)
            total += loss.item() * count
            tokens += count
    model.train()
    return total / tokens if tokens else float('nan')


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--val', type=Path, help='validation jsonl; logs val loss after each epoch')
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
    p.add_argument('--checkpoint-every', type=int, default=0,
                   help='save a resumable checkpoint (OUT-ckpt.pt) every N optimizer steps; an existing one is resumed')
    p.add_argument('--save-optimizer', action='store_true',
                   help='also save the AdamW state with the trainable parameter names (LESS warmup, R3c)')
    p.add_argument('--save-epochs', action='store_true',
                   help='also save the adapter after every completed epoch except the last (OUT-epochN)')
    p.add_argument('--dtype', choices=['auto', 'fp16', 'bf16'], default='auto',
                   help='auto: bf16 where supported (A100), else fp16 with a loss scaler (T4)')
    return p


def loss_record(epoch: int, step: int, train_loss: float, val_loss: float | None = None) -> dict:
    """One train-log row; takes plain floats so the writer is testable without torch."""
    return {'epoch': epoch, 'step': step, 'train_loss': round(float(train_loss), 6),
            'val_loss': None if val_loss is None else round(float(val_loss), 6)}


class TrainLog:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('')

    def append(self, row: dict) -> None:
        with self.path.open('a') as out:
            out.write(json.dumps(row) + '\n')


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def load_model(model_dir: str, dtype=None):
    import torch
    import transformers
    for name in ('AutoModelForCausalLM', 'AutoModelForImageTextToText'):
        try:
            model = getattr(transformers, name).from_pretrained(model_dir, dtype=dtype or torch.float16,
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
    args = build_parser().parse_args(argv)
    started = time.time()

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoTokenizer
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    tok = AutoTokenizer.from_pretrained(args.model)
    data_sha256 = sha256_file(args.data)
    data, skipped = load_examples(tok, args.data, args.max_tokens)
    val_data, val_skipped = load_examples(tok, args.val, args.max_tokens) if args.val else ([], 0)
    if args.val and not val_data:
        raise SystemExit(f'--val {args.val} produced no usable examples')
    if args.smoke:
        # the longest example first: a smoke run must hit the peak memory of the real run
        data = sorted(data, key=lambda d: len(d[0]), reverse=True)[:4]
        val_data = val_data[:16]
    use_bf16 = args.dtype == 'bf16' or (args.dtype == 'auto' and torch.cuda.is_bf16_supported())
    dtype = torch.bfloat16 if use_bf16 else torch.float16
    print(json.dumps({'examples': len(data), 'skipped_too_long': skipped,
                      'max_len': max(len(d[0]) for d in data), 'sample_target': data[0][2][:300]}), flush=True)

    model, loader = load_model(args.model, dtype)
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
    # fp16 needs a loss scaler; bf16 has fp32's range, so the scaler is disabled (a no-op) there.
    # Colab smoke 10-21: fp16 overflow made the scaler skip both smoke steps and lora_B stayed all zero.
    scaler = torch.amp.GradScaler('cuda', enabled=not use_bf16)
    model.train()
    args.out.mkdir(parents=True, exist_ok=True)
    train_log = TrainLog(args.out / 'train-log.jsonl') if args.val else None
    order, step, micro, t0, losses = [], 0, 0, time.time(), []
    epoch, logged_epoch, epoch_losses, recent = 0, 0, [], []

    def epoch_val() -> float | None:
        return validation_loss(model, val_data, dtype) if val_data else None

    # Colab recycled the A100 mid-run twice (10-22); a checkpoint every N optimizer steps (on the user's Drive when
    # KAGE_WORK points there) lets a reconnected runtime continue instead of starting over.
    ckpt_path = args.out.parent / f'{args.out.name}-ckpt.pt'
    trainable_named = [(n_, p_) for n_, p_ in model.named_parameters() if p_.requires_grad]

    def save_checkpoint() -> None:
        state = {'params': {n_: p_.detach().cpu() for n_, p_ in trainable_named}, 'opt': opt.state_dict(),
                 'sched': sched.state_dict(), 'scaler': scaler.state_dict(), 'step': step, 'micro': micro,
                 'epoch': epoch, 'logged_epoch': logged_epoch, 'order': order, 'epoch_losses': epoch_losses,
                 'recent': recent, 'py_random': random.getstate(), 'torch_rng': torch.get_rng_state(),
                 'cuda_rng': torch.cuda.get_rng_state(), 'steps_total': steps_total}
        tmp = ckpt_path.with_suffix('.tmp')
        torch.save(state, tmp)
        tmp.replace(ckpt_path)

    if args.checkpoint_every and ckpt_path.exists():
        state = torch.load(ckpt_path, map_location='cpu', weights_only=False)
        if state['steps_total'] != steps_total:
            raise SystemExit(f'checkpoint {ckpt_path} is for {state["steps_total"]} steps, not {steps_total}')
        with torch.no_grad():
            for n_, p_ in trainable_named:
                p_.copy_(state['params'][n_].to(p_.device))
        opt.load_state_dict(state['opt'])
        sched.load_state_dict(state['sched'])
        scaler.load_state_dict(state['scaler'])
        step, micro, epoch, logged_epoch = state['step'], state['micro'], state['epoch'], state['logged_epoch']
        order, epoch_losses, recent = state['order'], state['epoch_losses'], state['recent']
        random.setstate(state['py_random'])
        torch.set_rng_state(state['torch_rng'])
        torch.cuda.set_rng_state(state['cuda_rng'])
        print(json.dumps({'resumed_from': str(ckpt_path), 'step': step, 'epoch': epoch}), flush=True)

    while step < steps_total:
        if not order:
            if epoch:
                if train_log is not None:
                    train_log.append(loss_record(epoch, step, sum(epoch_losses) / len(epoch_losses), epoch_val()))
                logged_epoch = epoch
                if args.save_epochs:     # R3b: earlier epochs are early-stopping candidates for the transfer check
                    model.save_pretrained(args.out.parent / f'{args.out.name}-epoch{epoch}')
            epoch += 1
            epoch_losses, recent = [], []
            order = list(range(len(data)))
            random.shuffle(order)
        ids, labels, _ = data[order.pop()]
        with torch.autocast('cuda', dtype=dtype):
            loss = response_loss(model, ids, labels) / args.accum
        scaler.scale(loss).backward()
        raw = loss.item() * args.accum
        losses.append(raw)
        epoch_losses.append(raw)
        recent.append(raw)
        micro += 1
        if micro % args.accum == 0:
            scaler.unscale_(opt)
            grad_norm = float(torch.nn.utils.clip_grad_norm_(params, 1.0))
            scaler.step(opt)
            scaler.update()
            opt.zero_grad(set_to_none=True)
            sched.step()
            step += 1
            print(json.dumps({'step': step, 'of': steps_total, 'loss': round(sum(losses) / len(losses), 4),
                              'lr': sched.get_last_lr()[0], 'grad_norm': round(grad_norm, 4),
                              'scale': scaler.get_scale() if scaler.is_enabled() else None,
                              'seconds': round(time.time() - t0, 1),
                              'gpu_mb': torch.cuda.max_memory_allocated() // 2**20}), flush=True)
            if train_log is not None and step % 10 == 0:
                train_log.append(loss_record(epoch, step, sum(recent) / len(recent)))
                recent = []
            losses = []
            if args.checkpoint_every and step % args.checkpoint_every == 0 and step < steps_total:
                save_checkpoint()
    if train_log is not None and epoch > logged_epoch:
        train_log.append(loss_record(epoch, step, sum(epoch_losses) / len(epoch_losses), epoch_val()))

    wall = round(time.time() - started, 1)
    peak_gpu_mb = torch.cuda.max_memory_allocated() // 2**20
    lora_b_max = max(float(p_.detach().abs().max()) for n_, p_ in model.named_parameters() if 'lora_B' in n_)
    model.save_pretrained(args.out)
    if ckpt_path.exists():
        ckpt_path.unlink()                                 # finished: a rerun must not resume a stale checkpoint
    if args.save_optimizer:
        names = [n_ for n_, p_ in model.named_parameters() if p_.requires_grad]
        torch.save({'names': names, 'state': opt.state_dict(), 'betas': opt.param_groups[0]['betas'],
                    'eps': opt.param_groups[0]['eps']}, args.out / 'optimizer.pt')
    (args.out / 'train-config.json').write_text(json.dumps(
        vars(args) | {'data': str(args.data), 'out': str(args.out), 'val': str(args.val) if args.val else None,
                      'data_sha256': data_sha256, 'examples': len(data), 'skipped_too_long': skipped,
                      'val_examples': len(val_data), 'val_skipped_too_long': val_skipped,
                      'steps': steps_total, 'wall_seconds': wall, 'peak_gpu_mb': peak_gpu_mb,
                      'dtype': 'bf16' if use_bf16 else 'fp16', 'lora_b_max_abs': lora_b_max}, default=str))
    print(json.dumps({'saved': str(args.out), 'lora_b_max_abs': lora_b_max}), flush=True)
    if lora_b_max == 0.0:
        # lora_B starts at zero: still zero means no optimizer step changed the adapter (skipped or no grads).
        raise SystemExit('adapter unchanged after training (all lora_B == 0); refusing to hand it to eval')


if __name__ == '__main__':
    main()
