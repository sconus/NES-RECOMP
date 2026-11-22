/* nesrecomp runtime: game controllers (Xbox, PlayStation, Switch Pro and
   others SDL knows) as NES controllers 1 to 4.

   The first controller connected plays controller 1, the second
   controller 2, and so on; a controller plugged in later takes the first free slot,
   and unplugging one frees its slot. The keyboard keeps working
   alongside.

   Mapping, by position as on the NES pad (B on the left, A on the right):
     D-pad or left stick   D-pad (the stick past half way)
     right face button     A    (Xbox B, PlayStation circle, Switch A)
     bottom face button    B    (Xbox A, PlayStation cross, Switch B)
     Start / Menu          Start
     Back / Select / Share Select
   SDL is told not to swap Nintendo controllers' buttons to match their
   labels, so the same position means the same button on every brand.

   Beyond the NES buttons (PLAN-pause.md step 2):
     Select+Start held 0.5 s   opens the pause menu (a short press of
                               both still reaches the game)
     Home / Guide              opens it too, where the system lets SDL
                               see it
     left shoulder held        rewind
     right shoulder held       fast-forward
   In the menu: the D-pad (or stick) moves, A or Start chooses, B or
   Home closes. Only presses made after it opened count, and buttons
   held when it closes don't reach the game until let go. */
#include <SDL.h>
#include <stdio.h>
#include <string.h>
#include "gamepad.h"
#include "input.h"
#include "menu.h"

#define STICK_THRESHOLD 16384           /* half way, of 32767 */

#define SLOTS 4
static SDL_GameController *slot[SLOTS];
static int virtual_only;        /* the self-test ignores real controllers */

#define MENU_HOLD_MS 500        /* Select+Start held this long: the menu */
#define REPEAT_FIRST_MS 400     /* a direction held in the menu repeats */
#define REPEAT_MS 100

/* Each controller's buttons last frame, and the menu's timers. */
static struct {
    uint8_t prev;               /* NES buttons, as read_pad gives them */
    int prev_home;
    int combo_on;               /* Select+Start both held */
    uint32_t combo_since;
    int combo_used;             /* it opened (or was held in) the menu */
    uint32_t repeat_at;         /* the next repeat of a held direction */
    uint8_t mask;               /* held when the menu closed: ignored */
} pad[SLOTS];

static void open_device(int index) {
    if (!SDL_IsGameController(index)) return;
    if (virtual_only && !SDL_JoystickIsVirtual(index)) return;
    /* SDL also announces the controllers already connected when it
       starts, after gamepad_init has opened them: open each only once,
       or one pad plays as two players. */
    SDL_JoystickID id = SDL_JoystickGetDeviceInstanceID(index);
    for (int s = 0; s < SLOTS; s++)
        if (slot[s] && SDL_JoystickInstanceID(SDL_GameControllerGetJoystick(slot[s])) == id)
            return;
    for (int s = 0; s < SLOTS; s++) {
        if (slot[s]) continue;
        slot[s] = SDL_GameControllerOpen(index);
        memset(&pad[s], 0, sizeof pad[s]);
        return;
    }
}

static void close_instance(SDL_JoystickID id) {
    for (int s = 0; s < SLOTS; s++) {
        if (!slot[s]) continue;
        SDL_Joystick *j = SDL_GameControllerGetJoystick(slot[s]);
        if (SDL_JoystickInstanceID(j) == id) {
            SDL_GameControllerClose(slot[s]);
            slot[s] = NULL;
        }
    }
}

int gamepad_init(void) {
    SDL_SetHint(SDL_HINT_GAMECONTROLLER_USE_BUTTON_LABELS, "0");
    if (SDL_InitSubSystem(SDL_INIT_GAMECONTROLLER) != 0) return -1;
    for (int i = 0; i < SDL_NumJoysticks(); i++) open_device(i);
    return 0;
}

void gamepad_event(const SDL_Event *e) {
    if (e->type == SDL_CONTROLLERDEVICEADDED) open_device(e->cdevice.which);
    else if (e->type == SDL_CONTROLLERDEVICEREMOVED) close_instance(e->cdevice.which);
}

