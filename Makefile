# nesrecomp
#   make test               recompile nestest and check it against the log
#   make test-ppu           run tests/suite.txt (needs the test ROM clone)
#   make test-all           both
#   make game ROM=x.nes     recompile any NROM game into build/<name>
#   make run ROM=x.nes      ...and run it in a window
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

# --- test ROM suite: see tests/suite.txt and tests/run_tests.py --------
test-ppu:
	python3 tests/run_tests.py

test-all: test test-ppu

# --- any ROM ----------------------------------------------------------
NAME = $(basename $(notdir $(ROM)))

game:
	@test -n "$(ROM)" || { echo "usage: make game ROM=path/to/file.nes"; exit 1; }
	@mkdir -p build
	python3 recomp.py $(ROM) -o build/$(NAME).c $(call missed_arg,$(ROM))
	$(CC) $(CFLAGS) $(SDL_CFLAGS) -Iruntime -o build/$(NAME) build/$(NAME).c $(RT_SRC) $(LDLIBS)

run: game
	./build/$(NAME) $(ROM)

clean:
	rm -rf build $(NESTEST).missed

.PHONY: test test-ppu test-all game run clean
