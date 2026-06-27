#!/usr/bin/env python3
"""
patch_ipk.py — worked example of the Pre→TouchPad IPK patching workflow.

It demonstrates the four steps the field guide describes, end to end, on EA's
Tiger Woods PGA Tour 09:

  1. FETCH    the unpatched, stock .ipk from the webOS App Museum mirror.
  2. CRACK    open the `ar` archive (debian-binary, control.tar.gz, data.tar.gz)
              and the gzipped `data.tar` inside it.
  3. PATCH    in place, *length-preserving*:
                - bump the version in appinfo.json,
                - raise requiredMemory (the memory-quota fix),
                - (optional) apply binary byte-patches to the game executable,
                - force the executable's tar header mode to 0755 (Pre exec bit).
  4. REBUNDLE the `ar` archive to a new filename — never overwriting the stock ipk.

WHY length-preserving / in-place, and not a tarfile rebuild?
  Rebuilding data.tar with Python's tarfile writes PAX extended headers for
  long asset paths that the ancient on-device tar cannot parse -> silent PARTIAL
  install -> the game SIGSEGVs loading a missing asset. So we edit the bytes of
  the ORIGINAL data.tar in place and keep every record exactly the same length.
  That preserves the original's PAX bytes untouched. See touchpad-porting.md.

This is intentionally a *teaching* script: the appinfo edits are real and safe,
and the binary-patch / mode-fix machinery is shown so you can drop in the
offsets you found by tracing for a given game. Run with --help for options.
"""

import argparse
import gzip
import io
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

# --- The game we're working on (override on the command line) ----------------
STOCK_URL = "http://appstorage.webosarchive.org/packages/com.ea.app.tw09_1.0.28_all.ipk"
APP_ID = "com.ea.app.tw09"
# Path of appinfo.json *inside* data.tar. Path style varies by packager: this
# build uses absolute `/usr/...`; the Gameloft Irrlicht games use `./usr/...`.
# Preserve whatever the original uses — we auto-detect below rather than assume.
APPINFO_BASENAME = "appinfo.json"

# --- Patches to apply --------------------------------------------------------
NEW_VERSION = "1.0.29"     # bump BOTH appinfo "version" and control Version:
NEW_REQUIRED_MEMORY = 130  # raise above the observed on-device peak

# Binary byte-patches: (offset_in_member, expected_old_bytes, new_bytes).
# Length-preserving — new must equal old in length. Fill these in from your
# trace/disassembly (e.g. a redirected `bl` to a cave stub). Empty by default.
# The game executable's member path ends with this (here `.../tw09/tw09`); the
# exe basename is NOT the app id, so set it per game from the data.tar listing.
EXE_MEMBER_SUFFIX = "tw09/tw09"
BINARY_PATCHES: list[tuple[int, bytes, bytes]] = [
    # (0x0012ab, b"\x00\xf0", b"\x01\xf0"),
]


# ---------------------------------------------------------------------------
# ar archive: a 8-byte magic "!<arch>\n" then 60-byte headers + 2-aligned data.
# ---------------------------------------------------------------------------
AR_MAGIC = b"!<arch>\n"


def ar_parse(blob: bytes) -> list[dict]:
    """Return the ar members as dicts with name/header/data and their offsets."""
    if blob[:8] != AR_MAGIC:
        sys.exit("not an ar archive (bad magic) — is this really an .ipk?")
    members, pos = [], 8
    while pos + 60 <= len(blob):
        header = blob[pos:pos + 60]
        name = header[0:16].decode("ascii").rstrip()
        size = int(header[48:58].decode("ascii").strip())
        data_start = pos + 60
        members.append({"name": name, "header": header,
                        "data": blob[data_start:data_start + size]})
        pos = data_start + size + (size & 1)  # data is 2-byte aligned
    return members


def ar_build(members: list[dict]) -> bytes:
    out = bytearray(AR_MAGIC)
    for m in members:
        data = m["data"]
        # Rewrite the size field in the 60-byte header in case data length changed
        # (it won't for our length-preserving edits, but keep it honest).
        header = bytearray(m["header"])
        header[48:58] = f"{len(data):<10}".encode("ascii")
        out += header + data
        if len(data) & 1:
            out += b"\n"  # pad to even
    return bytes(out)


# ---------------------------------------------------------------------------
# ustar tar header helpers — for in-place, length-preserving member edits.
# ---------------------------------------------------------------------------
def tar_recompute_checksum(header: bytearray) -> None:
    """Recompute the 512-byte ustar header checksum (cols 148..156)."""
    header[148:156] = b" " * 8  # checksum field is treated as spaces while summing
    chksum = sum(header[:512])
    header[148:156] = f"{chksum:06o}\0 ".encode("ascii")


def find_member_offset(tar_bytes: bytes, predicate) -> tuple[int, int, int]:
    """Locate a member in a raw tar by walking 512-byte records.

    Returns (header_offset, data_offset, size) for the first member whose name
    satisfies predicate(name). We walk manually so we get byte offsets into the
    original buffer (tarfile gives member.offset / member.offset_data too, but
    walking keeps this dependency-free and obvious)."""
    pos = 0
    while pos + 512 <= len(tar_bytes):
        header = tar_bytes[pos:pos + 512]
        if header == b"\0" * 512:
            break
        name = header[0:100].split(b"\0", 1)[0].decode("ascii", "replace")
        size = int(header[124:136].split(b"\0", 1)[0].strip() or b"0", 8)
        data_off = pos + 512
        if predicate(name):
            return pos, data_off, size
        pos = data_off + (size + 511) // 512 * 512
    raise KeyError("member not found")


