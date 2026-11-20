"""Hidden signature shown by ``--author``.

Self-contained: standard library only, imports nothing from the program, so this one file is
copied unchanged into every program. Wire it before argument parsing, configuration and
logging::

    if "--author" in argv:
        return author.show()

In --help it appears only as a hint ("--author   who built this"); never in a README or a log.
In a console it plays a short animation (any key skips it); redirected, piped or with
NO_COLOR it prints a plain ASCII card.
"""

import os
import random
import shutil
import sys
import time
from datetime import date

NAME = "Viren Hirpara"
QUOTE = ("My soldiers, rage!", "My soldiers, scream!", "My soldiers, fight!")
BY = "Erwin Smith"

# crimson -> ember -> gold
EMBER = ((0x5B, 0x0E, 0x14), (0xB3, 0x12, 0x2E), (0xFF, 0x5A, 0x1F), (0xFF, 0xC8, 0x57))
WORD_COLORS = ((255, 122, 51), (255, 72, 48), (255, 200, 87))  # rage, scream, fight: hotter
TEXT, SOFT, FAINT = (226, 226, 226), (150, 150, 150), (96, 96, 96)
HEAD, WHITE = (255, 238, 204), (255, 255, 255)

PAD = 4  # spaces inside the frame on each side
RESET = "\x1b[0m"

# timeline, seconds
T_BORDER = 0.45
T_NAME, NAME_LEN, NAME_STAGGER = 0.40, 0.85, 0.15
T_QUOTE, Q_STEP, CHAR, SLAM, FLASH = 1.55, 0.55, 0.016, 0.27, 0.07
T_BY = 3.15
T_SIG, SIG_CHAR = 3.35, 0.012
END = 3.95

# 5x5 block letters ("#" = on); I is narrower
FONT = {
    "A": (" ### ", "#   #", "#####", "#   #", "#   #"),
    "B": ("#### ", "#   #", "#### ", "#   #", "#### "),
    "C": (" ####", "#    ", "#    ", "#    ", " ####"),
    "D": ("#### ", "#   #", "#   #", "#   #", "#### "),
    "E": ("#####", "#    ", "#### ", "#    ", "#####"),
    "F": ("#####", "#    ", "#### ", "#    ", "#    "),
    "G": (" ####", "#    ", "#  ##", "#   #", " ####"),
    "H": ("#   #", "#   #", "#####", "#   #", "#   #"),
    "I": ("###", " # ", " # ", " # ", "###"),
    "J": ("  ###", "    #", "    #", "#   #", " ### "),
    "K": ("#   #", "#  # ", "###  ", "#  # ", "#   #"),
    "L": ("#    ", "#    ", "#    ", "#    ", "#####"),
    "M": ("#   #", "## ##", "# # #", "#   #", "#   #"),
    "N": ("#   #", "##  #", "# # #", "#  ##", "#   #"),
    "O": (" ### ", "#   #", "#   #", "#   #", " ### "),
    "P": ("#### ", "#   #", "#### ", "#    ", "#    "),
    "Q": (" ### ", "#   #", "# # #", "#  # ", " ## #"),
    "R": ("#### ", "#   #", "#### ", "#  # ", "#   #"),
    "S": (" ####", "#    ", " ### ", "    #", "#### "),
    "T": ("#####", "  #  ", "  #  ", "  #  ", "  #  "),
    "U": ("#   #", "#   #", "#   #", "#   #", " ### "),
    "V": ("#   #", "#   #", "#   #", " # # ", "  #  "),
    "W": ("#   #", "#   #", "# # #", "## ##", "#   #"),
    "X": ("#   #", " # # ", "  #  ", " # # ", "#   #"),
    "Y": ("#   #", " # # ", "  #  ", "  #  ", "  #  "),
    "Z": ("#####", "   # ", "  #  ", " #   ", "#####"),
    "-": ("     ", "     ", " ### ", "     ", "     "),
    ".": ("  ", "  ", "  ", "  ", "# "),
    " ": ("   ", "   ", "   ", "   ", "   "),
}