static uint8_t read_pad(SDL_GameController *c) {
    static const struct { SDL_GameControllerButton b; uint8_t nes; } map[] = {
        { SDL_CONTROLLER_BUTTON_DPAD_UP, BTN_UP },
        { SDL_CONTROLLER_BUTTON_DPAD_DOWN, BTN_DOWN },
        { SDL_CONTROLLER_BUTTON_DPAD_LEFT, BTN_LEFT },
        { SDL_CONTROLLER_BUTTON_DPAD_RIGHT, BTN_RIGHT },
        { SDL_CONTROLLER_BUTTON_B, BTN_A },        /* right face button */
        { SDL_CONTROLLER_BUTTON_A, BTN_B },        /* bottom face button */
        { SDL_CONTROLLER_BUTTON_START, BTN_START },
        { SDL_CONTROLLER_BUTTON_BACK, BTN_SELECT },
    };
    uint8_t out = 0;
    for (size_t i = 0; i < sizeof map / sizeof map[0]; i++)
        if (SDL_GameControllerGetButton(c, map[i].b)) out |= map[i].nes;
    int x = SDL_GameControllerGetAxis(c, SDL_CONTROLLER_AXIS_LEFTX);
    int y = SDL_GameControllerGetAxis(c, SDL_CONTROLLER_AXIS_LEFTY);
    if (x <= -STICK_THRESHOLD) out |= BTN_LEFT;
    if (x >= STICK_THRESHOLD) out |= BTN_RIGHT;
    if (y <= -STICK_THRESHOLD) out |= BTN_UP;      /* SDL: up is negative */
    if (y >= STICK_THRESHOLD) out |= BTN_DOWN;
    return out;
}

uint8_t gamepad_buttons(int player) {
    if (!slot[player]) return 0;
    uint8_t b = read_pad(slot[player]);
    pad[player].mask &= b;                  /* let go: seen again */
    return b & (uint8_t)~pad[player].mask;
}

void gamepad_ignore_held(void) {
    for (int s = 0; s < SLOTS; s++)
        pad[s].mask = slot[s] ? read_pad(slot[s]) : 0;
}

static void want_key(struct pad_wants *w, int key) {
    if (w->nkeys < (int)(sizeof w->keys / sizeof w->keys[0])) w->keys[w->nkeys++] = key;
}

#define DIRS (BTN_UP | BTN_DOWN | BTN_LEFT | BTN_RIGHT)

void gamepad_frame(uint32_t now, int menu_open, struct pad_wants *w) {
    memset(w, 0, sizeof *w);
    for (int s = 0; s < SLOTS; s++) {
        if (!slot[s]) continue;
        SDL_GameController *c = slot[s];
        uint8_t b = read_pad(c);
        int home = SDL_GameControllerGetButton(c, SDL_CONTROLLER_BUTTON_GUIDE);
        uint8_t pressed = b & (uint8_t)~pad[s].prev;
        int home_pressed = home && !pad[s].prev_home;
        int combo = (b & (BTN_START | BTN_SELECT)) == (BTN_START | BTN_SELECT);
        if (!combo) pad[s].combo_on = pad[s].combo_used = 0;
        else if (!pad[s].combo_on) { pad[s].combo_on = 1; pad[s].combo_since = now; }
        if (!menu_open) {
            if (combo && !pad[s].combo_used && now - pad[s].combo_since >= MENU_HOLD_MS) {
                pad[s].combo_used = 1;
                w->open = s + 1;
            }
            if (home_pressed) w->open = s + 1;
            if (SDL_GameControllerGetButton(c, SDL_CONTROLLER_BUTTON_LEFTSHOULDER)) w->rewind = 1;
            if (SDL_GameControllerGetButton(c, SDL_CONTROLLER_BUTTON_RIGHTSHOULDER)) w->fast = 1;
        } else {
            /* Held both in the menu: not a fresh hold when it closes. */
            if (combo) pad[s].combo_used = 1;
            static const struct { uint8_t btn; int key; } dirs[4] = {
                { BTN_UP, MENU_UP }, { BTN_DOWN, MENU_DOWN },
                { BTN_LEFT, MENU_LEFT }, { BTN_RIGHT, MENU_RIGHT },
            };
            int repeat = (b & DIRS) && !(pressed & DIRS) &&
                         (int32_t)(now - pad[s].repeat_at) >= 0;
            if (pressed & DIRS) pad[s].repeat_at = now + REPEAT_FIRST_MS;
            else if (repeat) pad[s].repeat_at = now + REPEAT_MS;
            for (int i = 0; i < 4; i++)
                if ((pressed & dirs[i].btn) || (repeat && (b & dirs[i].btn)))
                    want_key(w, dirs[i].key);
            if (pressed & (BTN_A | BTN_START)) want_key(w, MENU_OK);
            if ((pressed & BTN_B) || home_pressed) want_key(w, MENU_BACK);
        }
        pad[s].prev = b;
        pad[s].prev_home = home;
    }
}

