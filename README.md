# Recompiler Gundam Breaker 3 Break Edition

<a href="https://recomplauncher.com"><picture><source media="(prefers-color-scheme: dark)" srcset="https://recomplauncher.com/assets/press/launcher/badge-light.svg"><img alt="Get it on RecompLauncher" src="https://recomplauncher.com/assets/press/launcher/badge-dark.svg" height="48"></picture></a>

[![Gundam Breaker 3 Running Natively on Steam Deck](https://youtube.com)](https://youtube.com)


**Status:** tested by the author on Steam Deck (2026-11-25): installs from the PKG and plays.

**How to play:** you need your own GUNDAM BREAKER 3 BREAK EDITION **base game, CUSA07651 v01.00**,
as a fake-signed `.pkg` or a dumped `CUSA07651` folder (not an update PKG). Download
`GB3-Recompiler-v…-Linux-x86_64.AppImage` from [Releases](https://github.com/Jazzneo/gb3-recompiler/releases),
run it, pick your PKG, press **Install**, then **Play**. In RecompLauncher, drop the PKG or folder on
the setup screen instead.

One AppImage that turns **your own** GUNDAM BREAKER 3 BREAK EDITION PS4 PKG (CUSA07651, v01.00)
into a playable Linux / Steam Deck install. It runs the game through
[psport](https://github.com/yerasuu/psport), a PS4 translation layer (the game's own x86-64 code
runs natively, psport supplies the PS4 system libraries and turns GPU work into Vulkan).

**No game data ships with this tool.** You give it your PKG; it unpacks it and builds every mod
from your own files. The mods are stored only as the bytes they change (1.3 MB of our own art and
shader constants), and each is applied only when your original record matches the expected
sha256.

## What you get

| Fix / mod | On by default | What it does |
|---|---|---|
| psport runtime (patched v0.2.0) | always | save fix (no endless SAVING), pad open fix, PSN sign-in question skipped, mission-end crash fix (`PS_LOW_FLEXIBLE`), F1 menu so L3+R3 reach the game |
| Shop box lighting fix | always | GPU library with the back-face normal flip guard (`ShaderBinaryVersion` 17); the first run rebuilds the shader cache |
| 720p render patch v2.6 + shader fix | yes | eboot patch `GB3-render-720p.xml` (33 writes, applied in memory by psport) plus 7 shader records: steady 30 FPS on a Steam Deck |
| Xbox button art | yes | A/B/X/Y glyphs in all three fonts, controller pictures, layout presets, blue EX prompts, skill-slot badges (loose copies and the HUD bundles in archive 000) |

`PS_GAME_PROFILE=none` is set for every launch, and `--guest-res` is never used.

Not fixed yet: the beam/naginata blade shape (a psport bug, also at 1080p), the □ in a few baked
menu banners, and the PS4 pad pictures on loading screens.

## Use it

1. Make it executable and start it (Desktop Mode on a Deck):
   ```bash
   chmod +x GB3-Recompiler-v*-Linux-x86_64.AppImage
   ./GB3-Recompiler-v*-Linux-x86_64.AppImage
   ```
2. **1** — pick your PKG (**Browse…** or **Find**) and an install folder. Default
   `~/Games/GB3-Recompiler`; it needs about 14 GB. A microSD works.
3. **2** — leave the options on (720p and Xbox art are what the Deck was tested with).
4. **3** — **Install**. Unpacking the 12 GB PKG takes a few minutes; the mods take seconds.
5. **Play**, or for Game Mode: Steam → *Add a Non-Steam Game* → tick
   **GUNDAM BREAKER 3 (psport)** (the installer adds that menu entry; it runs `play.sh` in the
   install folder).

### RecompLauncher

The release carries `recomplauncher.json` (inside the AppImage at `/recomplauncher.json`, and at the
top of the `.tar.xz`). The launcher's setup step runs
`--prepare --game=<your PKG or folder> --dir <game folder>/recompdata/GB3-Recompiler`, with the
720p and Xbox-art fixes as ticks; Play runs `--play --dir …`, and its Frame rate and Background
shader compiles settings are passed on the command line. Saves are in
`recompdata/GB3-Recompiler/psport-bundle/user/savedata`, logs in `recompdata/logs`.

Already playing with an older psport bundle? **Import old saves** copies
`~/Applications/Psport/psport-bundle/user/savedata/1/CUSA03489` (or a folder you pick) into the
new install. It never overwrites saves that are already there.

In game, **F1** opens the psport menu (quit, settings).

## Undo and changes

- Untick an option and press **Apply options**: the tool puts every record it changed back to the
  original first, then applies what is ticked. The 720p XML is renamed to `.xml.off` when off.
- **Restore original files** puts both archives back to the exact original bytes (checked:
  `GxArchivedFile000.dat` sha256 `59a90e3e…`, `001` `89a72ee7…`) and turns the 720p patch off.
  Saves are not touched.
- The undo information lives beside each archive as `*.gb3r-state.json`.
- **Back up saves** copies the save folder to `save-backups/<time>/` in the install folder.

## Command line

```bash
./GB3-Recompiler…AppImage install --pkg game.pkg [--dir DIR] [--no-xbox] [--no-720p] [--fps 30|60|uncapped]
./GB3-Recompiler…AppImage apply [--xbox|--no-xbox] [--720p|--no-720p]
./GB3-Recompiler…AppImage restore
./GB3-Recompiler…AppImage status
./GB3-Recompiler…AppImage import-saves [--from OLD_BUNDLE]
./GB3-Recompiler…AppImage --play [--dir DIR] [--60|--uncap|--async]   # start the installed game
./GB3-Recompiler…AppImage --prepare --game=PKG_OR_FOLDER --dir DIR [--xbox] [--720p]
                                       # windowless setup with "progress 0.4 Text" lines
bash ~/Games/GB3-Recompiler/play.sh --check   # what psport would use, launches nothing
```

If FUSE is not available, add `--appimage-extract-and-run` before the arguments.

## Install folder

```
~/Games/GB3-Recompiler/
  CUSA07651/        the unpacked game (mods applied here)
  psport-bundle/    psport; saves in user/savedata/1/CUSA03489, the 720p XML in patches/
  psport/           launch scripts (play-gb3.sh, common.sh, fix-interp.py, ...)
  play.sh           start the game
  gb3r.json         what was installed, with which options
```

Debug logs: `~/Games/PS4/psport-debug/<host>/<time>-CUSA07651/` (`run.log`, `faults.txt`).

## Building (developers)

```bash
python3 tools/make-patchdata.py --a000 <original 000.dat> --a001 <original 001.dat> \
    --scope ../GB3-Port-Scope --out data          # only when a mod changes
bash packaging/build-appimage.sh                  # -> dist/GB3-Recompiler-v<ver>-Linux-x86_64.{AppImage,tar.xz}
```

`build-appimage.sh` stages the runtime from `GB3-Port-Scope` (patched `out/psport`, the box-fix
`libpsport-gpu.so` md5 `e4cf03f2…`), bundles Fedora 45's Python 3 + Tk (run through the psport
bundle's own glibc loader, so it works on SteamOS without `python3-tk`), and packs it with the
static AppImage type-2 runtime. The stage step refuses to pack any `eboot.bin`, `.dat`, `.pkg`,
`.tex`, save or shader-cache file.

Licences: see `LICENSE-NOTES.md`.
