"""Игра «Кроссворд» — соло в личке против бота.

Бот генерирует кроссворд: слова + подсказки даёт LLM (fallback — банк
`crossword_bank`), а сетку собирает детерминированный локальный решатель
(пересечения гарантированно валидны). Сетка рендерится в PNG «чистым» Python
(stdlib `zlib`/`struct`, без Pillow) с встроенным битмап-шрифтом 5×7, отдаётся
через `/static` и показывается в карточке виджетом `image`.

Состояние живёт в `game_sessions.state` (JSONB), `game_type = 'crossword'`.

Вход:
- menu_crossword   — создать партию (кнопка «Crossword» из меню ДМ-игр).
- crossword_check  — проверить введённое слово.
- crossword_reveal — показать всё решение (сдаться).
- crossword_new / crossword_quit — новая партия / выход.
"""
import logging
import os
import random
import struct
import zlib
from urllib.parse import urlparse

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import GameSession, Profile
from app.services.games import party_games

logger = logging.getLogger(__name__)

MAX_WORDS = 8
CELL = 36  # размер ячейки сетки в пикселях PNG

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GRID = (95, 95, 95)


def _action_url() -> str:
    """URL эндпоинта — в add-on режиме кнопка доставляет клик только при function=URL."""
    return get_settings().chat_app_audience or "crossword"


# ---------------------------------------------------------------------------
# Решатель сетки
# ---------------------------------------------------------------------------

def _valid_placement(grid: dict, word: str, r: int, c: int, direction: str) -> int | None:
    """Число пересечений, если `word` можно поставить с (r,c) в `direction`, иначе None."""
    dr, dc = (0, 1) if direction == "across" else (1, 0)
    # Клетки сразу до начала и после конца должны быть пустыми (слова не сливаются).
    if (r - dr, c - dc) in grid:
        return None
    if (r + dr * len(word), c + dc * len(word)) in grid:
        return None
    crossings = 0
    for i, ch in enumerate(word):
        rr, cc = r + dr * i, c + dc * i
        existing = grid.get((rr, cc))
        if existing is not None:
            if existing != ch:
                return None
            crossings += 1
        else:
            # Соседи по перпендикуляру должны быть пустыми (нет прижатых параллельных слов).
            if direction == "across":
                if (rr - 1, cc) in grid or (rr + 1, cc) in grid:
                    return None
            else:
                if (rr, cc - 1) in grid or (rr, cc + 1) in grid:
                    return None
    return crossings


def _best_placement(grid: dict, word: str) -> tuple[str, int, int] | None:
    """Лучшая позиция слова (больше всего пересечений)."""
    best = None
    best_score = -1
    for (r, c), ch in list(grid.items()):
        for i, wch in enumerate(word):
            if wch != ch:
                continue
            for direction in ("across", "down"):
                if direction == "across":
                    sr, sc = r, c - i
                else:
                    sr, sc = r - i, c
                score = _valid_placement(grid, word, sr, sc, direction)
                if score is not None and score > best_score:
                    best = (direction, sr, sc)
                    best_score = score
    return best


def _place_words(words: list[str]) -> tuple[dict, dict]:
    """Жадная расстановка. Возврат (grid, placements), placements: word -> (dir, r, c)."""
    grid: dict = {}
    placements: dict = {}
    for i, w in enumerate(words):
        if i == 0:
            for j, ch in enumerate(w):
                grid[(0, j)] = ch
            placements[w] = ("across", 0, 0)
            continue
        pos = _best_placement(grid, w)
        if pos is None:
            continue
        direction, r, c = pos
        dr, dc = (0, 1) if direction == "across" else (1, 0)
        for j, ch in enumerate(w):
            grid[(r + dr * j, c + dc * j)] = ch
        placements[w] = (direction, r, c)
    return grid, placements


