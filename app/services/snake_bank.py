"""Банк ролей и бытовых проблем для игры Snake Oil / «Змеиное масло».

Роль (persona) — это покупатель с характером («😺 Cat», «🏴‍☠️ Pirate»), которому
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
    "👵 Granny",
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
        "the scratching post broke and the sofa is shredded",
        "can't catch the laser pointer's red dot",
        "meows all night and wakes the owner",
    ],
    "🏴‍☠️ Pirate": [
        "can't find the buried treasure",
        "the wooden leg creaks and scares the parrot",
        "the ship's wheel jams on turns",
        "the parrot is silent and won't give directions",
    ],
    "👵 Granny": [
        "lost her glasses and can't find them",
        "can't open the jam jar",
        "the grandkid won't eat the porridge",
        "the socks went missing in the wash again",
    ],
    "🤖 Robot": [
        "the battery dies at the worst moment",
        "got rusty in the rain",
        "can't understand human emotions",
        "a joint in the arm is stuck",
    ],
    "🦖 Dinosaur": [
        "arms are too short to reach its back",
        "can't reach the top branches",
        "stomps loudly and scares the neighbors",
        "a meteor ruined the evening plans again",
    ],
    "🧙 Wizard": [
        "the spell keeps misfiring",
        "the broom won't start in the morning",
        "the cauldron keeps escaping the lab",
        "can't find the crystal ball",
    ],
    "🕵️ Spy": [
        "can't eavesdrop through the wall",
        "the coded note got wet",
        "invisibility doesn't turn on in time",
        "needs to pass a message across the office unnoticed",
    ],
    "👨‍🚀 Astronaut": [
        "can't eat soup in zero gravity",
        "the spacesuit fogs up inside",
        "can't fall asleep floating around the cabin",
        "an alien souvenir woke the whole crew",
    ],
    "🧟 Zombie": [
        "an arm keeps falling off",
        "too slow to catch people",
        "the brains in the fridge went bad",
        "afraid of dawn and can't make it home",
    ],
    "🦄 Unicorn": [
        "the horn scratches every doorframe",
        "the rainbow comes out crooked",
        "the mane keeps tangling",
        "can't poke the watermelon with its horn at the picnic",
    ],
    "🥷 Ninja": [
        "can't open the creaky door silently",
        "a throwing star is stuck in the ceiling",
        "its shadow gives it away in the light",
        "can't sneak through crunchy snow",
    ],
    "🤠 Cowboy": [
        "the horse won't listen and leaves without him",
        "the hat keeps flying off at a gallop",
        "the revolver jammed before the duel",
        "can't drive the herd into the pen",
    ],
    "🧛 Vampire": [
        "can't open the curtains during the day",
        "garlic in the soup ruins the appetite",
        "can't check the mirror before going out",
        "the coffin creaks and keeps it awake",
    ],
    "🐝 Bee": [
        "can't find its way back to the hive",
        "the flower closed and the nectar is gone",
        "the honey is too sticky and drips everywhere",
        "a hive-mate took the whole comb",
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
        "can't sneak into the henhouse quietly",
        "cunning doesn't work on the new neighbors",
    ],
    "🧜‍♀️ Mermaid": [
        "can't comb wet hair",
        "the tail doesn't fit in the bathtub",
        "can't reach the treasure at the bottom",
        "loses its voice before the big concert",
    ],
    "👽 Alien": [
        "can't understand human customs",
        "the antenna won't pick up the ship's signal",
        "the human disguise doesn't work",
        "can't get used to Earth food",
    ],
    "🎅 Santa": [
        "can't fit down the chimney with the sack",
        "the reindeer refuse to fly in the snowstorm",
        "can't read the gift lists",
        "the beard gets stuck in the jacket zipper",
    ],
    "🤡 Clown": [
        "can't make a sad child laugh",
        "the red nose keeps falling off",
        "can't think of a new trick",
        "the shoes are too big to walk in",
    ],
}

# Общий фолбэк на случай роли без своего списка.
GENERIC_PROBLEMS: list[str] = [
    "can't open the jar",
    "the coffee keeps boiling over",
    "socks go missing in the wash",
    "the alarm clock won't wake it up",
    "can't chop onions without crying",
    "the vacuum can't reach under the sofa",
    "can't reach the top shelf",
    "cords keep tangling",
    "keys keep getting lost",
    "can't catch the mosquito at night",
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
