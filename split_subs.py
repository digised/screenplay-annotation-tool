#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re
import sys
import argparse

MIN_MS = 800
BASE_WEIGHT = 6
GAP_MS = 0
SPLIT_ON_PUNCT = False

CTRL = '\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufeff'
DASH = r'\-–—'

TIME_RE = re.compile(
    r'^\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*'
    r'((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})(.*)$'
)
SLASH_RE = re.compile(r'\s*/(?:\s+-?|-)\s*')
PUNCT_RE = re.compile(r'(?<=[؟?!])\s+|(?<=[^.\s]\.)\s+')


def to_ms(t):
    t = t.replace(',', '.')
    parts = t.split(':')
    sec, ms = parts[-1].split('.')
    ms = int(ms.ljust(3, '0')[:3])
    h = int(parts[-3]) if len(parts) == 3 else 0
    return ((h * 60 + int(parts[-2])) * 60 + int(sec)) * 1000 + ms


def fmt(ms, sep):
    h, r = divmod(ms, 3600000)
    m, r = divmod(r, 60000)
    s, ms = divmod(r, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def clean(s):
    s = s.strip(CTRL + ' \t')
    s = re.sub(rf'^[{DASH}]+\s*', '', s)
    s = re.sub(rf'\s*[{DASH}]+$', '', s)
    s = s.strip(CTRL + ' \t')
    return '\n'.join(x.strip(CTRL + ' \t') for x in s.split('\n')).strip()


def has_marker(line):
    l = line.strip(CTRL + ' \t')
    return bool(re.match(rf'^[{DASH}]', l)) or bool(re.search(rf'\s[{DASH}]$', l))


def split_text(lines, punct=False):
    marked = any(has_marker(l) for l in lines)
    if marked:
        pieces = []
        for l in lines:
            pieces += SLASH_RE.split(l)
    else:
        pieces = SLASH_RE.split('\n'.join(lines))
        if len(pieces) == 1 and not punct:
            return None

    pieces = [clean(p) for p in pieces]
    if punct:
        tmp = []
        for p in pieces:
            tmp += [clean(x) for x in PUNCT_RE.split(p)]
        pieces = tmp
    pieces = [p for p in pieces if p]
    return pieces or None


def allocate(total, weights, min_ms):
    n = len(weights)
    min_ms = min(min_ms, total // n)
    fixed = set()
    while True:
        free = [i for i in range(n) if i not in fixed]
        if not free:
            break
        rem = total - min_ms * len(fixed)
        wsum = sum(weights[i] for i in free)
        low = [i for i in free if rem * weights[i] / wsum < min_ms]
        if not low:
            break
        fixed.update(low)
    free = [i for i in range(n) if i not in fixed]
    rem = total - min_ms * len(fixed)
    wsum = sum(weights[i] for i in free) or 1
    bounds, acc = [0], 0.0
    for i in range(n):
        acc += min_ms if i in fixed else rem * weights[i] / wsum
        bounds.append(int(round(acc)))
    bounds[-1] = total
    return bounds


def process(text, min_ms, gap_ms, punct):
    text = text.replace('\r\n', '\n').replace('\r', '\n').lstrip('\ufeff')
    is_vtt = text.lstrip().startswith('WEBVTT')
    sep = '.' if is_vtt else ','
    blocks = re.split(r'\n[ \t]*\n', text.strip('\n'))

    use_ids = (not is_vtt) or any(
        len(b.split('\n')) > 1 and TIME_RE.match(b.split('\n')[1]) for b in blocks
    )

    out, idx, n_in = [], 1, 0
    for block in blocks:
        lines = block.split('\n')
        t_i = next((i for i, l in enumerate(lines) if TIME_RE.match(l)), None)
        if t_i is None:
            out.append(block)
            continue

        n_in += 1
        m = TIME_RE.match(lines[t_i])
        start, end, settings = to_ms(m.group(1)), to_ms(m.group(2)), m.group(3)
        body = lines[t_i + 1:]
        pieces = split_text(body, punct) if body else None

        if pieces is None or len(pieces) == 1 or end <= start:
            body_text = '\n'.join(body) if pieces is None else pieces[0]
            parts = [(start, end, body_text)]
        else:
            weights = [len(re.sub(r'\s', '', p)) + BASE_WEIGHT for p in pieces]
            bounds = allocate(end - start, weights, min_ms)
            parts = []
            for i, p in enumerate(pieces):
                s = start + bounds[i]
                e = start + bounds[i + 1]
                if i < len(pieces) - 1 and gap_ms:
                    e = max(s + 1, e - gap_ms)
                parts.append((s, e, p))

        for s, e, t in parts:
            head = f"{idx}\n" if use_ids else ""
            out.append(f"{head}{fmt(s, sep)} --> {fmt(e, sep)}{settings}\n{t}")
            idx += 1

    print(f"کیوهای ورودی: {n_in} | کیوهای خروجی: {idx - 1}")
    return '\n\n'.join(out) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input')
    ap.add_argument('-o', '--output')
    ap.add_argument('--min', type=int, default=MIN_MS, help='حداقل مدت هر جمله (ms)')
    ap.add_argument('--gap', type=int, default=GAP_MS, help='فاصله بین جمله‌ها (ms)')
    ap.add_argument('--punct', action='store_true', default=SPLIT_ON_PUNCT,
                    help='جدا کردن جمله‌ها با . ؟ ! هم')
    a = ap.parse_args()

    out_path = a.output or re.sub(r'(\.\w+)$', r'_split\1', a.input)
    with open(a.input, 'r', encoding='utf-8-sig') as f:
        data = f.read()
    result = process(data, a.min, a.gap, a.punct)
    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(result)
    print("ذخیره شد:", out_path)


if __name__ == '__main__':
    main()