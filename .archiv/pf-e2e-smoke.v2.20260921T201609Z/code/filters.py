"""Bloom- und Cuckoo-Filter, nur Python-Stdlib.

Beide Filter werden fuer eine feste Designkapazitaet N konfiguriert.
Die "Last" eines Laufs ist n / N, wobei n die Anzahl eingefuegter
Elemente ist. Alle Hashes kommen aus hashlib (sha256) und sind damit
plattform- und versionsdeterministisch.
"""

import hashlib


def _digest(item, tag=b""):
    return hashlib.sha256(item.to_bytes(8, "big") + tag).digest()


def _hash_pair(item, m):
    d = _digest(item)
    h1 = int.from_bytes(d[:8], "big") % m
    h2 = (int.from_bytes(d[8:16], "big") % (m - 1)) + 1
    return h1, h2


class BloomFilter:
    """Klassischer Bloom-Filter mit Double Hashing (Kirsch-Mitzenmacher)."""

    def __init__(self, capacity, bits_per_element=8, num_hashes=6):
        self.m = capacity * bits_per_element
        self.k = num_hashes
        self.bits = bytearray(self.m // 8 + 1)

    def _positions(self, item):
        h1, h2 = _hash_pair(item, self.m)
        for i in range(self.k):
            yield (h1 + i * h2) % self.m

    def add(self, item):
        for pos in self._positions(item):
            self.bits[pos >> 3] |= 1 << (pos & 7)
        return True

    def __contains__(self, item):
        return all(
            self.bits[pos >> 3] & (1 << (pos & 7)) for pos in self._positions(item)
        )


class CuckooFilter:
    """Einfacher Cuckoo-Filter nach Fan et al. (2014).

    Fingerprints in Buckets mit partial-key cuckoo hashing: aus dem
    Bucket-Index und dem Fingerprint laesst sich der Alternativ-Bucket
    berechnen, ohne das Originalelement zu kennen.
    """

    def __init__(self, capacity, num_buckets=4096, bucket_size=4,
                 fingerprint_bits=12, max_kicks=500):
        self.num_buckets = num_buckets
        self.bucket_size = bucket_size
        self.fp_bits = fingerprint_bits
        self.max_kicks = max_kicks
        self.table = [[0] * bucket_size for _ in range(num_buckets)]

    def _fingerprint(self, item):
        fp = int.from_bytes(_digest(item, b"fp")[:2], "big") & ((1 << self.fp_bits) - 1)
        return fp or 1  # 0 ist reserviert fuer "Slot leer"

    def _index(self, item):
        return int.from_bytes(_digest(item, b"ix")[:8], "big") % self.num_buckets

    def _alt_index(self, index, fp):
        h = int.from_bytes(_digest(fp, b"alt")[:8], "big") % self.num_buckets
        return (index ^ h) % self.num_buckets

    def _try_place(self, index, fp):
        bucket = self.table[index]
        for slot in range(self.bucket_size):
            if bucket[slot] == 0:
                bucket[slot] = fp
                return True
        return False

    def add(self, item):
        fp = self._fingerprint(item)
        i1 = self._index(item)
        i2 = self._alt_index(i1, fp)
        if self._try_place(i1, fp) or self._try_place(i2, fp):
            return True
        i = i1
        for _ in range(self.max_kicks):
            slot = (fp + i) % self.bucket_size
            self.table[i][slot], fp = fp, self.table[i][slot]
            i = self._alt_index(i, fp)
            if self._try_place(i, fp):
                return True
        return False

    def __contains__(self, item):
        fp = self._fingerprint(item)
        i1 = self._index(item)
        i2 = self._alt_index(i1, fp)
        return fp in self.table[i1] or fp in self.table[i2]
