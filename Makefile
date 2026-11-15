# nesrecomp
#   make test               recompile nestest and check it against the log,
#                           the game controller mapping and header reading
#   make test-ppu           run tests/suite.txt (needs the test ROM clone)
#   make test-all           both
#   make game ROM=x.nes     recompile any NROM game into build/<name>
#   make run ROM=x.nes      ...and run it in a window (options: ARGS="...")
#   make app                build the app (build/nesrecomp-app), PLAN-gui.md
#   make run-app            ...and open it
#   make test-app           check its screens (tests/check_app.py)
#   make app-bundle         build/nesrecomp.app, to double-click
#   make test-app-bundle    check it, opening it as Finder would (it shows
#                           a window briefly)
#   make clean
# ROM paths with spaces are not supported.
CC      ?= cc
CFLAGS  ?= -O1 -Wall
SDL_CFLAGS := $(shell sdl2-config --cflags)
SDL_LIBS   := $(shell sdl2-config --prefix)/lib/libSDL2.dylib
LDLIBS   = $(SDL_LIBS) -lz -lm
RT_SRC   = $(wildcard runtime/*.c)
RT_HDR   = $(wildcard runtime/*.h)
# Feed back spots a previous run had to interpret, if there are any.
missed_arg = $(if $(wildcard $(1).missed),--missed $(1).missed,)

# --- nestest: the CPU check --------------------------------------------
NESTEST = tests/nestest.nes

build/nestest: build/nestest.c $(RT_SRC) $(RT_HDR)
	$(CC) $(CFLAGS) $(SDL_CFLAGS) -Iruntime -o $@ build/nestest.c $(RT_SRC) $(LDLIBS)

build/nestest.c: recomp.py $(NESTEST)
	@mkdir -p build
	python3 recomp.py $(NESTEST) -o $@ --entry C000 $(call missed_arg,$(NESTEST))

test: build/nestest
	./build/nestest $(NESTEST) --headless --start C000 --trace --check-cycles > build/trace.txt
	python3 tests/compare_nestest.py tests/nestest.log build/trace.txt
	./build/nestest --test-gamepads
	python3 tests/check_headers.py build/nestest

# --- test ROM suite: see tests/suite.txt and tests/run_tests.py --------
test-ppu:
	python3 tests/run_tests.py

test-all: test test-ppu test-app

# --- any ROM ----------------------------------------------------------
NAME = $(basename $(notdir $(ROM)))

game:
	@test -n "$(ROM)" || { echo "usage: make game ROM=path/to/file.nes"; exit 1; }
	@mkdir -p build
	python3 recomp.py $(ROM) -o build/$(NAME).c $(call missed_arg,$(ROM))
	$(CC) $(CFLAGS) $(SDL_CFLAGS) -Iruntime -o build/$(NAME) build/$(NAME).c $(RT_SRC) $(LDLIBS)

run: game
	./build/$(NAME) $(ROM) $(ARGS)

# --- the app (app/, PLAN-gui.md) ------------------------------------
# app/art.h is written by tools/make_app_art.py; run that after editing it.
# The app finds the project (recomp.py, runtime/) where it was built, and
# builds games with the same SDL flags.
APP_DEFS = -DPROJECT_ROOT='"$(CURDIR)"' -DAPP_SDL_CFLAGS='"$(SDL_CFLAGS)"' \
           -DAPP_SDL_LIBS='"$(SDL_LIBS)"'
build/nesrecomp-app: app/app.c app/build.c app/build.h app/play.c app/play.h app/art.h
	@mkdir -p build
	$(CC) $(CFLAGS) $(SDL_CFLAGS) $(APP_DEFS) -Iapp -o $@ app/app.c app/build.c app/play.c $(LDLIBS)

app: build/nesrecomp-app

run-app: build/nesrecomp-app
	./build/nesrecomp-app

test-app: build/nesrecomp-app
	python3 tests/check_app.py

app-bundle: build/nesrecomp-app tools/make_app_bundle.py tools/make_app_art.py
	python3 tools/make_app_bundle.py

test-app-bundle: app-bundle
	python3 tests/check_app_bundle.py

clean:
	rm -rf build $(NESTEST).missed

.PHONY: test test-ppu test-all game run app run-app test-app app-bundle test-app-bundle clean
