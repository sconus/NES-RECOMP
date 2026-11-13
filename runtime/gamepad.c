/* nesrecomp runtime: game controllers (Xbox, PlayStation, Switch Pro and
   others SDL knows) as NES controllers 1 and 2.

   The first controller connected plays controller 1, the second
   controller 2; a controller plugged in later takes the first free slot,
   and unplugging one frees its slot. The keyboard keeps working
   alongside.

   Mapping, by position as on the NES pad (B on the left, A on the right):
     D-pad or left stick   D-pad (the stick past half way)
     right face button     A    (Xbox B, PlayStation circle, Switch A)
     bottom face button    B    (Xbox A, PlayStation cross, Switch B)
     Start / Menu          Start
     Back / Select / Share Select
   SDL is told not to swap Nintendo controllers' buttons to match their
   labels, so the same position means the same button on every brand. */
#include <SDL.h>
#include <stdio.h>
#include "gamepad.h"
#include "input.h"

#define STICK_THRESHOLD 16384           /* half way, of 32767 */

static SDL_GameController *slot[2];
static int virtual_only;        /* the self-test ignores real controllers */

static void open_device(int index) {
    if (!SDL_IsGameController(index)) return;
    if (virtual_only && !SDL_JoystickIsVirtual(index)) return;
    for (int s = 0; s < 2; s++) {
        if (slot[s]) continue;
        slot[s] = SDL_GameControllerOpen(index);
        return;
    }
}

static void close_instance(SDL_JoystickID id) {
    for (int s = 0; s < 2; s++) {
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
    return slot[player] ? read_pad(slot[player]) : 0;
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

    if (failures) return 1;
    printf("PASS: game controller mapping (virtual controllers)\n");
    return 0;
}