def build_puzzle(items: list[dict]) -> dict | None:
    """Собрать сетку из `[{'word','clue'}, ...]`.

    Возвращает {'rows', 'cols', 'placements': [{word, clue, dir, row, col, num}]}
    или None. Пробует детерминированный порядок и несколько перемешанных,
    выбирая вариант с наибольшим числом размещённых слов.
    """
    words: list[str] = []
    seen: set[str] = set()
    for it in items:
        w = str(it.get("word", "")).lower()
        if w and w not in seen:
            seen.add(w)
            words.append(w)
    if not words:
        return None

    attempts = [sorted(words, key=lambda w: (-len(w), w))]
    for seed in (7, 13, 42, 101, 202):
        rng = random.Random(seed)
        order = words[:]
        rng.shuffle(order)
        attempts.append(order)

    best = None
    for order in attempts:
        grid, placements = _place_words(order)
        result = _finalize(grid, placements, items)
        if result is None:
            continue
        if best is None or len(result["placements"]) > len(best["placements"]):
            best = result
    return best


def _finalize(grid: dict, placements: dict, items: list[dict]) -> dict | None:
    """Нормализовать координаты, пронумеровать клетки и собрать метаданные."""
    if not grid:
        return None
    min_r = min(r for r, _ in grid)
    max_r = max(r for r, _ in grid)
    min_c = min(c for _, c in grid)
    max_c = max(c for _, c in grid)
    rows = max_r - min_r + 1
    cols = max_c - min_c + 1

    clue_by_word = {str(it.get("word", "")).lower(): str(it.get("clue", "")) for it in items}

    placed = []
    for w, (direction, r, c) in placements.items():
        placed.append({
            "word": w.upper(),
            "clue": clue_by_word.get(w, ""),
            "dir": "across" if direction == "across" else "down",
            "row": r - min_r,
            "col": c - min_c,
        })

    # Нумерация стартовых клеток в порядке чтения (слева направо, сверху вниз).
    starts: dict[tuple, int] = {}
    num = 0
    for p in sorted(placed, key=lambda p: (p["row"], p["col"])):
        key = (p["row"], p["col"])
        if key not in starts:
            num += 1
            starts[key] = num
    for p in placed:
        p["num"] = starts[(p["row"], p["col"])]

    return {"rows": rows, "cols": cols, "placements": placed}


# ---------------------------------------------------------------------------
# PNG-рендер (чистый Python, без Pillow)
# ---------------------------------------------------------------------------

