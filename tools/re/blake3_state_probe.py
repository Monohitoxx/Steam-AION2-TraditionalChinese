"""睇 region_58d0000.bin 裡面嘅 BLAKE3 結構：IV 周圍係唔係 hasher state（有 block buffer）。
"""
import os
import re
import struct
import sys

WS = r'C:\Users\Mono\Desktop\Steam-AION2-TraditionalChinese'
path = os.path.join(WS, 'regions', 'region_58d0000.bin')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

data = open(path, 'rb').read()
base = 0x58d0000
IV32 = struct.pack('<8I', 0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
                   0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19)
IV64 = struct.pack('<8Q', 0x6A09E667F3BCC908, 0xBB67AE8584CAA73B, 0x3C6EF372FE94F82B,
                   0xA54FF53A5F1D36F1, 0x510E527FADE682D1, 0x9B05688C2B3E6C1F,
                   0x1F83D9ABFB41BD6B, 0x5BE0CD19137E2179)
ROOT = struct.pack('<Q', 0xCD02190910CE83F6)


def show(va, before=0x40, after=0xC0, label=''):
    off = va - base
    lo = max(0, off - before)
    hi = min(len(data), off + after)
    print(f'\n--- {label} VA 0x{va:x}（offset 0x{off:x}）---')
    for i in range(lo, hi, 16):
        row = data[i:i + 16]
        txt = ''.join(chr(b) if 32 <= b < 127 else '.' for b in row)
        print(f'  {base + i:08x}  {row.hex(" "):<47s}  {txt}')


for name, needle in (('IV32', IV32), ('IV64', IV64)):
    i = data.find(needle)
    while i != -1:
        # 睇下有冇邊個 IV 出現位置附近有可讀字串（hasher state 嘅 block buffer 會有）
        window = data[max(0, i - 0x100):i + 0x100]
        runs = [m.group().decode('latin1') for m in re.finditer(rb'[\x20-\x7e]{6,}', window)]
        wide = [m.group().decode('utf-16le', 'replace') for m in
                re.finditer(rb'(?:[\x20-\x7e]\x00){5,}', window)]
        print(f'{name} @0x{base + i:x}  附近 ASCII={runs[:4]} UTF16={wide[:4]}')
        i = data.find(needle, i + 1)

# 逐個 IV32 出現位置前後掃，睇下有冇 root 常數 / 種子字串 / 其他 IV（狀態陣列特徵）
print('\n=== 每個 IV32 出現位置嘅「上一層」係咩（前面 0x20 bytes）===')
i = data.find(IV32)
count = 0
while i != -1 and count < 12:
    prev = data[max(0, i - 0x20):i]
    print(f'  IV32 @0x{base + i:x}  前 0x20: {prev.hex(" ")}')
    i = data.find(IV32, i + 1)
    count += 1

# 呢個 region 有冇 en-US / L10N / blake3 等字串
print('\n=== region 內相關字串 ===')
for needle in (b'en-US', b'L10N', b'blake3', b'BLAKE3', b'String', b'AION2'):
    offs = [m.start() for m in re.finditer(re.escape(needle), data)]
    print(f'  {needle!r}: {len(offs)} 個' + (f'  頭幾個 @' + ' '.join(f'0x{base + o:x}' for o in offs[:5]) if offs else ''))
show(0x58d56a0, 0x40, 0xA0, 'utf16 en-US 位置')
show(0x5968d40, 0x40, 0x140, 'IV64 表')
