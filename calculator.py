import pygame
import sys
import math
import re
from collections import deque
import time

# ── Initialisation ──────────────────────────────────────────────────────────
pygame.init()
pygame.display.set_caption("NEON CALC  •  Scientific Calculator")

# ── Constants ────────────────────────────────────────────────────────────────
W, H = 560, 900
FPS  = 60

# Colour palette  (neon-on-dark)
BG        = (8,   10,  18)
PANEL     = (13,  16,  26)
BORDER    = (28,  33,  55)
NEON_CYAN = (0,   240, 255)
NEON_PINK = (255,  20, 147)
NEON_LIME = (57,  255,  20)
NEON_GOLD = (255, 215,   0)
DIM_CYAN  = (0,   120, 130)
DIM_PINK  = (120,  10,  70)
WHITE     = (230, 235, 255)
GRAY      = (90,  95, 120)
DARK_GRAY = (35,  38,  55)
RED_ERR   = (255,  60,  60)

# Font sizes
def load_font(size, bold=False):
    try:
        name = "dejavusansmono" if not bold else "dejavusansmonobold"
        return pygame.font.SysFont(name, size, bold=bold)
    except Exception:
        return pygame.font.SysFont("monospace", size, bold=bold)

F_HUGE   = load_font(42, bold=True)
F_LARGE  = load_font(26, bold=True)
F_MED    = load_font(18, bold=True)
F_SMALL  = load_font(14)
F_TINY   = load_font(12)

# ── Helper: rounded rect with glow ──────────────────────────────────────────
def draw_rounded_rect(surf, color, rect, radius=10, border=0, border_color=None):
    pygame.draw.rect(surf, color, rect, border_radius=radius)
    if border and border_color:
        pygame.draw.rect(surf, border_color, rect, border, border_radius=radius)

def draw_glow(surf, color, rect, radius=10, strength=3):
    glow_color = tuple(min(255, int(c * 0.35)) for c in color)
    for i in range(strength, 0, -1):
        expanded = pygame.Rect(rect.x - i, rect.y - i,
                               rect.width + 2*i, rect.height + 2*i)
        pygame.draw.rect(surf, glow_color, expanded, 1, border_radius=radius + i)

# ── Ripple Effect ────────────────────────────────────────────────────────────
class Ripple:
    def __init__(self, x, y, color):
        self.x, self.y = x, y
        self.color = color
        self.radius = 4
        self.max_radius = 38
        self.alpha = 180
        self.alive = True

    def update(self):
        self.radius += 2.5
        self.alpha  -= 12
        if self.radius >= self.max_radius or self.alpha <= 0:
            self.alive = False

    def draw(self, surf):
        if self.alpha <= 0: return
        s = pygame.Surface((self.max_radius*2+4, self.max_radius*2+4), pygame.SRCALPHA)
        col = (*self.color, max(0, int(self.alpha)))
        pygame.draw.circle(s, col, (self.max_radius+2, self.max_radius+2), int(self.radius), 2)
        surf.blit(s, (self.x - self.max_radius - 2, self.y - self.max_radius - 2))

# ── Button ────────────────────────────────────────────────────────────────────
class Button:
    def __init__(self, label, x, y, w, h,
                 bg=DARK_GRAY, fg=WHITE, accent=NEON_CYAN,
                 action=None, font=None, tooltip=""):
        self.label   = label
        self.rect    = pygame.Rect(x, y, w, h)
        self.bg      = bg
        self.fg      = fg
        self.accent  = accent
        self.action  = action
        self.font    = font or F_MED
        self.tooltip = tooltip
        self.pressed = False
        self.hover   = False
        self.press_t = 0.0      # animation timer 0→1

    def hit(self, pos):
        return self.rect.collidepoint(pos)

    def update(self, dt):
        if self.pressed:
            self.press_t = min(1.0, self.press_t + dt * 10)
        else:
            self.press_t = max(0.0, self.press_t - dt * 8)

    def draw(self, surf, ripples):
        t    = self.press_t
        shrink = int(t * 3)
        r = self.rect.inflate(-shrink * 2, -shrink * 2)
        r.center = self.rect.center

        # Hover / press tint
        if t > 0.01:
            mix = tuple(min(255, int(self.bg[i] + (self.accent[i]-self.bg[i]) * t * 0.45))
                        for i in range(3))
            draw_rounded_rect(surf, mix, r, radius=8)
        else:
            draw_rounded_rect(surf, self.bg, r, radius=8)

        # Border
        b_col = self.accent if (self.hover or t > 0.1) else BORDER
        pygame.draw.rect(surf, b_col, r, 1, border_radius=8)

        # Glow when hovered
        if self.hover:
            draw_glow(surf, self.accent, r, radius=8, strength=2)

        # Label
        txt = self.font.render(self.label, True, self.fg if not self.hover else self.accent)
        surf.blit(txt, txt.get_rect(center=r.center))

