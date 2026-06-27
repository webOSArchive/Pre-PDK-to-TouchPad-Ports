# examples/ — teaching material, not a turnkey patcher

This folder holds a **worked example** of the Pre→TouchPad IPK patching workflow. It exists to show
the *shape* of the process end to end, so a dev (or their AI agent) can see how the pieces fit
together before doing the real work on their own game.

> **This is a teaching script, not a tool.** `patch_ipk.py` is hard-wired to one game (EA's Tiger
> Woods PGA Tour 09) and applies a deliberately minimal, safe set of edits. Do not expect to point it
> at another `.ipk` and get a working port. Read it, understand each step, then write the patches your
> game actually needs.

## `patch_ipk.py`

Runs the four steps the field guide describes, end to end:

1. **Fetch** the stock `.ipk` from the webOS App Museum mirror.
2. **Crack** open the `ar` archive (`debian-binary`, `control.tar.gz`, `data.tar.gz`) and gunzip the
   inner `data.tar`.
3. **Patch**, *length-preserving and in place*:
   - bump the version in `appinfo.json` **and** the control `Version:`,
   - raise `requiredMemory` (the memory-quota fix), reclaiming the byte by dropping the space after
     the colon so the record stays the same length,
   - force the game executable's tar header to mode `0755` and recompute its checksum (so the Pre's
     jailer will `exec()` it),
   - a guarded slot for **binary byte-patches** — empty by default.
4. **Rebundle** the `ar` to a new filename (it refuses to overwrite an existing file — never clobber
   a stock `.ipk`).

```bash
python3 patch_ipk.py                  # fetch + patch -> com.ea.app.tw09_1.0.29_patched_all.ipk
python3 patch_ipk.py --in stock.ipk   # patch a local stock .ipk instead of downloading
python3 patch_ipk.py --help
```

It uses the **length-preserving in-place** approach (it never rebuilds `data.tar` with Python's
`tarfile`), so it sidesteps the PAX-header partial-install trap described in `../touchpad-porting.md`.

## The patches are different for every game

There is **no universal patch.** Each game breaks for its own reason and needs its own fix, found by
the diagnosis loop in the field guide (reproduce on device → check the memory log → GL-trace →
disassemble). What changes from game to game:

- **The download URL, app id, and the executable's member path** inside `data.tar` (here the exe is
  `…/tw09/tw09`, whose basename is *not* the app id — you must read the real path from the tar listing
  for your game).
- **`requiredMemory`** — the right value is whatever sits just above the *observed on-device peak*,
  not a fixed number. Keep the bump modest so the original Pre still passes its launch-time RAM check.
- **The binary byte-patches** — this is the part that's genuinely per-game and that this script leaves
  empty on purpose. The actual offsets, the original bytes to guard against, and the replacement
  bytes (e.g. redirecting a `bl` to a code-cave stub for the depth-mask fix, MSAA, or anisotropy) all
  come from tracing and disassembling *that specific binary*. Some games need a graphics byte-patch;
  some (like EA Monopoly) need only the `appinfo.json` memory bump and no binary change at all.
- **Whether you can in-place patch at all.** This example only edits bytes inside the original
  `data.tar`. If your changes alter file *lengths* or you must restage the app directory, repack with
  `palm-package`, not a `tarfile` rebuild — see the field guide.

## Always verify the artifact

Whatever you patch, confirm it before shipping — extract from the *final* `.ipk` and check the control
`Package`/`Version`, the `appinfo.json` `version`/`requiredMemory`, the binary's md5 against your
intended build, the executable's mode (`0755`), and — on device — the install **file count**, never
the installer's exit code (partial installs report success). See `../CLAUDE.md` and
`../touchpad-porting.md` for the full method and the hard-won gotchas.
