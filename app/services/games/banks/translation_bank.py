"""Банк пар «рус ↔ англ» для игры «Переведи-ка» (Translate it).

Каждая пара — (ru, en). Бот показывает случайную сторону и случайное направление:
рус → англ (production) или англ → рус (comprehension). Судья — LLM, поэтому банк
задаёт только эталонный перевод; синонимы принимает судья.
"""
import random

PAIRS = [
    # --- Основные фразы ---
    ("привет", "hello"),
    ("спасибо", "thank you"),
    ("пожалуйста", "please"),
    ("до свидания", "goodbye"),
    ("доброе утро", "good morning"),
    ("как дела?", "how are you?"),
    ("извините", "excuse me"),
    ("я не понимаю", "I don't understand"),
    ("говорите медленнее", "speak more slowly"),
    ("сколько это стоит?", "how much does it cost?"),
    ("где туалет?", "where is the toilet?"),
    ("мне нужна помощь", "I need help"),
    ("я голоден", "I am hungry"),
    ("я хочу пить", "I am thirsty"),
    ("хорошего дня", "have a nice day"),
    ("я устал", "I am tired"),
    ("мне скучно", "I am bored"),
    ("у меня болит голова", "I have a headache"),
    ("будьте осторожны", "be careful"),
    ("увидимся завтра", "see you tomorrow"),

    # --- Существительные / прилагательные ---
    ("кот", "cat"),
    ("собака", "dog"),
    ("дом", "house"),
    ("работа", "work"),
    ("деньги", "money"),
    ("время", "time"),
    ("друг", "friend"),
    ("семья", "family"),
    ("еда", "food"),
    ("вода", "water"),
    ("книга", "book"),
    ("город", "city"),
    ("погода", "weather"),
    ("путешествие", "travel"),
    ("здоровье", "health"),
    ("мечта", "dream"),

    # --- Глаголы / действия ---
    ("учиться", "to study"),
    ("работать", "to work"),
    ("готовить", "to cook"),
    ("путешествовать", "to travel"),
    ("просыпаться", "to wake up"),
    ("засыпать", "to fall asleep"),
    ("убираться", "to clean up"),
    ("встречаться с друзьями", "to meet friends"),
    ("заниматься спортом", "to do sports"),
    ("смотреть фильм", "to watch a movie"),

    # --- Настоящее время ---
    ("Я живу в Минске.", "I live in Minsk."),
    ("Она работает в банке.", "She works in a bank."),
    ("Мы учим английский.", "We are learning English."),
    ("Я люблю читать книги.", "I love reading books."),
    ("Он играет на гитаре.", "He plays the guitar."),
    ("Сегодня хорошая погода.", "The weather is nice today."),
    ("Я пью кофе каждое утро.", "I drink coffee every morning."),
    ("Моя сестра живёт в Лондоне.", "My sister lives in London."),
    ("Мы смотрим фильм по вечерам.", "We watch a movie in the evenings."),
    ("Дети играют в парке.", "The children are playing in the park."),

    # --- Прошедшее время ---
    ("Я был в Париже.", "I have been to Paris."),
    ("Она купила новое платье.", "She bought a new dress."),
    ("Мы ходили на пляж летом.", "We went to the beach in summer."),
    ("Он закончил работу вчера.", "He finished the work yesterday."),
    ("Вчера шёл дождь.", "It rained yesterday."),
    ("Я встретил старого друга.", "I met an old friend."),
    ("Они смотрели фильм вчера вечером.", "They watched a movie last night."),

    # --- Будущее время ---
    ("Я позвоню тебе завтра.", "I will call you tomorrow."),
    ("Мы поедем в Италию летом.", "We are going to Italy in the summer."),
    ("Она будет учиться в университете.", "She will study at university."),
    ("Скоро пойдёт дождь.", "It is going to rain soon."),
    ("Я помогу тебе с сумками.", "I will help you with your bags."),

    # --- Фразовые глаголы (на примерах) ---
    ("У нас закончилось молоко.", "We ran out of milk."),
    ("Я с нетерпением жду встречи.", "I am looking forward to the meeting."),
    ("Он бросил курить.", "He gave up smoking."),
    ("Она присматривала за детьми.", "She looked after the children."),
    ("Они отложили встречу.", "They put off the meeting."),
    ("Я ищу свои ключи.", "I am looking for my keys."),
    ("Я случайно встретил его.", "I ran into him."),
    ("Я узнал правду.", "I found out the truth."),

    # --- Вопросы ---
    ("Как тебя зовут?", "What is your name?"),
    ("Откуда ты?", "Where are you from?"),
    ("Который час?", "What time is it?"),
    ("Ты говоришь по-английски?", "Do you speak English?"),
    ("Что ты делаешь?", "What are you doing?"),
    ("Ты был когда-нибудь в Японии?", "Have you ever been to Japan?"),
    ("Как долго ты здесь живёшь?", "How long have you lived here?"),

    # --- Разные предложения ---
    ("Я хочу выучить английский.", "I want to learn English."),
    ("Мне нравится готовить.", "I like cooking."),
    ("Он не ест мясо.", "He doesn't eat meat."),
    ("Мы должны закончить проект к пятнице.", "We must finish the project by Friday."),
    ("Ты можешь говорить медленнее?", "Can you speak more slowly?"),
    ("Это самый лучший ресторан в городе.", "This is the best restaurant in town."),
    ("Я учусь водить машину.", "I am learning to drive."),
    ("Она хорошо говорит по-английски.", "She speaks English well."),
    ("Я опоздал на автобус.", "I missed the bus."),
    ("Нам нужно купить продукты.", "We need to buy some groceries."),
    ("Он боится пауков.", "He is afraid of spiders."),
    ("Мы планируем поездку.", "We are planning a trip."),
    ("Эта книга интереснее, чем та.", "This book is more interesting than that one."),
    ("Я не могу найти свои ключи.", "I can't find my keys."),
    ("Пожалуйста, закрой дверь.", "Please close the door."),
    ("Сколько это займёт времени?", "How long will it take?"),
    ("Я рад тебя видеть.", "I am glad to see you."),
    ("Он родился в 2005 году.", "He was born in 2005."),
    ("Давайте начнём.", "Let's start."),
]


def random_translation_pair() -> tuple[str, str]:
    """Случайная пара (ru, en)."""
    return random.choice(PAIRS)
