# 自动解析 hexdump /sys/firmware/acpi/tables/TLBI 的结果
#!/usr/bin/env python3
import struct
import sys


def parse_hexdump_file(filename):
    data = bytearray()

    with open(filename, "r") as f:
        for line in f:
            parts = line.strip().split()

            # skip offset column
            for word in parts[1:]:
                if len(word) != 4:
                    continue

                val = int(word, 16)

                # hexdump words are 16-bit little-endian
                data.append(val & 0xFF)
                data.append((val >> 8) & 0xFF)

    return bytes(data)


def u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


def u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def parse_tlbi(data):
    print("==== TLBI TABLE ====")

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
        sub_len = u32(data, offset + 4)
        ident = u32(data, offset + 8)
        ndom = u32(data, offset + 12)
        dom_off = u32(data, offset + 16)

        print(f"  Type      : {typ}")
        print(f"  CPU       : {ident}")
        print(f"  Length    : {sub_len}")
        print(f"  Domains   : {ndom}")
        print(f"  DomOffset : 0x{dom_off:x}")

        domains = []
        for j in range(ndom):
            domains.append(u32(data, dom_off + j * 4))

        print(f"  Domain IDs: {domains}")

        offset += sub_len


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 acpi_check.py tlbi.txt")
        sys.exit(1)

    filename = sys.argv[1]
    data = parse_hexdump_file(filename)
    parse_tlbi(data)


if __name__ == "__main__":
    main()