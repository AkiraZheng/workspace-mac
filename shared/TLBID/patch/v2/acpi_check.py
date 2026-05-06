# 自动解析 hexdump /sys/firmware/acpi/tables/TLBI 的结果
#!/usr/bin/env python3
import struct
import sys

def parse_hexdump_file(filename):
data = bytearray()

```
with open(filename, "r") as f:
    for line in f:
        parts = line.strip().split()

        # 跳过 offset
        for word in parts[1:]:
            if len(word) != 4:
                continue

            val = int(word, 16)

            # 小端 16-bit → bytes
            data.append(val & 0xFF)
            data.append((val >> 8) & 0xFF)

return bytes(data)
```

def u16(b, o): return struct.unpack_from("<H", b, o)[0]
def u32(b, o): return struct.unpack_from("<I", b, o)[0]

def parse_tlbi(data):
print("==== TLBI TABLE ====")

```
sig = data[0:4].decode()
length = u32(data, 4)

print(f"Signature : {sig}")
print(f"Length    : {length}")

comp_num = u32(data, 36)
print(f"Components: {comp_num}")

offset = 40

for i in range(comp_num):
    print(f"\nComponent {i} @ 0x{offset:x}")

    typ = u16(data, offset)
    length = u32(data, offset + 4)
    ident = u32(data, offset + 8)
    ndom = u32(data, offset + 12)
    dom_off = u32(data, offset + 16)

    print(f"  Type      : {typ}")
    print(f"  CPU       : {ident}")
    print(f"  Domains   : {ndom}")
    print(f"  DomOffset : 0x{dom_off:x}")

    domains = []
    for j in range(ndom):
        domains.append(u32(data, dom_off + j * 4))

    print(f"  Domain IDs: {domains}")

    offset += length
```

if **name** == "**main**":
if len(sys.argv) != 2:
print("Usage: python3 tlbi_parser.py tlbi.txt")
sys.exit(1)

```
binary = parse_hexdump_file(sys.argv[1])
parse_tlbi(binary)
```
