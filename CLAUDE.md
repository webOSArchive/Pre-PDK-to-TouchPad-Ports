# CLAUDE.md — Pre → TouchPad PDK game-porting workspace

This folder is a workspace for patching **Palm Pre webOS PDK games** (native C/C++/ARM `.ipk`s) so they run — and look better — on the **HP TouchPad**, while staying Pre-compatible where possible. All work is done by **surgical patching of the shipped `.ipk`** (binary byte-patches and/or `appinfo.json` edits); there is no source.

> This is the **PDK `.ipk`-patching track**. The Android NDK shim track (apkenv-based wrapper) now lives in a separate workspace at `/home/jonwise/Projects/webos-android`.

## Start here
- **`touchpad-porting.md`** (this folder) — the full field guide for **patching shipped PDK `.ipk`s**: on-device GL tracing, symptom→cause map, binary-patch + IPK mechanics, the memory-quota bug class, graphics upgrades, and the one-IPK universal technique. Read it first. It's also staged to PR into the webOS Archive MCP knowledge base (`github.com/webOSArchive/webos-mcp`, `knowledge/` dir → served as `webos://knowledge/touchpad-porting`).
- Cross-session methodology also lives in Claude memory: `pre-to-touchpad-porting-playbook` + `driver-touchpad-port` + `nova-sandstorm-touchpad-port`.

## What's in this folder
Originals are kept **untouched** (a hard rule — patch to a new filename, never overwrite the stock IPK). The stock originals have since been moved out; the patched builds are **not checked into git** either (they're large binaries that don't belong in the repo). Download the published builds — and the stock originals to patch — from the **webOS App Museum: https://appcatalog.webosarchive.org**. The table below documents the shipped builds.

| Game | File | What it is |
|---|---|---|
| Gameloft DRIVER | `com.gameloft.app.driver_2.2.0_touchpad.ipk` | TouchPad edition — the real depth fix (correct occlusion + sky, native colors) |
| | `com.gameloft.app.driverhd_2.0.0_touchpad.ipk` | HD remaster, **separate app id** `…driverhd`: + 4× MSAA, 32-bit color, 4× anisotropic. Icons: `driverhd-64/256/512.png` |
| EA Tiger Woods PGA Tour | `com.ea.app.tw09_1.1.0_all.ipk` | **current release** — one universal build: HD on the TouchPad, capability-probe fallback to stock on the Pre |
| | `com.ea.app.tw09_1.0.28_patched_all.ipk` | older TouchPad-only patch (pre-HD); superseded by 1.1.0 |
| EA Monopoly | `com.ea.app.monopoly_20.1.00_patched_all.ipk` | memory-quota fix (`requiredMemory` 67→100) + `metadata.json`; universal, **binary byte-identical to EA's** |
| Gameloft N.O.V.A. | `com.gameloft.app.nova_1.1.0_all.ipk` | **universal** Irrlicht game — capability-probe 4× MSAA + 32-bit color, `requiredMemory` 86→130. Validated on Pre 2 + TouchPad. Built with `palm-package` + 0755 binary fix |
| Gameloft Modern Combat: Sandstorm | `com.gameloft.app.sandstorm_1.2.0_all.ipk` | **universal** Irrlicht game — same HD lift, `requiredMemory` 89→190. Long asset paths forced the `palm-package` repack (Python tarfile PAX rebuild broke it). Validated on Pre 2 + TouchPad |

## Conventions
- **Patch, don't rebuild.** Prefer length-preserving byte patches inside the gzipped `data.tar` (python `tarfile` `member.offset_data`); reuse the original `debian-binary` + `control.tar.gz`. Added code (MSAA/aniso/probe stubs) goes in a cave stub inside `.ARM.extab`. App-id rename = `appinfo.json` `id`/`title` + install path + control `Package:` only.
- **Always verify the artifact.** After building, extract from the final `.ipk` and check: control `Package`/`Version`, `appinfo.json` (`version`, `requiredMemory`, `title`), `metadata.json`, and the **binary md5 vs the intended build**. (Caught a real miss this way — a tar member-name mismatch that silently shipped the unpatched binary.)
- **Bump the version on every shipped change** — control `Version:` *and* appinfo `"version"`, both. Same-version reinstalls hit the jail/descriptor cache and silently serve stale code.
- **Naming:** `_touchpad` / `_patched_all` / `_all` suffixes; big remasters get a `*hd` app id, compatibility fixes keep the original id.
- Temp/scratch work goes in the session scratchpad, **never** this folder.