# Битовый шрифт 5×7 для A-Z. '#' = пиксель, '.' = пусто.
_FONT5 = {
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "B": ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
    "C": [".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."],
    "D": ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "F": ["#####", "#....", "#....", "####.", "#....", "#....", "#...."],
    "G": [".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".###."],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "I": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"],
    "J": ["..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."],
    "K": ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "M": ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"],
    "N": ["#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "Q": [".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    "S": [".###.", "#...#", "#....", ".###.", "....#", "#...#", ".###."],
    "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    "U": ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "V": ["#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
    "W": ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"],
    "X": ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"],
    "Y": ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
    "Z": ["#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"],
}

# Мини-шрифт 3×5 для цифр (номера подсказок в углу клетки). 'X' = пиксель.
_FONT3 = {
    "0": ["XXX", "X.X", "X.X", "X.X", "XXX"],
    "1": [".X.", "XX.", ".X.", ".X.", "XXX"],
    "2": ["XXX", "..X", "XXX", "X..", "XXX"],
    "3": ["XXX", "..X", "XXX", "..X", "XXX"],
    "4": ["X.X", "X.X", "XXX", "..X", "..X"],
    "5": ["XXX", "X..", "XXX", "..X", "XXX"],
    "6": ["XXX", "X..", "XXX", "X.X", "XXX"],
    "7": ["XXX", "..X", "..X", "..X", "..X"],
    "8": ["XXX", "X.X", "XXX", "X.X", "XXX"],
    "9": ["XXX", "X.X", "XXX", "..X", "XXX"],
}


def _fill_rect(pixels: bytearray, W: int, H: int, x0: int, y0: int, x1: int, y1: int, color: tuple) -> None:
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    if x0 >= x1 or y0 >= y1:
        return
    r, g, b = color
    for y in range(y0, y1):
        base = (y * W + x0) * 3
        for x in range(x0, x1):
            i = base + (x - x0) * 3
            pixels[i] = r
            pixels[i + 1] = g
            pixels[i + 2] = b


def _draw_bitmap(pixels, W, H, glyph, x0, y0, scale, color) -> None:
    for gy, row in enumerate(glyph):
        for gx, bit in enumerate(row):
            if bit != ".":
                _fill_rect(pixels, W, H, x0 + gx * scale, y0 + gy * scale,
                           x0 + gx * scale + scale, y0 + gy * scale + scale, color)


def _write_png(pixels: bytearray, width: int, height: int) -> bytes:
    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))

    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)  # filter type 0 (None)
        raw += pixels[y * stride:(y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def render_png(placements: list[dict], rows: int, cols: int, cell: int = CELL) -> bytes:
    """Отрисовать сетку кроссворда в PNG. Чёрная клетка = блок, белая = клетка."""
    solution = [[None] * cols for _ in range(rows)]
    for p in placements:
        dr, dc = (0, 1) if p["dir"] == "across" else (1, 0)
        for i, ch in enumerate(p["word"]):
            solution[p["row"] + dr * i][p["col"] + dc * i] = ch

    revealed: set = set()
    for p in placements:
        if not p.get("solved"):
            continue
        dr, dc = (0, 1) if p["dir"] == "across" else (1, 0)
        for i in range(len(p["word"])):
            revealed.add((p["row"] + dr * i, p["col"] + dc * i))

    numbers = {(p["row"], p["col"]): p["num"] for p in placements}

    W, H = cols * cell, rows * cell
    pixels = bytearray(b"\xff" * (W * H * 3))  # белый фон

    for r in range(rows):
        for c in range(cols):
            x0, y0 = c * cell, r * cell
            if solution[r][c] is None:
                _fill_rect(pixels, W, H, x0, y0, x0 + cell, y0 + cell, BLACK)
                continue
            # Граница белой клетки.
            _fill_rect(pixels, W, H, x0, y0, x0 + cell, y0 + 1, GRID)
            _fill_rect(pixels, W, H, x0, y0 + cell - 1, x0 + cell, y0 + cell, GRID)
            _fill_rect(pixels, W, H, x0, y0, x0 + 1, y0 + cell, GRID)
            _fill_rect(pixels, W, H, x0 + cell - 1, y0, x0 + cell, y0 + cell, GRID)
            # Номер подсказки в углу.
            if (r, c) in numbers:
                num_scale = max(1, cell // 12)
                cx, cy = x0 + 2, y0 + 2
                for ch in str(numbers[(r, c)]):
                    g = _FONT3.get(ch)
                    if g:
                        _draw_bitmap(pixels, W, H, g, cx, cy, num_scale, BLACK)
                        cx += (len(g[0]) + 1) * num_scale
            # Отгаданная буква по центру.
            if (r, c) in revealed:
                ch = solution[r][c]
                g = _FONT5.get(ch)
                if g:
                    scale = max(1, cell // 10)
                    gw, gh = 5 * scale, 7 * scale
                    _draw_bitmap(pixels, W, H, g, x0 + (cell - gw) // 2,
                                 y0 + (cell - gh) // 2, scale, BLACK)
    return _write_png(pixels, W, H)


# ---------------------------------------------------------------------------
# Отдача PNG
# ---------------------------------------------------------------------------

def _static_dir() -> str:
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "static", "crosswords")
    os.makedirs(d, exist_ok=True)
    return d


def _png_path(game_id: int, render: int) -> str:
    return os.path.join(_static_dir(), f"cw_{game_id}_{render}.png")


def _image_url(game_id: int, render: int) -> str:
    u = urlparse(get_settings().chat_app_audience or "http://localhost")
    return f"{u.scheme}://{u.netloc}/static/crosswords/cw_{game_id}_{render}.png"


def _render_and_save(placements: list[dict], rows: int, cols: int, game_id: int, render: int) -> None:
    png = render_png(placements, rows, cols)
    with open(_png_path(game_id, render), "wb") as f:
        f.write(png)


# ---------------------------------------------------------------------------
# Карточки
# ---------------------------------------------------------------------------

def _btn(text: str, method: str, game_id: int) -> dict:
    return {
        "text": text,
        "onClick": {"action": {
            "function": _action_url(),
            "parameters": [
                {"key": "method", "value": method},
                {"key": "game_id", "value": str(game_id)},
            ],
        }},
    }


def _clues_text(placements: list[dict]) -> str:
    across = sorted([p for p in placements if p["dir"] == "across"], key=lambda p: p["num"])
    down = sorted([p for p in placements if p["dir"] == "down"], key=lambda p: p["num"])
    lines: list[str] = []
    if across:
        lines.append("**Across**")
        for p in across:
            mark = " ✅" if p.get("solved") else ""
            lines.append(f"{p['num']}. {p['clue']} ({len(p['word'])} letters){mark}")
    if down:
        lines.append("**Down**")
        for p in down:
            mark = " ✅" if p.get("solved") else ""
            lines.append(f"{p['num']}. {p['clue']} ({len(p['word'])} letters){mark}")
    return "\n".join(lines)


def build_crossword_card(state: dict, game_id: int) -> dict:
    placements = state.get("placements", [])
    solved = sum(1 for p in placements if p.get("solved"))
    total = len(placements)
    image_url = _image_url(game_id, state.get("render", 0))

    return {"cardsV2": [{
        "cardId": "crossword",
        "card": {
            "header": {"title": "Crossword 🧩", "subtitle": f"Solved {solved}/{total} words"},
            "sections": [{"widgets": [
                {"image": {"imageUrl": image_url, "altText": "Crossword grid"}},
                {"textParagraph": {"text": _clues_text(placements)}},
                {"textInput": {
                    "name": "answer",
                    "label": "Your answer",
                    "type": "SINGLE_LINE",
                    "hintText": "Type one word from the crossword",
                }},
                {"buttonList": {"buttons": [
                    _btn("🎯 Check", "crossword_check", game_id),
                    _btn("👁 Reveal", "crossword_reveal", game_id),
                    _btn("🆕 New game", "crossword_new", game_id),
                    _btn("🛑 Quit", "crossword_quit", game_id),
                ]}},
            ]}],
        },
    }]}


def _result_card(state: dict, game_id: int, won: bool) -> dict:
    placements = state.get("placements", [])
    image_url = _image_url(game_id, state.get("render", 0))
    total = len(placements)
    if won:
        title = "🎉 Crossword solved!"
        body = f"All {total} words found — great job!"
    else:
        title = "👁 Crossword revealed"
        body = "Here is the full solution. Try another one!"

    return {"cardsV2": [{
        "cardId": "crossword",
        "card": {
            "header": {"title": title, "subtitle": "Crossword"},
            "sections": [{"widgets": [
                {"image": {"imageUrl": image_url, "altText": "Crossword solution"}},
                {"textParagraph": {"text": _clues_text(placements)}},
                {"buttonList": {"buttons": [_btn("🆕 New game", "crossword_new", game_id)]}},
            ]}],
        },
    }]}


# ---------------------------------------------------------------------------
# Игровой цикл
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return "".join(ch for ch in (text or "").upper() if ch.isascii() and ch.isalpha())


async def _pick_words() -> list[dict]:
    from app.services.games.games_llm import generate_crossword_words

    return await generate_crossword_words(MAX_WORDS)


async def _active_session(db: AsyncSession, game_id: int) -> GameSession | None:
    session = await db.get(GameSession, game_id)
    if session is None or session.game_type != "crossword" or session.status != "active":
        return None
    return session


async def start_crossword(db: AsyncSession, space_name: str, profile: Profile) -> dict:
    """Создать партию: сгенерировать слова, собрать сетку, отрисовать PNG."""
    if await party_games.get_active_game(db, space_name) is not None:
        return {"text": "A game is already running — finish it or press «🆕 New game»."}

    items = await _pick_words()
    puzzle = build_puzzle(items)
    if puzzle is None or len(puzzle["placements"]) < 4:
        return {"text": "Couldn't build a crossword from those words 🤷 — try again."}

    placements = puzzle["placements"]
    for p in placements:
        p["solved"] = False
    state = {
        "game": "crossword",
        "rows": puzzle["rows"],
        "cols": puzzle["cols"],
        "placements": placements,
        "render": 0,
    }
    session = await party_games._start_session(db, space_name, "crossword", "Crossword", state)
    if session is None:
        return {"text": "A game is already running — finish it first."}
    _render_and_save(placements, state["rows"], state["cols"], session.id, state["render"])
    return build_crossword_card(state, session.id)


async def check(db: AsyncSession, game_id: int, profile: Profile, text: str) -> dict:
    """Проверить введённое слово: если оно есть в сетке — открыть его."""
    session = await _active_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    placements = state.get("placements", [])

    guess = _normalize(text)
    if not guess:
        return {"text": "Type an English word 😊", "cardsV2": build_crossword_card(state, game_id)}

    matched = [p for p in placements if not p.get("solved") and p["word"].upper() == guess]
    if not matched:
        return {"text": f"“{guess}” is not in this crossword — try another clue.",
                "cardsV2": build_crossword_card(state, game_id)}

    for p in matched:
        p["solved"] = True
    solved = sum(1 for p in placements if p.get("solved"))
    total = len(placements)

    state["render"] = state.get("render", 0) + 1
    _render_and_save(placements, state.get("rows"), state.get("cols"), game_id, state["render"])

    if solved >= total:
        state["won"] = True
        res = await db.execute(
            update(GameSession)
            .where(GameSession.id == session.id, GameSession.status == "active")
            .values(status="finished", state=state)
        )
        if res.rowcount == 0:
            return {"text": "Game already finished"}
        await db.commit()
        return _result_card(state, game_id, won=True)

    session.state = state
    await db.commit()
    return build_crossword_card(state, game_id)


async def reveal(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Сдаться: открыть всё решение и завершить партию."""
    session = await _active_session(db, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    state = session.state or {}
    placements = state.get("placements", [])
    for p in placements:
        p["solved"] = True
    state["render"] = state.get("render", 0) + 1
    state["won"] = False
    _render_and_save(placements, state.get("rows"), state.get("cols"), game_id, state["render"])

    res = await db.execute(
        update(GameSession)
        .where(GameSession.id == session.id, GameSession.status == "active")
        .values(status="finished", state=state)
    )
    if res.rowcount == 0:
        return {"text": "Game already finished"}
    await db.commit()
    return _result_card(state, game_id, won=False)


async def new_game(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Закрыть активную партию в space и начать новую."""
    session = await db.get(GameSession, game_id)
    space_name = session.space_name if session else ""
    if not space_name:
        return {"text": "Game not found 🤷"}

    active = await party_games.get_active_game(db, space_name)
    if active is not None:
        active.status = "cancelled"
        await db.commit()

    return await start_crossword(db, space_name, profile)


async def quit_game(db: AsyncSession, game_id: int, profile: Profile) -> dict:
    """Закрыть активную партию без изменения счёта."""
    session = await db.get(GameSession, game_id)
    if session is None:
        return {"text": "Game not found 🤷"}
    session.status = "cancelled"
    await db.commit()
    return {"text": "Crossword closed. Press «🧩 Crossword» in the games menu to play again."}
