"""Test script for verifying TLV encoding and decoding behavior."""

import binascii

from chip.tlv import TLVReader, TLVWriter

# Create a structure with tags 1, 2, 7
writer = TLVWriter()
writer.put(None, {1: 10, 2: 20, 7: 30})
encoded = writer.encoding
print("Encoded:", binascii.hexlify(encoded).decode())

# Read it back
reader = TLVReader(encoded)
decoded = reader.get()["Any"]
print("Decoded:", decoded)

# Modify and write back
decoded[1] = 100
writer2 = TLVWriter()
writer2.put(None, decoded)
encoded2 = writer2.encoding
print("Re-encoded:", binascii.hexlify(encoded2).decode())

# Read again
reader3 = TLVReader(encoded2)
print("Final decoded:", reader3.get()["Any"])
