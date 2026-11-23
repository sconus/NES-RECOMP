# nesrecomp
#   make test               recompile nestest and check it against the log,
#                           the game controller mapping and header reading
#   make test-ppu           run tests/suite.txt (needs the test ROM clone)
#   make test-all           both
#   make test-menu          the pause menu: its pictures, save, load, reset and
#                           slots through it (tests/check_menu.py, PLAN-pause.md)
#   make test-states        save a state mid-run and load it, for every ROM in
#                           the suite (tests/check_states.py, PLAN-savestates.md)
#   make test-titles        the game's title picture, for the app's shelf
#                           (tests/check_titles.py, PLAN-library.md)
#   make test-keys          the window's keys the same on the ALL KEYS page,
#                           the README and the cards (tests/check_keys.py)
#   make game ROM=x.nes     recompile any NROM game into build/<name>
#   make run ROM=x.nes      ...and run it in a window (options: ARGS="...")
#   make recomp             the recompiler in C (build/nesrecomp-recomp)
#   make test-recomp        check it reads (and later translates) every ROM
#                           under tests/ as recomp.py does
#   make sdl2               build the app's own SDL2 (tools/build_sdl2.sh;
#                           needs SDL's source release in build/sdl2/src)
#   make app                build the app (build/nesrecomp-app), PLAN-gui.md
#   make run-app            ...and open it
#   make test-app           check its screens (tests/check_app.py)
#   make app-bundle         build/nesrecomp.app, to double-click
#   make test-app-bundle    check it, opening it as Finder would (it shows
#                           a window briefly)
#   make test-record        check recording movies (tests/check_record.py; a
#                           window shows for 2 seconds)
#   make test-standalone    check the app needs nothing from Homebrew
#                           (tests/check_standalone.py, PLAN-standalone.md)
#   make windows            the Windows build, so far the recompiler
#                           (build/windows/, with Zig; PLAN-windows.md)
#   make windows-game ROM=x.nes   a game for Windows, build/windows/<name>.exe
#                           (with SDL2.dll beside it)
#   make windows-app        the app for Windows, in build/windows/app/
#                           (tools/make_windows_app.py; checked on GitHub's
#                           Windows machine)
#   make same-c             write down the C the Mac's recompiler writes
#                           (tests/same_c.txt); make test-same-c checks it
#   make release            build/NES-RECOMP-<version>.zip: the app, a read-me
#                           and the licenses, to give away
#   make test-release       check it as a downloaded copy would be treated
#   make clean
# ROM paths with spaces are not supported.
CC      ?= cc
CFLAGS  ?= -O1 -Wall
SDL_CFLAGS := $(shell sdl2-config --cflags)
SDL_LIBS   := $(shell sdl2-config --prefix)/lib/libSDL2.dylib
# The runtime records movies with Apple's AVFoundation (runtime/
# record_mac.m, Objective-C; PLAN-standalone.md step 6).
RT_FRAMEWORKS = -framework AVFoundation -framework CoreMedia -framework CoreVideo \
                -framework Foundation