# ── Expression Evaluator ────────────────────────────────────────────────────
SAFE_NAMES = {
    k: v for k, v in math.__dict__.items() if not k.startswith("_")
}
SAFE_NAMES.update({"abs": abs, "round": round})

def preprocess(expr: str, use_radians: bool) -> str:
    """Expand human-friendly notation to valid Python math."""
    expr = expr.replace("×", "*").replace("÷", "/").replace("^", "**")
    expr = expr.replace("π", "pi").replace("e", "e")

    # trig: wrap argument with deg→rad conversion if in degree mode
    if not use_radians:
        for fn in ("sin", "cos", "tan"):
            expr = re.sub(
                rf"\b{fn}\s*\(",
                f"{fn}(radians(",
                expr
            )
        # close extra parens
        depth = 0
        balanced = []
        for ch in expr:
            balanced.append(ch)
            if ch == "(": depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    depth = 0
        # add missing closing parens
        while depth > 0:
            balanced.append(")")
            depth -= 1
        expr = "".join(balanced)
    else:
        pass  # radians: pass trig directly

    # implicit multiplication: "2(" → "2*(", but NOT "log10(" → "log1*("
    # Only match digits not preceded by a word character (i.e. standalone numeric literals)
    expr = re.sub(r"(?<!\w)(\d+)\(", r"\1*(", expr)
    expr = re.sub(r"\)(\d)",          r")*\1", expr)
    return expr

def safe_eval(expr: str, use_radians: bool = True):
    if not expr.strip():
        return None, ""
    try:
        processed = preprocess(expr, use_radians)
        result = eval(processed, {"__builtins__": {}}, SAFE_NAMES)  # type: ignore[arg-type]
        if isinstance(result, complex):
            return result, str(result)
        # Pretty-print floats
        if isinstance(result, float):
            if result != result:        return None, "Undefined"
            if math.isinf(result):      return None, "Infinity"
            # trim trailing zeros
            formatted = f"{result:.10g}"
            return result, formatted
        return result, str(result)
    except ZeroDivisionError:
        return None, "Division by Zero"
    except Exception as e:
        return None, f"Error"