# ------------------------------------------------------------------------------ plain card
def plain_card() -> str:
    year = date.today().year
    by = f"- {BY}"
    return "\n".join([
        "",
        f"  {' '.join(NAME.upper())}",
        "",
        f'  "{QUOTE[0]}',
        f"   {QUOTE[1]}",
        f'   {QUOTE[2]}"',
        f"{by:>{len(QUOTE[2]) + 5}}",
        "",
        f"  crafted by {NAME}  (c) {year}",
        "",
        "",
    ])  # fmt: skip


# ------------------------------------------------------------------------------ letters
def pixels(word: str) -> list[str]:
    rows = [""] * 5
    for n, ch in enumerate(word.upper()):
        glyph = FONT.get(ch, FONT[" "])
        for y in range(5):
            rows[y] += ("" if n == 0 else " ") + glyph[y]
    return rows


def big(word: str) -> list[str]:
    """Two columns per pixel: square pixels in a normal console font."""
    return ["".join("██" if p == "#" else "  " for p in row) for row in pixels(word)]


def compact(word: str) -> list[str]:
    """Half blocks: two pixel rows per text row."""
    px = pixels(word)
    px.append(" " * len(px[0]))
    out = []
    for y in (0, 2, 4):
        out.append(
            "".join(
                "█" if a == "#" and b == "#" else "▀" if a == "#" else "▄" if b == "#" else " "
                for a, b in zip(px[y], px[y + 1], strict=True)
            )
        )
    return out


# ------------------------------------------------------------------------------ colour
def mix(t: float) -> tuple[int, int, int]:
    t = min(max(t, 0.0), 1.0) * (len(EMBER) - 1)
    i = min(int(t), len(EMBER) - 2)
    f = t - i
    a, b = EMBER[i], EMBER[i + 1]
    return (
        round(a[0] + (b[0] - a[0]) * f),
        round(a[1] + (b[1] - a[1]) * f),
        round(a[2] + (b[2] - a[2]) * f),
    )


def dim(rgb, k: float) -> tuple[int, int, int]:
    return (round(rgb[0] * k), round(rgb[1] * k), round(rgb[2] * k))


def sgr(rgb, bold: bool = False, italic: bool = False) -> str:
    flags = ("1;" if bold else "") + ("3;" if italic else "")
    return f"\x1b[0;{flags}38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


