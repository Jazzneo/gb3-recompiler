# Licences

| Part | Licence | Terms in the AppImage |
|---|---|---|
| This tool (`app/`, `packaging/`, `tools/`, the patch data in `data/`) | GPL-2.0-or-later | this file; GPL-2.0 text in `runtime/psport-bundle/LICENSE` |
| psport runtime (`out/psport`, `out/gpu/libpsport-gpu.so`) with this port's patches | GPL-2.0 | `runtime/psport-bundle/LICENSE`, `LICENSES.md`, `LICENSES/` |
| Libraries in `runtime/psport-bundle/lib` (glibc, SDL3, FFmpeg, FreeType, fmt, …) | LGPL-2.1+/MIT/BSD/Zlib and others | `THIRD-PARTY-NOTICES`, `SOURCES.txt`, `LICENSES/` |
| `bin/ps4-pkg-tool` (xXJSONDeruloXx/ps4-pkg-tools) | GPL-2.0-or-later | `bin/LICENSE-ps4-pkg-tool.txt` |
| psport online module `out/gpu/libpsport-net.so` (shadPS4 network code + this port's TSS agreement change) and `scripts/` | GPL-2.0-or-later | `runtime/psport-bundle/LICENSE`, `scripts/*/NOTICE.txt` |
| Co-op server `runtime/shadnet` (shadNet 0.1.9 + `server/shadnet-gb3.diff`) and its Fedora 45 libraries (Qt 6, ICU, OpenSSL, SQLite, glibc …) | GPL-2.0-or-later (server); LGPL-3.0/LGPL-2.1+/Apache-2.0/MIT/Unicode and others (libraries) | `runtime/shadnet/SOURCE.md`, `share/PACKAGES.txt`; sources at github.com/shadps4-emu/shadNet and src.fedoraproject.org |
| Bundled Python 3 and Tcl/Tk (Fedora 45 builds) | PSF-2.0, Tcl/Tk licence (BSD-style) | upstream sources: python.org, tcl.tk; Fedora source RPMs |
| AppImage type-2 runtime | MIT | github.com/AppImage/type2-runtime |
| GUNDAM BREAKER 3, its code, assets, PKG, saves | **not licensed, not included** | © Bandai Namco Entertainment |

## Source

- This tool: the `Recompiler Gundam breaker 3 Break edition/` folder of the GB3 port project.
- psport: upstream <https://github.com/yerasuu/psport> tag v0.2.0, plus the local patches listed in
  the project's `AGENTS.md` (save-event callbacks, pad user -1, GB3 PSN prompt, low flexible
  memory, F1 menu) and the shop-box fix (`GB3-Port-Scope/shop-box-lighting/boxfix-s_and_b64-exec.diff`,
  `ShaderBinaryVersion` 17). The patched tree is `GB3-Port-Scope/psport-src`.
- Co-op server: shadNet 0.1.9 (upstream commit a53dad5) plus `server/shadnet-gb3.diff`; the
  patched tree is `GB3-Port-Scope/shadnet-server`.
- Modified psport binaries are labelled as modified: `runtime/psport-bundle/RUNTIME-VERSION` reads
  `psport v0.2.0-gb3`.

If you pass the AppImage on, the GPL requires the recipient to be able to get that source: publish
it alongside, or include a written offer.

## Game content

The AppImage contains no game code or assets, no keys and no saves. The mod data are byte runs
of art and constants made for this port (Xbox glyphs, diagrams and badges, 720p shader constants,
the 720p eboot patch's new instructions); they are applied only on top of the player's own,
checksum-matched game files. GUNDAM BREAKER 3, PlayStation, Xbox and Steam are trademarks of their
owners; this tool is not affiliated with any of them.
