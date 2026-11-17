/* nesrecomp app: supporting it (see support.h). Objective-C for the Mac's
   menu bar, which SDL makes (the app menu: About, Hide, Quit...) and
   which C can't reach. Without ARC: the one object lives as long as the
   app. */
#import <Cocoa/Cocoa.h>
#include <stdio.h>
#include <string.h>
#include "os.h"
#include "support.h"

int support_open(void) { return os_open_url(SUPPORT_URL); }

@interface NRSupport : NSObject
- (void)support:(id)sender;
@end

@implementation NRSupport
- (void)support:(id)sender {
    (void)sender;
    support_open();
}
@end

static NRSupport *target;

static NSMenu *app_menu(void) {
    NSMenu *main = [NSApp mainMenu];
    if (!main || [main numberOfItems] < 1) return nil;
    return [[main itemAtIndex:0] submenu];
}

static NSString *title(void) {
    return [NSString stringWithUTF8String:SUPPORT_MENU_TITLE];
}

int support_menu_add(void *window) {
    (void)window;                       /* (the Mac's menu is the app's) */
    @autoreleasepool {
        NSMenu *menu = app_menu();
        if (!menu) return -1;
        if ([menu indexOfItemWithTitle:title()] >= 0) return 0;
        if (!target) target = [[NRSupport alloc] init];
        NSMenuItem *item = [[NSMenuItem alloc] initWithTitle:title() action:@selector(support:)
                                               keyEquivalent:@""];
        [item setTarget:target];
        /* After "About NES RECOMP", the menu's first item. */
        [menu insertItem:item atIndex:[menu numberOfItems] ? 1 : 0];
        [item release];
    }
    return 0;
}

void support_menu_titles(char *out, size_t n) {
    out[0] = 0;
    @autoreleasepool {
        NSMenu *menu = app_menu();
        size_t k = 0;
        for (NSInteger i = 0; menu && i < [menu numberOfItems]; i++) {
            NSMenuItem *it = [menu itemAtIndex:i];
            const char *t = [it isSeparatorItem] ? "-" : [[it title] UTF8String];
            int w = snprintf(out + k, n - k, "%s\n", t ? t : "");
            if (w < 0 || (size_t)w >= n - k) break;
            k += (size_t)w;
        }
    }
}

int support_menu_choose(void) {
    @autoreleasepool {
        NSMenu *menu = app_menu();
        NSInteger i = menu ? [menu indexOfItemWithTitle:title()] : -1;
        if (i < 0) return -1;
        [menu performActionForItemAtIndex:i];
    }
    return 0;
}