# ------------------------------------------------------------------------------ the card
class Card:
    """The signature card at any moment ``t`` of the animation (``t >= END``: finished)."""

    def __init__(self, render, rng: random.Random):
        self.rng = rng
        self.words = [render(w) for w in NAME.split()]
        self.word_h = len(self.words[0])
        year = date.today().year
        # (lead, typed part, last word, tail): the words themselves are never changed
        self.quote = [
            ("“", *QUOTE[0].rsplit(" ", 1), ""),
            (" ", *QUOTE[1].rsplit(" ", 1), ""),
            (" ", *QUOTE[2].rsplit(" ", 1), "”"),
        ]
        self.quote = [(lead, head + " ", word, tail) for lead, head, word, tail in self.quote]
        self.quote_w = max(sum(map(len, q)) for q in self.quote)
        self.by = f"— {BY}"
        self.sig = ("crafted by ", NAME, f"  ·  © {year}")
        self.sig_w = sum(map(len, self.sig))
        name_w = max(len(rows[0]) for rows in self.words)
        self.inner = max(name_w, self.quote_w + 8, self.sig_w) + 2 * PAD
        self.qx = (self.inner - self.quote_w) // 2

        rows: list[tuple] = [("blank",)]
        for i, word in enumerate(self.words):
            if i:
                rows.append(("blank",))
            rows += [("name", i, y) for y in range(len(word))]
        rows += [("blank",), *[("quote", i) for i in range(3)], ("by",), ("blank",)]
        rows += [("rule",), ("sig",), ("blank",)]
        self.rows = rows
        self.width = self.inner + 2
        self.height = len(rows) + 2
        self._border = self._border_cells()

    # -- frame
    def _border_cells(self) -> dict[tuple[int, int], tuple[int, str]]:
        w, h = self.width, self.height
        cells = {}
        for x in range(w):
            top = "╭" if x == 0 else "╮" if x == w - 1 else "─"
            bottom = "╰" if x == 0 else "╯" if x == w - 1 else "─"
            cells[(x, 0)] = (x, top)
            cells[(x, h - 1)] = (w + (h - 2) + (w - 1 - x), bottom)
        for y in range(1, h - 1):
            cells[(w - 1, y)] = (w + y - 1, "│")
            cells[(0, y)] = (2 * w + (h - 2) + (h - 2 - y), "│")
        return {
            pos: (index, sgr(dim(mix(0.85 * pos[0] / (w - 1) + 0.15 * pos[1] / (h - 1)), 0.8))
                  + ch)
            for pos, (index, ch) in cells.items()
        }  # fmt: skip

    def _cell(self, x: int, y: int, shown: int) -> str:
        index, text = self._border[(x, y)]
        return text if index < shown else " "

    # -- rows
    def _name(self, t: float, word: int, y: int) -> str:
        row = self.words[word][y]
        w = len(row)
        x0 = (self.inner - w) // 2
        start = T_NAME + word * NAME_STAGGER
        if t < start - 0.12:
            return " " * self.inner
        sweep = (t - start) / NAME_LEN * (w + 10) - 5
        out = [" " * x0]
        for x, ch in enumerate(row):
            if x < sweep - 2:
                if ch == " ":
                    out.append(" ")
                else:
                    shade = 0.85 * x / max(w - 1, 1) + 0.15 * y / max(self.word_h - 1, 1)
                    out.append(sgr(mix(0.15 + 0.85 * shade), bold=True) + ch)
            elif x <= sweep + 1:  # the bright decoding edge
                if ch != " ":
                    out.append(sgr(HEAD, bold=True) + ch)
                else:
                    out.append(sgr(dim(EMBER[1], 0.7)) + "░")
            elif ch != " ":
                noise = self.rng.choice("▒▓█")
                out.append(sgr(dim(EMBER[1], 0.35 + 0.35 * self.rng.random())) + noise)
            elif self.rng.random() < 0.18:
                out.append(sgr(dim(EMBER[0], 0.9)) + self.rng.choice("░▒"))
            else:
                out.append(" ")
        out.append(" " * (self.inner - x0 - w))
        return "".join(out)

    def _quote(self, t: float, i: int) -> str:
        lead, typed, word, tail = self.quote[i]
        start = T_QUOTE + i * Q_STEP
        if t < start:
            return " " * self.inner
        n = min(len(typed), int((t - start) / CHAR))
        parts = [" " * self.qx, sgr(EMBER[3], bold=True) + lead, sgr(TEXT) + typed[:n]]
        used = len(lead) + n
        since = t - (start + SLAM)
        if since >= 0:
            flashes = (0, 2 * FLASH) if i == 2 else (0,)
            white = any(f <= since < f + FLASH for f in flashes)
            color = WHITE if white else WORD_COLORS[i]
            parts.append(sgr(color, bold=True) + word)
            parts.append(sgr(EMBER[3], bold=True) + tail)
            used += len(word) + len(tail)
        parts.append(" " * (self.inner - self.qx - used))
        return "".join(parts)

    def _by(self, t: float) -> str:
        if t < T_BY:
            return " " * self.inner
        x = self.qx + self.quote_w - len(self.by)
        color = FAINT if t < T_BY + 0.08 else SOFT
        return " " * x + sgr(color, italic=True) + self.by + " " * (self.inner - x - len(self.by))

    def _rule(self, t: float) -> str:
        if t < T_SIG:
            return " " * self.inner
        w = 26
        x0 = (self.inner - w) // 2
        line = "".join(sgr(dim(mix(x / (w - 1)), 0.55)) + "─" for x in range(w))
        return " " * x0 + line + " " * (self.inner - x0 - w)

    def _sig(self, t: float) -> str:
        if t < T_SIG:
            return " " * self.inner
        n = int((t - T_SIG) / SIG_CHAR)
        x0 = (self.inner - self.sig_w) // 2
        before, name, after = self.sig
        out = [" " * x0]
        shown = 0
        for k, ch in enumerate(before + name + after):
            if k >= n:
                break
            if len(before) <= k < len(before) + len(name):
                j = k - len(before)
                out.append(sgr(mix(0.35 + 0.65 * j / max(len(name) - 1, 1)), bold=True) + ch)
            else:
                out.append(sgr(SOFT) + ch)
            shown += 1
        out.append(" " * (self.inner - x0 - shown))
        return "".join(out)

    def lines(self, t: float) -> list[str]:
        w, h = self.width, self.height
        shown = int(len(self._border) * min(1.0, t / T_BORDER))
        body = {
            "blank": lambda *_: " " * self.inner,
            "name": lambda word, y: self._name(t, word, y),
            "quote": lambda i: self._quote(t, i),
            "by": lambda: self._by(t),
            "rule": lambda: self._rule(t),
            "sig": lambda: self._sig(t),
        }
        out = ["".join(self._cell(x, 0, shown) for x in range(w)) + RESET]
        for y, (kind, *args) in enumerate(self.rows, 1):
            out.append(
                self._cell(0, y, shown) + body[kind](*args) + self._cell(w - 1, y, shown) + RESET
            )
        out.append("".join(self._cell(x, h - 1, shown) for x in range(w)) + RESET)
        return out


