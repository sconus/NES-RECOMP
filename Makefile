# nesrecomp
#   make test               recompile nestest and check it against the log,
#                           the game controller mapping and header reading
#   make test-ppu           run tests/suite.txt (needs the test ROM clone)
#   make test-all           both
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
#   make test-standalone    check the app needs nothing from Homebrew
#                           (tests/check_standalone.py, PLAN-standalone.md)
#   make clean
# ROM paths with spaces are not supported.
CC      ?= cc
CFLAGS  ?= -O1 -Wall
SDL_CFLAGS := $(shell sdl2-config --cflags)
SDL_LIBS   := $(shell sdl2-config --prefix)/lib/libSDL2.dylib
LDLIBS   = $(SDL_LIBS) -lz -lm
RT_SRC   = $(wildcard runtime/*.c)
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
	python3 tests/check_headers.py build/nestest

# --- test ROM suite: see tests/suite.txt and tests/run_tests.py --------
test-ppu: $(RECOMP)
	python3 tests/run_tests.py

test-all: test test-ppu test-app

# --- any ROM ----------------------------------------------------------
NAME = $(basename $(notdir $(ROM)))

game: $(RECOMP)
	@test -n "$(ROM)" || { echo "usage: make game ROM=path/to/file.nes"; exit 1; }
	@mkdir -p build
	$(RECOMP) $(ROM) -o build/$(NAME).c $(call missed_arg,$(ROM))
	$(CC) $(CFLAGS) $(SDL_CFLAGS) -Iruntime -o build/$(NAME) build/$(NAME).c $(RT_SRC) $(LDLIBS)

run: game
	./build/$(NAME) $(ROM) $(ARGS)

# --- the recompiler in C (recomp/, PLAN-standalone.md step 2) -----------
# The same program as recomp.py, which stays as the reference it is
# checked against (tests/check_recomp.py). It builds in the project's
# FDS BIOS (runtime/fds_bios.h). Built for Intel and Apple Silicon, like
# the app, which carries it.
RECOMP_SRC = $(wildcard recomp/*.c)
RECOMP_HDR = $(wildcard recomp/*.h)
build/nesrecomp-recomp: $(RECOMP_SRC) $(RECOMP_HDR) runtime/fds_bios.h
	@mkdir -p build
	$(CC) -O2 -Wall -Wextra -arch arm64 -arch x86_64 -mmacosx-version-min=11.0 -o $@ $(RECOMP_SRC) -lz

recomp: build/nesrecomp-recomp

test-recomp: build/nesrecomp-recomp
	python3 tests/check_recomp.py

# --- the app (app/, PLAN-gui.md, PLAN-standalone.md) ------------------
# app/art.h is written by tools/make_app_art.py; run that after editing it.
# The app finds the project (runtime/) where it was built, and the
# recompiler (build/nesrecomp-recomp) beside its own program.
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
APP_DEFS = -DPROJECT_ROOT='"$(CURDIR)"'

$(SDL2_LIB): tools/build_sdl2.sh
	sh tools/build_sdl2.sh

sdl2: $(SDL2_LIB)

build/nesrecomp-app: app/app.c app/build.c app/build.h app/play.c app/play.h app/art.h $(SDL2_LIB) \
                     $(RECOMP)
	@mkdir -p build
	$(CC) $(CFLAGS) $(APP_ARCH) $(APP_SDL) $(APP_DEFS) -Iapp -o $@ app/app.c app/build.c app/play.c $(APP_LIBS)

app: build/nesrecomp-app

run-app: build/nesrecomp-app
	./build/nesrecomp-app

test-app: build/nesrecomp-app
	python3 tests/check_app.py

app-bundle: build/nesrecomp-app $(RECOMP) tools/make_app_bundle.py tools/make_app_art.py
	python3 tools/make_app_bundle.py

test-app-bundle: app-bundle
	python3 tests/check_app_bundle.py

test-standalone: app-bundle
	python3 tests/check_standalone.py

# build/sdl2 stays: it holds SDL's downloaded source (`rm -rf build/sdl2`
# to build it again from a new download).
clean:
	find build -mindepth 1 -maxdepth 1 ! -name sdl2 -exec rm -rf {} + 2>/dev/null; \
	rm -f $(NESTEST).missed

.PHONY: test test-ppu test-all game run recomp test-recomp sdl2 app run-app test-app app-bundle test-app-bundle test-standalone clean
