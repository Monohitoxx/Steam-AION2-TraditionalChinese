"""離線搵新 dat 嘅 AES key：用已知明文（raw table 開頭 01 00 00 00 'AION2'）做驗證。

唔再依賴 v2 容器「頭 32 bytes 係零」嘅假設（新 dat 已經唔係）。
"""
import os
import struct
import sys
import time

from Crypto.Cipher import AES

WS = r'C:\Users\Mono\Desktop\Steam-AION2-TraditionalChinese'
LP = os.path.join(WS, 'tools', 'langpack')
REG = os.path.join(WS, 'regions2')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

NEW_DAT = os.path.join(LP, 'official-en-US.dat')
OLD_DAT = os.path.join(WS, 'langpack', 'L10NString.dat')
OLD_KEY = bytes.fromhex('0cfdab7bcb727e404a20577c83be3399207f02ab68c18f300d36fd3c66cb218e')
MARKERS = (b'AION2', b'\x01\x00\x00\x00AION2')


def body(dat: bytes) -> bytes:
    return dat[0x14:]


def check_key(dat: bytes, key: bytes, span: int = 0x60) -> bool:
    """候選 key 令 body 頭 span bytes 出現已知明文就當命中。"""
    ct = dat[0x14:0x14 + span]
    pt = AES.new(key, AES.MODE_ECB).decrypt(ct)
    return any(m in pt for m in MARKERS)


print('=== 先用舊 key + 舊 dat 驗證方法 ===')
old = open(OLD_DAT, 'rb').read()
print(f'舊 dat {len(old)} bytes；舊 key 測試 =', check_key(old, OLD_KEY))
hdr = AES.new(OLD_KEY, AES.MODE_ECB).decrypt(old[0x14:0x34])
print('舊 dat body 頭 32 bytes 明文:', hdr.hex(' '))

new = open(NEW_DAT, 'rb').read()
print(f'\n新 dat {len(new)} bytes，version={struct.unpack_from("<I", new, 0)[0]}')
print('新 dat 頭 0x40 bytes:', new[:0x40].hex(' '))
print('新 dat 頭兩個 AES block 相同？', new[0x14:0x24] == new[0x24:0x34])

# 掃 region 檔案裡面每個 32-byte 視窗
targets = sys.argv[1:] or ['region_1496e3000.bin', 'region_9e9e0000.bin', 'region_38dc0000.bin']
for name in targets:
    path = os.path.join(REG, name)
    if not os.path.exists(path):
        print(f'{name}: 唔存在')
        continue
    data = open(path, 'rb').read()
    base = int(name.split('_')[1].split('.')[0], 16)
    t0 = time.time()
    hits = []
    for off in range(0, len(data) - 31):
        if data[off:off + 4] in (b'\x00\x00\x00\x00', b'\xff\xff\xff\xff'):
            continue
        key = data[off:off + 32]
        if check_key(new, key):
            hits.append((base + off, key.hex()))
    print(f'\n{name}（0x{base:x}，{len(data)} bytes）：掃 {time.time() - t0:.1f} 秒，命中 {len(hits)}')
    for va, k in hits[:6]:
        print(f'  ★ 候選 key @0x{va:x}: {k}')
    # 舊 key 在唔在？
    if OLD_KEY in data:
        print(f'  （注意：region 內有舊 en-US key @0x{base + data.index(OLD_KEY):x}）')