# ------------------------------------------------------------------------------ console
def _vt_console(stream) -> bool:
    """True when ANSI colour/cursor sequences work on this stream (switches them on in
    Windows consoles)."""
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    try:
        if not stream.isatty():
            return False
        "█░▒▓╭─│“”—·©".encode(stream.encoding or "ascii")
    except (AttributeError, ValueError, LookupError, UnicodeError, OSError):
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes
        import msvcrt

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if mode.value & 0x0004:  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def _key_pressed() -> bool:
    if os.name != "nt":
        return False
    try:
        import msvcrt

        hit = False
        while msvcrt.kbhit():
            msvcrt.getwch()
            hit = True
        return hit
    except Exception:
        return False


def _choose_card(columns: int, rows: int) -> Card | None:
    rng = random.Random()
    for render in (big, compact):
        card = Card(render, rng)
        if card.width < columns and card.height < rows:
            return card
    return None


class _Screen:
    """Repaints rows of a block reserved below the cursor. Only relative cursor moves (up,
    down, carriage return) are used: every terminal and ConPTY handles them the same way."""

    def __init__(self, stream, height: int):
        self.stream, self.height = stream, height
        self.row = height  # the cursor sits on the line below the block
        stream.write("\r\x1b[?25l" + "\n" * height)  # hide the cursor, make room

    def paint(self, frame: list[str], previous: list[str]) -> None:
        out = []
        for i, line in enumerate(frame):
            if line == previous[i]:
                continue
            if i < self.row:
                out.append(f"\x1b[{self.row - i}A")
            elif i > self.row:
                out.append(f"\x1b[{i - self.row}B")
            out.append("\r" + line)
            self.row = i
        if out:
            self.stream.write("".join(out))
            self.stream.flush()

    def close(self) -> None:
        down = self.height - self.row
        self.stream.write((f"\x1b[{down}B" if down else "") + f"\r{RESET}\x1b[?25h\n")
        self.stream.flush()


def _play(card: Card, stream) -> None:
    screen = _Screen(stream, card.height)
    previous = [""] * card.height
    begin = time.monotonic()
    try:
        while True:
            t = time.monotonic() - begin
            done = t >= END or _key_pressed()
            frame = card.lines(END + 1 if done else t)
            screen.paint(frame, previous)
            previous = frame
            if done:
                break
            time.sleep(1 / 60)
    except KeyboardInterrupt:
        screen.paint(card.lines(END + 1), previous)
    finally:
        screen.close()


def show(stream=None) -> int:
    if stream is None:
        stream = sys.stdout
    if stream is None:  # no console at all (windowed build)
        return 0
    try:
        if _vt_console(stream):
            size = shutil.get_terminal_size((80, 24))
            card = _choose_card(size.columns, size.lines)
            if card is not None:
                _play(card, stream)
                return 0
    except Exception:
        try:
            stream.write(f"{RESET}\x1b[?25h\n")
        except Exception:
            pass
    stream.write(plain_card())
    stream.flush()
    return 0
