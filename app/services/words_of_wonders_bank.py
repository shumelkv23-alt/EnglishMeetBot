"""Банк головоломок для игры «Words of Wonders».

Каждая головоломка — набор букв (`letters`, 6–7 букв) + курированный список слов
(`words`), которые можно из них сложить. Слова подобраны вручную — только частые,
A2–B2, без аббревиатур и редких форм. Это «основные» слова, которые надо угадать
(рисуются квадратиками); любое другое валидное слово, которое игрок назовёт,
проверяется LLM и идёт в бонус-счётчик.
"""
import random

PUZZLES: list[dict] = [
    {"letters": "silent", "words": ["silent", "listen", "list", "line", "lines", "sent", "set", "let", "lies", "lie", "net", "ten", "nest", "sit", "tie", "tile"]},
    {"letters": "planet", "words": ["planet", "plan", "plane", "plant", "plate", "late", "let", "net", "ten", "pen", "pet", "pan", "tap", "tale", "tape", "lean"]},
    {"letters": "wonder", "words": ["wonder", "word", "worn", "wore", "down", "done", "drew", "red", "row", "own", "new", "now", "end", "won", "one", "rod", "nod"]},
    {"letters": "market", "words": ["market", "make", "mark", "mate", "meat", "team", "rate", "take", "tear", "term", "arm", "art", "eat", "tea", "rat", "mat"]},
    {"letters": "castle", "words": ["castle", "cast", "case", "seat", "sale", "salt", "late", "last", "east", "tale", "lace", "scale", "steal", "least"]},
    {"letters": "garden", "words": ["garden", "danger", "range", "grade", "grand", "drag", "dear", "read", "near", "gear", "anger", "den", "red", "age", "era"]},
    {"letters": "winter", "words": ["winter", "write", "twin", "wine", "wire", "went", "wet", "win", "wit", "ten", "tie", "tin", "net", "rent", "tire", "newt"]},
    {"letters": "summer", "words": ["summer", "user", "sure", "use", "sum", "mum", "muse", "serum", "ruse"]},
    {"letters": "create", "words": ["create", "tree", "rate", "tear", "race", "care", "cart", "car", "cat", "eat", "tea", "ear", "art", "acre", "react", "trace"]},
    {"letters": "orange", "words": ["orange", "range", "anger", "near", "gear", "earn", "gone", "organ", "ogre", "era", "ear", "ran", "rag", "age"]},
    {"letters": "animal", "words": ["animal", "mail", "main", "nail", "man", "aim", "lain"]},
    {"letters": "family", "words": ["family", "mail", "film", "fail", "fly", "may", "lay", "aim"]},
    {"letters": "friend", "words": ["friend", "find", "fine", "fire", "ride", "rein", "fern", "dine", "nerd", "red", "end", "die", "fed"]},
    {"letters": "mother", "words": ["mother", "other", "home", "more", "term", "them", "hero", "her", "hot", "met", "toe", "rot"]},
    {"letters": "father", "words": ["father", "heart", "earth", "after", "fear", "hate", "hear", "heat", "rate", "tear", "hat", "far", "her"]},
    {"letters": "sister", "words": ["sister", "resist", "rise", "site", "rest", "set", "sit", "sir", "tire", "tie", "stir"]},
    {"letters": "travel", "words": ["travel", "late", "rate", "real", "tear", "tale", "alert", "later", "valet", "earl", "let", "rat"]},
    {"letters": "morning", "words": ["morning", "ring", "grim", "grin", "iron", "norm", "minor", "morn"]},
    {"letters": "spring", "words": ["spring", "ring", "sign", "sing", "spin", "grin", "rip", "sin", "pin", "pig", "sip"]},
    {"letters": "forest", "words": ["forest", "store", "frost", "rose", "rest", "soft", "sort", "fort", "sore", "set", "toe"]},
    {"letters": "window", "words": ["window", "wind", "down", "own", "win", "won", "now", "don", "nod"]},
    {"letters": "kitchen", "words": ["kitchen", "think", "thick", "thin", "then", "hint", "neck", "nice", "kite", "inch", "cent", "ten", "hit"]},
    {"letters": "secret", "words": ["secret", "tree", "rest", "set", "see", "crest", "steer", "reset"]},
    {"letters": "answer", "words": ["answer", "wear", "swear", "near", "earn", "news", "warn", "war", "sea", "saw", "was"]},
    {"letters": "minute", "words": ["minute", "time", "unit", "mine", "menu", "tune", "item", "mute", "net", "ten"]},
    {"letters": "station", "words": ["station", "saint", "stain", "toast", "titan", "into", "sat", "sit", "ton", "not"]},
    {"letters": "picture", "words": ["picture", "price", "cute", "rice", "ripe", "true", "trip", "tie", "cup", "cut", "ice", "epic"]},
    {"letters": "country", "words": ["country", "count", "court", "corn", "turn", "tour", "torn", "your", "run", "out", "cut", "try"]},
]


def random_puzzle() -> dict:
    """Случайная головоломка (копия, чтобы не мутировать банк)."""
    p = random.choice(PUZZLES)
    return {"letters": p["letters"], "words": list(p["words"])}
