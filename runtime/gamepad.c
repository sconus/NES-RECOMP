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
   That's the usual layout: the pause menu's PADS page changes it, for
   every pad at once (controls.c, PLAN-controllers.md step 4). The left
   stick is always the D-pad's directions, whatever the layout. Menu
   moves and Select+Start follow the layout (they're NES buttons), so
   they're always on some button; Home and the shoulders never move.

   Beyond the NES buttons (PLAN-pause.md step 2):
     Select+Start held 0.5 s   opens the pause menu (a short press of
                               both still reaches the game)
     Home / Guide              opens it too, where the system lets SDL
                               see it
     left shoulder held        rewind
     right shoulder held       fast-forward
   In the menu: the D-pad (or stick) moves, A or Start chooses, B or
   Home closes. Only presses made after it opened count, and buttons
   held when it closes don't reach the game until let go.

   The menu's button test (PLAN-controllers.md step 1) lights each
   button as it's pressed, so there no button moves or chooses: only
   Home, or Select+Start held 0.5 s, leave it. Each controller's own
   player lights (PlayStation and Switch pads have them) show its slot. */
#include <SDL.h>
#include <stdio.h>
#include <string.h>
#include "gamepad.h"
#include "input.h"
#include "menu.h"
#include "controls.h"

#define STICK_THRESHOLD 16384           /* half way, of 32767 */

#define SLOTS 4
static SDL_GameController *slot[SLOTS];
static int virtual_only;        /* the self-test ignores real controllers */
static int started;             /* gamepad_init has run */

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
        if (slot[s]) SDL_GameControllerSetPlayerIndex(slot[s], s);  /* its lights */
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
    started = 1;
    for (int i = 0; i < SDL_NumJoysticks(); i++) open_device(i);
    return 0;
}

void gamepad_event(const SDL_Event *e) {
    if (e->type == SDL_CONTROLLERDEVICEADDED) open_device(e->cdevice.which);
    else if (e->type == SDL_CONTROLLERDEVICEREMOVED) close_instance(e->cdevice.which);
}

static void held_buttons(SDL_GameController *c, uint8_t held[SDL_CONTROLLER_BUTTON_MAX]) {
    for (int b = 0; b < SDL_CONTROLLER_BUTTON_MAX; b++)
        held[b] = SDL_GameControllerGetButton(c, (SDL_GameControllerButton)b) != 0;
}

