#!/usr/bin/env bash
# Run INSIDE the fedora:45 build container: copy Fedora's Python + tkinter (Tcl/Tk 9) into
# AppDir/python so the window works on SteamOS and any distro without python3-tk.
#
# The copied programs are Fedora 45 builds (glibc 2.44). They are started through the psport
# bundle's own glibc 2.44 loader (runtime/psport-bundle/lib/ld-linux-x86-64.so.2, also from
# Fedora 45), so the host's glibc version does not matter. Libraries the psport bundle already
# has are not copied twice.
#
#   bash packaging/bundle-python.sh /w/build/AppDir
set -euo pipefail
appdir=${1:?AppDir}
py=$(readlink -f /usr/bin/python3)
ver=$(basename "$py")                # python3.15
dst=$appdir/python
rm -rf "$dst"
mkdir -p "$dst/bin" "$dst/lib"
cp -L "$py" "$dst/bin/$ver"
ln -s "$ver" "$dst/bin/python3"

std=/usr/lib64/$ver
mkdir -p "$dst/lib64/$ver"
# stdlib without the test suite, idle, ensurepip, pydoc data, turtle demos, venv/pip bits
( cd "$std" && tar cf - --exclude='./test' --exclude='./idlelib' --exclude='./ensurepip' \
    --exclude='./pydoc_data' --exclude='./turtledemo' --exclude='./site-packages' \
    --exclude='*/__pycache__' --exclude='./lib2to3' --exclude='./unittest/test' \
    --exclude='./tkinter/test' --exclude='./config-*' . ) | ( cd "$dst/lib64/$ver" && tar xf - )
mkdir -p "$dst/lib64/$ver/site-packages"

bundle_lib=$appdir/runtime/psport-bundle/lib
skip='^(linux-vdso|ld-linux|libc\.so|libm\.so|libpthread|libdl\.so|librt\.so|libmvec|libutil\.so|libresolv)'
copy_deps() {
    ldd "$1" | awk '/=> \//{print $1" "$3}' | while read -r name path; do
        [[ $name =~ $skip ]] && continue
        [[ -e $bundle_lib/$name || -e $dst/lib/$name ]] && continue
        cp -L "$path" "$dst/lib/$name"
        copy_deps "$path"
    done
}
copy_deps "$py"
for so in "$dst/lib64/$ver/lib-dynload/"*.so; do copy_deps "$so"; done

# Tcl/Tk script libraries (Tcl 9 may also carry them inside the .so as a zipfs)
for d in /usr/share/tcl9* /usr/share/tk9* /usr/lib64/tcl9* /usr/lib64/tk9*; do
    [[ -d $d ]] && cp -a "$d" "$dst/lib/"
done
ls "$dst/lib" | sed 's/^/  /' | head -80
du -sh "$dst"
