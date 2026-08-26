"""Банк английских слов для игры Alias.

Слова подобраны для объяснения без слов-запретов (обычный формат Alias):
существительные, глаголы и прилагательные, знакомые участникам уровня A2–B2.
Плюс пара быстрых хелперов — выбор случайного слова без повторов.
"""
import random

# ~220 слов. Сгруппированы по темам для удобства пополнения, в игре используется
# единый плоский список.
WORDS: list[str] = [
    # animals
    "cat", "dog", "horse", "cow", "lion", "tiger", "elephant", "monkey",
    "rabbit", "bear", "wolf", "fox", "fish", "bird", "chicken", "duck",
    "snake", "spider", "bee", "butterfly", "whale", "shark", "penguin",
    "frog", "mouse", "sheep", "goat", "pig",
    # food
    "pizza", "hamburger", "spaghetti", "bread", "cheese", "milk", "egg",
    "apple", "banana", "orange", "lemon", "potato", "carrot", "tomato",
    "chocolate", "ice cream", "cake", "soup", "salad", "coffee", "tea",
    "water", "juice", "rice", "meat", "sugar", "salt", "honey",
    # everyday objects
    "chair", "table", "bed", "door", "window", "key", "phone", "computer",
    "book", "pen", "pencil", "paper", "clock", "lamp", "mirror", "umbrella",
    "bag", "wallet", "glasses", "watch", "camera", "television", "radio",
    "pillow", "blanket", "sofa", "cupboard", "shelf", "ladder", "scissors",
    "broom", "bucket", "rope", "hammer", "nail", "screwdriver",
    # places
    "kitchen", "bathroom", "bedroom", "garden", "school", "hospital",
    "airport", "station", "library", "museum", "beach", "mountain", "forest",
    "river", "lake", "island", "bridge", "tunnel", "castle", "church",
    "bank", "market", "restaurant", "hotel", "zoo", "park",
    # transport
    "car", "bus", "train", "plane", "bicycle", "motorcycle", "boat", "ship",
    "helicopter", "taxi", "truck", "tram", "subway", "rocket", "scooter",
    # people & jobs
    "doctor", "teacher", "policeman", "firefighter", "chef", "farmer",
    "driver", "pilot", "dentist", "nurse", "soldier", "artist", "musician",
    "dancer", "singer", "actor", "waiter", "judge", "lawyer", "engineer",
    "scientist", "photographer", "hairdresser", "tailor", "baker",
    # body & clothes
    "head", "hand", "foot", "eye", "ear", "nose", "mouth", "tooth",
    "hair", "finger", "leg", "arm", "shoulder", "knee", "heart", "stomach",
    "shirt", "trousers", "dress", "skirt", "shoes", "socks", "hat", "coat",
    "jacket", "gloves", "scarf", "belt", "button",
    # verbs
    "run", "jump", "swim", "fly", "sleep", "eat", "drink", "read", "write",
    "sing", "dance", "laugh", "cry", "cook", "drive", "climb", "throw",
    "catch", "paint", "draw", "build", "break", "open", "close", "push",
    "pull", "carry", "hide", "find", "win", "lose", "think", "smile",
    # adjectives & abstract
    "big", "small", "fast", "slow", "hot", "cold", "happy", "sad", "angry",
    "tired", "hungry", "thirsty", "old", "young", "tall", "short", "loud",
    "quiet", "clean", "dirty", "heavy", "light", "soft", "hard", "wet",
    "dry", "expensive", "cheap", "beautiful", "dangerous", "funny",
    # nature & weather
    "sun", "moon", "star", "cloud", "rain", "snow", "wind", "storm",
    "thunder", "lightning", "rainbow", "flower", "tree", "grass", "leaf",
    "stone", "sand", "fire", "ice", "smoke", "shadow",
]

# Набор слов, используемый при игре (без повторов за раунд — см. alias_game.py).
# Здесь только исходный список; сам выбор без повторов делается в сервисе.