/* --test-gamepads: plug in virtual controllers, press and tilt them, and
   check what comes out. No hardware or window needed. */
static int failures;

static void expect(const char *what, int player, uint8_t want) {
    SDL_GameControllerUpdate();
    uint8_t got = gamepad_buttons(player);
    if (got != want) {
        printf("FAIL %s: controller %d gave $%02X, expected $%02X\n",
               what, player + 1, got, want);
        failures++;
    }
}

static void drain(void) {
    SDL_Event e;
    SDL_PumpEvents();
    while (SDL_PollEvent(&e)) gamepad_event(&e);
}

static int attach(void) {
    SDL_VirtualJoystickDesc d;
    SDL_zero(d);
    d.version = SDL_VIRTUAL_JOYSTICK_DESC_VERSION;
    d.type = SDL_JOYSTICK_TYPE_GAMECONTROLLER;
    d.naxes = SDL_CONTROLLER_AXIS_MAX;
    d.nbuttons = SDL_CONTROLLER_BUTTON_MAX;
    d.name = "nesrecomp virtual controller";
    int index = SDL_JoystickAttachVirtualEx(&d);
    drain();
    return index;
}

static SDL_Joystick *joy(int player) {
    return slot[player] ? SDL_GameControllerGetJoystick(slot[player]) : NULL;
}

static void press(int player, SDL_GameControllerButton b, int down) {
    SDL_JoystickSetVirtualButton(joy(player), b, (Uint8)down);
}

static void tilt(int player, SDL_GameControllerAxis a, int v) {
    SDL_JoystickSetVirtualAxis(joy(player), a, (Sint16)v);
}

/* The menu buttons (PLAN-pause.md step 2), on controller 1 with a
   pretend clock: one gamepad_frame per call, at `t` milliseconds. */
static struct pad_wants w;

static void at(uint32_t t, int menu_open) {
    SDL_GameControllerUpdate();
    gamepad_frame(t, menu_open, &w);
}

static void expect_wants(const char *what, int open, int rewind, int fast,
                         int nkeys, const int *keys) {
    int ok = w.open == open && w.rewind == rewind && w.fast == fast && w.nkeys == nkeys;
    for (int i = 0; ok && i < nkeys; i++) ok = w.keys[i] == keys[i];
    if (!ok) {
        printf("FAIL %s: open %d rewind %d fast %d, %d menu keys (", what,
               w.open, w.rewind, w.fast, w.nkeys);
        for (int i = 0; i < w.nkeys; i++) printf("%s%d", i ? " " : "", w.keys[i]);
        printf("); expected open %d rewind %d fast %d, %d keys\n", open, rewind, fast, nkeys);
        failures++;
    }
}
#define NOTHING(what) expect_wants(what, 0, 0, 0, 0, NULL)
#define KEY(what, k) do { int k1[1] = { k }; expect_wants(what, 0, 0, 0, 1, k1); } while (0)

