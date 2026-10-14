"""Regression checks for plaintext, encrypted and legacy compressed entries."""
import hashlib
import pathlib
import struct
import tempfile
import unittest
from unittest.mock import patch

from Crypto.Cipher import AES
import pak_extract


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = pathlib.Path(self.temp.name) / 'fixture.pak'
        self.payload = struct.pack('<I', 2) + bytes(range(33))
        self.key = bytes(range(32))
        self.footer = bytearray(221)
        struct.pack_into('<II', self.footer, 17, pak_extract.PAK_MAGIC, 11)

    def write_entry(self, encrypted=False):
        size = len(self.payload)
        stored = self.payload
        if encrypted:
            stored = AES.new(self.key, AES.MODE_ECB).encrypt(stored + bytes(-size % 16))
        header = (struct.pack('<qqqi', 0, size, size, 0)
                  + hashlib.sha1(stored[:size]).digest()
                  + bytes([int(encrypted)]) + struct.pack('<I', 0))
        self.path.write_bytes(header + stored + self.footer)

    def test_plaintext(self):
        self.write_entry()
        self.assertEqual(pak_extract.extract_dat(str(self.path)), self.payload)

    def test_encrypted_with_padding(self):
        self.write_entry(True)
        with patch.object(pak_extract, 'load_pak_key', return_value=self.key):
            self.assertEqual(pak_extract.extract_dat(str(self.path)), self.payload)

    def test_corruption(self):
        self.write_entry(True)
        data = bytearray(self.path.read_bytes()); data[60] ^= 1
        self.path.write_bytes(data)
        with self.assertRaisesRegex(RuntimeError, 'SHA-1'):
            pak_extract.extract_dat(str(self.path))

    def test_wrong_key(self):
        self.write_entry(True)
        with patch.object(pak_extract, 'load_pak_key', return_value=bytes(32)):
            with self.assertRaisesRegex(RuntimeError, 'v2'):
                pak_extract.extract_dat(str(self.path))

    def test_truncation(self):
        self.write_entry()
        data = bytearray(self.path.read_bytes())
        struct.pack_into('<qq', data, 8, 1000, 1000)
        self.path.write_bytes(data)
        with self.assertRaisesRegex(RuntimeError, '長度'):
            pak_extract.extract_dat(str(self.path))

    def test_legacy_compressed_entry(self):
        stored = b'block'
        header = (struct.pack('<qqqi', 0, len(stored), len(self.payload), 1)
                  + bytes(20) + struct.pack('<iQQBI', 1, 73, 78, 0, 65536))
        self.path.write_bytes(header + stored + self.footer)
        with patch.object(pak_extract.ooz, 'decompress', return_value=self.payload) as decoder:
            self.assertEqual(pak_extract.extract_dat(str(self.path)), self.payload)
            decoder.assert_called_once_with(stored, len(self.payload))


if __name__ == '__main__':
    unittest.main()
