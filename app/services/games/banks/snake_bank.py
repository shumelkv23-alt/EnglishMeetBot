"""Банк ролей и бытовых проблем для игры Snake Oil / «Snake Oil».

Роль (persona) — это покупатель с характером («😺 Cat», «🏴☠️ Пират»), которому
продавцы впаривают товар из двух случайных слов. Проблема — бытовая ситуация,
которую товар должен решить. Проблемы подобраны ПОД роль покупателя, чтобы
питчинг был смешнее (кот — про банку с кормом, пират — про сокровища и т.п.);
для ролей без своего списка есть общий фолбэк.
"""
import random

# Роли покупателей: эмодзи + короткое название.
PERSONAS: list[str] = [
    "😺 Cat",
    "🏴‍☠️ Pirate",
    "👵 Grandma",
    "🤖 Robot",
    "🦖 Dinosaur",
    "🧙 Wizard",
    "🕵️ Spy",
    "👨‍🚀 Astronaut",
    "🧟 Zombie",
    "🦄 Unicorn",
    "🥷 Ninja",
    "🤠 Cowboy",
    "🧛 Vampire",
    "🐝 Bee",
    "🐻 Bear",
    "🦊 Fox",
    "🧜‍♀️ Mermaid",
    "👽 Alien",
    "🎅 Santa",
    "🤡 Clown",
]

# Проблемы под конкретную роль покупателя.
PERSONA_PROBLEMS: dict[str, list[str]] = {
    "😺 Cat": [
        "can't open a can of food",
        "the scratching post broke and the couch is ruined",
        "can't catch the red laser dot",
        "meows at night and wakes the owner",
    ],
    "🏴‍☠️ Pirate": [
        "can't find the buried treasure",
        "the wooden leg squeaks and scares the parrot",
        "the ship's wheel jams on turns",
        "the parrot is silent and won't hint the route",
    ],
    "👵 Grandma": [
        "lost their glasses and can't find them",
        "can't open a jar of jam",
        "the grandkid won't eat porridge",
        "the socks got lost in the laundry again",
    ],
    "🤖 Robot": [
        "the battery dies at the worst moment",
        "got rusty in the rain",
        "can't figure out human emotions",
        "the arm joint keeps jamming",
    ],
    "🦖 Dinosaur": [
        "arms are too short to reach the back",
        "can't reach the top branches",
        "stomps loudly and scares the neighbors",
        "a meteorite ruined evening plans again",
    ],
    "🧙 Wizard": [
        "the spell keeps failing",
        "the broom won't start in the morning",
        "the cauldron keeps escaping the lab",
        "can't find the crystal ball",
    ],
    "🕵️ Spy": [
        "can't eavesdrop through the wall",
        "the coded note got soaked",
        "invisibility won't turn on in time",
        "needs to sneak a message across the office",
    ],
    "👨‍🚀 Astronaut": [
        "can't eat soup in zero gravity",
        "the spacesuit fogs up inside",
        "can't fall asleep floating around the cabin",
        "an alien souvenir woke the crew",
    ],
    "🧟 Zombie": [
        "the arm keeps falling off",
        "can't catch people — too slow",
        "the brains in the fridge went bad",
        "afraid of dawn and won't make it home",
    ],
    "🦄 Unicorn": [
        "the horn scratches the doorframes",
        "the rainbow comes out crooked",
        "the mane keeps tangling",
        "can't spear a watermelon with the horn",
    ],
    "🥷 Ninja": [
        "can't silently open a squeaky door",
        "a shuriken is stuck in the ceiling",
        "their shadow gives them away in the light",
        "can't sneak across crunchy snow",
    ],
    "🤠 Cowboy": [
        "the horse won't obey and leaves without them",
        "the hat keeps flying off while riding",
        "the revolver jammed before the duel",
        "can't herd the cattle into the pen",
    ],
    "🧛 Vampire": [
        "can't open the curtains during the day",
        "the garlic in the soup ruins the appetite",
        "can't check the mirror before going out",
        "the coffin squeaks and ruins sleep",
    ],
    "🐝 Bee": [
        "can't find the way back to the hive",
        "the flower closed and the nectar is gone",
        "the honey is too sticky and drips everywhere",
        "the hive neighbor took the whole comb",
    ],
    "🐻 Bear": [
        "can't climb the tree for honey",
        "the den freezes in winter",
        "can't open the hive without getting stung",
        "woke up from hibernation too early",
    ],
    "🦊 Fox": [
        "can't reach the grapes on the high branch",
        "the tail keeps getting muddy",
        "can't sneak quietly into the henhouse",
        "the tricks don't work on the new neighbors",
    ],
    "🧜‍♀️ Mermaid": [
        "can't comb wet hair",
        "the tail doesn't fit in the bath",
        "can't reach the treasure at the bottom",
        "the voice vanishes before the big concert",
    ],
    "👽 Alien": [
        "can't understand human customs",
        "the antenna can't pick up the ship's signal",
        "the human disguise isn't working",
        "can't get used to Earth food",
    ],
    "🎅 Santa": [
        "can't fit down the chimney with the sack",
        "the reindeer refuse to fly in the snowfall",
        "can't read the gift lists",
        "the beard gets stuck in the jacket zipper",
    ],
    "🤡 Clown": [
        "can't make a sad child laugh",
        "the clown nose keeps falling off",
        "can't come up with a new trick",
        "the shoes are too big and hard to walk in",
    ],
}

# Общий фолбэк на случай роли без своего списка.
GENERIC_PROBLEMS: list[str] = [
    "can't open a jar",
    "the coffee keeps boiling over",
    "the socks get lost in the laundry",
    "the alarm doesn't wake them up",
    "can't chop an onion without crying",
    "the vacuum can't reach under the couch",
    "can't reach the top shelf",
    "the cables are always tangled",
    "the keys keep getting lost",
    "can't catch a mosquito at night",
]


def random_persona(exclude: set[str] | None = None) -> str:
    """Случайная роль покупателя (не из exclude, если передан)."""
    pool = [p for p in PERSONAS if exclude is None or p not in exclude]
    return random.choice(pool or PERSONAS)


def random_problem(persona: str, exclude: set[str] | None = None) -> str:
    """Случайная проблема под роль покупателя (фолбэк — общий список)."""
    source = PERSONA_PROBLEMS.get(persona, GENERIC_PROBLEMS)
    pool = [p for p in source if exclude is None or p not in exclude]
    return random.choice(pool or source)
