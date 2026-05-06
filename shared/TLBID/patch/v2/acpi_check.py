#!/usr/bin/env python3
import struct
import sys

# 自动解析 hexdump /sys/firmware/acpi/tables/TLBI 的结果

def read_u16(buf, off):
return struct.unpack_from("<H", buf, off)[0]

def read_u32(buf, off):
return struct.unpack_from("<I", buf, off)[0]

def parse_tlbi(data):
print("==== TLBI TABLE PARSE ====")

```
# Header
sig = data[0:4].decode()
length = read_u32(data, 4)
revision = data[8]
checksum = data[9]

print(f"Signature: {sig}")
print(f"Length   : {length}")
print(f"Revision : {revision}")
print(f"Checksum : {checksum}")

if sig != "TLBI":
    print("❌ Invalid signature")
    return

if length != len(data):
    print("❌ Length mismatch")

# Verify checksum
if sum(data) & 0xFF != 0:
    print("❌ Checksum invalid")
else:
    print("✅ Checksum OK")

# Number of components
comp_num = read_u32(data, 36)
print(f"\nNumber of components: {comp_num}")

# Subtable parsing starts at offset 40
offset = 40
comp_idx = 0

print("\n==== COMPONENTS ====")

while offset < len(data) and comp_idx < comp_num:
    start = offset

    typ = read_u16(data, offset)
    res = read_u16(data, offset + 2)
    length = read_u32(data, offset + 4)
    ident = read_u32(data, offset + 8)
    ndom = read_u32(data, offset + 12)
    dom_off = read_u32(data, offset + 16)

    print(f"\nComponent #{comp_idx}")
    print(f"  Type       : {typ} ({'PE' if typ==1 else 'SMMU' if typ==2 else 'UNKNOWN'})")
    print(f"  Identifier : {ident}")
    print(f"  Length     : {length}")
    print(f"  Domains    : {ndom}")
    print(f"  DomOffset  : 0x{dom_off:x}")

    # Validate length
    expected_len = 20 + ndom * 4
    if length != expected_len:
        print(f"  ❌ Length mismatch (expected {expected_len})")

    # Validate domain offset
    if dom_off < start or dom_off >= len(data):
        print("  ❌ Domain offset out of range")

    # Read domains
    domains = []
    for i in range(ndom):
        dom = read_u32(data, dom_off + i * 4)
        domains.append(dom)

    print(f"  Domain IDs : {domains}")

    # Move to next subtable
    offset += length
    comp_idx += 1

# Final checks
if comp_idx != comp_num:
    print("\n❌ Component count mismatch")
else:
    print("\n✅ Component count OK")

if offset != len(data):
    print(f"\n⚠️ Table parsing ended at 0x{offset:x}, total 0x{len(data):x}")
else:
    print("\n✅ Table fully consumed")
```

if **name** == "**main**":
if len(sys.argv) != 2:
print("Usage: tlbi_parser.py <TLBI binary>")
sys.exit(1)

```
with open(sys.argv[1], "rb") as f:
    data = f.read()

parse_tlbi(data)
```
