"""掃 regions\ 全部檔：熵值、ASCII 字串密度、有冇 code 特徵。"""
import math
import os
import re
import sys

WS = r'C:\Users\Mono\Desktop\Steam-AION2-TraditionalChinese'
REG = os.path.join(WS, 'regions')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def ent(b):
    if not b:
        return 0
    h = [0] * 256
    for x in b:
        h[x] += 1
    return -sum((c / len(b)) * math.log2(c / len(b)) for c in h if c)


rows = []
for name in os.listdir(REG):
    if not name.endswith('.bin'):
        continue
    path = os.path.join(REG, name)
    data = open(path, 'rb').read()
    if not data:
        continue
    base = int(name.split('_')[1].split('.')[0], 16)
    ascii_runs = re.findall(rb'[\x20-\x7e]{6,}', data)
    wide = re.findall(rb'(?:[\x20-\x7e]\x00){4,}', data)
    uniq = len(set(ascii_runs))
    rows.append((base, len(data), ent(data[: 1 << 20]), len(ascii_runs), uniq, len(wide), name,
                 [s.decode('latin1') for s in ascii_runs[:4]]))

rows.sort()
print(f'{"base":>12s} {"size":>10s} {"熵":>5s} {"ascii":>6s} {"uniq":>5s} {"wide":>5s}  樣本字串')
for base, size, e, n, uniq, wide, name, sample in rows:
    print(f'0x{base:010x} {size:10d} {e:5.2f} {n:6d} {uniq:5d} {wide:5d}  {sample}')