static uint8_t read_pad(SDL_GameController *c) {
    uint8_t held[SDL_CONTROLLER_BUTTON_MAX];
    held_buttons(c, held);
    uint8_t out = controls_pad_buttons(held, SDL_CONTROLLER_BUTTON_MAX);   /* the layout */
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

/* The PADS page waiting for a button (menu.c): what each pad held
   when it started, so only a fresh press is the answer. */
static uint8_t watch_prev[SLOTS][SDL_CONTROLLER_BUTTON_MAX];

void gamepad_watch_start(void) {
    for (int s = 0; s < SLOTS; s++) {
        if (slot[s]) held_buttons(slot[s], watch_prev[s]);
        else memset(watch_prev[s], 0, sizeof watch_prev[s]);
    }
}

int gamepad_watch(void) {
    int found = -1;
    for (int s = 0; s < SLOTS; s++) {
        uint8_t held[SDL_CONTROLLER_BUTTON_MAX] = { 0 };
        if (slot[s]) held_buttons(slot[s], held);
        for (int b = 0; b < SDL_CONTROLLER_BUTTON_MAX; b++)
            if (found < 0 && held[b] && !watch_prev[s][b] && b != SDL_CONTROLLER_BUTTON_GUIDE)
                found = b;
        memcpy(watch_prev[s], held, sizeof held);
    }
    return found;
}

void gamepad_layout_changed(void) {
    /* The buttons held now, under the new layout, aren't fresh presses:
       the one that answered mustn't also move the menu. */
    for (int s = 0; s < SLOTS; s++)
        if (slot[s]) pad[s].prev = read_pad(slot[s]);
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
        if (menu_open == 2) {
            /* The button test: every button only lights up. A fresh
               Select+Start held 0.5 s, or Home, leaves it. */
            if (combo && !pad[s].combo_used && now - pad[s].combo_since >= MENU_HOLD_MS) {
                pad[s].combo_used = 1;
                want_key(w, MENU_LEAVE);
            } else if (home_pressed) want_key(w, MENU_LEAVE);
        } else if (!menu_open) {
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
            if (pressed & BTN_B) want_key(w, MENU_BACK);
            if (home_pressed) want_key(w, MENU_LEAVE);
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

/* What a slot holds (gamepad.h), for the Controllers page. */
static const char *brand(SDL_GameController *c) {
    switch (SDL_GameControllerGetType(c)) {
    case SDL_CONTROLLER_TYPE_XBOX360: return "XBOX 360";
    case SDL_CONTROLLER_TYPE_XBOXONE: return "XBOX";
    case SDL_CONTROLLER_TYPE_PS3: return "PS3";
    case SDL_CONTROLLER_TYPE_PS4: return "PS4";
    case SDL_CONTROLLER_TYPE_PS5: return "PS5";
    case SDL_CONTROLLER_TYPE_NINTENDO_SWITCH_PRO: return "SWITCH PRO";
    case SDL_CONTROLLER_TYPE_NINTENDO_SWITCH_JOYCON_LEFT:
    case SDL_CONTROLLER_TYPE_NINTENDO_SWITCH_JOYCON_RIGHT:
    case SDL_CONTROLLER_TYPE_NINTENDO_SWITCH_JOYCON_PAIR: return "JOY-CON";
    case SDL_CONTROLLER_TYPE_AMAZON_LUNA: return "LUNA";
    case SDL_CONTROLLER_TYPE_GOOGLE_STADIA: return "STADIA";
    case SDL_CONTROLLER_TYPE_NVIDIA_SHIELD: return "SHIELD";
    case SDL_CONTROLLER_TYPE_VIRTUAL: return "VIRTUAL";
    default: return NULL;
    }
}

void gamepad_info(int player, struct pad_info *p) {
    memset(p, 0, sizeof *p);
    SDL_GameController *c = player >= 0 && player < SLOTS ? slot[player] : NULL;
    if (!c) return;
    p->present = 1;
    const char *n = SDL_GameControllerName(c);
    snprintf(p->name, sizeof p->name, "%s", n ? n : "CONTROLLER");
    for (char *q = p->name; *q; q++)
        if (*q >= 'a' && *q <= 'z') *q -= 32;
    p->brand = brand(c);
    p->nes = read_pad(c);
    p->lb = SDL_GameControllerGetButton(c, SDL_CONTROLLER_BUTTON_LEFTSHOULDER);
    p->rb = SDL_GameControllerGetButton(c, SDL_CONTROLLER_BUTTON_RIGHTSHOULDER);
    p->home = SDL_GameControllerGetButton(c, SDL_CONTROLLER_BUTTON_GUIDE);
}

/* Virtual controllers for the tests (gamepad.h): "2:a+start". */
static const struct { const char *name; unsigned bit; SDL_GameControllerButton b; } vbuttons[] = {
    { "a", PAD_TEST_A, SDL_CONTROLLER_BUTTON_B },           /* by position, as read_pad */
    { "b", PAD_TEST_B, SDL_CONTROLLER_BUTTON_A },
    { "select", PAD_TEST_SELECT, SDL_CONTROLLER_BUTTON_BACK },
    { "start", PAD_TEST_START, SDL_CONTROLLER_BUTTON_START },
    { "up", PAD_TEST_UP, SDL_CONTROLLER_BUTTON_DPAD_UP },
    { "down", PAD_TEST_DOWN, SDL_CONTROLLER_BUTTON_DPAD_DOWN },
    { "left", PAD_TEST_LEFT, SDL_CONTROLLER_BUTTON_DPAD_LEFT },
    { "right", PAD_TEST_RIGHT, SDL_CONTROLLER_BUTTON_DPAD_RIGHT },
    { "lb", PAD_TEST_LB, SDL_CONTROLLER_BUTTON_LEFTSHOULDER },
    { "rb", PAD_TEST_RB, SDL_CONTROLLER_BUTTON_RIGHTSHOULDER },
    { "home", PAD_TEST_HOME, SDL_CONTROLLER_BUTTON_GUIDE },
    { "x", PAD_TEST_X, SDL_CONTROLLER_BUTTON_X },           /* the left face button */
    { "y", PAD_TEST_Y, SDL_CONTROLLER_BUTTON_Y },           /* the top one */
    { "ls", PAD_TEST_LS, SDL_CONTROLLER_BUTTON_LEFTSTICK }, /* the sticks, pressed in */
    { "rs", PAD_TEST_RS, SDL_CONTROLLER_BUTTON_RIGHTSTICK },
};
#define NVBUTTONS (sizeof vbuttons / sizeof vbuttons[0])

int gamepad_parse_virtual(const char *spec, int *player, unsigned *buttons) {
    if (spec[0] < '1' || spec[0] > '4' || spec[1] != ':') return 0;
    *player = spec[0] - '1';
    *buttons = 0;
    const char *q = spec + 2;
    if (!strcmp(q, "none")) return 1;
    while (*q) {
        size_t len = strcspn(q, "+");
        size_t i;
        for (i = 0; i < NVBUTTONS; i++)
            if (strlen(vbuttons[i].name) == len && !strncmp(q, vbuttons[i].name, len)) break;
        if (i == NVBUTTONS) return 0;
        *buttons |= vbuttons[i].bit;
        q += len;
        if (*q == '+') q++;
    }
    return *buttons != 0;
}

void gamepad_virtual(int player, unsigned buttons) {
    if (player < 0 || player >= SLOTS) return;
    if (!started) {                 /* headless: virtual controllers only */
        virtual_only = 1;
        SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
        if (gamepad_init() != 0) {
            fprintf(stderr, "no game controller support: %s\n", SDL_GetError());
            return;
        }
    }
    /* Plugged in until one lands in this slot; the ones that filled the
       free slots before it are unplugged again. */
    int extra[SLOTS], nextra = 0;
    while (!slot[player]) {
        int had[SLOTS];
        for (int s = 0; s < SLOTS; s++) had[s] = slot[s] != NULL;
        if (attach() < 0) { fprintf(stderr, "can't attach a virtual controller\n"); return; }
        int landed = -1;
        for (int s = 0; s < SLOTS; s++) if (!had[s] && slot[s]) landed = s;
        if (landed < 0) return;             /* all four taken */
        if (landed != player) extra[nextra++] = landed;
    }
    for (int i = 0; i < nextra; i++) {
        SDL_JoystickID id = SDL_JoystickInstanceID(joy(extra[i]));
        for (int d = 0; d < SDL_NumJoysticks(); d++)
            if (SDL_JoystickGetDeviceInstanceID(d) == id) { SDL_JoystickDetachVirtual(d); break; }
    }
    drain();
    for (size_t i = 0; i < NVBUTTONS; i++)
        press(player, vbuttons[i].b, (buttons & vbuttons[i].bit) != 0);
    SDL_GameControllerUpdate();
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
    press(0, SDL_CONTROLLER_BUTTON_GUIDE, 1); at(3670, 1); KEY("Home in the menu", MENU_LEAVE);
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

    /* The button test (PLAN-controllers.md): buttons only light up. */
    at(7200, 2); NOTHING("nothing held on the button test");
    press(0, SDL_CONTROLLER_BUTTON_A, 1); at(7217, 2); NOTHING("B on the button test");
    press(0, SDL_CONTROLLER_BUTTON_A, 0);
    press(0, SDL_CONTROLLER_BUTTON_B, 1); at(7234, 2); NOTHING("A on the button test");
    press(0, SDL_CONTROLLER_BUTTON_B, 0);
    press(0, SDL_CONTROLLER_BUTTON_START, 1); at(7251, 2); NOTHING("Start on the button test");
    press(0, SDL_CONTROLLER_BUTTON_START, 0);
    press(0, SDL_CONTROLLER_BUTTON_DPAD_DOWN, 1); at(7268, 2); at(7800, 2);
    NOTHING("D-pad held on the button test");
    press(0, SDL_CONTROLLER_BUTTON_DPAD_DOWN, 0); at(7817, 2);
    press(0, SDL_CONTROLLER_BUTTON_GUIDE, 1); at(7834, 2); KEY("Home on the button test", MENU_LEAVE);
    press(0, SDL_CONTROLLER_BUTTON_GUIDE, 0); at(7851, 2);
    press(0, START, 1); press(0, BACK, 1);
    at(7900, 2); NOTHING("Select+Start just pressed on the button test");
    at(8399, 2); NOTHING("Select+Start held 0.499 s on the button test");
    at(8400, 2); KEY("Select+Start held 0.5 s on the button test", MENU_LEAVE);
    at(8417, 1); at(8900, 2); NOTHING("Select+Start held on, back on the test");
    press(0, START, 0); press(0, BACK, 0); at(8917, 1);
    struct pad_info pi;
    press(0, SDL_CONTROLLER_BUTTON_LEFTSHOULDER, 1); press(0, SDL_CONTROLLER_BUTTON_B, 1);
    SDL_GameControllerUpdate();
    gamepad_info(0, &pi);
    if (!pi.present || pi.nes != BTN_A || !pi.lb || pi.rb || pi.home ||
        !pi.brand || strcmp(pi.brand, "VIRTUAL") || strcmp(pi.name, "NESRECOMP VIRTUAL CONTROLLER")) {
        printf("FAIL the button test's view of controller 1: present %d NES $%02X LB %d RB %d "
               "Home %d, %s (%s)\n", pi.present, pi.nes, pi.lb, pi.rb, pi.home,
               pi.brand ? pi.brand : "no brand", pi.name);
        failures++;
    }
    press(0, SDL_CONTROLLER_BUTTON_LEFTSHOULDER, 0); press(0, SDL_CONTROLLER_BUTTON_B, 0);
    at(9000, 0);
    gamepad_info(2, &pi);
    if (slot[2] == NULL && pi.present) { printf("FAIL an empty slot shows a controller\n"); failures++; }
    {
        int pl; unsigned bt;
        if (!gamepad_parse_virtual("2:a+start+lb", &pl, &bt) || pl != 1 ||
            bt != (PAD_TEST_A | PAD_TEST_START | PAD_TEST_LB) ||
            gamepad_parse_virtual("5:a", &pl, &bt) || gamepad_parse_virtual("1:q", &pl, &bt) ||
            !gamepad_parse_virtual("1:none", &pl, &bt) || bt) {
            printf("FAIL reading the script's pad= words\n");
            failures++;
        }
    }

    /* Controller 2 can open it too, and says so. */
    if (slot[1]) {
        press(1, START, 1); press(1, BACK, 1); at(8000, 0); at(8500, 0);
        expect_wants("controller 2's Select+Start", 2, 0, 0, 0, NULL);
        press(1, START, 0); press(1, BACK, 0); at(8517, 0);
    }
}

/* The PADS page's layout (PLAN-controllers.md step 4): every pad, the
   menu's ways in and moves, and the wait for a button. */
static void layout_checks(void) {
    const SDL_GameControllerButton Y = SDL_CONTROLLER_BUTTON_Y, X = SDL_CONTROLLER_BUTTON_X,
        START = SDL_CONTROLLER_BUTTON_START, BACK = SDL_CONTROLLER_BUTTON_BACK,
        LS = SDL_CONTROLLER_BUTTON_LEFTSTICK;
    if (!slot[0] || !slot[1]) { printf("FAIL: the layout checks need controllers 1 and 2\n"); failures++; return; }
    controls_pad_set(CB_A, Y, NULL);                /* A on the top button */
    press(0, Y, 1); expect("the top button is A on controller 1", 0, BTN_A);
    press(0, Y, 0);
    press(1, Y, 1); expect("... and on controller 2", 1, BTN_A);
    press(1, Y, 0);
    press(0, SDL_CONTROLLER_BUTTON_B, 1); expect("the right button no longer A", 0, 0);
    press(0, SDL_CONTROLLER_BUTTON_B, 0);
    tilt(0, SDL_CONTROLLER_AXIS_LEFTX, -32768); expect("the stick still left", 0, BTN_LEFT);
    tilt(0, SDL_CONTROLLER_AXIS_LEFTX, 0);

    /* Select moved to the left button: Select+Start is that and Start. */
    controls_pad_set(CB_SELECT, X, NULL);
    at(20000, 0);
    press(0, X, 1); press(0, START, 1);
    at(20100, 0); at(20600, 0);
    expect_wants("the new Select+Start held 0.5 s", 1, 0, 0, 0, NULL);
    press(0, X, 0); press(0, START, 0); at(20617, 0);
    press(0, BACK, 1); press(0, START, 1);
    at(21000, 0); at(21600, 0); NOTHING("the old Select (now nothing) with Start held 0.5 s");
    press(0, BACK, 0); press(0, START, 0); at(21617, 0);
    press(1, X, 1); press(1, START, 1);
    at(22000, 0); at(22500, 0);
    expect_wants("controller 2's new Select+Start", 2, 0, 0, 0, NULL);
    press(1, X, 0); press(1, START, 0); at(22517, 0);
    at(22534, 1); press(0, Y, 1); at(22551, 1); KEY("the top button (A) chooses in the menu", MENU_OK);
    press(0, Y, 0); at(22568, 1);

    /* Waiting: only a fresh press, on any pad, is the answer; Home never. */
    press(0, Y, 1); SDL_GameControllerUpdate();
    gamepad_watch_start();
    SDL_GameControllerUpdate();
    if (gamepad_watch() != -1) { printf("FAIL a button held as the wait started taken\n"); failures++; }
    press(0, SDL_CONTROLLER_BUTTON_GUIDE, 1); SDL_GameControllerUpdate();
    if (gamepad_watch() != -1) { printf("FAIL Home taken as the answer\n"); failures++; }
    press(0, SDL_CONTROLLER_BUTTON_GUIDE, 0);
    press(0, Y, 0); SDL_GameControllerUpdate(); gamepad_watch();
    press(0, Y, 1); SDL_GameControllerUpdate();
    int got = gamepad_watch();
    if (got != Y) { printf("FAIL the top button pressed again: %d, not %d\n", got, Y); failures++; }
    press(0, Y, 0);
    press(1, SDL_CONTROLLER_BUTTON_RIGHTSHOULDER, 1); SDL_GameControllerUpdate();
    got = gamepad_watch();
    if (got != SDL_CONTROLLER_BUTTON_RIGHTSHOULDER) {
        printf("FAIL controller 2's shoulder: %d (the menu refuses it, but it's seen)\n", got);
        failures++;
    }
    press(1, SDL_CONTROLLER_BUTTON_RIGHTSHOULDER, 0);

    /* The answer held as the layout changes isn't a menu press too. */
    at(23000, 2); press(0, LS, 1); at(23017, 2);
    controls_pad_set(CB_A, LS, NULL);
    gamepad_layout_changed();
    at(23034, 1); NOTHING("the button that answered, held on as A");
    press(0, LS, 0); at(23051, 1);
    controls_pad_defaults();
    gamepad_layout_changed();
    press(0, SDL_CONTROLLER_BUTTON_B, 1); expect("DEFAULTS: the right button A again", 0, BTN_A);
    press(0, SDL_CONTROLLER_BUTTON_B, 0);
    at(23068, 0);
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
    layout_checks();

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
    printf("PASS: game controller mapping, layouts and menu buttons (virtual controllers)\n");
    return 0;
}