# ---------------------------------------------------------------------------
# Step 3 patches, all operating on the raw (decompressed) data.tar bytes.
# ---------------------------------------------------------------------------
def patch_appinfo(tar: bytearray) -> None:
    """Length-preserving edits to appinfo.json: version + requiredMemory.

    We keep the JSON byte length identical by padding/trimming whitespace so the
    member's size field and tar layout never change."""
    h_off, d_off, size = find_member_offset(
        tar, lambda n: n.endswith(APPINFO_BASENAME))
    original = bytes(tar[d_off:d_off + size])
    text = original.decode("utf-8")

    text = re.sub(r'("version"\s*:\s*)"[^"]*"',
                  rf'\g<1>"{NEW_VERSION}"', text, count=1)
    # requiredMemory may be a number or a string; normalize to a number. Drop any
    # space after the colon so a longer value (e.g. 67->130) reclaims that byte
    # and keeps the record length-preserving — the field guide's documented trick.
    text = re.sub(r'("requiredMemory"\s*:)\s*("?\d+"?)',
                  rf'\g<1>{NEW_REQUIRED_MEMORY}', text, count=1)

    new = text.encode("utf-8")
    # Re-pad to the original length so the record stays byte-for-byte sized.
    if len(new) < size:
        new += b" " * (size - len(new))   # trailing space is ignored by JSON
    elif len(new) > size:
        # Reclaim space by collapsing runs of whitespace; bail if still too big.
        new = re.sub(rb"[ \t]{2,}", b" ", new)
        if len(new) > size:
            sys.exit(f"appinfo grew {len(new)-size}B and can't be reclaimed — "
                     "use palm-package for this game instead (see field guide)")
        new += b" " * (size - len(new))
    tar[d_off:d_off + size] = new
    print(f"  patched {APPINFO_BASENAME}: version={NEW_VERSION}, "
          f"requiredMemory={NEW_REQUIRED_MEMORY}")


def patch_binary(tar: bytearray) -> None:
    """Apply byte-patches to the game executable and force its mode to 0755."""
    h_off, d_off, size = find_member_offset(
        tar, lambda n: not n.endswith("/") and n.endswith(EXE_MEMBER_SUFFIX))
    for off, old, neu in BINARY_PATCHES:
        if len(old) != len(neu):
            sys.exit(f"non-length-preserving patch at {off:#x}")
        actual = bytes(tar[d_off + off:d_off + off + len(old)])
        if actual != old:
            sys.exit(f"patch guard failed at {off:#x}: "
                     f"expected {old.hex()} got {actual.hex()}")
        tar[d_off + off:d_off + off + len(neu)] = neu
    if BINARY_PATCHES:
        print(f"  applied {len(BINARY_PATCHES)} binary byte-patch(es)")

    # Force mode 0755 so the Pre's jailer will exec() it, then fix the checksum.
    header = bytearray(tar[h_off:h_off + 512])
    header[100:108] = b"0000755\0"  # ustar mode field, octal
    tar_recompute_checksum(header)
    tar[h_off:h_off + 512] = header
    print("  set executable mode 0100755 + recomputed tar header checksum")


def patch_control_version(members: list[dict]) -> None:
    """Bump Version: in the control.tar.gz to match appinfo (stale-cache trap)."""
    for m in members:
        if m["name"].startswith("control.tar"):
            raw = bytearray(gzip.decompress(m["data"]))
            h_off, d_off, size = find_member_offset(
                bytes(raw), lambda n: n.endswith("control"))
            text = raw[d_off:d_off + size].decode("utf-8")
            text = re.sub(r"(?m)^(Version:\s*).*$",
                          rf"\g<1>{NEW_VERSION}", text, count=1)
            new = text.encode("utf-8").ljust(size)[:size]
            raw[d_off:d_off + size] = new
            m["data"] = gzip.compress(bytes(raw))
            print(f"  patched control Version: {NEW_VERSION}")
            return


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=STOCK_URL, help="stock .ipk download URL")
    ap.add_argument("--in", dest="infile",
                    help="use a local stock .ipk instead of downloading")
    ap.add_argument("--out", default=f"{APP_ID}_{NEW_VERSION}_patched_all.ipk",
                    help="output .ipk filename (never the stock name!)")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists():
        sys.exit(f"refusing to overwrite existing {out} — pick a new name")

    # 1) FETCH ---------------------------------------------------------------
    if args.infile:
        print(f"[1/4] reading {args.infile}")
        blob = Path(args.infile).read_bytes()
    else:
        print(f"[1/4] fetching {args.url}")
        with urllib.request.urlopen(args.url) as r:
            blob = r.read()
    print(f"      {len(blob):,} bytes")

    # 2) CRACK ---------------------------------------------------------------
    print("[2/4] cracking ar + gunzip data.tar")
    members = ar_parse(blob)
    data_member = next(m for m in members if m["name"].startswith("data.tar"))
    data_tar = bytearray(gzip.decompress(data_member["data"]))

    # 3) PATCH ---------------------------------------------------------------
    print("[3/4] patching (length-preserving, in place)")
    patch_appinfo(data_tar)
    patch_binary(data_tar)
    patch_control_version(members)
    data_member["data"] = gzip.compress(bytes(data_tar))

    # 4) REBUNDLE ------------------------------------------------------------
    print("[4/4] rebundling ar")
    out.write_bytes(ar_build(members))
    print(f"\nwrote {out} ({out.stat().st_size:,} bytes)")
    print("VERIFY before shipping: extract from the .ipk and check control "
          "Package/Version, appinfo version/requiredMemory, the binary md5, "
          "and on-device install FILE COUNT (not the installer exit code).")


if __name__ == "__main__":
    main()