# ── Main Calculator App ──────────────────────────────────────────────────────
class Calculator:
    def __init__(self):
        self.screen  = pygame.display.set_mode((W, H))
        self.clock   = pygame.time.Clock()
        self.ripples : list[Ripple] = []
        self.buttons : list[Button] = []
        self.history : deque[tuple[str,str]] = deque(maxlen=6)

        # State
        self.expr        = ""
        self.preview     = ""
        self.error       = False
        self.use_radians = True
        self.memory      = 0.0
        self.mem_active  = False
        self.just_result = False    # flag: last action was "="
        self.cursor_vis  = True
        self.cursor_t    = 0.0

        # Scanline texture
        self.scanlines = self._make_scanlines()

        self._build_buttons()

    # ── Scanline overlay ────────────────────────────────────────────────────
    def _make_scanlines(self):
        s = pygame.Surface((W, H), pygame.SRCALPHA)
        for y in range(0, H, 3):
            pygame.draw.line(s, (0, 0, 0, 28), (0, y), (W, y))
        return s

    # ── Button layout ───────────────────────────────────────────────────────
    def _build_buttons(self):
        self.buttons.clear()

        BUTTON_DATA = [
            # row 0 — memory + mode
            [("MC",   DARK_GRAY, WHITE,      NEON_PINK, "memory_clear"),
             ("MR",   DARK_GRAY, WHITE,      NEON_PINK, "memory_recall"),
             ("M+",   DARK_GRAY, WHITE,      NEON_PINK, "memory_add"),
             ("M−",   DARK_GRAY, WHITE,      NEON_PINK, "memory_sub"),
             ("DEG" if self.use_radians else "RAD",
                      DARK_GRAY, NEON_GOLD, NEON_GOLD,  "toggle_angle")],

            # row 1 — scientific
            [("sin",  DARK_GRAY, NEON_CYAN,  NEON_CYAN, "sin("),
             ("cos",  DARK_GRAY, NEON_CYAN,  NEON_CYAN, "cos("),
             ("tan",  DARK_GRAY, NEON_CYAN,  NEON_CYAN, "tan("),
             ("log",  DARK_GRAY, NEON_CYAN,  NEON_CYAN, "log10("),
             ("ln",   DARK_GRAY, NEON_CYAN,  NEON_CYAN, "log(")],

            # row 2 — scientific cont.
            [("√",    DARK_GRAY, NEON_CYAN,  NEON_CYAN, "sqrt("),
             ("x²",   DARK_GRAY, NEON_CYAN,  NEON_CYAN, "**2"),
             ("xʸ",   DARK_GRAY, NEON_CYAN,  NEON_CYAN, "**"),
             ("π",    DARK_GRAY, NEON_LIME,  NEON_LIME, "pi"),
             ("e",    DARK_GRAY, NEON_LIME,  NEON_LIME, "e")],

            # row 3 — standard top
            [("(",    DARK_GRAY, WHITE,       NEON_CYAN, "("),
             (")",    DARK_GRAY, WHITE,       NEON_CYAN, ")"),
             ("%",    DARK_GRAY, WHITE,       NEON_CYAN, "%"),
             ("±",    DARK_GRAY, WHITE,       NEON_CYAN, "negate"),
             ("⌫",    (50,20,20), NEON_PINK,  NEON_PINK, "backspace")],

            # row 4 — digits
            [("7", PANEL, WHITE, NEON_CYAN, "7"),
             ("8", PANEL, WHITE, NEON_CYAN, "8"),
             ("9", PANEL, WHITE, NEON_CYAN, "9"),
             ("÷", DARK_GRAY, NEON_PINK, NEON_PINK, "/"),
             ("AC",(50,20,20), NEON_PINK, NEON_PINK, "clear")],

            # row 5
            [("4", PANEL, WHITE, NEON_CYAN, "4"),
             ("5", PANEL, WHITE, NEON_CYAN, "5"),
             ("6", PANEL, WHITE, NEON_CYAN, "6"),
             ("×", DARK_GRAY, NEON_PINK, NEON_PINK, "*"),
             ("1/x",DARK_GRAY, NEON_CYAN, NEON_CYAN, "reciprocal")],

            # row 6
            [("1", PANEL, WHITE, NEON_CYAN, "1"),
             ("2", PANEL, WHITE, NEON_CYAN, "2"),
             ("3", PANEL, WHITE, NEON_CYAN, "3"),
             ("−", DARK_GRAY, NEON_PINK, NEON_PINK, "-"),
             ("abs",DARK_GRAY,NEON_CYAN,NEON_CYAN,"abs(")],

            # row 7 — bottom
            [("0", PANEL, WHITE, NEON_CYAN, "0"),
             ("00",PANEL, WHITE, NEON_CYAN, "00"),
             (".", PANEL, WHITE, NEON_CYAN, "."),
             ("+", DARK_GRAY, NEON_PINK, NEON_PINK, "+"),
             ("=", (0,80,100), NEON_CYAN, NEON_CYAN, "=")],
        ]

        MARGIN  = 10
        START_Y = 430
        COLS    = 5
        GAP     = 8
        BTN_W   = (W - 2*MARGIN - (COLS-1)*GAP) // COLS
        BTN_H   = 52

        for row_i, row in enumerate(BUTTON_DATA):
            for col_i, (label, bg, fg, accent, action) in enumerate(row):
                x = MARGIN + col_i * (BTN_W + GAP)
                y = START_Y + row_i * (BTN_H + GAP)
                btn = Button(label, x, y, BTN_W, BTN_H,
                             bg=bg, fg=fg, accent=accent,
                             action=action)
                # Make "=" larger font
                if action == "=":
                    btn.font = F_LARGE
                self.buttons.append(btn)

    # ── Input handling ───────────────────────────────────────────────────────
    def handle_action(self, action: str, btn_rect: pygame.Rect = None):
        cx = btn_rect.centerx if btn_rect else W//2
        cy = btn_rect.centery if btn_rect else H//2
        accent = NEON_CYAN

        if action == "clear":
            self.expr, self.preview, self.error = "", "", False
            self.just_result = False
            accent = NEON_PINK
        elif action == "backspace":
            if self.expr: self.expr = self.expr[:-1]
            self.just_result = False
            accent = NEON_PINK
        elif action == "=":
            self._evaluate()
            accent = NEON_CYAN
        elif action == "negate":
            if self.expr:
                if self.expr.startswith("-"):
                    self.expr = self.expr[1:]
                else:
                    self.expr = "-" + self.expr
        elif action == "reciprocal":
            val, _ = safe_eval(self.expr, self.use_radians)
            if val and val != 0:
                self.expr = str(1/val)
                self.just_result = True
        elif action == "toggle_angle":
            self.use_radians = not self.use_radians
            # Rebuild to update DEG/RAD label
            self._build_buttons()
        elif action == "memory_clear":
            self.memory, self.mem_active = 0.0, False
            accent = NEON_PINK
        elif action == "memory_recall":
            if self.just_result: self.expr = ""
            self.expr += str(self.memory)
            self.just_result = False
        elif action == "memory_add":
            val, _ = safe_eval(self.expr, self.use_radians)
            if val is not None:
                self.memory += val
                self.mem_active = True
        elif action == "memory_sub":
            val, _ = safe_eval(self.expr, self.use_radians)
            if val is not None:
                self.memory -= val
                self.mem_active = True
        else:
            # Append character
            if self.just_result:
                # after "=" only operators continue; digits restart
                if action in "+-*/%**" or action.startswith(("sin","cos","tan","log","sqrt","abs")):
                    pass
                else:
                    self.expr = ""
                self.just_result = False
            self.expr += action

        # Live preview
        if self.expr:
            _, text = safe_eval(self.expr, self.use_radians)
            if text and text != "Error":
                self.preview = text
                self.error   = False
            else:
                self.preview = ""
        else:
            self.preview = ""

        # Ripple
        self.ripples.append(Ripple(cx, cy, accent))

    def _evaluate(self):
        if not self.expr: return
        val, text = safe_eval(self.expr, self.use_radians)
        if val is not None:
            self.history.appendleft((self.expr, text))
            self.expr        = text
            self.preview     = ""
            self.error       = False
            self.just_result = True
        else:
            self.error   = True
            self.preview = text   # show error message

    # ── Keyboard ─────────────────────────────────────────────────────────────
    def handle_key(self, event):
        k = event.key
        uni = event.unicode

        if k == pygame.K_RETURN or k == pygame.K_KP_ENTER:
            self.handle_action("=")
        elif k == pygame.K_BACKSPACE:
            self.handle_action("backspace")
        elif k == pygame.K_ESCAPE:
            self.handle_action("clear")
        elif k == pygame.K_DELETE:
            self.handle_action("clear")
        elif uni in "0123456789":
            self.handle_action(uni)
        elif uni in "+-*/.%()^":
            self.handle_action(uni.replace("^","**"))
        elif uni == "e" and not (event.mod & pygame.KMOD_CTRL):
            self.handle_action("e")
        elif k == pygame.K_p and not (event.mod & pygame.KMOD_CTRL):
            self.handle_action("pi")

    # ── Drawing ───────────────────────────────────────────────────────────────
    def draw_display(self):
        s = self.screen
        DISP_RECT = pygame.Rect(10, 10, W-20, 410)

        # Panel background
        draw_rounded_rect(s, PANEL, DISP_RECT, radius=14)
        pygame.draw.rect(s, NEON_CYAN, DISP_RECT, 1, border_radius=14)
        draw_glow(s, NEON_CYAN, DISP_RECT, radius=14, strength=2)

        # Title bar
        title = F_TINY.render("NEON CALC  •  SCIENTIFIC  •  PYGAME EDITION", True, DIM_CYAN)
        s.blit(title, (DISP_RECT.x + 12, DISP_RECT.y + 10))

        # DEG/RAD indicator
        angle_lbl = "RAD" if self.use_radians else "DEG"
        angle_col = NEON_LIME if self.use_radians else NEON_GOLD
        atxt = F_TINY.render(angle_lbl, True, angle_col)
        s.blit(atxt, (DISP_RECT.right - 60, DISP_RECT.y + 10))

        # MEM indicator
        if self.mem_active:
            mtxt = F_TINY.render(f"M={self.memory:g}", True, NEON_PINK)
            s.blit(mtxt, (DISP_RECT.right - 130, DISP_RECT.y + 10))

        # ── History ────────────────────────────────────────────────────────
        hist_y = DISP_RECT.y + 34
        for i, (expr, result) in enumerate(self.history):
            alpha = 180 - i * 28
            if alpha <= 0: break
            col = tuple(max(0, int(c * alpha/180)) for c in GRAY)
            # trim long expressions
            disp_expr = (expr[:28] + "…") if len(expr) > 30 else expr
            disp_res  = result
            et = F_TINY.render(disp_expr + " =", True, col)
            rt = F_TINY.render(disp_res,          True, col)
            s.blit(et, (DISP_RECT.x + 14, hist_y))
            s.blit(rt, (DISP_RECT.right - rt.get_width() - 14, hist_y))
            hist_y += 22

        # ── Separator ──────────────────────────────────────────────────────
        pygame.draw.line(s, BORDER,
                         (DISP_RECT.x + 10, 220), (DISP_RECT.right - 10, 220), 1)

        # ── Expression ────────────────────────────────────────────────────
        expr_disp = self.expr if self.expr else "0"
        # scale font to fit
        font = F_HUGE
        txt  = font.render(expr_disp, True, WHITE)
        while txt.get_width() > DISP_RECT.width - 28 and font.size > 14:
            font = load_font(max(14, font.size - 4), bold=True)
            txt  = font.render(expr_disp, True, WHITE)

        expr_y = 270
        s.blit(txt, (DISP_RECT.right - txt.get_width() - 14, expr_y))

        # Cursor blink
        if self.cursor_vis and not self.just_result:
            cur_x = DISP_RECT.right - txt.get_width() - 14 + txt.get_width() + 3
            pygame.draw.rect(s, NEON_CYAN,
                             pygame.Rect(cur_x, expr_y + 4, 3, txt.get_height() - 8))

        # ── Preview / Error ────────────────────────────────────────────────
        if self.error:
            et = F_MED.render(self.preview, True, RED_ERR)
            s.blit(et, (DISP_RECT.right - et.get_width() - 14, expr_y + 56))
        elif self.preview and self.preview != self.expr:
            pt = F_MED.render("= " + self.preview, True, NEON_CYAN)
            s.blit(pt, (DISP_RECT.right - pt.get_width() - 14, expr_y + 56))

        # ── Keyboard hint bar ──────────────────────────────────────────────
        hint = "↩ Enter  ⌫ Backspace  Esc: Clear  p: π"
        ht = F_TINY.render(hint, True, GRAY)
        s.blit(ht, (DISP_RECT.x + 12, DISP_RECT.bottom - 24))

    def draw(self):
        self.screen.fill(BG)

        # Subtle grid bg
        for gx in range(0, W, 40):
            pygame.draw.line(self.screen, (15,18,30), (gx,0), (gx,H))
        for gy in range(0, H, 40):
            pygame.draw.line(self.screen, (15,18,30), (0,gy), (W,gy))

        # Display panel
        self.draw_display()

        # Buttons
        for btn in self.buttons:
            btn.draw(self.screen, self.ripples)

        # Ripples
        for r in self.ripples:
            r.draw(self.screen)

        # Scanlines
        self.screen.blit(self.scanlines, (0,0))

        pygame.display.flip()

    # ── Main loop ────────────────────────────────────────────────────────────
    def run(self):
        while True:
            dt = self.clock.tick(FPS) / 1000.0

            # Cursor blink
            self.cursor_t += dt
            if self.cursor_t >= 0.5:
                self.cursor_t  = 0.0
                self.cursor_vis = not self.cursor_vis

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                elif event.type == pygame.KEYDOWN:
                    self.handle_key(event)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for btn in self.buttons:
                        if btn.hit(event.pos):
                            btn.pressed = True
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    for btn in self.buttons:
                        if btn.pressed and btn.hit(event.pos):
                            self.handle_action(btn.action, btn.rect)
                        btn.pressed = False
                elif event.type == pygame.MOUSEMOTION:
                    for btn in self.buttons:
                        btn.hover = btn.hit(event.pos)

            # Update
            for btn in self.buttons:
                btn.update(dt)
            self.ripples = [r for r in self.ripples if r.alive]
            for r in self.ripples:
                r.update()

            self.draw()


if __name__ == "__main__":
    Calculator().run()
