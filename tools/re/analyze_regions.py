"""分析 user 抽落嚟嘅 regions，搵 L10N key 相關結構。"""
import json
import math
import os
import struct
import sys

WS = r'C:\Users\Mono\Desktop\Steam-AION2-TraditionalChinese'
REG = os.path.join(WS, 'regions')
SP = (r'C:\Users\Mono\AppData\Local\Temp\claude\C--Users-Mono-Desktop-Aion2-Chinese-Patch'
      r'\3b238eae-d654-4868-9ad5-e3d47280c29d\scratchpad')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

OLD_KEY = bytes.fromhex('0cfdab7bcb727e404a20577c83be3399207f02ab68c18f300d36fd3c66cb218e')
ROOT = struct.pack('<Q', 0xCD02190910CE83F6)
ROOT_HALVES = [struct.pack('<I', 0x10CE83F6), struct.pack('<I', 0xCD021909)]
SEED = struct.pack('<Q', 12138667997771595427)
IV32 = struct.pack('<8I', 0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A, 0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19)
IV64 = struct.pack('<8Q', 0x6A09E667F3BCC908, 0xBB67AE8584CAA73B, 0x3C6EF372FE94F82B,
                   0xA54FF53A5F1D36F1, 0x510E527FADE682D1, 0x9B05688C2B3E6C1F,
                   0x1F83D9ABFB41BD6B, 0x5BE0CD19137E2179)

try:
    keys = {int(k): bytes.fromhex(v) for k, v in json.load(open(os.path.join(SP, 'keys.json'))).items()}
    KEYSET = {v: k for k, v in keys.items()}
except Exception:
    KEYSET = {}

targets = sys.argv[1:] or ['region_58d0000.bin', 'region_38e0000.bin']


def ent(b):
    if not b:
        return 0
    h = [0] * 256
    for x in b:
        h[x] += 1
    return -sum((c / len(b)) * math.log2(c / len(b)) for c in h if c)


def hits(data, needle):
    out, i = [], data.find(needle)
    while i != -1:
        out.append(i)
        i = data.find(needle, i + 1)
    return out


for name in targets:
    path = os.path.join(REG, name)
    if not os.path.exists(path):
        print(f'{name}: 唔存在')
        continue
    data = open(path, 'rb').read()
    base = int(name.split('_')[1].split('.')[0], 16)
    print(f'\n===== {name}（base 0x{base:x}，{len(data)} bytes）=====')
    blocks = [data[i:i + 4096] for i in range(0, len(data), 4096)]
    profile = ' '.join(f'{ent(b):.1f}' for b in blocks[:16])
    print('  每 4KB 熵值（頭 16 塊）:', profile)
    for label, needle in (('BLAKE3 IV32', IV32), ('BLAKE3 IV64', IV64), ('rootConst', ROOT),
                          ('root½lo', ROOT_HALVES[0]), ('root½hi', ROOT_HALVES[1]), ('seed(en-US)', SEED),
                          ('utf16 L10NString', 'L10NString'.encode('utf-16le')),
                          ('ascii L10NString', b'L10NString'),
                          ('utf16 en-US', 'en-US'.encode('utf-16le')), ('ascii en-US', b'en-US'),
                          ('old en-US key', OLD_KEY)):
        h = hits(data, needle)
        if h:
            print(f'  {label:18s} {len(h):3d} 個 @ ' + ' '.join(f'0x{base + i:x}' for i in h[:6]))
    # 有冇任何已知 key
    found = []
    for i in range(0, len(data) - 31):
        k = data[i:i + 32]
        if k in KEYSET:
            found.append((i, KEYSET[k]))
    if found:
        print(f'  命中 keys.json 嘅 key：{len(found)} 個（頭 3 個）', [(hex(base + i), s) for i, s in found[:3]])
    # 32-byte 對齊、熵高嘅區塊（可能係 key 表）
    kb = name[:-4] + '_keyscan.txt'
    with open(os.path.join(REG, kb), 'w', encoding='utf-8') as fh:
        for i in range(0, len(data) - 31, 8):
            fh.write(data[i:i + 32].hex() + '\n')