## Device (TouchPad on novacom, USB)
- Apps install under `/media/cryptofs/apps/usr/palm/applications/<id>/` (NOT `/usr/palm/applications/`).
- Fast iteration: `novacom put` the binary into the app dir + `jailer -N -i <id>` to drop the cached jail, then relaunch — no repackage/install. `novacom run` word-splits its command, so push a script and `sh` it.
- Device-compatible helpers (e.g. GL interposers) must be built with `/opt/PalmPDK/arm-gcc` (GCC 4.3.3 / glibc 2.4); the host cross-gcc links too-new glibc and won't load.

## Hard-won gotchas
- **A black screen is not always graphics.** Menus-fine-then-black/"crash" when gameplay loads is usually the **`requiredMemory` quota** — the TouchPad's bigger framebuffer exceeds a Pre-tuned budget and webOS reaps the app. Check `/var/log/messages` for `exceeded its memory quota` (`restriction =` *is* `requiredMemory`; death logs as `status 0`, not SIGSEGV). Fix by raising `requiredMemory`. A live edit needs a **Luna restart** to apply; a fresh install may need one reboot before the jail goes live.
- **Never ship the LD_PRELOAD launcher** used for GL tracing — it washes the render white. Trace with it; bake fixes into the binary.
- **Universal Pre+TouchPad graphics:** gate the risky MSAA/32-bit lift with a **capability probe** (request HD config → if `SDL_SetVideoMode` returns NULL, reset attrs and retry stock), not a device-ID check (the binary usually can't reach `PDL_GetHardwareID`, and you can't add a dynamic import via byte-patch). Trilinear/anisotropic are safe to leave unconditional — they help the Pre's SGX too.
- **`metadata.json` `{"version":1,"devices":[101]}`** is additive (adds TouchPad; does not block phones). Install via Preware / WebOS Quick Install, not `palm-install`.
- **Ship the main binary mode `0755`, not `0644`, for any UNIVERSAL (Pre-compatible) build.** The TouchPad's installer force-chmods to `0777` so `0644` works there and *hides* the bug — but the **Pre's jailer refuses to `exec()` a `0644` file** (`jailer: error: Permission denied`; app registers, then dies instantly). ipkg installers (Quick Install/Preware) chmod on install; `palm-install` does **not** (preserves `0644` → Pre exec fails). (Supersedes the older "PDK binaries don't need +x / store 0644" note — that was TouchPad-only.)
- **Repacking with long asset paths: use `palm-package`, never a Python `tarfile` rebuild.** Games with paths >100 chars get PAX extended headers; Python 3.12's PAX encoding is unparseable by the old on-device tar → ipkg extracts a few hundred files then bails (`resultStatus=1`) while `palm-install`/ApplicationInstaller **report success (exit 0)** → silently PARTIAL install → game SIGSEGVs in file-load (`FileStream::Load`→`ftell(NULL)`) on a missing asset (mimics a code crash). `palm-package <appdir> -o .` emits a device-compatible tar; it normalizes the binary to `0644`, so post-fix the binary's ustar header mode to `0100755` + recompute the header checksum (length-preserving). **Always verify install completeness by on-device FILE COUNT, not installer exit code.** (Length-preserving in-place patches of the *original* `data.tar.gz` — binary bytes + header mode/checksum, appinfo kept same length — also avoid this, since they preserve the original's PAX bytes.)
- **`/dev/fb0` capture doesn't reliably show the GL/compositor layer** on the TouchPad (black during video overlays; triple-buffered) — don't trust framebuffer screenshots for PDK games; rely on the user's eyes.
