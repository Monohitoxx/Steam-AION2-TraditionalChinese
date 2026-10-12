"""喺所有抽到嘅 region 裡面搵「邊個 region 引用 BLAKE3 IV 表 / root 常數」。
（RIP-relative disp32 可以跨 region，所以逐個 region 用返佢自己嘅 VA base 掃。）
"""
import os
import struct
import sys

WS = r'C:\Users\Mono\Desktop\Steam-AION2-TraditionalChinese'
REG = os.path.join(WS, 'regions')
sys.path.insert(0, os.path.join(WS, 'tools', 're'))
import xref as X  # noqa: E402

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

IV64 = b''.join(struct.pack('<Q', v) for v in
                (0x6A09E667F3BCC908, 0xBB67AE8584CAA73B, 0x3C6EF372FE94F82B, 0xA54FF53A5F1D36F1,
                 0x510E527FADE682D1, 0x9B05688C2B3E6C1F, 0x1F83D9ABFB41BD6B, 0x5BE0CD19137E2179))
IV32 = b''.join(struct.pack('<I', v) for v in
                (0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A, 0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19))

# 已知嘅 IV 表 VA（由上次掃描得知）
TARGET_VAS = {
    'blake3 IV64 table': 0x5968d40,
    'blake3 IV32 table': 0x5968e40,
}

print('目標 VA：', {k: hex(v) for k, v in TARGET_VAS.items()})
SPAN = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0
print('span =', SPAN)
for name in sorted(os.listdir(REG)):
    if not name.endswith('.bin'):
        continue
    path = os.path.join(REG, name)
    size = os.path.getsize(path)
    if size > 16 << 20:      # 跳過 128MB 嘅 stub 抽樣
        continue
    data = open(path, 'rb').read()
    base = int(name.split('_')[1].split('.')[0], 16)
    hits = X.scan_xrefs(data, base, TARGET_VAS, span=SPAN)
    total = sum(len(v) for v in hits.values())
    if total:
        print(f'\n{name}（base 0x{base:x}，{size} bytes）：{total} 個引用')
        for tname, sites in hits.items():
            for start, disp_off in sites[:6]:
                print(f'  {tname} <- 指令 @0x{base + start:x}')
                lo = max(0, start - 32)
                chunk = data[lo:start + 32]
                for i in range(0, len(chunk), 16):
                    print(f'     {base + lo + i:012x}  ' + chunk[i:i + 16].hex(' '))
