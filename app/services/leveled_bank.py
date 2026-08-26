"""Банк раздела «English by level» (обучение английскому по уровням A/B/C).

Статический учебный материал: три уровня CEFR (A = A1–A2, B = B1–B2, C = C1–C2),
по 12 тем на уровень. Каждая тема = заметка (лёгкий HTML) + 8 лексических единиц
[english, русский, пример] + 5 грамматических/употребительских заданий
[вопрос, [3 варианта], верный_индекс, пояснение].

Темы — смесь общего и рабочего английского (greetings, travel, meetings, negotiations…).
Тексты правил и пояснений хранятся в лёгком HTML (<b>/<i>/<s>/<h3>/<p>) и
конвертируются в карточный markdown хелпером leveled._md (общий с callready._md).
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Уровни (3). themes — id тем в THEMES.
# ---------------------------------------------------------------------------
LEVELS: list[dict] = [
    {"id": "a", "label": "A", "name": "Beginner",     "sub": "A1–A2", "icon": "🟢", "themes": ["greetings", "routine", "food", "job", "family", "time", "home", "weather", "articles", "present_cont", "past_simple", "plurals"]},
    {"id": "b", "label": "B", "name": "Intermediate", "sub": "B1–B2", "icon": "🔵", "themes": ["travel", "smalltalk", "meetings", "shopping", "tech", "health", "environment", "media", "present_perfect", "conditionals", "comparatives", "modals"]},
    {"id": "c", "label": "C", "name": "Advanced",     "sub": "C1–C2", "icon": "🟣", "themes": ["negotiation", "presentation", "debate", "idioms", "leadership", "business", "register", "society", "mixed_conditionals", "reported_speech", "passive", "inversion"]},
]

# ---------------------------------------------------------------------------
# Темы. id → {id, level, icon, title, sub, notes (HTML), terms (8), quiz (5)}.
# ---------------------------------------------------------------------------
THEMES: dict[str, dict] = {
    # ------------------------------------------------------------- Level A
    "greetings": {
        "id": "greetings",
        "level": "a",
        "icon": "👋",
        "title": "Greetings & introductions",
        "sub": "Say hello, introduce yourself, meet people.",
        "notes": (
            "<h3>Hello, hi and first impressions</h3>"
            "<p>Use <b>Hello / Hi</b> for a friendly start. <b>Nice to meet you</b> works when you meet someone for the first time. <b>How are you?</b> is a common follow-up — the short answer is <b>I'm fine, thanks. And you?</b></p>"
            "<p><b>RU:</b> «Nice to meet you» — «приятно познакомиться» (только при первом знакомстве). «How are you?» — это приветствие, а не настоящий вопрос о самочувствии; короткий ответ нормален.</p>"
            "<p><b>Common mistake:</b> не путайте <s>How do you do?</s> (очень формально) и <b>How are you?</b> — в повседневной речи достаточно <b>How are you?</b></p>"
        ),
        "terms": [
            ["hello / hi", "привет", "Hi! Nice to meet you."],
            ["nice to meet you", "приятно познакомиться", "Nice to meet you, Anna."],
            ["how are you?", "как дела?", "How are you? — I'm fine, thanks."],
            ["my name is ...", "меня зовут ...", "My name is Alex."],
            ["where are you from?", "откуда вы?", "Where are you from? — I'm from Minsk."],
            ["good morning / afternoon", "доброе утро / день", "Good morning, everyone!"],
            ["see you later", "увидимся позже", "Thanks! See you later."],
            ["have a nice day", "хорошего дня", "Have a nice day!"],
        ],
        "quiz": [
            ["Choose the correct first greeting.", ["Nice to meet you.", "How do you do?", "See you later."], 0, "When you meet someone for the first time, say “Nice to meet you.”"],
            ["Complete: “___ are you from?”", ["Where", "What", "Who"], 0, "Use “Where” to ask about a place: “Where are you from?”"],
            ["Choose the natural reply to “How are you?”", ["I'm fine, thanks.", "I'm a doctor.", "Yes, please."], 0, "“How are you?” is a greeting; “I'm fine, thanks” is the natural short answer."],
            ["Complete: “Nice ___ meet you.”", ["to", "for", "at"], 0, "The fixed phrase is “Nice to meet you.”"],
            ["Choose the correct goodbye.", ["See you later!", "Nice to meet you!", "Good morning!"], 0, "“See you later” is a farewell; the others are greetings."],
        ],
    },
    "routine": {
        "id": "routine",
        "level": "a",
        "icon": "🕗",
        "title": "Daily routine",
        "sub": "Talk about your day: get up, work, relax.",
        "notes": (
            "<h3>Talking about your day</h3>"
            "<p>Use the <b>Present Simple</b> for things you do every day: <b>I get up at seven.</b> Add <b>usually / always / sometimes</b> to say how often.</p>"
            "<p><b>RU:</b> Present Simple — простое настоящее для регулярных действий. Наречия частоты <b>usually</b> (обычно), <b>always</b> (всегда), <b>sometimes</b> (иногда) ставятся перед основным глаголом.</p>"
            "<p><b>Common mistake:</b> не забывайте <b>-s</b> у глагола после he/she: <s>She get up</s> → <b>She gets up</b>.</p>"
        ),
        "terms": [
            ["get up", "вставать", "I get up at seven."],
            ["go to work", "идти на работу", "She goes to work by bus."],
            ["have breakfast", "завтракать", "We have breakfast at eight."],
            ["work out / exercise", "тренироваться", "He works out in the evening."],
            ["come home", "приходить домой", "I come home at six."],
            ["go to bed", "ложиться спать", "They go to bed at eleven."],
            ["every day", "каждый день", "I read every day."],
            ["usually / sometimes", "обычно / иногда", "I usually walk to work."],
        ],
        "quiz": [
            ["Choose the correct routine.", ["She gets up at seven.", "She get up at seven.", "She getting up at seven."], 0, "With “she”, add -s: “gets up”."],
            ["Complete: “I ___ breakfast at eight.”", ["have", "has", "having"], 0, "Use “have” with “I”."],
            ["Choose the correct frequency.", ["I usually walk to work.", "I walk usually to work.", "I usually to walk to work."], 0, "“usually” goes before the main verb: “usually walk”."],
            ["Choose the correct verb form.", ["He works out in the evening.", "He work out in the evening.", "He working out in the evening."], 0, "With “he”, add -s: “works out”."],
            ["Complete: “They go to bed ___ eleven.”", ["at", "on", "in"], 0, "Use “at” with clock times: “at eleven”."],
        ],
    },
    "food": {
        "id": "food",
        "level": "a",
        "icon": "🍕",
        "title": "Food & ordering",
        "sub": "Order food and drink, ask about prices.",
        "notes": (
            "<h3>Ordering food like a pro</h3>"
            "<p>Start with <b>Can I have …?</b> or <b>I'd like …</b> to order politely. Ask <b>How much is it?</b> about the price. To say thanks after the meal: <b>The food was delicious.</b></p>"
            "<p><b>RU:</b> «Can I have…?» и «I'd like…» — вежливые способы заказать. «How much is it?» — «сколько это стоит?».</p>"
            "<p><b>Common mistake:</b> не путайте <b>How much</b> (неисчисляемое / цена) и <b>How many</b> (исчисляемое): <b>How much water?</b>, но <b>How many apples?</b></p>"
        ),
        "terms": [
            ["menu", "меню", "Can I see the menu, please?"],
            ["order", "заказывать", "I'd like to order a pizza."],
            ["delicious", "вкусный", "This soup is delicious."],
            ["bill / check", "счёт", "Could we have the bill, please?"],
            ["water", "вода", "Can I have some water?"],
            ["How much is it?", "сколько это стоит?", "How much is the salad?"],
            ["vegetarian", "вегетарианский", "Do you have vegetarian options?"],
            ["take away", "на вынос", "I'd like to take it away, please."],
        ],
        "quiz": [
            ["Choose the polite way to order.", ["Can I have a coffee, please?", "Give me a coffee.", "Coffee now."], 0, "“Can I have … please?” is the polite form."],
            ["Complete: “___ much is it?”", ["How", "What", "Who"], 0, "Ask “How much” about price."],
            ["Choose the correct question.", ["How much water do you want?", "How many water do you want?", "How much apples do you want?"], 0, "“water” is uncountable → “How much”."],
            ["Complete: “Could we have the ___ please?”", ["bill", "menu", "delicious"], 0, "Ask for the “bill” to pay."],
            ["Choose the correct word.", ["This soup is delicious.", "This soup is deliciously.", "This soup delicious."], 0, "Use the adjective “delicious” after “is”."],
        ],
    },
    "job": {
        "id": "job",
        "level": "a",
        "icon": "💼",
        "title": "Your job & workplace",
        "sub": "Say what you do, where you work, what you like.",
        "notes": (
            "<h3>Describing your job</h3>"
            "<p>Say <b>I work as a …</b> or <b>I am a …</b> to describe your role. <b>I work for …</b> tells the company. Use <b>colleague</b> for a person you work with.</p>"
            "<p><b>RU:</b> «I work as a developer» — «я работаю разработчиком». «I work for a bank» — «я работаю в банке». Профессии идут с артиклем <b>a/an</b>.</p>"
            "<p><b>Common mistake:</b> не забывайте артикль: <s>I am engineer</s> → <b>I am an engineer</b>.</p>"
        ),
        "terms": [
            ["job / work", "работа", "I love my job."],
            ["colleague", "коллега", "My colleague helps me a lot."],
            ["office", "офис", "We work in a big office."],
            ["meeting", "встреча / совещание", "I have a meeting at ten."],
            ["team", "команда", "I work in a small team."],
            ["customer / client", "клиент", "Our clients are happy."],
            ["full-time", "полная занятость", "She works full-time."],
            ["salary", "зарплата", "The salary is good."],
        ],
        "quiz": [
            ["Choose the correct sentence.", ["I work as a designer.", "I work as designer.", "I work designer."], 0, "Say “work as a …” with the article “a”."],
            ["Complete: “I ___ an engineer.”", ["am", "is", "do"], 0, "Use “am” with “I”: “I am an engineer”."],
            ["Choose the correct word.", ["My colleague helps me.", "My colleague help me.", "My colleague helping me."], 0, "“colleague” is singular → “helps”."],
            ["Complete: “I work ___ a small team.”", ["in", "on", "at"], 0, "Use “in a team”."],
            ["Choose the correct article.", ["She is a doctor.", "She is doctor.", "She is an doctor."], 0, "Professions take “a/an”: “a doctor”."],
        ],
    },
    "family": {
        "id": "family",
        "level": "a",
        "icon": "👨‍👩‍👧",
        "title": "Family & people",
        "sub": "Talk about your family and people around you.",
        "notes": (
            "<h3>Talking about your family</h3>"
            "<p>Use <b>have</b> to say who is in your family: <b>I have one brother.</b> Add <b>'s</b> for possession: <b>my sister's car</b>. Ask about someone's life with <b>Are you married?</b></p>"
            "<p><b>RU:</b> «have» — «иметь» (у меня есть…). Притяжательный падеж: «my sister's car» — «машина моей сестры». «Are you married?» — «вы женаты/замужем?».</p>"
            "<p><b>Common mistake:</b> не путайте <s>He have</s> и <b>He has</b> — у he/she/it глагол <b>has</b>.</p>"
        ),
        "terms": [
            ["family", "семья", "My family is big."],
            ["mother / father", "мать / отец", "My mother is a teacher."],
            ["brother / sister", "брат / сестра", "I have one brother and two sisters."],
            ["son / daughter", "сын / дочь", "Their daughter is five years old."],
            ["husband / wife", "муж / жена", "His wife works at a hospital."],
            ["children", "дети", "They have three children."],
            ["married", "женат / замужем", "Are you married?"],
            ["single", "не женат / не замужем", "I'm single."],
        ],
        "quiz": [
            ["Choose the correct possessive.", ["My sister's car is blue.", "My sister car is blue.", "My sisters car is blue."], 0, "Use apostrophe-s for possession: “my sister's car”."],
            ["Complete: “They ___ three children.”", ["have", "has", "is"], 0, "Use “have” with “they”."],
            ["Choose the correct question.", ["Are you married?", "Do you married?", "Have you married?"], 0, "Ask “Are you married?” — “married” is an adjective after “be”."],
            ["Complete: “I have one brother ___ two sisters.”", ["and", "but", "or"], 0, "Use “and” to add items in a list."],
            ["Choose the correct verb form.", ["She has one brother.", "She have one brother.", "She having one brother."], 0, "With “she”, use “has”."],
        ],
    },
    "time": {
        "id": "time",
        "level": "a",
        "icon": "🕐",
        "title": "Numbers, time & dates",
        "sub": "Tell the time, talk about days and dates.",
        "notes": (
            "<h3>Saying the time and dates</h3>"
            "<p>Use <b>What time is it?</b> to ask the time, and answer <b>It's three o'clock.</b> For dates, <b>on Monday</b> (day), <b>in June</b> (month), <b>at five o'clock</b> (time).</p>"
            "<p><b>RU:</b> «on» + день недели, «in» + месяц/год, «at» + точное время. «half past two» — «полтретьего» (2:30).</p>"
            "<p><b>Common mistake:</b> не путайте предлоги времени: <s>in Monday</s> → <b>on Monday</b>.</p>"
        ),
        "terms": [
            ["What time is it?", "который час?", "What time is it? — It's three o'clock."],
            ["half past", "половина (после)", "The meeting is at half past nine."],
            ["quarter to", "без четверти", "It's a quarter to four."],
            ["o'clock", "ровно (час)", "Let's meet at six o'clock."],
            ["morning / afternoon / evening", "утро / день / вечер", "See you in the afternoon."],
            ["today / tomorrow / yesterday", "сегодня / завтра / вчера", "The deadline is tomorrow."],
            ["week / month / year", "неделя / месяц / год", "She visits once a week."],
            ["date", "дата", "What's the date today?"],
        ],
        "quiz": [
            ["Choose the correct preposition.", ["See you on Monday.", "See you in Monday.", "See you at Monday."], 0, "Use “on” with days of the week."],
            ["Complete: “The meeting is at half ___ nine.”", ["past", "after", "to"], 0, "“Half past nine” = 9:30."],
            ["Choose the correct question.", ["What time is it?", "What is the hour?", "How many time is it?"], 0, "Ask “What time is it?”"],
            ["Complete: “She visits once ___ week.”", ["a", "the", "an"], 0, "“Once a week” = one time per week."],
            ["Choose the correct preposition.", ["Let's meet at six o'clock.", "Let's meet on six o'clock.", "Let's meet in six o'clock."], 0, "Use “at” with clock times."],
        ],
    },
    "home": {
        "id": "home",
        "level": "a",
        "icon": "🏠",
        "title": "Home & rooms",
        "sub": "Describe your home and what's in it.",
        "notes": (
            "<h3>Describing your home</h3>"
            "<p>Use <b>there is / there are</b> to say what exists in a place: <b>There is a sofa in the living room.</b> Describe rooms with <b>kitchen, bedroom, bathroom</b>.</p>"
            "<p><b>RU:</b> «there is» — «есть, имеется» (единственное), «there are» — множественное. «in the kitchen» — «на кухне».</p>"
            "<p><b>Common mistake:</b> <s>There are a sofa</s> → <b>There is a sofa</b> (единственное число).</p>"
        ),
        "terms": [
            ["home / house", "дом", "I live in a small house."],
            ["room", "комната", "My room is bright."],
            ["kitchen", "кухня", "We cook in the kitchen."],
            ["bedroom", "спальня", "The bedroom is upstairs."],
            ["bathroom", "ванная", "The bathroom is next to the kitchen."],
            ["living room", "гостиная", "There is a big sofa in the living room."],
            ["furniture", "мебель", "The furniture is new."],
            ["live", "жить", "Where do you live?"],
        ],
        "quiz": [
            ["Choose the correct sentence.", ["There is a sofa in the living room.", "There are a sofa in the living room.", "There is sofa in the living room."], 0, "“sofa” is singular → “There is a sofa”."],
            ["Complete: “Where do you ___?”", ["live", "lives", "living"], 0, "After “do you”, use the base verb “live”."],
            ["Choose the correct word.", ["The bathroom is next to the kitchen.", "The bathroom is next the kitchen.", "The bathroom is next on the kitchen."], 0, "“Next to” = beside."],
            ["Complete: “We cook in the ___.”", ["kitchen", "bathroom", "living room"], 0, "People cook in the “kitchen”."],
            ["Choose the correct plural.", ["There are two bedrooms.", "There is two bedrooms.", "There are two bedroom."], 0, "“bedrooms” is plural → “There are two bedrooms”."],
        ],
    },
    "weather": {
        "id": "weather",
        "level": "a",
        "icon": "🌦️",
        "title": "Weather & seasons",
        "sub": "Talk about the weather and the time of year.",
        "notes": (
            "<h3>Talking about the weather</h3>"
            "<p>Start with <b>It's sunny / rainy / cold.</b> Use <b>What's the weather like?</b> to ask. Talk about seasons: <b>in summer, in winter</b>.</p>"
            "<p><b>RU:</b> «What's the weather like?» — «какая погода?». Погода описывается с «It's»: «It's cold» — «холодно». Сезоны с «in».</p>"
            "<p><b>Common mistake:</b> не забывайте «It's»: <s>Cold today</s> → <b>It's cold today</b>.</p>"
        ),
        "terms": [
            ["weather", "погода", "The weather is nice today."],
            ["sunny", "солнечно", "It's sunny and warm."],
            ["rainy", "дождливо", "It's rainy in autumn."],
            ["cold / hot", "холодно / жарко", "It's cold outside."],
            ["cloudy", "облачно", "It's cloudy but dry."],
            ["snow", "снег", "There is a lot of snow in winter."],
            ["season", "время года / сезон", "My favourite season is summer."],
            ["temperature", "температура", "The temperature is twenty degrees."],
        ],
        "quiz": [
            ["Choose the correct sentence.", ["It's sunny and warm.", "Is sunny and warm.", "Sunny and warm."], 0, "Use “It's” to describe the weather."],
            ["Complete: “What's the weather ___?”", ["like", "is", "does"], 0, "The fixed question is “What's the weather like?”"],
            ["Choose the correct word.", ["It's cold outside.", "It's cold out.", "It cold outside."], 0, "Use “It's cold outside” (with “It's”)."],
            ["Complete: “There is a lot of snow ___ winter.”", ["in", "on", "at"], 0, "Use “in” with seasons: “in winter”."],
            ["Choose the correct adjective.", ["It's cloudy but dry.", "It's cloud but dry.", "It's cloudy but dryly."], 0, "Use the adjective “cloudy” after “It's”."],
        ],
    },
    "articles": {
        "id": "articles",
        "level": "a",
        "icon": "📚",
        "title": "Articles: a / an / the",
        "sub": "When to use a, an, the — or nothing.",
        "notes": (
            "<h3>The articles a / an / the</h3>"
            "<p>Use <b>a / an</b> for one thing, not specific: <b>a dog</b>, <b>an apple</b>. Use <b>the</b> when both people know which one: <b>the dog in the garden</b>. Use <b>no article</b> for general ideas: <b>I like music</b>.</p>"
            "<p><b>RU:</b> «a/an» — неопределённый артикль (один из многих, любой). «the» — определённый (конкретный, известный). Общие понятия идут без артикля.</p>"
            "<p><b>Common mistake:</b> <b>a</b> перед согласным <i>звуком</i> (<b>a university</b>), <b>an</b> перед гласным <i>звуком</i> (<b>an hour</b>).</p>"
        ),
        "terms": [
            ["a / an", "неопределённый артикль (один, любой)", "I have a dog. She is an engineer."],
            ["the", "определённый артикль (конкретный)", "The dog in the garden is friendly."],
            ["zero article", "без артикля (общее понятие)", "I like music, coffee and sports."],
            ["a + consonant sound", "a перед согласным звуком", "a book, a university, a house"],
            ["an + vowel sound", "an перед гласным звуком", "an apple, an hour, an umbrella"],
            ["the + mentioned before", "the когда уже упоминали", "I saw a film. The film was great."],
            ["the + only one", "the с единственным в своём роде", "the sun, the moon, the world"],
            ["the + superlative", "the с превосходной степенью", "the best, the biggest, the most"],
        ],
        "quiz": [
            ["Choose the correct article.", ["I have a dog.", "I have dog.", "I have the dog."], 0, "Use “a” for one non-specific thing: “a dog”."],
            ["Choose the correct article.", ["The sun is very bright.", "Sun is very bright.", "A sun is very bright."], 0, "Use “the” for the only one: “the sun”."],
            ["Complete: “She is ___ engineer.”", ["an", "a", "the"], 0, "“engineer” starts with a vowel sound → “an”."],
            ["Choose the correct article.", ["I like music.", "I like the music.", "I like a music."], 0, "General ideas take no article: “I like music”."],
            ["Complete: “___ best film is this one.”", ["The", "A", "An"], 0, "Use “the” with superlatives: “the best”."],
        ],
    },
    "present_cont": {
        "id": "present_cont",
        "level": "a",
        "icon": "🔛",
        "title": "Present continuous",
        "sub": "What you are doing right now (am/is/are + -ing).",
        "notes": (
            "<h3>What are you doing right now?</h3>"
            "<p>Use <b>am / is / are + verb-ing</b> for actions happening now: <b>I am working</b>. Compare with Present Simple for regular actions: <b>I work every day</b>.</p>"
            "<p><b>RU:</b> Present Continuous — «сейчас, в этот момент»: «I am working» — «я сейчас работаю». Present Simple — регулярное: «I work every day».</p>"
            "<p><b>Common mistake:</b> не забывайте <b>am/is/are</b>: <s>I working</s> → <b>I am working</b>.</p>"
        ),
        "terms": [
            ["am / is / are + -ing", "настоящее длительное (сейчас)", "I am working right now."],
            ["I am doing", "я делаю (сейчас)", "I am reading a book now."],
            ["he/she is doing", "он/она делает (сейчас)", "She is cooking dinner."],
            ["they are doing", "они делают (сейчас)", "They are watching TV."],
            ["now", "сейчас", "I am writing now."],
            ["at the moment", "в данный момент", "He is busy at the moment."],
            ["right now", "прямо сейчас", "We are talking right now."],
            ["Present Simple vs Continuous", "регулярное vs сейчас", "I work every day, but today I am resting."],
        ],
        "quiz": [
            ["Choose the correct sentence.", ["I am working right now.", "I working right now.", "I am work right now."], 0, "Use “am + verb-ing”: “am working”."],
            ["Choose the correct sentence.", ["She is cooking dinner.", "She cooking dinner.", "She is cook dinner."], 0, "Use “is + verb-ing”: “is cooking”."],
            ["Complete: “They ___ watching TV.”", ["are", "is", "am"], 0, "Use “are” with “they”."],
            ["Choose the correct sentence.", ["I work every day.", "I am working every day.", "I works every day."], 0, "Regular actions → Present Simple: “I work”."],
            ["Complete: “I am ___ a book now.”", ["reading", "read", "reads"], 0, "Use “am + verb-ing”: “am reading”."],
        ],
    },
    "past_simple": {
        "id": "past_simple",
        "level": "a",
        "icon": "⏳",
        "title": "Past simple",
        "sub": "Talk about finished actions in the past.",
        "notes": (
            "<h3>Talking about the past</h3>"
            "<p>Use <b>Past Simple</b> for finished actions: <b>I worked yesterday</b>. Regular verbs add <b>-ed</b>: work → worked. Many common verbs are irregular: <b>go → went</b>, <b>have → had</b>.</p>"
            "<p><b>RU:</b> Past Simple — завершённое действие в прошлом. Правильные глаголы: +ed. Неправильные (go/went, have/had, see/saw) надо запоминать.</p>"
            "<p><b>Common mistake:</b> в отрицаниях и вопросах с did — основа глагола: <s>Did you went?</s> → <b>Did you go?</b></p>"
        ),
        "terms": [
            ["-ed (regular)", "правильные глаголы (окончание -ed)", "I worked, I played, I studied."],
            ["went", "пошёл (go)", "I went to the cinema."],
            ["had", "имел (have)", "She had a great time."],
            ["saw", "увидел (see)", "We saw a film."],
            ["did (question)", "вспомогательный did в вопросе", "Did you go to work?"],
            ["didn't (negative)", "отрицание didn't", "I didn't see him."],
            ["yesterday", "вчера", "I worked yesterday."],
            ["last week / last year", "на прошлой неделе / в прошлом году", "They moved last year."],
        ],
        "quiz": [
            ["Choose the correct past form.", ["I went to the cinema.", "I go to the cinema.", "I goed to the cinema."], 0, "“go” is irregular → “went”."],
            ["Choose the correct question.", ["Did you go to work?", "Did you went to work?", "You did go to work?"], 0, "After “did”, use the base verb “go”."],
            ["Choose the correct negative.", ["I didn't see him.", "I didn't saw him.", "I not saw him."], 0, "“didn't + base verb”: “didn't see”."],
            ["Complete: “I ___ yesterday.” (work)", ["worked", "work", "works"], 0, "Regular verb → “worked”."],
            ["Choose the correct sentence.", ["She had a great time.", "She has a great time.", "She haved a great time."], 0, "“have” → past “had”."],
        ],
    },
    "plurals": {
        "id": "plurals",
        "level": "a",
        "icon": "🔢",
        "title": "Plurals & countability",
        "sub": "One, two, many — and uncountable nouns.",
        "notes": (
            "<h3>One, two, many</h3>"
            "<p>Add <b>-s</b> for most plurals: <b>book → books</b>. Add <b>-es</b> after -s/-x/-ch/-sh: <b>box → boxes</b>. Some nouns are uncountable and stay singular: <b>water, money, information</b>.</p>"
            "<p><b>RU:</b> Множественное число: +s, после шипящих +es (box→boxes, watch→watches). Неисчисляемые (water, money, information) не имеют множественного числа.</p>"
            "<p><b>Common mistake:</b> <s>informations</s>, <s>moneys</s> — неисчисляемые не ставятся во множественное число.</p>"
        ),
        "terms": [
            ["-s (regular)", "множественное число +s", "one book → two books"],
            ["-es (after -s/-ch/-sh/-x)", "множественное +es после шипящих", "box → boxes, watch → watches"],
            ["man / men", "мужчина / мужчины (неправильное)", "one man → two men"],
            ["child / children", "ребёнок / дети (неправильное)", "one child → three children"],
            ["countable", "исчисляемое", "books, cars, apples"],
            ["uncountable", "неисчисляемое", "water, money, information"],
            ["much / many", "много (неисчисл. / исчисл.)", "much water, many books"],
            ["some / any", "несколько / немного", "I have some milk."],
        ],
        "quiz": [
            ["Choose the correct plural.", ["two boxes", "two boxs", "two box"], 0, "After -x, add “-es”: “boxes”."],
            ["Choose the correct plural.", ["three children", "three childs", "three childrens"], 0, "“child” is irregular → “children”."],
            ["Choose the correct word.", ["much water", "many water", "a water"], 0, "“water” is uncountable → “much water”."],
            ["Choose the correct word.", ["many books", "much books", "many book"], 0, "“books” is countable → “many books”."],
            ["Complete: “I have some ___.”", ["milk", "milks", "a milk"], 0, "“milk” is uncountable → no plural, no article."],
        ],
    },

    # ------------------------------------------------------------- Level B
    "travel": {
        "id": "travel",
        "level": "b",
        "icon": "✈️",
        "title": "Travel & directions",
        "sub": "Get around, ask for directions, buy tickets.",
        "notes": (
            "<h3>Getting around a new place</h3>"
            "<p>To ask the way, use <b>Excuse me, how do I get to …?</b> or <b>Could you tell me where … is?</b> After “Could you tell me…”, keep normal word order: <b>where the station is</b>.</p>"
            "<p><b>RU:</b> После «Could you tell me…» порядок слов обычный, не вопросительный: «where the station is», а не «where is the station».</p>"
            "<p><b>Common mistake:</b> не забывайте <b>the</b> перед конкретным местом: <b>the station, the airport, the museum</b>.</p>"
        ),
        "terms": [
            ["get to", "добраться до", "How do I get to the station?"],
            ["direction", "направление", "Can you give me directions?"],
            ["turn left / right", "повернуть налево / направо", "Turn left at the corner."],
            ["straight ahead", "прямо", "Go straight ahead for two blocks."],
            ["ticket", "билет", "I need a ticket to London."],
            ["platform", "платформа", "The train leaves from platform 3."],
            ["luggage / baggage", "багаж", "Where can I leave my luggage?"],
            ["check in", "зарегистрироваться", "We check in at the hotel."],
        ],
        "quiz": [
            ["Choose the polite way to ask for directions.", ["Excuse me, how do I get to the station?", "Where is station?", "Tell me the station."], 0, "“Excuse me, how do I get to …?” is polite and clear."],
            ["Complete: “Could you tell me where ___ ?”", ["the station is", "is the station", "the station"], 0, "After “Could you tell me…”, use normal word order: “where the station is”."],
            ["Choose the correct direction.", ["Turn left at the corner.", "Turn left on the corner.", "Turn left the corner."], 0, "Use “at” for a point: “at the corner”."],
            ["Complete: “Go straight ___ for two blocks.”", ["ahead", "front", "on"], 0, "The phrase is “straight ahead”."],
            ["Choose the correct phrase.", ["I need a ticket to London.", "I need ticket to London.", "I need a ticket for go to London."], 0, "Use “a ticket to + place”."],
        ],
    },
    "smalltalk": {
        "id": "smalltalk",
        "level": "b",
        "icon": "☕",
        "title": "Small talk",
        "sub": "Chat casually about weather, weekend, hobbies.",
        "notes": (
            "<h3>Light conversation</h3>"
            "<p>Small talk usually starts with a safe topic: <b>the weather</b>, <b>the weekend</b>, or <b>how someone has been</b>. Use <b>How was your weekend?</b> and answer with <b>It was nice, thanks. I …</b></p>"
            "<p><b>RU:</b> Small talk — лёгкая непринуждённая беседа. Безопасные темы: погода, выходные, хобби, путешествия. Избегайте слишком личных тем.</p>"
            "<p><b>Common mistake:</b> не отвечайте на «How was your weekend?» односложно — добавьте деталь: «It was nice. I went hiking.»</p>"
        ),
        "terms": [
            ["small talk", "лёгкая беседа", "We had some small talk before the meeting."],
            ["How was your weekend?", "как прошли выходные?", "How was your weekend? — It was nice."],
            ["weather", "погода", "The weather is lovely today."],
            ["hobby", "хобби", "My hobby is photography."],
            ["weekend", "выходные", "What did you do on the weekend?"],
            ["How have you been?", "как у тебя дела (давно)?", "How have you been? — Great, thanks."],
            ["catch up", "обменяться новостями", "Let's catch up over coffee."],
            ["nice to see you", "рад тебя видеть", "Nice to see you again!"],
        ],
        "quiz": [
            ["Choose a good small-talk opener.", ["How was your weekend?", "How old are you?", "How much do you earn?"], 0, "The weekend is a safe, friendly topic; salary and age are too personal."],
            ["Complete: “How have you ___?”", ["been", "be", "is"], 0, "“How have you been?” uses the past participle “been”."],
            ["Choose the natural reply.", ["It was nice, thanks. I went hiking.", "Yes.", "I don't know."], 0, "Add a short detail to keep the conversation going."],
            ["Choose the correct phrase.", ["Nice to see you again!", "Nice to seeing you again!", "Nice see you again!"], 0, "The fixed phrase is “Nice to see you”."],
            ["Complete: “Let's catch ___ over coffee.”", ["up", "on", "in"], 0, "“Catch up” = exchange news."],
        ],
    },
    "meetings": {
        "id": "meetings",
        "level": "b",
        "icon": "📅",
        "title": "Meetings & updates",
        "sub": "Give an update, agree, set the next step.",
        "notes": (
            "<h3>Work updates</h3>"
            "<p>To give a status, use <b>We are working on …</b> (in progress) and <b>by Friday</b> for a deadline. To agree, say <b>I agree with that</b> or <b>That works for me</b>.</p>"
            "<p><b>RU:</b> «We are working on…» — о текущей работе. «by Friday» — «не позднее пятницы». «That works for me» — «мне это подходит».</p>"
            "<p><b>Common mistake:</b> не путайте <b>by Friday</b> (до пятницы) и <b>on Friday</b> (в пятницу).</p>"
        ),
        "terms": [
            ["update", "обновление / новость", "Let me give you a quick update."],
            ["deadline", "срок", "The deadline is Friday."],
            ["agenda", "повестка", "What's on the agenda today?"],
            ["agree", "соглашаться", "I agree with that approach."],
            ["next step", "следующий шаг", "The next step is to test it."],
            ["in progress", "в работе", "The task is in progress."],
            ["follow up", "вернуться с ответом", "I'll follow up by email."],
            ["reschedule", "перенести", "Could we reschedule the meeting?"],
        ],
        "quiz": [
            ["Choose the correct status update.", ["We are working on it now.", "We working on it now.", "We work on it now."], 0, "Use “are + verb-ing” for work in progress."],
            ["Complete: “The deadline is ___ Friday.”", ["by", "on", "at"], 0, "“by Friday” means no later than Friday."],
            ["Choose the natural agreement.", ["That works for me.", "That works to me.", "That works me."], 0, "The phrase is “That works for me”."],
            ["Choose the correct word.", ["I'll follow up by email.", "I'll follow up on email.", "I'll follow up email."], 0, "“Follow up by email” = send a follow-up via email."],
            ["Complete: “Could we ___ the meeting?”", ["reschedule", "rescheduling", "to reschedule"], 0, "After “Could we”, use the base verb: “reschedule”."],
        ],
    },
    "shopping": {
        "id": "shopping",
        "level": "b",
        "icon": "🛍️",
        "title": "Shopping & money",
        "sub": "Buy things, talk about price, pay, return.",
        "notes": (
            "<h3>Buying and paying</h3>"
            "<p>Ask <b>How much does it cost?</b> or <b>Is it on sale?</b> to talk about price. To pay, <b>Can I pay by card?</b> To return something, <b>I'd like to return this</b>.</p>"
            "<p><b>RU:</b> «How much does it cost?» — «сколько это стоит?». «on sale» — «по скидке». «pay by card» — «оплатить картой».</p>"
            "<p><b>Common mistake:</b> «pay <b>by</b> card» (способ оплаты), но «pay <b>for</b> something» (за что-то).</p>"
        ),
        "terms": [
            ["cost", "стоить", "How much does it cost?"],
            ["price", "цена", "The price is too high."],
            ["on sale", "по скидке", "These shoes are on sale."],
            ["discount", "скидка", "Is there a discount?"],
            ["pay by card", "оплатить картой", "Can I pay by card?"],
            ["receipt", "чек", "Could I have a receipt?"],
            ["return", "вернуть", "I'd like to return this."],
            ["try on", "примерить", "Can I try on these jeans?"],
        ],
        "quiz": [
            ["Choose the correct question.", ["How much does it cost?", "How many does it cost?", "How much is it cost?"], 0, "Ask “How much does it cost?”"],
            ["Complete: “Can I pay ___ card?”", ["by", "with", "for"], 0, "“Pay by card” is the correct phrase."],
            ["Choose the correct word.", ["These shoes are on sale.", "These shoes are in sale.", "These shoes are at sale."], 0, "“On sale” = discounted."],
            ["Complete: “I'd like to ___ these jeans.”", ["try on", "try in", "try at"], 0, "“Try on” = put on clothes to check the fit."],
            ["Choose the correct phrase.", ["Is there a discount?", "Is there discount?", "Is there a discount to have?"], 0, "Use the article: “a discount”."],
        ],
    },
    "tech": {
        "id": "tech",
        "level": "b",
        "icon": "💻",
        "title": "Technology & devices",
        "sub": "Talk about devices, apps and tech problems.",
        "notes": (
            "<h3>Talking about tech and devices</h3>"
            "<p>Use <b>device</b> for a phone/laptop, <b>app</b> for a program. Talk about problems with <b>It's not working</b> or <b>the battery is dead</b>. Use <b>update</b> as a verb and a noun.</p>"
            "<p><b>RU:</b> «device» — «устройство». «It's not working» — «это не работает». «the battery is dead» — «батарея села». «update» — и глагол, и существительное.</p>"
            "<p><b>Common mistake:</b> не путайте <b>download</b> (скачать к себе) и <b>upload</b> (загрузить на сервер).</p>"
        ),
        "terms": [
            ["device", "устройство", "My device is a bit old."],
            ["app", "приложение", "I installed a new app."],
            ["battery", "батарея", "My battery is dead."],
            ["charge", "заряжать", "I need to charge my phone."],
            ["download / upload", "скачать / загрузить", "Let me download the file."],
            ["screen", "экран", "The screen is broken."],
            ["password", "пароль", "I forgot my password."],
            ["update", "обновление / обновлять", "Please update the app."],
        ],
        "quiz": [
            ["Choose the correct sentence.", ["My battery is dead.", "My battery is die.", "My battery dead."], 0, "Use “is dead” — “dead” is an adjective after “is”."],
            ["Complete: “I need to ___ my phone.”", ["charge", "charging", "to charge"], 0, "After “need to”, use the base verb “charge”."],
            ["Choose the correct word.", ["I installed a new app.", "I installed a new app on.", "I installed new app."], 0, "“App” is countable → “a new app”."],
            ["Complete: “Please ___ the app.”", ["update", "updating", "to update"], 0, "Use the base verb “update” after “please”."],
            ["Complete: “My screen ___ broken.”", ["is", "are", "be"], 0, "Use “is” with singular “screen”."],
        ],
    },
    "health": {
        "id": "health",
        "level": "b",
        "icon": "🏥",
        "title": "Health & lifestyle",
        "sub": "Describe how you feel and give advice.",
        "notes": (
            "<h3>Health and lifestyle</h3>"
            "<p>Use <b>I feel …</b> or <b>I have a headache</b> to describe how you are. Use <b>should</b> for advice: <b>You should see a doctor.</b> Talk about habits with <b>stay healthy</b>.</p>"
            "<p><b>RU:</b> «I feel tired» — «я чувствую усталость». «I have a headache» — «у меня болит голова». «should + глагол» — совет.</p>"
            "<p><b>Common mistake:</b> «should» без частицы to: <s>You should to rest</s> → <b>You should rest</b>.</p>"
        ),
        "terms": [
            ["healthy / unhealthy", "здоровый / вредный", "I try to eat healthy food."],
            ["feel", "чувствовать", "I feel tired today."],
            ["headache", "головная боль", "I have a headache."],
            ["rest", "отдыхать", "You should rest more."],
            ["exercise", "упражнения / заниматься", "Regular exercise is important."],
            ["diet", "питание / диета", "A balanced diet helps."],
            ["stress", "стресс", "Work gives me a lot of stress."],
            ["doctor", "врач", "You should see a doctor."],
        ],
        "quiz": [
            ["Choose the correct advice.", ["You should rest more.", "You should to rest more.", "You should resting more."], 0, "“Should” takes the base verb, no “to”."],
            ["Complete: “I ___ tired today.”", ["feel", "feels", "feeling"], 0, "Use “feel” with “I”."],
            ["Choose the correct phrase.", ["I have a headache.", "I have headache.", "I have an headache."], 0, "“Headache” is countable → “a headache”."],
            ["Complete: “You should see a ___.”", ["doctor", "doctors", "the doctor of"], 0, "Use “a doctor”."],
            ["Choose the correct sentence.", ["Regular exercise is important.", "Regular exercise are important.", "Regular exercise important."], 0, "“exercise” (uncountable) → “is”."],
        ],
    },
    "environment": {
        "id": "environment",
        "level": "b",
        "icon": "🌍",
        "title": "Environment",
        "sub": "Discuss environmental problems and solutions.",
        "notes": (
            "<h3>Talking about the environment</h3>"
            "<p>Use <b>pollution</b>, <b>climate change</b>, and <b>renewable energy</b> to discuss the environment. Use <b>should</b> and <b>we need to …</b> to suggest solutions.</p>"
            "<p><b>RU:</b> «pollution» — «загрязнение». «climate change» — «изменение климата». «renewable energy» — «возобновляемая энергия». «we need to…» — «нам нужно…».</p>"
            "<p><b>Common mistake:</b> «pollution» неисчисляемое — не говорите <s>a pollution</s>.</p>"
        ),
        "terms": [
            ["environment", "окружающая среда", "We should protect the environment."],
            ["pollution", "загрязнение", "Air pollution is a big problem."],
            ["climate change", "изменение климата", "Climate change is a global issue."],
            ["renewable energy", "возобновляемая энергия", "Solar is renewable energy."],
            ["recycle", "перерабатывать", "We recycle plastic and paper."],
            ["waste", "отходы", "We need to reduce waste."],
            ["save", "экономить / спасать", "Save water and electricity."],
            ["sustainable", "устойчивый / экологичный", "We want a sustainable future."],
        ],
        "quiz": [
            ["Choose the correct sentence.", ["We should protect the environment.", "We should protecting the environment.", "We should to protect the environment."], 0, "“Should + base verb” with no “to”."],
            ["Complete: “Air ___ is a big problem.”", ["pollution", "pollutions", "a pollution"], 0, "“Pollution” is uncountable → no article, no plural."],
            ["Choose the correct word.", ["We recycle plastic and paper.", "We recycle plastics and papers.", "We recycle a plastic."], 0, "“Plastic” and “paper” as materials are uncountable."],
            ["Complete: “We need to reduce ___.”", ["waste", "wastes", "a waste"], 0, "“Waste” is uncountable here."],
            ["Choose the correct phrase.", ["Solar is renewable energy.", "Solar is renewable energies.", "Solar is a renewable energy."], 0, "“Energy” is uncountable → no article."],
        ],
    },
    "media": {
        "id": "media",
        "level": "b",
        "icon": "📰",
        "title": "News & media",
        "sub": "Follow the news and talk about current events.",
        "notes": (
            "<h3>Following the news</h3>"
            "<p>Use <b>the news</b>, <b>an article</b>, and <b>a report</b> to talk about media. Say <b>I heard that …</b> or <b>Did you see the news?</b> to start a conversation about current events.</p>"
            "<p><b>RU:</b> «the news» — новости (всегда с the). «article» — «статья». «Did you see the news?» — «ты видел новости?».</p>"
            "<p><b>Common mistake:</b> «news» неисчисляемое и всегда с the: <s>a news</s> → <b>the news</b>.</p>"
        ),
        "terms": [
            ["news", "новости", "Did you see the news?"],
            ["article", "статья", "I read an interesting article."],
            ["report", "репортаж / отчёт", "The report is out today."],
            ["headline", "заголовок", "The headline caught my eye."],
            ["source", "источник", "Check the source of the story."],
            ["journalist / reporter", "журналист", "The reporter asked good questions."],
            ["media", "СМИ", "Social media spreads news fast."],
            ["current events", "текущие события", "We talk about current events."],
        ],
        "quiz": [
            ["Choose the correct sentence.", ["Did you see the news?", "Did you see a news?", "Did you see news?"], 0, "“News” always takes “the”."],
            ["Complete: “I read an interesting ___.”", ["article", "articles", "the article of"], 0, "Use “an article”."],
            ["Choose the correct word.", ["Social media spreads news fast.", "Social media spread news fast.", "Social media spreading news fast."], 0, "“media” is singular here → “spreads”."],
            ["Complete: “Check the ___ of the story.”", ["source", "sources", "a source of"], 0, "Use “the source”."],
            ["Choose the correct phrase.", ["The headline caught my eye.", "The headline caught my eyes.", "The headline catch my eye."], 0, "The idiom is “catch someone's eye” (singular)."],
        ],
    },
    "present_perfect": {
        "id": "present_perfect",
        "level": "b",
        "icon": "✅",
        "title": "Present perfect",
        "sub": "Connect past experience to now (have/has + done).",
        "notes": (
            "<h3>Connecting past and present</h3>"
            "<p>Use <b>have/has + past participle</b> for experience or unfinished time: <b>I have visited London</b>, <b>I have worked here for two years</b>. Use <b>yet</b> in questions/negatives, <b>already</b> in positives.</p>"
            "<p><b>RU:</b> Present Perfect — результат/опыт к настоящему: «I have visited» — «я (когда-то) посетил». «for two years» — «в течение двух лет» (продолжается).</p>"
            "<p><b>Common mistake:</b> не путайте с Past Simple: <b>I have visited</b> (опыт, без даты) vs <b>I visited in 2020</b> (есть дата).</p>"
        ),
        "terms": [
            ["have / has + participle", "настоящее совершённое", "I have finished the report."],
            ["I have done", "я сделал (результат есть)", "I have visited London."],
            ["she has done", "она сделала", "She has left the office."],
            ["ever", "когда-либо", "Have you ever been to Paris?"],
            ["never", "никогда", "I have never tried sushi."],
            ["already", "уже", "I have already seen that film."],
            ["yet", "ещё (в вопросах/отрицаниях)", "Have you finished yet?"],
            ["for / since", "в течение / с (момента)", "I have worked here for two years."],
        ],
        "quiz": [
            ["Choose the correct sentence.", ["I have visited London.", "I have visit London.", "I has visited London."], 0, "Use “have + past participle”: “have visited”."],
            ["Choose the correct sentence.", ["She has left the office.", "She have left the office.", "She has leave the office."], 0, "With “she”, use “has + past participle”."],
            ["Complete: “Have you ___ been to Paris?”", ["ever", "yet", "already"], 0, "“Have you ever …?” asks about experience."],
            ["Choose the correct sentence.", ["I have worked here for two years.", "I worked here for two years now.", "I have work here for two years."], 0, "Unfinished time → Present Perfect: “have worked”."],
            ["Complete: “Have you finished ___?”", ["yet", "already", "ever"], 0, "“yet” goes at the end of questions/negatives."],
        ],
    },
    "conditionals": {
        "id": "conditionals",
        "level": "b",
        "icon": "🔀",
        "title": "First & second conditionals",
        "sub": "If + present → will; if + past → would.",
        "notes": (
            "<h3>If this, then that</h3>"
            "<p>First conditional (real future): <b>If it rains, I will stay home.</b> Second conditional (unreal present): <b>If I had more time, I would travel.</b></p>"
            "<p><b>RU:</b> First conditional: «If + Present Simple, will + глагол» — реальное будущее. Second: «If + Past Simple, would + глагол» — нереальное/гипотетическое настоящее.</p>"
            "<p><b>Common mistake:</b> в первой части не ставьте will: <s>If it will rain</s> → <b>If it rains</b>.</p>"
        ),
        "terms": [
            ["first conditional", "реальное условие (if + наст., will)", "If it rains, I will stay home."],
            ["second conditional", "нереальное условие (if + прош., would)", "If I had more time, I would travel."],
            ["if", "если", "If you help me, I will finish faster."],
            ["will", "буду (реальное будущее)", "I will call you later."],
            ["would", "бы (нереальное)", "I would travel more."],
            ["unless", "если не", "I won't go unless you come."],
            ["as long as", "при условии, что", "I'll help as long as it's quick."],
            ["in case", "на случай если", "Take an umbrella in case it rains."],
        ],
        "quiz": [
            ["Choose the correct sentence.", ["If it rains, I will stay home.", "If it will rain, I will stay home.", "If it rains, I would stay home."], 0, "First conditional: “If + present, will”."],
            ["Choose the correct sentence.", ["If I had more time, I would travel.", "If I have more time, I would travel.", "If I had more time, I will travel."], 0, "Second conditional: “If + past, would”."],
            ["Complete: “I ___ call you later.”", ["will", "would", "do"], 0, "Real future → “will”."],
            ["Choose the correct word.", ["I won't go unless you come.", "I won't go unless you will come.", "I won't go unless you came."], 0, "“unless + present”, not “will”."],
            ["Complete: “Take an umbrella in case it ___.”", ["rains", "will rain", "rained"], 0, "“In case + present simple”."],
        ],
    },
    "comparatives": {
        "id": "comparatives",
        "level": "b",
        "icon": "⚖️",
        "title": "Comparatives & superlatives",
        "sub": "Bigger, more expensive, the best.",
        "notes": (
            "<h3>Comparing things</h3>"
            "<p>Use <b>-er</b> for short adjectives: <b>big → bigger</b>. Use <b>more</b> for long ones: <b>more expensive</b>. Superlatives: <b>the biggest, the most expensive</b>.</p>"
            "<p><b>RU:</b> Сравнительная степень: короткие прилагательные +er, длинные — more. Превосходная: the + -est / the most.</p>"
            "<p><b>Common mistake:</b> не удваивайте more: <s>more better</s> → <b>better</b>.</p>"
        ),
        "terms": [
            ["-er (short adjectives)", "сравнительная степень коротких", "big → bigger, cheap → cheaper"],
            ["more (long adjectives)", "сравнительная длинных", "expensive → more expensive"],
            ["the -est", "превосходная коротких", "the biggest, the cheapest"],
            ["the most", "превосходная длинных", "the most expensive"],
            ["better / worse", "лучше / хуже (неправильные)", "This is better than that."],
            ["than", "чем", "My car is faster than yours."],
            ["as ... as", "такой же ... как", "It's as good as the old one."],
            ["less / least", "меньше / наименее", "This option is less risky."],
        ],
        "quiz": [
            ["Choose the correct comparative.", ["This car is faster than mine.", "This car is more fast than mine.", "This car is more faster than mine."], 0, "Short adjective → “faster” (no “more”)."],
            ["Choose the correct comparative.", ["This is more expensive.", "This is expensiver.", "This is more expensiver."], 0, "Long adjective → “more expensive”."],
            ["Choose the correct superlative.", ["the biggest", "the most big", "the more big"], 0, "Short adjective → “the biggest”."],
            ["Choose the correct word.", ["This is better than that.", "This is more good than that.", "This is more better than that."], 0, "“good” is irregular → “better”."],
            ["Complete: “It's as good ___ the old one.”", ["as", "than", "like"], 0, "“As … as” compares equality."],
        ],
    },
    "modals": {
        "id": "modals",
        "level": "b",
        "icon": "🎛️",
        "title": "Modal verbs",
        "sub": "Can, could, should, might, must.",
        "notes": (
            "<h3>Can, could, should, might</h3>"
            "<p>Use <b>can</b> for ability (<b>I can swim</b>), <b>should</b> for advice (<b>You should rest</b>), <b>might</b> for possibility (<b>It might rain</b>), <b>must</b> for obligation (<b>You must wear a seatbelt</b>).</p>"
            "<p><b>RU:</b> «can» — мочь/уметь. «should» — следует (совет). «might» — возможно. «must» — должен (обязательство). После модальных — глагол без to.</p>"
            "<p><b>Common mistake:</b> после модального глагола — основа без to: <s>I can to swim</s> → <b>I can swim</b>.</p>"
        ),
        "terms": [
            ["can", "мочь / уметь", "I can swim."],
            ["could", "мог / вежливая просьба", "Could you help me?"],
            ["should", "следует (совет)", "You should rest more."],
            ["might", "возможно", "It might rain later."],
            ["must", "должен (обязательство)", "You must wear a seatbelt."],
            ["have to", "вынужден (внешняя необходимость)", "I have to work late."],
            ["mustn't", "запрещено", "You mustn't smoke here."],
            ["don't have to", "не обязательно", "You don't have to come."],
        ],
        "quiz": [
            ["Choose the correct sentence.", ["I can swim.", "I can to swim.", "I can swimming."], 0, "After modals, use the base verb, no “to”."],
            ["Choose the correct advice.", ["You should rest more.", "You should to rest more.", "You should resting more."], 0, "“Should + base verb”."],
            ["Choose the correct word.", ["It might rain later.", "It might to rain later.", "It might rains later."], 0, "“Might + base verb”: “might rain”."],
            ["Choose the correct word.", ["You mustn't smoke here.", "You don't have to smoke here.", "You mustn't to smoke here."], 0, "“Mustn't” = prohibited; “don't have to” = not necessary."],
            ["Choose the correct sentence.", ["I have to work late.", "I have work late.", "I have to working late."], 0, "“Have to + base verb”: “have to work”."],
        ],
    },

    # ------------------------------------------------------------- Level C
    "negotiation": {
        "id": "negotiation",
        "level": "c",
        "icon": "🤝",
        "title": "Negotiations",
        "sub": "Propose, compromise, close a deal.",
        "notes": (
            "<h3>Winning a negotiation politely</h3>"
            "<p>Soften proposals with <b>Would you be open to …?</b> or <b>What if we …?</b> To push back, use <b>I see your point, however …</b> To close, <b>Let's agree on …</b></p>"
            "<p><b>RU:</b> «Would you be open to…?» — мягкое предложение. «I see your point, however…» — «понимаю вашу позицию, но…». «Let's agree on…» — «давайте договоримся о…».</p>"
            "<p><b>Common mistake:</b> «What if we + Past Simple?» звучит гипотетически и мягко: «What if we extended the deadline?» — а не «extend».</p>"
        ),
        "terms": [
            ["proposal", "предложение", "Let me make a proposal."],
            ["compromise", "компромисс", "Can we find a compromise?"],
            ["concession", "уступка", "We are ready to make a concession."],
            ["deal", "сделка", "It looks like we have a deal."],
            ["negotiate", "вести переговоры", "We need to negotiate the terms."],
            ["counter-offer", "встречное предложение", "Here is our counter-offer."],
            ["bottom line", "нижняя граница", "What is your bottom line?"],
            ["mutually beneficial", "взаимовыгодный", "We want a mutually beneficial deal."],
        ],
        "quiz": [
            ["Choose the softer proposal.", ["Would you be open to extending the deadline?", "Extend the deadline.", "We extend the deadline."], 0, "“Would you be open to …?” sounds softer and more collaborative."],
            ["Complete: “What if we ___ the deadline?”", ["extended", "extend", "extending"], 0, "“What if + Past Simple” makes a hypothetical, polite proposal."],
            ["Choose the polite way to disagree.", ["I see your point, however, we have a concern.", "You're wrong.", "No way."], 0, "“I see your point, however…” pushes back without being rude."],
            ["Choose the correct phrase.", ["It looks like we have a deal.", "It looks like we have deal.", "It looks like we have the deal."], 0, "“Have a deal” = reach an agreement."],
            ["Complete: “We want a ___ beneficial deal.”", ["mutually", "mutual", "mutuality"], 0, "Use the adverb “mutually” to modify “beneficial”."],
        ],
    },
    "presentation": {
        "id": "presentation",
        "level": "c",
        "icon": "📊",
        "title": "Presentations",
        "sub": "Structure a talk, engage the audience, handle questions.",
        "notes": (
            "<h3>Presenting with confidence</h3>"
            "<p>Structure a talk with signposting: <b>First, … / Next, … / Finally, …</b> To engage the audience, say <b>Let me walk you through …</b> To handle questions, <b>That's a good question — let me get back to you on that.</b></p>"
            "<p><b>RU:</b> Signposting («First… Next… Finally…») помогает аудитории следить. «Let me walk you through…» — «позвольте провести вас по…». Если вопрос трудный, вежливо отложите ответ.</p>"
            "<p><b>Common mistake:</b> «Let me walk you through + существительное» без предлога: «walk you through the data», а не «walk you through on the data».</p>"
        ),
        "terms": [
            ["walk through", "провести по шагам", "Let me walk you through the update."],
            ["highlight", "выделить главное", "Let me highlight the key numbers."],
            ["audience", "аудитория", "Our audience is mostly technical."],
            ["overview", "обзор", "Here's a quick overview."],
            ["key takeaway", "главный вывод", "The key takeaway is simple."],
            ["slide", "слайд", "Let's move to the next slide."],
            ["engage", "вовлекать", "I want to engage the audience."],
            ["Q&A", "вопросы и ответы", "We'll have time for Q&A at the end."],
        ],
        "quiz": [
            ["Choose the correct signposting.", ["First, let's look at the results.", "First, let's look the results.", "First, let's look on the results."], 0, "“Look at” something (with “at”)."],
            ["Complete: “Let me walk you ___ the update.”", ["through", "on", "in"], 0, "“Walk someone through something” — no extra preposition."],
            ["Choose the polite way to defer a question.", ["That's a good question — let me get back to you.", "I don't know.", "Next."], 0, "Defer politely and promise a follow-up."],
            ["Choose the correct phrase.", ["Let me highlight the key numbers.", "Let me highlight on the key numbers.", "Let me highlight to the key numbers."], 0, "“Highlight” takes a direct object, no preposition."],
            ["Complete: “We'll have time for ___ at the end.”", ["Q&A", "the Q&A", "a Q&A"], 0, "“Q&A” is used without an article here."],
        ],
    },
    "debate": {
        "id": "debate",
        "level": "c",
        "icon": "💭",
        "title": "Opinions & debates",
        "sub": "State, support and challenge opinions politely.",
        "notes": (
            "<h3>Expressing and challenging opinions</h3>"
            "<p>State an opinion with <b>In my view, …</b> or <b>From my perspective, …</b>. To challenge politely, <b>I see it differently because …</b> To concede, <b>That's a fair point.</b></p>"
            "<p><b>RU:</b> «In my view…» — «на мой взгляд». «I see it differently because…» — мягкое несогласие с аргументом. «That's a fair point» — «справедливое замечание».</p>"
            "<p><b>Common mistake:</b> после «In my view» не нужен предлог: «In my view, it's too risky», а не «In my view of it».</p>"
        ),
        "terms": [
            ["in my view", "на мой взгляд", "In my view, it's too risky."],
            ["perspective", "точка зрения", "From my perspective, it's worth trying."],
            ["argue", "утверждать / спорить", "I would argue that it's cheaper."],
            ["evidence", "доказательство", "Is there evidence for that?"],
            ["counterargument", "контраргумент", "Here's a counterargument."],
            ["concede", "признать (частично)", "I concede that point."],
            ["bias", "предвзятость", "The data has some bias."],
            ["devil's advocate", "адвокат дьявола", "Let me play devil's advocate."],
        ],
        "quiz": [
            ["Choose the polite way to state an opinion.", ["In my view, it's too risky.", "You are wrong.", "That's stupid."], 0, "“In my view” states an opinion without attacking."],
            ["Complete: “From my ___, it's worth trying.”", ["perspective", "prospective", "perception"], 0, "“From my perspective” = from my point of view."],
            ["Choose the polite disagreement.", ["I see it differently because the data says otherwise.", "No, you're wrong.", "Whatever."], 0, "“I see it differently because…” gives a reason, politely."],
            ["Choose the correct concession.", ["That's a fair point.", "That's a fair point of.", "That's fair point."], 0, "The phrase is “That's a fair point”."],
            ["Complete: “Let me play ___ advocate.”", ["devil's", "devils", "the devil"], 0, "The idiom is “play devil's advocate”."],
        ],
    },
    "idioms": {
        "id": "idioms",
        "level": "c",
        "icon": "🎭",
        "title": "Idioms & nuance",
        "sub": "Sound natural with common idioms and register.",
        "notes": (
            "<h3>Idioms that make you sound natural</h3>"
            "<p>Common work idioms: <b>touch base</b> (quick check-in), <b>on the same page</b> (agree), <b>think outside the box</b> (be creative). Use them sparingly — one per message sounds natural.</p>"
            "<p><b>RU:</b> «touch base» — «списаться/созвониться накоротке». «on the same page» — «одинаково понимаем ситуацию». «think outside the box» — «мыслить нестандартно».</p>"
            "<p><b>Common mistake:</b> не переводите идиомы дословно — «touch base» ≠ «трогать базу».</p>"
        ),
        "terms": [
            ["touch base", "созвониться / списаться накоротке", "Let's touch base next week."],
            ["on the same page", "понимать одинаково", "Let's make sure we're on the same page."],
            ["think outside the box", "мыслить нестандартно", "We need to think outside the box."],
            ["ballpark figure", "примерная цифра", "Can you give me a ballpark figure?"],
            ["in the loop", "в курсе", "Please keep me in the loop."],
            ["cut corners", "срезать углы (экономить на качестве)", "We shouldn't cut corners on quality."],
            ["get the ball rolling", "начать", "Let's get the ball rolling."],
            ["wrap up", "завершить", "Let's wrap up the meeting."],
        ],
        "quiz": [
            ["Choose the correct meaning of “touch base”.", ["A quick check-in or update", "To physically touch something", "A baseball game"], 0, "“Touch base” = make a quick contact / check-in."],
            ["Complete: “Let's make sure we're on the same ___.”", ["page", "paper", "line"], 0, "The idiom is “on the same page”."],
            ["Choose the correct idiom for “be creative”.", ["Think outside the box", "Cut corners", "Touch base"], 0, "“Think outside the box” = be creative."],
            ["Choose the correct meaning of “cut corners”.", ["To save money/time by lowering quality", "To literally cut paper", "To drive fast"], 0, "“Cut corners” = do something cheaply/quickly, often badly."],
            ["Complete: “Let's ___ up the meeting.”", ["wrap", "touch", "ball"], 0, "“Wrap up” = finish / close."],
        ],
    },
    "leadership": {
        "id": "leadership",
        "level": "c",
        "icon": "🧭",
        "title": "Leadership & management",
        "sub": "Delegate, empower and hold people accountable.",
        "notes": (
            "<h3>Leading and managing</h3>"
            "<p>To delegate, use <b>Could you take ownership of …?</b> To empower, <b>I trust your judgement.</b> To hold people accountable, <b>Let's set clear expectations.</b></p>"
            "<p><b>RU:</b> «take ownership of…» — «взять на себя ответственность за…». «I trust your judgement» — «я доверяю вашему суждению». «set expectations» — «определить ожидания».</p>"
            "<p><b>Common mistake:</b> «delegate» требует to: <s>delegate you the task</s> → <b>delegate the task to you</b>.</p>"
        ),
        "terms": [
            ["leadership", "лидерство", "Good leadership builds trust."],
            ["delegate", "делегировать", "Delegate the task to the team."],
            ["take ownership", "взять ответственность", "Could you take ownership of this?"],
            ["empower", "наделять полномочиями", "We want to empower our team."],
            ["accountable", "подотчётный", "Everyone is accountable for results."],
            ["stakeholder", "заинтересованная сторона", "We need to update the stakeholders."],
            ["vision", "видение / стратегия", "The company has a clear vision."],
            ["prioritize", "расставлять приоритеты", "Let's prioritize the urgent tasks."],
        ],
        "quiz": [
            ["Choose the correct sentence.", ["Could you take ownership of this?", "Could you take ownership on this?", "Could you take ownership this?"], 0, "“Take ownership of something”."],
            ["Complete: “Delegate the task ___ the team.”", ["to", "for", "on"], 0, "“Delegate something to someone”."],
            ["Choose the correct word.", ["Everyone is accountable for results.", "Everyone are accountable for results.", "Everyone accountable for results."], 0, "“Everyone” takes a singular verb → “is”."],
            ["Complete: “Let's ___ the urgent tasks.”", ["prioritize", "prioritizing", "to prioritize"], 0, "“Let's + base verb”: “prioritize”."],
            ["Choose the correct phrase.", ["We want to empower our team.", "We want to empower on our team.", "We want empower our team."], 0, "“Want to + base verb”; “empower” takes a direct object."],
        ],
    },
    "business": {
        "id": "business",
        "level": "c",
        "icon": "📈",
        "title": "Economy & business",
        "sub": "Talk about revenue, profit, growth and markets.",
        "notes": (
            "<h3>Business and the economy</h3>"
            "<p>Use <b>revenue</b>, <b>profit</b>, and <b>growth</b> to talk about results. <b>The market is growing</b> means positive change. Use <b>invest in</b> to talk about spending for the future.</p>"
            "<p><b>RU:</b> «revenue» — «выручка». «profit» — «прибыль». «growth» — «рост». «invest in…» — «инвестировать в…».</p>"
            "<p><b>Common mistake:</b> не путайте <b>revenue</b> (доход до вычета расходов) и <b>profit</b> (после вычета).</p>"
        ),
        "terms": [
            ["revenue", "выручка", "Revenue grew by ten percent."],
            ["profit", "прибыль", "The company made a profit."],
            ["growth", "рост", "We expect strong growth next year."],
            ["market", "рынок", "The market is competitive."],
            ["invest", "инвестировать", "We invest in new technology."],
            ["budget", "бюджет", "The project is over budget."],
            ["shareholder", "акционер", "Shareholders want results."],
            ["expand", "расширяться", "The company plans to expand abroad."],
        ],
        "quiz": [
            ["Choose the correct sentence.", ["We invest in new technology.", "We invest on new technology.", "We invest new technology."], 0, "“Invest in something”."],
            ["Complete: “The company made a ___.”", ["profit", "profits", "the profit of"], 0, "Use “a profit”."],
            ["Choose the correct word.", ["The market is competitive.", "The market are competitive.", "The market competitive."], 0, "“market” is singular → “is”."],
            ["Complete: “We expect strong ___ next year.”", ["growth", "grow", "grew"], 0, "Use the noun “growth”."],
            ["Choose the correct phrase.", ["Revenue grew by ten percent.", "Revenue grew with ten percent.", "Revenue grew ten percent of."], 0, "“Grow by + percentage” is the correct pattern."],
        ],
    },
    "register": {
        "id": "register",
        "level": "c",
        "icon": "🎩",
        "title": "Formal vs informal",
        "sub": "Match your tone to the situation and audience.",
        "notes": (
            "<h3>Matching your tone to the situation</h3>"
            "<p>Informal: <b>Can you send it over?</b> Formal: <b>Could you forward it at your earliest convenience?</b> Learn to switch register for emails vs chat.</p>"
            "<p><b>RU:</b> Регистр — степень формальности. «Could you…» вежливее «Can you…». «at your earliest convenience» — «как только будет удобно» (формально).</p>"
            "<p><b>Common mistake:</b> не смешивайте регистры в одном сообщении: <s>Dear sir, give me the file</s> — либо формально, либо неформально.</p>"
        ),
        "terms": [
            ["register", "регистр / стиль речи", "Match your register to the audience."],
            ["formal / informal", "формальный / неформальный", "Use a formal tone in reports."],
            ["Could you …?", "не могли бы вы …?", "Could you send the file over?"],
            ["at your earliest convenience", "как только будет удобно", "Please reply at your earliest convenience."],
            ["polite", "вежливый", "A polite request gets a better reply."],
            ["tone", "тон", "The tone of the email is friendly."],
            ["appropriate", "уместный", "Is that the appropriate level of formality?"],
            ["I would appreciate", "я был бы признателен", "I would appreciate your feedback."],
        ],
        "quiz": [
            ["Choose the more formal request.", ["Could you forward the file at your earliest convenience?", "Send the file now.", "File me the thing."], 0, "“Could you … at your earliest convenience?” is the most formal."],
            ["Complete: “I would ___ your feedback.”", ["appreciate", "appreciated", "appreciating"], 0, "“I would appreciate + noun” (base verb after “would”)."],
            ["Choose the correct word.", ["Use a formal tone in reports.", "Use a formal tone on reports.", "Use a formal tone at reports."], 0, "“In reports” = inside written documents."],
            ["Complete: “Please reply at your earliest ___.”", ["convenience", "convenient", "conveniently"], 0, "Use the noun “convenience”."],
            ["Choose the polite request.", ["Could you send the file over?", "Send the file over.", "You send the file over."], 0, "“Could you …?” is polite."],
        ],
    },
    "society": {
        "id": "society",
        "level": "c",
        "icon": "🏛️",
        "title": "Culture & society",
        "sub": "Discuss social topics with nuance and balance.",
        "notes": (
            "<h3>Discussing society and culture</h3>"
            "<p>Use <b>society</b>, <b>culture</b>, and <b>community</b> to discuss social topics. To generalise carefully, use <b>in general</b> or <b>tend to</b>. To express nuance, use <b>it depends on …</b>.</p>"
            "<p><b>RU:</b> «society» — «общество». «in general» — «в целом». «tend to» — «иметь тенденцию». «It depends on…» — «зависит от…».</p>"
            "<p><b>Common mistake:</b> «society» неисчисляемое в общем смысле — не <s>a society</s>, а <b>society</b>.</p>"
        ),
        "terms": [
            ["society", "общество", "Society is changing fast."],
            ["culture", "культура", "Every country has its own culture."],
            ["community", "сообщество", "The local community is supportive."],
            ["in general", "в целом", "In general, people are friendly."],
            ["tend to", "иметь тенденцию", "People tend to prefer convenience."],
            ["it depends on", "зависит от", "It depends on the context."],
            ["values", "ценности", "Different cultures have different values."],
            ["custom / tradition", "обычай / традиция", "It's a local tradition."],
        ],
        "quiz": [
            ["Choose the correct sentence.", ["Society is changing fast.", "Society are changing fast.", "A society is changing fast."], 0, "“Society” (general sense) is uncountable → “is”, no article."],
            ["Complete: “People tend ___ prefer convenience.”", ["to", "for", "on"], 0, "“Tend to + verb”."],
            ["Choose the correct word.", ["The local community is supportive.", "The local community are supportive.", "The local community supportive."], 0, "“community” is singular → “is”."],
            ["Complete: “It depends ___ the context.”", ["on", "of", "at"], 0, "“Depend on something”."],
            ["Choose the correct phrase.", ["In general, people are friendly.", "In general, people is friendly.", "In the general, people are friendly."], 0, "“In general” (no article); “people” → “are”."],
        ],
    },
    "mixed_conditionals": {
        "id": "mixed_conditionals",
        "level": "c",
        "icon": "🔁",
        "title": "Third & mixed conditionals",
        "sub": "Regret and hypothetical past (had + would have).",
        "notes": (
            "<h3>Regret and hypothetical past</h3>"
            "<p>Third conditional (unreal past): <b>If I had known, I would have called.</b> Mixed conditional (past → present): <b>If I had studied, I would be rich now.</b></p>"
            "<p><b>RU:</b> Third conditional: «If + Past Perfect, would have + глагол» — о прошлом, которое не изменить. Mixed: прошлое условие → настоящее следствие.</p>"
            "<p><b>Common mistake:</b> не путайте: <s>If I would have known</s> → <b>If I had known</b>.</p>"
        ),
        "terms": [
            ["third conditional", "нереальное прошлое (if + had done, would have)", "If I had known, I would have called."],
            ["mixed conditional", "прошлое → настоящее", "If I had studied, I would be rich."],
            ["would have", "сделал бы (в прошлом)", "I would have helped you."],
            ["could have", "мог бы (в прошлом)", "You could have called me."],
            ["should have", "следовало бы (упрек)", "You should have told me."],
            ["if I had known", "если бы я знал", "If I had known, I would have come."],
            ["if only", "если бы только", "If only I had listened."],
            ["wish + past perfect", "жаль, что не (в прошлом)", "I wish I had saved more."],
        ],
        "quiz": [
            ["Choose the correct sentence.", ["If I had known, I would have called.", "If I would have known, I would have called.", "If I had knew, I would have called."], 0, "Third conditional: “If + had done, would have done”."],
            ["Choose the correct sentence.", ["You should have told me.", "You should told me.", "You should have tell me."], 0, "“Should have + past participle”: “should have told”."],
            ["Complete: “I wish I ___ saved more.”", ["had", "have", "would"], 0, "“Wish + past perfect” for past regrets: “had saved”."],
            ["Choose the correct phrase.", ["If only I had listened.", "If only I would listened.", "If only I have listened."], 0, "“If only + past perfect” for past regret."],
            ["Choose the correct sentence.", ["You could have called me.", "You could have call me.", "You could called me."], 0, "“Could have + past participle”: “could have called”."],
        ],
    },
    "reported_speech": {
        "id": "reported_speech",
        "level": "c",
        "icon": "🗣️",
        "title": "Reported speech",
        "sub": "Say what someone else said.",
        "notes": (
            "<h3>Reporting what someone said</h3>"
            "<p>Move tenses back: <b>“I am tired” → He said he was tired.</b> Questions: <b>“Where do you live?” → She asked where I lived.</b> Commands: <b>“Close the door” → He told me to close the door.</b></p>"
            "<p><b>RU:</b> Косвенная речь — сдвиг времён назад (is→was, will→would). В косвенном вопросе порядок слов обычный: «where I lived», а не «where did I live».</p>"
            "<p><b>Common mistake:</b> в косвенном вопросе не используйте вспомогательный глагол did: <s>She asked where did I live</s> → <b>where I lived</b>.</p>"
        ),
        "terms": [
            ["he said (that)", "он сказал, что", "He said he was tired."],
            ["she asked", "она спросила", "She asked where I lived."],
            ["he told me to", "он велел мне", "He told me to close the door."],
            ["say / tell", "сказать / сказать (кому-то)", "She told me the news."],
            ["backshift", "сдвиг времён назад", "is → was, will → would"],
            ["he wondered", "он поинтересовался", "He wondered if I was free."],
            ["she denied / admitted", "она отрицала / признала", "She admitted she was wrong."],
            ["report a question", "передать вопрос", "She asked if I was free."],
        ],
        "quiz": [
            ["Choose the correct reported speech.", ["He said he was tired.", "He said he is tired.", "He said that he is tired."], 0, "Backshift: “I am” → “he was”."],
            ["Choose the correct reported question.", ["She asked where I lived.", "She asked where did I live.", "She asked where I live."], 0, "Reported question: normal word order, no “did”."],
            ["Choose the correct command.", ["He told me to close the door.", "He told me close the door.", "He told me to closing the door."], 0, "“Tell someone to + base verb”."],
            ["Choose the correct word.", ["She admitted she was wrong.", "She admitted that she is wrong.", "She admitted she wrong."], 0, "“Admit (that) + clause”; backshift “is → was”."],
            ["Choose the correct sentence.", ["She asked if I was free.", "She asked if was I free.", "She asked if I am free."], 0, "Reported “yes/no” question: “if + normal order”."],
        ],
    },
    "passive": {
        "id": "passive",
        "level": "c",
        "icon": "🔄",
        "title": "Passive voice",
        "sub": "When the action matters more than the doer.",
        "notes": (
            "<h3>When the action matters more than the doer</h3>"
            "<p>Use the passive <b>be + past participle</b> when the doer is unknown or unimportant: <b>The report was written yesterday.</b> Add <b>by</b> to name the doer: <b>written by the team</b>.</p>"
            "<p><b>RU:</b> Пассивный залог: «be + третья форма глагола». Фокус на действии, а не на том, кто сделал. «by» указывает исполнителя.</p>"
            "<p><b>Common mistake:</b> сохраняйте форму be в нужном времени: <s>The report is wrote</s> → <b>The report is written</b>.</p>"
        ),
        "terms": [
            ["be + past participle", "пассивный залог", "The report was written."],
            ["is / are + participle", "настоящий пассив", "These products are made here."],
            ["was / were + participle", "прошедший пассив", "The email was sent yesterday."],
            ["has been + participle", "совершённый пассив", "The work has been finished."],
            ["will be + participle", "будущий пассив", "The results will be published."],
            ["by + doer", "исполнитель (by)", "The app was built by our team."],
            ["get + participle", "разговорный пассив", "The phone got damaged."],
            ["it is said that", "говорят, что (пассивный оборот)", "It is said that prices will rise."],
        ],
        "quiz": [
            ["Choose the correct passive.", ["The report was written yesterday.", "The report wrote yesterday.", "The report was wrote yesterday."], 0, "Passive: “was + past participle”: “was written”."],
            ["Choose the correct passive.", ["These products are made here.", "These products are make here.", "These products made here."], 0, "“Are + past participle”: “are made”."],
            ["Choose the correct sentence.", ["The app was built by our team.", "The app was build by our team.", "The app built by our team."], 0, "“Was built by …” — past participle “built”."],
            ["Choose the correct passive.", ["The work has been finished.", "The work has been finish.", "The work has finished."], 0, "Present perfect passive: “has been finished”."],
            ["Choose the correct sentence.", ["The results will be published.", "The results will published.", "The results will be publish."], 0, "Future passive: “will be published”."],
        ],
    },
    "inversion": {
        "id": "inversion",
        "level": "c",
        "icon": "🔝",
        "title": "Inversion & emphasis",
        "sub": "Never have I … — adding force with word order.",
        "notes": (
            "<h3>Adding emphasis with inversion</h3>"
            "<p>Invert subject and verb after negative adverbials: <b>Never have I seen such a thing.</b> Or after <b>Not only … but also</b>: <b>Not only was it cheap, but it was also good.</b></p>"
            "<p><b>RU:</b> Инверсия — перестановка подлежащего и глагола после отрицательных наречий (never, rarely, not only) для усиления.</p>"
            "<p><b>Common mistake:</b> инверсия требует вспомогательный глагол: <s>Never I have seen</s> → <b>Never have I seen</b>.</p>"
        ),
        "terms": [
            ["never have I", "никогда я не (инверсия)", "Never have I seen such a thing."],
            ["not only ... but also", "не только ... но и", "Not only was it cheap, it was also good."],
            ["rarely / seldom", "редко (инверсия)", "Rarely do we see such talent."],
            ["hardly ... when", "едва ... как", "Hardly had I left when it started."],
            ["no sooner ... than", "не успел ... как", "No sooner had we arrived than it began."],
            ["little did I know", "мало ли я знал", "Little did I know what was coming."],
            ["only then / only after", "только тогда / только после", "Only then did I understand."],
            ["so + adjective ... that", "настолько ... что", "So good was the film that I watched it twice."],
        ],
        "quiz": [
            ["Choose the correct inversion.", ["Never have I seen such a thing.", "Never I have seen such a thing.", "Never I seen such a thing."], 0, "After “never”, invert: “have I seen”."],
            ["Choose the correct sentence.", ["Not only was it cheap, it was also good.", "Not only it was cheap, it was also good.", "Not only was cheap, it was also good."], 0, "“Not only” → inversion: “was it cheap”."],
            ["Complete: “Rarely ___ we see such talent.”", ["do", "are", "have"], 0, "Inversion with “do” for present simple: “do we see”."],
            ["Choose the correct sentence.", ["Only then did I understand.", "Only then I did understand.", "Only then I understood."], 0, "After “only then”, invert: “did I understand”."],
            ["Choose the correct inversion.", ["Hardly had I left when it started.", "Hardly I had left when it started.", "Hardly had left I when it started."], 0, "“Hardly had + subject”: “Hardly had I left”."],
        ],
    },
}


# ---------------------------------------------------------------------------
# Справочные хелперы (без БД) — для engine и тестов.
# ---------------------------------------------------------------------------

def level_by_id(level_id: str) -> dict | None:
    """Уровень по id (a/b/c), иначе None."""
    for lvl in LEVELS:
        if lvl["id"] == level_id:
            return lvl
    return None


def theme_by_id(theme_id: str) -> dict | None:
    """Тема по id, иначе None."""
    return THEMES.get(theme_id)


def themes_for_level(level_id: str) -> list[dict]:
    """Список тем уровня в порядке, заданном в LEVELS[].themes."""
    lvl = level_by_id(level_id)
    if lvl is None:
        return []
    return [THEMES[tid] for tid in lvl["themes"] if tid in THEMES]