LDLIBS   = $(SDL_LIBS) -lz -lm $(RT_FRAMEWORKS)
RT_SRC   = $(wildcard runtime/*.c) $(wildcard runtime/*.m)
RT_HDR   = $(wildcard runtime/*.h)
# The recompiler: the C version (recomp/, PLAN-standalone.md step 2).
# recomp.py stays as the reference it is checked against (make test-recomp).
RECOMP   = build/nesrecomp-recomp
# Feed back spots a previous run had to interpret, if there are any.
missed_arg = $(if $(wildcard $(1).missed),--missed $(1).missed,)

# --- nestest: the CPU check --------------------------------------------
NESTEST = tests/nestest.nes

build/nestest: build/nestest.c $(RT_SRC) $(RT_HDR)
	$(CC) $(CFLAGS) $(SDL_CFLAGS) -Iruntime -o $@ build/nestest.c $(RT_SRC) $(LDLIBS)

build/nestest.c: $(RECOMP) $(NESTEST)
	@mkdir -p build
	$(RECOMP) $(NESTEST) -o $@ --entry C000 $(call missed_arg,$(NESTEST))

test: build/nestest
	./build/nestest $(NESTEST) --headless --start C000 --trace --check-cycles > build/trace.txt
	python3 tests/compare_nestest.py tests/nestest.log build/trace.txt
	./build/nestest --test-gamepads
	./build/nestest --test-controls
	@mkdir -p build/title_test
	./build/nestest --test-title build/title_test
	python3 tests/check_headers.py build/nestest

# --- test ROM suite: see tests/suite.txt and tests/run_tests.py --------
test-ppu: $(RECOMP)
	python3 tests/run_tests.py
	python3 tests/check_bandai_save.py

test-all: test test-ppu test-app test-record test-states test-menu test-titles test-keys

# --- save states (runtime/state.c, PLAN-savestates.md) -----------------
test-states: $(RECOMP)
	python3 tests/check_states.py

# --- the pause menu (runtime/menu.c, PLAN-pause.md) ------------------------
test-menu: $(RECOMP)
	python3 tests/check_menu.py

test-titles: $(RECOMP)
	python3 tests/check_titles.py

test-keys:
	python3 tests/check_keys.py

# --- recording (runtime/record_mac.m, PLAN-standalone.md step 6) ---------
test-record: $(RECOMP)
	python3 tests/check_record.py

# --- any ROM ----------------------------------------------------------
NAME = $(basename $(notdir $(ROM)))

game: $(RECOMP)
	@test -n "$(ROM)" || { echo "usage: make game ROM=path/to/file.nes"; exit 1; }
	@mkdir -p build
	$(RECOMP) $(ROM) -o build/$(NAME).c $(call missed_arg,$(ROM))
	$(CC) $(CFLAGS) $(SDL_CFLAGS) -Iruntime -o build/$(NAME) build/$(NAME).c $(RT_SRC) $(LDLIBS)

# The keys the pause menu's KEYBOARD pages set are kept in build/controls.txt.
run: game
	./build/$(NAME) $(ROM) --controls build/controls.txt $(ARGS)

# --- the recompiler in C (recomp/, PLAN-standalone.md step 2) -----------
# The same program as recomp.py, which stays as the reference it is
# checked against (tests/check_recomp.py). It builds in the project's
# FDS BIOS (runtime/fds_bios.h). Built for Intel and Apple Silicon, like
# the app, which carries it.
RECOMP_SRC = $(wildcard recomp/*.c)
RECOMP_HDR = $(wildcard recomp/*.h)
build/nesrecomp-recomp: $(RECOMP_SRC) $(RECOMP_HDR) runtime/fds_bios.h
	@mkdir -p build
	$(CC) -O2 -Wall -Wextra -arch arm64 -arch x86_64 -mmacosx-version-min=11.0 -o $@ $(RECOMP_SRC)

recomp: build/nesrecomp-recomp

test-recomp: build/nesrecomp-recomp
	python3 tests/check_recomp.py

# --- the app (app/, PLAN-gui.md, PLAN-standalone.md) ------------------
# app/art.h is written by tools/make_app_art.py; run that after editing it.
# The app holds no path of the project (PLAN-standalone.md step 4): it
# finds the recompiler (build/nesrecomp-recomp) beside its own program,
# and runtime/ at ../runtime from there (in the bundle, both inside it).
# Its builds go to ~/Library/Application Support/NES RECOMP, but run-app
# sets NESRECOMP_ROOT so they go to build/ here, as before.
# It uses its own SDL2, not Homebrew's: built from SDL's source release
# by tools/build_sdl2.sh into build/sdl2/ (for Intel and Apple Silicon,
# macOS 11 on), and the app is built for both too. It finds the library
# at sdl2/lib beside it (or in the bundle's Frameworks), and builds games
# against it.
SDL2_DIR  = build/sdl2
SDL2_LIB  = $(SDL2_DIR)/lib/libSDL2.dylib
APP_ARCH  = -arch arm64 -arch x86_64 -mmacosx-version-min=11.0
APP_SDL   = -I$(SDL2_DIR)/include/SDL2 -D_THREAD_SAFE
APP_LIBS  = $(SDL2_LIB) -Wl,-rpath,@executable_path/sdl2/lib \
            -Wl,-rpath,@executable_path/../Frameworks -lz -lm

$(SDL2_LIB): tools/build_sdl2.sh
	sh tools/build_sdl2.sh

sdl2: $(SDL2_LIB)

build/nesrecomp-app: app/app.c app/build.c app/build.h app/play.c app/play.h app/hood.c app/hood.h \
                     app/code.c app/code.h app/shelf.c app/shelf.h app/support.h app/support_mac.m app/os.h app/os_mac.c \
                     app/art.h $(SDL2_LIB) \
                     $(RECOMP)
	@mkdir -p build
	$(CC) $(CFLAGS) $(APP_ARCH) $(APP_SDL) -Iapp -o $@ app/app.c app/build.c app/play.c app/hood.c app/code.c app/shelf.c \
	    app/os_mac.c app/support_mac.m $(APP_LIBS) -framework Cocoa

app: build/nesrecomp-app

run-app: build/nesrecomp-app
	NESRECOMP_ROOT="$(CURDIR)" ./build/nesrecomp-app

test-app: build/nesrecomp-app
	python3 tests/check_app.py

app-bundle: build/nesrecomp-app $(RECOMP) $(RT_SRC) $(RT_HDR) tools/make_app_bundle.py tools/make_app_art.py
	python3 tools/make_app_bundle.py

test-app-bundle: app-bundle
	python3 tests/check_app_bundle.py

test-standalone: app-bundle
	python3 tests/check_standalone.py

# --- Windows (PLAN-windows.md) -------------------------------------------
# Built here with Zig (build/zig, from ziglang.org), which builds Windows
# programs on a Mac; checked on a GitHub Windows machine
# (.github/workflows/windows.yml).
ZIG ?= build/zig/zig-aarch64-macos-0.17.1/zig
WIN_CC = $(ZIG) cc -target x86_64-windows-gnu

# With Windows's UTF-8 setting (app/windows/utf8.rc), so ROM names with
# accents or other alphabets open (PLAN-windows.md step 6).
build/windows/nesrecomp-recomp.exe: $(RECOMP_SRC) $(RECOMP_HDR) runtime/fds_bios.h app/windows/utf8.rc app/windows/manifest.xml
	@mkdir -p build/windows
	$(WIN_CC) -O2 -Wall -Wextra -o $@ $(RECOMP_SRC) app/windows/utf8.rc

windows: build/windows/nesrecomp-recomp.exe

# A game for Windows, as `make game` makes one for the Mac: SDL's official
# Windows build (build/sdl2-windows, SDL2-devel-2.32.10-mingw.zip) and
# zlib 1.3.1 (build/zlib/src), both from their release pages; SDL2.dll is
# put beside the game.
SDL2_WIN = build/sdl2-windows/src/SDL2-2.32.10/x86_64-w64-mingw32
ZLIB_SRC = build/zlib/src/zlib-1.3.1
ZLIB_WIN_OBJ = $(patsubst $(ZLIB_SRC)/%.c,build/windows/zlib/%.o,$(wildcard $(ZLIB_SRC)/*.c))
RT_WIN_SRC = $(wildcard runtime/*.c)

build/windows/zlib/%.o: $(ZLIB_SRC)/%.c
	@mkdir -p build/windows/zlib
	$(WIN_CC) -O2 -c $< -o $@

# The app for Windows, in a folder with what it needs beside it
# (PLAN-windows.md step 4).
windows-app: build/windows/nesrecomp-recomp.exe
	python3 tools/make_windows_app.py --cc "$(WIN_CC)" --sdl2 $(SDL2_WIN) --zlib-src $(ZLIB_SRC) \
	    --recomp build/windows/nesrecomp-recomp.exe --out build/windows/app

windows-game: build/windows/nesrecomp-recomp.exe $(RECOMP) $(ZLIB_WIN_OBJ)
	@test -n "$(ROM)" || { echo "usage: make windows-game ROM=path/to/file.nes"; exit 1; }
	@mkdir -p build/windows
	$(RECOMP) $(ROM) -o build/windows/$(NAME).c $(call missed_arg,$(ROM))
	$(WIN_CC) -O1 -Wall -I$(SDL2_WIN)/include/SDL2 -I$(ZLIB_SRC) -Iruntime -o build/windows/$(NAME).exe \
	    build/windows/$(NAME).c $(RT_WIN_SRC) $(ZLIB_WIN_OBJ) $(SDL2_WIN)/lib/libSDL2.dll.a -lole32
	cp $(SDL2_WIN)/bin/SDL2.dll build/windows/

# The fingerprints of the C the Mac's recompiler writes (tests/same_c.txt),
# which every system's must match; written again after a change to the C.
same-c: $(RECOMP)
	python3 tests/check_same_c.py --write

test-same-c: $(RECOMP)
	python3 tests/check_same_c.py

# NES RECOMP for Windows to give away (PLAN-windows.md step 6):
# build/NES-RECOMP-<version>-windows.zip, with the app's own Zig, Zig's
# official Windows build (build/zig/win-unpack, from
# zig-x86_64-windows-0.17.1.zip on ziglang.org, checked against its
# SHA-256). Its C library is made here by this Mac's Zig.
WIN_ZIG_DIR = build/zig/win-unpack/zig-x86_64-windows-0.17.1
WIN_ZIG_SHA256 = b03f477a1943673e02aca0f570e8030dffd536ce1f45cbc4d3326ec31159562e

$(WIN_ZIG_DIR)/zig.exe:
	@mkdir -p build/zig/win-unpack
	curl -sSfL -o build/zig/zig-x86_64-windows-0.17.1.zip https://ziglang.org/download/0.17.1/zig-x86_64-windows-0.17.1.zip
	echo "$(WIN_ZIG_SHA256)  build/zig/zig-x86_64-windows-0.17.1.zip" | shasum -a 256 -c -
	unzip -q -o build/zig/zig-x86_64-windows-0.17.1.zip -d build/zig/win-unpack

release-windows: build/windows/nesrecomp-recomp.exe $(WIN_ZIG_DIR)/zig.exe tools/make_windows_app.py tools/make_windows_release.py LICENSE
	python3 tools/make_windows_app.py --cc "$(WIN_CC)" --sdl2 $(SDL2_WIN) --zlib-src $(ZLIB_SRC) \
	    --recomp build/windows/nesrecomp-recomp.exe --out build/windows/release-app --zig $(WIN_ZIG_DIR)
	python3 tools/make_windows_release.py --app build/windows/release-app --zig $(WIN_ZIG_DIR) \
	    --sdl2-license $(SDL2_WIN)/../LICENSE.txt --zlib-src $(ZLIB_SRC)

# What can be checked here (its contents, no path of this Mac, the
# read-me); the rest on GitHub's Windows machine.
test-release-windows: release-windows
	python3 tests/check_release_windows.py

# --- a release (PLAN-standalone.md step 9) ------------------------------
release: app-bundle tools/make_release.py LICENSE
	python3 tools/make_release.py

test-release: release
	python3 tests/check_release.py

# build/sdl2 stays: it holds SDL's downloaded source (`rm -rf build/sdl2`
# to build it again from a new download).
clean:
	find build -mindepth 1 -maxdepth 1 ! -name sdl2 -exec rm -rf {} + 2>/dev/null; \
	rm -f $(NESTEST).missed

.PHONY: windows-app release-windows test-release-windows test test-ppu test-all test-record release test-release windows windows-game same-c test-same-c game run recomp test-recomp sdl2 app run-app test-app app-bundle test-app-bundle test-standalone clean