def random_word(exclude: set[str] | None = None) -> str | None:
    """Случайное слово, не входящее в exclude. None, если все уже использованы."""
    pool = [w for w in WORDS if exclude is None or w not in exclude]
    if not pool:
        return None
    return random.choice(pool)


def sample_words(count: int, exclude: set[str] | None = None) -> list[str]:
    """До count случайных неповторяющихся слов (без слов из exclude)."""
    pool = [w for w in WORDS if exclude is None or w not in exclude]
    return random.sample(pool, min(count, len(pool)))


# Конкретные существительные для игры Snake Oil / «Змеиное масло».
# Только «осязаемые» предметы/существа/еда, которые можно скомбинировать в товар.
# Без глаголов (jump/run), без абстракций (sad/happy/грусть) — их не «впаришь».
PRODUCT_NOUNS: list[str] = [
    # предметы, гаджеты, инструменты
    "sponge", "robot", "toothbrush", "soap", "magnet", "balloon", "umbrella",
    "lamp", "clock", "pillow", "blanket", "mirror", "scissors", "broom", "bucket",
    "rope", "hammer", "nail", "screwdriver", "ladder", "key", "phone", "computer",
    "book", "pen", "pencil", "paper", "glasses", "watch", "camera", "television",
    "radio", "chair", "table", "bed", "door", "window", "bag", "wallet", "shelf",
    "cupboard", "sofa", "bottle", "cup", "plate", "fork", "spoon", "knife", "pan",
    "pot", "fridge", "vacuum", "fan", "heater", "flashlight", "battery", "charger",
    "brush", "comb", "towel", "curtain", "carpet", "cage", "net", "helmet", "mask",
    "gloves", "scarf", "belt", "button", "hat", "coat", "jacket", "shoes", "socks",
    "shirt", "dress", "skirt", "backpack", "suitcase", "whistle", "compass",
    "guitar", "piano", "drum", "telescope", "microscope", "typewriter", "candle",
    # еда
    "pizza", "hamburger", "spaghetti", "bread", "cheese", "milk", "egg", "apple",
    "banana", "orange", "lemon", "potato", "carrot", "tomato", "chocolate",
    "ice cream", "cake", "soup", "salad", "coffee", "tea", "water", "juice",
    "rice", "meat", "sugar", "salt", "honey", "cookie", "candy", "popcorn",
    "sandwich", "butter", "jam", "ketchup", "noodle", "corn",
    # животные и существа
    "cat", "dog", "horse", "cow", "lion", "tiger", "elephant", "monkey", "rabbit",
    "bear", "wolf", "fox", "fish", "bird", "chicken", "duck", "snake", "spider",
    "bee", "butterfly", "whale", "shark", "penguin", "frog", "mouse", "sheep",
    "goat", "pig", "dinosaur", "dragon", "unicorn", "zombie", "vampire", "alien",
    "mermaid",
    # природа и материалы
    "flower", "tree", "grass", "leaf", "stone", "sand", "ice", "wood", "metal",
    "glass", "rubber", "gold", "cotton", "wool",
]


def sample_product_words(count: int, exclude: set[str] | None = None) -> list[str]:
    """До count случайных КОНКРЕТНЫХ существительных для Snake Oil (без exclude)."""
    pool = [w for w in PRODUCT_NOUNS if exclude is None or w not in exclude]
    return random.sample(pool, min(count, len(pool)))