static void menu_checks(void) {
    const SDL_GameControllerButton
        START = SDL_CONTROLLER_BUTTON_START, BACK = SDL_CONTROLLER_BUTTON_BACK;
    at(0, 0); NOTHING("nothing held");

    /* A short Select+Start reaches the game and doesn't open the menu. */
    press(0, START, 1); press(0, BACK, 1);
    at(1000, 0); NOTHING("Select+Start just pressed");
    expect("Select+Start reach the game", 0, BTN_START | BTN_SELECT);
    at(1300, 0); at(1499, 0); NOTHING("Select+Start held 0.499 s");
    press(0, START, 0); press(0, BACK, 0);
    at(1600, 0); NOTHING("Select+Start let go");
    /* Start, then Select later: the half second counts from both. */
    press(0, START, 1); at(2000, 0);
    press(0, BACK, 1); at(2400, 0); at(2899, 0); NOTHING("Select held 0.499 s with Start");
    press(0, START, 0); press(0, BACK, 0); at(2950, 0);

    /* Held half a second: the menu, once. */
    press(0, START, 1); press(0, BACK, 1);
    at(3000, 0); at(3250, 0); NOTHING("Select+Start held 0.25 s");
    at(3500, 0); expect_wants("Select+Start held 0.5 s", 1, 0, 0, 0, NULL);
    at(3517, 0); NOTHING("the menu asked for once");

    /* In the menu: the buttons held as it opened do nothing. */
    at(3534, 1); NOTHING("Select+Start still held in the menu");
    press(0, BACK, 0); at(3551, 1); NOTHING("Select let go in the menu");
    press(0, START, 0); at(3568, 1); NOTHING("Start let go in the menu");
    press(0, START, 1); at(3585, 1); KEY("Start pressed in the menu", MENU_OK);
    press(0, START, 0); at(3602, 1);
    press(0, SDL_CONTROLLER_BUTTON_B, 1); at(3619, 1); KEY("A in the menu", MENU_OK);
    at(3636, 1); NOTHING("A held in the menu");
    press(0, SDL_CONTROLLER_BUTTON_B, 0);
    press(0, SDL_CONTROLLER_BUTTON_A, 1); at(3653, 1); KEY("B in the menu", MENU_BACK);
    press(0, SDL_CONTROLLER_BUTTON_A, 0);
    press(0, SDL_CONTROLLER_BUTTON_GUIDE, 1); at(3670, 1); KEY("Home in the menu", MENU_BACK);
    press(0, SDL_CONTROLLER_BUTTON_GUIDE, 0); at(3687, 1);
    press(0, SDL_CONTROLLER_BUTTON_DPAD_UP, 1); at(3704, 1); KEY("D-pad up in the menu", MENU_UP);
    press(0, SDL_CONTROLLER_BUTTON_DPAD_UP, 0); at(3721, 1);
    press(0, SDL_CONTROLLER_BUTTON_DPAD_LEFT, 1); at(3738, 1); KEY("D-pad left", MENU_LEFT);
    press(0, SDL_CONTROLLER_BUTTON_DPAD_LEFT, 0); at(3755, 1);
    press(0, SDL_CONTROLLER_BUTTON_DPAD_RIGHT, 1); at(3772, 1); KEY("D-pad right", MENU_RIGHT);
    press(0, SDL_CONTROLLER_BUTTON_DPAD_RIGHT, 0); at(3789, 1);
    /* Down held: once, then again after 0.4 s, then every 0.1 s. */
    press(0, SDL_CONTROLLER_BUTTON_DPAD_DOWN, 1); at(4000, 1); KEY("D-pad down", MENU_DOWN);
    at(4200, 1); at(4399, 1); NOTHING("D-pad down held 0.399 s");
    at(4400, 1); KEY("D-pad down held 0.4 s", MENU_DOWN);
    at(4450, 1); NOTHING("between repeats");
    at(4500, 1); KEY("D-pad down held 0.5 s", MENU_DOWN);
    press(0, SDL_CONTROLLER_BUTTON_DPAD_DOWN, 0); at(4600, 1); NOTHING("D-pad let go");
    tilt(0, SDL_CONTROLLER_AXIS_LEFTY, 32767); at(4617, 1); KEY("stick down in the menu", MENU_DOWN);
    tilt(0, SDL_CONTROLLER_AXIS_LEFTY, 0); at(4634, 1);
    /* Shoulders do nothing in the menu (rewind keeps no frames). */
    press(0, SDL_CONTROLLER_BUTTON_LEFTSHOULDER, 1); at(4651, 1); NOTHING("left shoulder in the menu");
    press(0, SDL_CONTROLLER_BUTTON_LEFTSHOULDER, 0);

    /* It closes with A held (the A that chose RESUME): the game doesn't
       see that A until it is let go and pressed again. */
    press(0, SDL_CONTROLLER_BUTTON_B, 1); at(4700, 1); KEY("A choosing", MENU_OK);
    gamepad_ignore_held();
    at(4717, 0); expect("A held as the menu closed", 0, 0);
    press(0, SDL_CONTROLLER_BUTTON_DPAD_UP, 1);
    expect("a new button after the menu closed", 0, BTN_UP);
    press(0, SDL_CONTROLLER_BUTTON_DPAD_UP, 0);
    press(0, SDL_CONTROLLER_BUTTON_B, 0); expect("A let go", 0, 0);
    press(0, SDL_CONTROLLER_BUTTON_B, 1); expect("A pressed again", 0, BTN_A);
    press(0, SDL_CONTROLLER_BUTTON_B, 0);

    /* Select+Start held as the menu closes: no menu again until let go. */
    press(0, START, 1); press(0, BACK, 1); at(5000, 1); at(5600, 1);
    gamepad_ignore_held();
    at(5617, 0); NOTHING("Select+Start held as the menu closed");
    at(6200, 0); NOTHING("Select+Start held on from the menu");
    press(0, START, 0); press(0, BACK, 0); at(6217, 0);
    gamepad_buttons(0);                     /* let go: the game sees them again */
    press(0, START, 1); press(0, BACK, 1); at(6300, 0); at(6800, 0);
    expect_wants("Select+Start held again 0.5 s", 1, 0, 0, 0, NULL);
    press(0, START, 0); press(0, BACK, 0); at(6817, 0);

    /* Home opens it at once (where the system lets it through). */
    press(0, SDL_CONTROLLER_BUTTON_GUIDE, 1); at(7000, 0);
    expect_wants("Home", 1, 0, 0, 0, NULL);
    at(7017, 0); NOTHING("Home held");
    press(0, SDL_CONTROLLER_BUTTON_GUIDE, 0); at(7034, 0);

    /* The shoulders: rewind and fast-forward, not buttons for the game. */
    press(0, SDL_CONTROLLER_BUTTON_LEFTSHOULDER, 1); at(7100, 0);
    expect_wants("left shoulder", 0, 1, 0, 0, NULL);
    expect("left shoulder isn't a game button", 0, 0);
    press(0, SDL_CONTROLLER_BUTTON_LEFTSHOULDER, 0); at(7117, 0); NOTHING("left shoulder let go");
    press(0, SDL_CONTROLLER_BUTTON_RIGHTSHOULDER, 1); at(7134, 0);
    expect_wants("right shoulder", 0, 0, 1, 0, NULL);
    expect("right shoulder isn't a game button", 0, 0);
    press(0, SDL_CONTROLLER_BUTTON_RIGHTSHOULDER, 0); at(7151, 0);

    /* Controller 2 can open it too, and says so. */
    if (slot[1]) {
        press(1, START, 1); press(1, BACK, 1); at(8000, 0); at(8500, 0);
        expect_wants("controller 2's Select+Start", 2, 0, 0, 0, NULL);
        press(1, START, 0); press(1, BACK, 0); at(8517, 0);
    }
}

