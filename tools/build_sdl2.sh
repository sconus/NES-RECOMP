#!/bin/sh
# Build SDL2 from its official source release, for the app to carry
# (PLAN-standalone.md step 1): one library for Intel and Apple Silicon
# Macs, macOS 11 and later, built with only Apple's C compiler.
#
#   tools/build_sdl2.sh      (run by `make sdl2`)
#
# It expects the release unpacked at build/sdl2/src/SDL2-$VERSION, from
#   https://github.com/libsdl-org/SDL/releases/download/release-$VERSION/SDL2-$VERSION.tar.gz
# and leaves:
#   build/sdl2/lib/libSDL2.dylib   both architectures, named
#                                  @rpath/libSDL2.dylib, so a program finds
#                                  it where its rpath says
#   build/sdl2/include/SDL2/       the headers
#   build/sdl2/LICENSE.txt         SDL's license (zlib)
# Each architecture is built on its own and the two are joined with lipo.
# The folders it was built in are written as "sdl2/..." in the library
# (SDL names its source files in messages), so the app carries no path of
# this Mac (PLAN-standalone.md step 4).
set -e
VERSION=2.32.10
MINOS=11.0
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$ROOT/build/sdl2
SRC=$OUT/src/SDL2-$VERSION
[ -f "$SRC/configure" ] || { echo "no SDL2 source at $SRC"; exit 1; }

for arch in arm64 x86_64; do
    work=$OUT/work-$arch
    rm -rf "$work" "$OUT/install-$arch"
    mkdir -p "$work"
    (cd "$work" &&
     # No pkg-config and no /usr/local or Homebrew paths: only the Mac's
     # own frameworks, so nothing from this Mac's extras gets in.
     PKG_CONFIG=/usr/bin/false \
     CC="cc -arch $arch -mmacosx-version-min=$MINOS" \
     CFLAGS="-O2 -ffile-prefix-map=$OUT=sdl2" LDFLAGS="-mmacosx-version-min=$MINOS" \
     "$SRC/configure" --host=$arch-apple-darwin --prefix="$OUT/install-$arch" \
         --disable-static --without-x --disable-video-x11 --disable-video-wayland \
         --disable-video-opengles --disable-hidapi-libusb > configure.log 2>&1 &&
     make -j8 > make.log 2>&1 &&
     make install > install.log 2>&1) || { echo "SDL2 build failed for $arch: see $work"; exit 1; }
done

rm -rf "$OUT/lib" "$OUT/include"
mkdir -p "$OUT/lib"
lipo -create "$OUT/install-arm64/lib/libSDL2-2.0.0.dylib" \
             "$OUT/install-x86_64/lib/libSDL2-2.0.0.dylib" -output "$OUT/lib/libSDL2.dylib"
install_name_tool -id @rpath/libSDL2.dylib "$OUT/lib/libSDL2.dylib" 2>/dev/null
codesign --force -s - "$OUT/lib/libSDL2.dylib"
cp -R "$OUT/install-arm64/include" "$OUT/include"
cp "$SRC/LICENSE.txt" "$OUT/LICENSE.txt"
echo "built $OUT/lib/libSDL2.dylib ($(lipo -archs "$OUT/lib/libSDL2.dylib"))"
