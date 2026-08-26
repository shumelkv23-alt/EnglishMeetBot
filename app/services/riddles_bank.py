"""Банк загадок для игры «Riddles» — курированный, детерминированный.

Каждая запись: riddle (текст загадки), answer (канонический ответ, с артиклем
там, где он естественен), hint (короткая подсказка, можно пустую строку).
Сравнение ответа в сервисе снимает артикли и лишние знаки, а синонимы ловит LLM.
"""

import random

RIDDLES: list[dict] = [
    {
        "riddle": "What has keys but can't open locks?",
        "answer": "a piano",
        "hint": "It makes music.",
    },
    {
        "riddle": "What has a face and two hands but no arms or legs?",
        "answer": "a clock",
        "hint": "You check it for the time.",
    },
    {
        "riddle": "What gets wetter the more it dries?",
        "answer": "a towel",
        "hint": "You use it after a shower.",
    },
    {
        "riddle": "What has to be broken before you can use it?",
        "answer": "an egg",
        "hint": "You cook it for breakfast.",
    },
    {
        "riddle": "I'm tall when I'm young, and short when I'm old. What am I?",
        "answer": "a candle",
        "hint": "It burns and gives light.",
    },
    {
        "riddle": "What has a neck but no head?",
        "answer": "a bottle",
        "hint": "You drink from it.",
    },
    {
        "riddle": "What can you catch but not throw?",
        "answer": "a cold",
        "hint": "It's a common illness.",
    },
    {
        "riddle": "What has one eye but can't see?",
        "answer": "a needle",
        "hint": "You sew with it.",
    },
    {
        "riddle": "What goes up but never comes down?",
        "answer": "your age",
        "hint": "It only grows.",
    },
    {
        "riddle": "What has many teeth but can't bite?",
        "answer": "a comb",
        "hint": "You use it on your hair.",
    },
    {
        "riddle": "What has a thumb and four fingers but is not alive?",
        "answer": "a glove",
        "hint": "You wear it in winter.",
    },
    {
        "riddle": "What has a head and a tail but no body?",
        "answer": "a coin",
        "hint": "You pay with it.",
    },
    {
        "riddle": "What kind of room has no doors or windows?",
        "answer": "a mushroom",
        "hint": "It's a food that grows outside.",
    },
    {
        "riddle": "What has cities but no houses, forests but no trees, and water but no fish?",
        "answer": "a map",
        "hint": "You use it to find your way.",
    },
    {
        "riddle": "What can travel around the world while staying in a corner?",
        "answer": "a stamp",
        "hint": "It goes on an envelope.",
    },
    {
        "riddle": "The more you take, the more you leave behind. What are they?",
        "answer": "footsteps",
        "hint": "You make them when you walk.",
    },
    {
        "riddle": "What has a mouth but cannot speak, and a bed but never sleeps?",
        "answer": "a river",
        "hint": "Water flows in it.",
    },
    {
        "riddle": "I speak without a mouth and hear without ears. What am I?",
        "answer": "an echo",
        "hint": "You hear your voice repeated.",
    },
    {
        "riddle": "What can fill a room but takes up no space?",
        "answer": "light",
        "hint": "It comes from a lamp or the sun.",
    },
    {
        "riddle": "What is so fragile that saying its name breaks it?",
        "answer": "silence",
        "hint": "It's very quiet.",
    },
    {
        "riddle": "What begins with T, ends with T, and has T in it?",
        "answer": "a teapot",
        "hint": "It pours hot drinks.",
    },
    {
        "riddle": "What has legs but doesn't walk?",
        "answer": "a table",
        "hint": "You eat at it.",
    },
    {
        "riddle": "I shave every day, but my beard stays the same. Who am I?",
        "answer": "a barber",
        "hint": "They cut hair for a living.",
    },
    {
        "riddle": "What runs all around a yard without moving?",
        "answer": "a fence",
        "hint": "It marks a border.",
    },
    {
        "riddle": "What has words but never speaks?",
        "answer": "a book",
        "hint": "You read it.",
    },
    {
        "riddle": "What is always in front of you but can't be seen?",
        "answer": "the future",
        "hint": "It hasn't happened yet.",
    },
    {
        "riddle": "What is black when clean and white when dirty?",
        "answer": "a blackboard",
        "hint": "You find it in a classroom.",
    },
    {
        "riddle": "What can you hold without using your hands?",
        "answer": "your breath",
        "hint": "You do it under water.",
    },
    {
        "riddle": "What belongs to you but others use it more than you do?",
        "answer": "your name",
        "hint": "People call you by it.",
    },
    {
        "riddle": "What is full of holes but still holds water?",
        "answer": "a sponge",
        "hint": "You wash dishes with it.",
    },
    {
        "riddle": "What has a ring but no finger?",
        "answer": "a telephone",
        "hint": "It rings.",
    },
    {
        "riddle": "What comes down but never goes up?",
        "answer": "rain",
        "hint": "It falls from clouds.",
    },
    {
        "riddle": "What is always coming but never arrives?",
        "answer": "tomorrow",
        "hint": "It's the day after today.",
    },
    {
        "riddle": "What has a tongue but cannot taste?",
        "answer": "a shoe",
        "hint": "You wear it.",
    },
    {
        "riddle": "What has a bark but no bite?",
        "answer": "a tree",
        "hint": "It grows in a forest.",
    },
    {
        "riddle": "The more there is, the less you see. What is it?",
        "answer": "darkness",
        "hint": "It's the opposite of light.",
    },
    {
        "riddle": "What can be broken without being touched?",
        "answer": "a promise",
        "hint": "You keep it, or you don't.",
    },
    {
        "riddle": "What goes through cities and fields but never moves?",
        "answer": "a road",
        "hint": "Cars drive on it.",
    },
    {
        "riddle": "What walks on four legs in the morning, two in the afternoon, and three in the evening?",
        "answer": "a human",
        "hint": "The riddle of the Sphinx — a person at different ages.",
    },
    {
        "riddle": "What has a head but no eyes, nose, or mouth?",
        "answer": "a nail",
        "hint": "You hammer it.",
    },
]


def random_riddle() -> dict:
    """Случайная загадка из банка."""
    return random.choice(RIDDLES)
