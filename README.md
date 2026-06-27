# touchpad-pdk — Porting Palm Pre PDK games to the HP TouchPad

A workspace for patching **Palm Pre webOS PDK games** (native C/C++/ARM `.ipk` packages) so they
run — and look better — on the **HP TouchPad**, while staying backward-compatible with the Pre
where possible.

There is **no source code** for these games. All work is done by **surgically patching the shipped
`.ipk`**: length-preserving binary byte-patches inside the binary, plus small `appinfo.json` /
`metadata.json` edits. The goal is fixing TouchPad-specific breakage (black screens, crashes) and
opportunistically upgrading graphics (MSAA, 32-bit color, anisotropic filtering).

## Why these games break on a TouchPad

A PDK game built for the Pre assumes the Pre's small screen and memory budget. On a TouchPad you
get two recurring failure classes:

1. **Memory-quota death.** The TouchPad's larger framebuffer pushes the app past a Pre-tuned
   `requiredMemory` value, and webOS reaps it. Symptom: menus work, then a black screen / "crash"
   when gameplay loads. (`/var/log/messages` shows `exceeded its memory quota`.) Fix: raise
   `requiredMemory` in `appinfo.json`.
2. **Graphics-state bugs** that the Pre's GL driver tolerated but the TouchPad's does not
   (e.g. a depth clear no-op'd by a depth mask → broken occlusion). Fix: a targeted byte-patch.

A black screen is **not always graphics** — check the memory quota first.

## Tooling you'll want

- **webOS SDK** — for `palm-package`, `palm-install`, `novacom`, and the PDK ARM toolchain
  (`/opt/PalmPDK/arm-gcc`) used to build on-device helpers like GL interposers. Download it from
  the **webOS SDK archive: https://sdk.webosarchive.org**.
- **webos-mcp** — a Model Context Protocol server that gives an AI agent the webOS Archive knowledge
  base (including this porting guide) and device/SDK helpers. Get it from npm:
  **https://www.npmjs.com/package/webos-mcp**. Handy if you're driving this workflow with an AI agent.

## Where to get the games

The `.ipk` files are **not stored in this repo** — they're large binaries that don't belong in
git. Download both the **stock originals** (to patch) and the **published patched builds** from the
**webOS App Museum: https://appcatalog.webosarchive.org**.

## Shipped builds

| Game | File | Notes |
|---|---|---|
| Gameloft DRIVER | `driver/com.gameloft.app.driver_2.2.0_touchpad.ipk` | depth-fix (correct occlusion + sky) |
| Gameloft DRIVER HD | `driver/com.gameloft.app.driverhd_2.0.0_touchpad.ipk` | separate app id; +4× MSAA, 32-bit color, 4× aniso |
| EA Tiger Woods PGA Tour 09 | `tw09/com.ea.app.tw09_1.1.0_all.ipk` | universal: HD on TouchPad, capability-probe fallback to stock on Pre |
| EA Monopoly | `com.ea.app.monopoly_20.1.00_patched_all.ipk` | memory-quota fix only; binary byte-identical to EA's |
| Gameloft N.O.V.A. | `com.gameloft.app.nova_1.1.0_all.ipk` | universal Irrlicht; probe MSAA + 32-bit, `requiredMemory` 86→130 |
| Gameloft Modern Combat: Sandstorm | `com.gameloft.app.sandstorm_1.2.0_all.ipk` | universal Irrlicht; same lift, `requiredMemory` 89→190 |

(The `.ipk`s themselves live in the App Museum, not this repo; the table is the canonical list of shipped builds.)

## Worked example script

`examples/patch_ipk.py` runs the whole loop end to end on EA's Tiger Woods PGA Tour 09:
it (1) **fetches** the stock `.ipk` from the App Museum, (2) **cracks** open the `ar` archive and the
gzipped `data.tar`, (3) **patches** in place — bumps the version, raises `requiredMemory` (the
memory-quota fix), force-sets the executable's tar header to mode `0755` and recomputes its checksum,
and has a slot for length-preserving binary byte-patches — and (4) **rebundles** to a new filename.

```bash
python3 examples/patch_ipk.py                 # fetch + patch -> com.ea.app.tw09_1.0.29_patched_all.ipk
python3 examples/patch_ipk.py --in stock.ipk  # patch a local stock .ipk instead of downloading
```

It uses the safe **length-preserving in-place** edit (no `tarfile` rebuild), so it sidesteps the PAX
partial-install trap. Adapt it to another game by changing the URL, app id, executable member path,
and the patch constants at the top.

## The method (how to repeat this for another game)

1. **Read `touchpad-porting.md` first.** It is the full field guide: on-device GL tracing,
   symptom→cause map, binary-patch + IPK mechanics, the memory-quota bug class, and graphics
   upgrades.
2. **Reproduce on device.** Install the stock `.ipk` on a TouchPad over novacom/USB and find the
   symptom. Check `/var/log/messages` for memory-quota reaps before assuming a graphics bug.
3. **Trace, don't guess.** Use the GL interposer (LD_PRELOAD) to capture the GL call stream and
   locate the offending state. Build any on-device helper with `/opt/PalmPDK/arm-gcc`
   (GCC 4.3.3 / glibc 2.4) — the host cross-gcc links too-new glibc and won't load.
4. **Patch, don't rebuild.** Apply length-preserving byte patches inside the gzipped `data.tar`
   (find member offsets with Python `tarfile` `member.offset_data`). Put added code (MSAA/aniso/
   probe stubs) in a cave inside `.ARM.extab`. Edit `appinfo.json` / `metadata.json` in place,
   same length.
5. **Make graphics universal with a capability probe**, not a device-ID check: request the HD GL
   config, and if `SDL_SetVideoMode` returns NULL, reset attrs and retry the stock config. Trilinear/
   anisotropic are safe to leave unconditional.
6. **Bump the version** in *both* control `Version:` and appinfo `"version"` on every shipped change
   — same-version reinstalls serve stale cached code.
7. **Verify the artifact.** Extract from the final `.ipk` and check control `Package`/`Version`,
   `appinfo.json`, `metadata.json`, and the **binary md5 vs the intended build**. For universal
   builds, confirm the main binary is mode **0755** (the Pre's jailer refuses to exec 0644).
8. **Verify install completeness by on-device file count**, not the installer's exit code — partial
   installs report success.

## Hard rules

- **Never overwrite a stock `.ipk`.** Patch to a new filename (`_touchpad` / `_patched_all` / `_all`;
  big remasters get a `*hd` app id).
- **Repacking games with long asset paths: use `palm-package`, never a Python `tarfile` rebuild**
  (Python 3.12 PAX headers are unparseable by the on-device tar → silent partial install).
- **Don't trust `/dev/fb0` screenshots** for PDK games — rely on the user's eyes.
- Temp/scratch work stays out of this folder.

See **`CLAUDE.md`** for the full conventions and gotchas, and **`touchpad-porting.md`** for the
deep technical guide.