int gamepad_self_test(void) {
    /* Real controllers connected to the Mac (or plugged in meanwhile)
       mustn't take the slots the test is checking. */
    virtual_only = 1;
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
    if (gamepad_init() != 0) {
        printf("FAIL: SDL game controller support: %s\n", SDL_GetError());
        return 1;
    }
    int first = attach();
    if (first < 0 || !slot[0]) {
        printf("FAIL: couldn't attach a virtual controller: %s\n", SDL_GetError());
        return 1;
    }
    expect("nothing pressed", 0, 0);
    press(0, SDL_CONTROLLER_BUTTON_B, 1);  expect("right face button", 0, BTN_A);
    press(0, SDL_CONTROLLER_BUTTON_B, 0);
    press(0, SDL_CONTROLLER_BUTTON_A, 1);  expect("bottom face button", 0, BTN_B);
    press(0, SDL_CONTROLLER_BUTTON_A, 0);
    press(0, SDL_CONTROLLER_BUTTON_START, 1);
    press(0, SDL_CONTROLLER_BUTTON_BACK, 1);
    expect("Start and Back", 0, BTN_START | BTN_SELECT);
    press(0, SDL_CONTROLLER_BUTTON_START, 0);
    press(0, SDL_CONTROLLER_BUTTON_BACK, 0);
    press(0, SDL_CONTROLLER_BUTTON_DPAD_UP, 1);
    press(0, SDL_CONTROLLER_BUTTON_DPAD_LEFT, 1);
    expect("D-pad up-left", 0, BTN_UP | BTN_LEFT);
    press(0, SDL_CONTROLLER_BUTTON_DPAD_UP, 0);
    press(0, SDL_CONTROLLER_BUTTON_DPAD_LEFT, 0);
    tilt(0, SDL_CONTROLLER_AXIS_LEFTX, -32768); expect("stick left", 0, BTN_LEFT);
    tilt(0, SDL_CONTROLLER_AXIS_LEFTX, 32767);  expect("stick right", 0, BTN_RIGHT);
    tilt(0, SDL_CONTROLLER_AXIS_LEFTX, 8000);   expect("stick near the middle", 0, 0);
    tilt(0, SDL_CONTROLLER_AXIS_LEFTX, 0);
    tilt(0, SDL_CONTROLLER_AXIS_LEFTY, 32767);  expect("stick down", 0, BTN_DOWN);
    tilt(0, SDL_CONTROLLER_AXIS_LEFTY, -32768); expect("stick up", 0, BTN_UP);
    tilt(0, SDL_CONTROLLER_AXIS_LEFTY, 0);

    attach();                           /* a second controller: player 2 */
    if (!slot[1]) { printf("FAIL: second controller didn't become controller 2\n"); failures++; }
    else {
        press(1, SDL_CONTROLLER_BUTTON_B, 1);
        expect("controller 2's right face button", 1, BTN_A);
        expect("controller 1 unaffected", 0, 0);
        press(1, SDL_CONTROLLER_BUTTON_B, 0);
    }

    attach();                           /* a third and fourth: players 3, 4 */
    attach();
    if (!slot[3]) { printf("FAIL: fourth controller didn't become controller 4\n"); failures++; }
    else {
        press(3, SDL_CONTROLLER_BUTTON_START, 1);
        expect("controller 4's Start", 3, BTN_START);
        expect("controller 3 unaffected", 2, 0);
        press(3, SDL_CONTROLLER_BUTTON_START, 0);
    }

    /* Unplug the first: controller 1 is free, controller 2 stays. */
    SDL_JoystickDetachVirtual(first);
    drain();
    if (slot[0]) { printf("FAIL: unplugged controller still controller 1\n"); failures++; }
    if (!slot[1]) { printf("FAIL: unplugging controller 1 dropped controller 2\n"); failures++; }
    attach();                           /* the next one fills slot 1 */
    if (!slot[0]) { printf("FAIL: new controller didn't take the free slot\n"); failures++; }
    else {
        press(0, SDL_CONTROLLER_BUTTON_A, 1);
        expect("new controller 1", 0, BTN_B);
    }

    press(0, SDL_CONTROLLER_BUTTON_A, 0);
    menu_checks();

    /* SDL announcing a controller that is already open (it does so for
       every one connected at the start): still one slot each. One is
       unplugged first, so there is a free slot a copy could take. */
    if (slot[3]) {
        SDL_JoystickID gone = SDL_JoystickInstanceID(joy(3));
        for (int i = 0; i < SDL_NumJoysticks(); i++)
            if (SDL_JoystickGetDeviceInstanceID(i) == gone) { SDL_JoystickDetachVirtual(i); break; }
        drain();
        if (slot[3]) { printf("FAIL: unplugged controller 4 still there\n"); failures++; }
    }
    int before = 0, after = 0;
    for (int s = 0; s < SLOTS; s++) before += slot[s] != NULL;
    for (int i = 0; i < SDL_NumJoysticks(); i++) {
        SDL_Event e;
        SDL_zero(e);
        e.type = SDL_CONTROLLERDEVICEADDED;
        e.cdevice.which = i;
        gamepad_event(&e);
    }
    for (int s = 0; s < SLOTS; s++) after += slot[s] != NULL;
    if (after != before) {
        printf("FAIL: controllers announced again took %d more slot(s)\n", after - before);
        failures++;
    }

    if (failures) return 1;
    printf("PASS: game controller mapping and menu buttons (virtual controllers)\n");
    return 0;
}