def _hangman_words() -> dict[str, str]:
    """Слова «Виселицы» → короткая подсказка (одно слово без пробелов/дефисов).

    Подсказка — краткое описание, чтобы слово можно было угадать по смыслу
    («это сладкое», «это животное», «это металлический инструмент»).
    """
    groups: list[tuple[str, list[str]]] = [
        # животные
        ("animal", ["cat", "dog", "horse", "cow", "lion", "tiger", "elephant",
                      "monkey", "rabbit", "bear", "wolf", "fox", "snake", "frog",
                      "mouse", "sheep", "goat", "pig"]),
        ("bird", ["bird", "chicken", "duck", "penguin"]),
        ("insect", ["spider", "bee", "butterfly"]),
        ("sea animal", ["fish", "whale", "shark"]),
        # еда
        ("sweet food", ["chocolate", "cake", "sugar", "honey"]),
        ("drink", ["milk", "coffee", "tea", "water", "juice"]),
        ("fruit or vegetable", ["apple", "banana", "orange", "lemon", "potato",
                            "carrot", "tomato"]),
        ("food", ["pizza", "hamburger", "spaghetti", "bread", "cheese", "egg",
                 "soup", "salad", "rice", "meat", "salt"]),
        # предметы
        ("metal tool", ["key", "scissors", "hammer", "nail", "screwdriver"]),
        ("furniture", ["chair", "table", "bed", "sofa", "cupboard", "shelf", "ladder"]),
        ("household item", ["door", "window", "phone", "computer", "book", "pen",
                            "pencil", "paper", "clock", "lamp", "mirror", "umbrella",
                            "bag", "wallet", "glasses", "watch", "camera",
                            "television", "radio", "pillow", "blanket", "broom",
                            "bucket", "rope"]),
        # места
        ("place at home", ["kitchen", "bathroom", "bedroom", "garden"]),
        ("city place", ["school", "hospital", "airport", "station", "library",
                            "museum", "bank", "market", "restaurant", "hotel",
                            "zoo", "park", "church"]),
        ("place in nature", ["beach", "mountain", "forest", "river", "lake",
                              "island", "bridge", "tunnel", "castle"]),
        # транспорт
        ("transport", ["car", "bus", "train", "plane", "bicycle", "motorcycle",
                       "boat", "ship", "helicopter", "taxi", "truck", "tram",
                       "subway", "rocket", "scooter"]),
        # профессии
        ("profession", ["doctor", "teacher", "policeman", "firefighter", "chef",
                       "farmer", "driver", "pilot", "dentist", "nurse", "soldier",
                       "artist", "musician", "dancer", "singer", "actor", "waiter",
                       "judge", "lawyer", "engineer", "scientist", "photographer",
                       "hairdresser", "tailor", "baker"]),
        # тело и одежда
        ("body part", ["head", "hand", "foot", "eye", "ear", "nose", "mouth",
                        "tooth", "hair", "finger", "leg", "arm", "shoulder",
                        "knee", "heart", "stomach"]),
        ("clothing", ["shirt", "trousers", "dress", "skirt", "shoes", "socks",
                    "hat", "coat", "jacket", "gloves", "scarf", "belt", "button"]),
        # глаголы
        ("action", ["run", "jump", "swim", "fly", "sleep", "eat", "drink",
                      "read", "write", "sing", "dance", "laugh", "cry", "cook",
                      "drive", "climb", "throw", "catch", "paint", "draw",
                      "build", "break", "open", "close", "push", "pull", "carry",
                      "hide", "find", "win", "lose", "think", "smile"]),
        # прилагательные
        ("quality", ["big", "small", "fast", "slow", "hot", "cold", "happy",
                      "sad", "angry", "tired", "hungry", "thirsty", "old",
                      "young", "tall", "short", "loud", "quiet", "clean", "dirty",
                      "heavy", "light", "soft", "hard", "wet", "dry", "expensive",
                      "cheap", "beautiful", "dangerous", "funny"]),
        # природа и погода
        ("nature", ["sun", "moon", "star", "cloud", "rain", "snow", "wind",
                     "storm", "thunder", "lightning", "rainbow", "flower", "tree",
                     "grass", "leaf", "stone", "sand", "fire", "ice", "smoke",
                     "shadow"]),
    ]
    result: dict[str, str] = {}
    for hint, words in groups:
        for word in words:
            result[word] = hint
    return result


HANGMAN_WORDS: dict[str, str] = _hangman_words()


def random_hangman_word(exclude: set[str] | None = None) -> tuple[str, str] | None:
    """Случайное слово для «Виселицы» вместе с подсказкой: (word, hint)."""
    pool = [
        (w, h) for w, h in HANGMAN_WORDS.items()
        if exclude is None or w not in exclude
    ]
    if not pool:
        return None
    return random.choice(pool)

