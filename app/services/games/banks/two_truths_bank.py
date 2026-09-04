"""Банк наборов «Две правды, одна ложь» (Two Truths and a Lie).

Детерминированный фолбэк, когда LLM недоступен (паттерн wordle_bank/millionaire_bank).
Каждый набор: `topic` + `statements` (ровно 3 утверждения на английском) + `lie`
— 1-based индекс ложного утверждения. Правды достоверны, ложь правдоподобна.
"""
import random

FALLBACK_SETS = [
    {
        "topic": "Bananas 🍌",
        "statements": [
            "Bananas grow on trees.",
            "Bananas are berries, but strawberries are not.",
            "Bananas are naturally slightly radioactive.",
        ],
        "lie": 1,
    },
    {
        "topic": "Honey 🍯",
        "statements": [
            "Honey never spoils — edible honey was found in ancient Egyptian tombs.",
            "A worker honey bee lives for about five years.",
            "Bees must visit about two million flowers to make half a kilo of honey.",
        ],
        "lie": 2,
    },
    {
        "topic": "The Eiffel Tower 🗼",
        "statements": [
            "The Eiffel Tower was built for the 1889 World's Fair.",
            "The Eiffel Tower grows about 15 cm taller in summer because of the heat.",
            "The Eiffel Tower is the tallest building in Europe.",
        ],
        "lie": 3,
    },
    {
        "topic": "Octopuses 🐙",
        "statements": [
            "An octopus has three hearts.",
            "An octopus has bones in its arms.",
            "An octopus has blue blood.",
        ],
        "lie": 2,
    },
    {
        "topic": "Penguins 🐧",
        "statements": [
            "Wild penguins live in the Arctic.",
            "Penguins are birds that cannot fly.",
            "Emperor penguins are found in Antarctica.",
        ],
        "lie": 1,
    },
    {
        "topic": "The Great Wall of China 🏯",
        "statements": [
            "The Great Wall of China is over 20,000 kilometers long in total.",
            "Parts of the Great Wall were built more than 2,000 years ago.",
            "The Great Wall of China is clearly visible from space with the naked eye.",
        ],
        "lie": 3,
    },
]


def random_two_truths() -> dict:
    """Случайный набор из банка."""
    return random.choice(FALLBACK_SETS)
