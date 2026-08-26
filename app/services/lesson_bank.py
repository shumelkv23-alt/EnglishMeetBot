"""Банк готовых «занятие-карточек» — fallback для LLM (REQ-10).

По формату лежит список готовых планов. Когда LLM недоступен (нет ключа или
сбой), вызывающий код берёт отсюда первый неиспользованный план. Каждый план —
словарь той же структуры, что возвращает llm_lesson (content для LessonSession).
"""
from app.services.llm_lesson import ALL_FORMATS

_DEFAULT_LEVEL = "B1"

# Полный план занятия. Ключи соответствуют JSON-схеме llm_lesson.
LESSONS: dict[str, list[dict]] = {
    "discussion": [
        {
            "topic": "Habits",
            "level": _DEFAULT_LEVEL,
            "warmup": "What's the first thing you do after waking up?",
            "words": ["routine", "break a habit", "procrastinate", "willpower", "trigger", "stick to"],
            "main_instruction": "Take turns answering, then ask a follow-up question of your own.",
            "main_items": [
                "What habit would you like to build?",
                "What habit have you tried to break?",
                "Why is it so hard to change a small habit?",
                "What habit do you admire in other people?",
            ],
            "phrases": ["That reminds me of…", "How about you?", "I used to… but now…"],
            "follow_ups": ["Why?", "Can you give an example?", "How does that make you feel?"],
            "wrapup": "One habit you'll try to change this week?",
        },
        {
            "topic": "Travel",
            "level": _DEFAULT_LEVEL,
            "warmup": "Do you prefer mountains or the sea?",
            "words": ["destination", "pack light", "get away", "jet lag", "off the beaten path", "a must-see"],
            "main_instruction": "Take turns answering, then ask a follow-up question of your own.",
            "main_items": [
                "What's the best trip you've ever taken?",
                "What place would you never go back to?",
                "What's your ideal way to travel — alone or with others?",
                "Where would you go if money were no object?",
            ],
            "phrases": ["I'd love to…", "It was worth it because…", "The best part was…"],
            "follow_ups": ["What happened next?", "Would you do it again?", "What did you learn?"],
            "wrapup": "One place you'd like to visit next?",
        },
        {
            "topic": "Food",
            "level": _DEFAULT_LEVEL,
            "warmup": "Do you cook more, or eat out more?",
            "words": ["home-cooked", "takeaway", "cuisine", "spicy", "comfort food", "ingredients"],
            "main_instruction": "Take turns answering, then ask a follow-up question of your own.",
            "main_items": [
                "What dish reminds you of home?",
                "What food can you not stand?",
                "What's the best thing you've ever eaten?",
                "What would you cook for a guest?",
            ],
            "phrases": ["It tastes like…", "I can't get enough of…", "It's an acquired taste."],
            "follow_ups": ["Why?", "How is it made?", "Would you eat it again?"],
            "wrapup": "One new dish you'd like to try?",
        },
    ],
    "debate": [
        {
            "topic": "Remote work",
            "level": _DEFAULT_LEVEL,
            "warmup": "Do you like working from home?",
            "words": ["productivity", "work-life balance", "commute", "distraction", "flexible", "burnout"],
            "main_instruction": "Split into For / Against and defend your side with reasons and examples.",
            "main_items": [
                "Statement: Working from home is better than the office.",
                "What about people who live alone?",
                "Does it work for every job?",
                "What happens to team spirit?",
            ],
            "phrases": ["I agree because…", "I see your point, but…", "In my opinion…", "On the other hand…"],
            "follow_ups": ["Why do you think so?", "Can you give an example?", "What would you do?"],
            "wrapup": "One change you'd make to your work setup?",
        },
        {
            "topic": "Social media",
            "level": _DEFAULT_LEVEL,
            "warmup": "How much time do you spend on your phone each day?",
            "words": ["scrolling", "influencer", "privacy", "addictive", "filter", "go viral"],
            "main_instruction": "Split into For / Against and defend your side with reasons and examples.",
            "main_items": [
                "Statement: Social media does more harm than good.",
                "Does it connect people or isolate them?",
                "Should there be an age limit?",
                "Is it possible to quit completely?",
            ],
            "phrases": ["That's a fair point, but…", "I'd argue that…", "From my experience…", "It depends on…"],
            "follow_ups": ["Can you explain that?", "What's an example?", "Who does this affect most?"],
            "wrapup": "One thing you'd change about social media?",
        },
        {
            "topic": "Cars in the city",
            "level": _DEFAULT_LEVEL,
            "warmup": "How do you usually get to work?",
            "words": ["traffic", "congestion", "public transport", "pedestrian", "parking", "emissions"],
            "main_instruction": "Split into For / Against and defend your side with reasons and examples.",
            "main_items": [
                "Statement: Private cars should be banned from city centres.",
                "What about people who need a car for work?",
                "Would it hurt small businesses?",
                "How would cities change?",
            ],
            "phrases": ["That's a strong point, but…", "We should consider…", "It would mean that…", "The evidence shows…"],
            "follow_ups": ["Why is that a problem?", "What's the alternative?", "Who would benefit?"],
            "wrapup": "One change you'd make to your city's transport?",
        },
    ],
    "four_hats": [
        {
            "topic": "Four-day work week",
            "level": _DEFAULT_LEVEL,
            "warmup": "What would you do with one extra free day?",
            "words": ["shorter week", "efficiency", "burnout", "workload", "deadline", "morale"],
            "main_instruction": "Argue the same question from all four hats — try to think like each one.",
            "main_items": [
                "Question: Should every company switch to a four-day work week?",
                "Optimist: focus on the benefits.",
                "Skeptic: find the risks and problems.",
                "Emotional: how would people actually feel?",
                "Practical: how would it work day to day?",
            ],
            "phrases": ["From the optimistic side…", "The risk here is…", "People would feel…", "In practice…"],
            "follow_ups": ["Why might that happen?", "What would you need?", "Is that realistic?"],
            "wrapup": "Which hat was the most convincing?",
        },
        {
            "topic": "Cashless society",
            "level": _DEFAULT_LEVEL,
            "warmup": "Do you usually pay with cash or a card?",
            "words": ["cashless", "contactless", "privacy", "convenience", "digital wallet", "the elderly"],
            "main_instruction": "Argue the same question from all four hats — try to think like each one.",
            "main_items": [
                "Question: Should cash be removed completely?",
                "Optimist: focus on the benefits.",
                "Skeptic: find the risks and problems.",
                "Emotional: how would people feel?",
                "Practical: how would it work for everyone?",
            ],
            "phrases": ["The upside is…", "A serious downside is…", "Older people might…", "Realistically…"],
            "follow_ups": ["Who would be affected?", "Can you give an example?", "Is that fair?"],
            "wrapup": "Which hat changed your mind the most?",
        },
        {
            "topic": "AI at work",
            "level": _DEFAULT_LEVEL,
            "warmup": "Do you use AI in your job?",
            "words": ["automate", "accuracy", "bias", "upskill", "efficiency", "job security"],
            "main_instruction": "Argue the same question from all four hats — try to think like each one.",
            "main_items": [
                "Question: Should companies use AI to do more of the work?",
                "Optimist: focus on the benefits.",
                "Skeptic: find the risks and problems.",
                "Emotional: how would employees feel?",
                "Practical: how would it actually work?",
            ],
            "phrases": ["On the bright side…", "The danger is…", "Workers might feel…", "In reality…"],
            "follow_ups": ["Why might that happen?", "Who would be affected?", "Is that worth the risk?"],
            "wrapup": "Which hat was hardest to argue?",
        },
    ],
    "roleplay": [
        {
            "topic": "At the restaurant",
            "level": _DEFAULT_LEVEL,
            "warmup": "What's your favourite place to eat out?",
            "words": ["complain", "apologize", "replace", "refund", "make it right", "the manager"],
            "main_instruction": "Pick a role and improvise the scene together.",
            "main_items": [
                "Situation: You ordered a dish but it came cold.",
                "Role 1 — Customer: complain politely and ask for a replacement.",
                "Role 2 — Waiter: apologize and offer a solution.",
                "Role 3 — Manager: make sure the customer leaves happy.",
            ],
            "phrases": ["I'm sorry to say, but…", "That's not acceptable.", "Let me fix this for you.", "Would that be okay?"],
            "follow_ups": ["What did you say exactly?", "How did the other side react?", "What's a better way?"],
            "wrapup": "What's the hardest customer situation to handle?",
        },
        {
            "topic": "Job interview",
            "level": _DEFAULT_LEVEL,
            "warmup": "What was your first job?",
            "words": ["strength", "weakness", "experience", "salary expectations", "why us", "team player"],
            "main_instruction": "Pick a role and improvise the scene together.",
            "main_items": [
                "Situation: An interview for a job you really want.",
                "Role 1 — Candidate: sell yourself confidently.",
                "Role 2 — Interviewer: ask the tough questions.",
                "Role 3 — Colleague: jump in with an unexpected question.",
            ],
            "phrases": ["One of my strengths is…", "In my previous role…", "I'm looking for…", "Can you tell me more?"],
            "follow_ups": ["What would you answer?", "Was that a good question?", "What would the perfect candidate say?"],
            "wrapup": "One question you'd hate to be asked in an interview?",
        },
        {
            "topic": "Returning a purchase",
            "level": _DEFAULT_LEVEL,
            "warmup": "Have you ever returned something to a shop?",
            "words": ["refund", "exchange", "receipt", "warranty", "faulty", "store credit"],
            "main_instruction": "Pick a role and improvise the scene together.",
            "main_items": [
                "Situation: You bought shoes but they fell apart after a week.",
                "Role 1 — Customer: ask for a refund or exchange.",
                "Role 2 — Cashier: follow the store policy, but be helpful.",
                "Role 3 — Manager: decide what's fair.",
            ],
            "phrases": ["I'd like to return this…", "It stopped working after…", "Our policy says…", "Let me check what I can do."],
            "follow_ups": ["What would you say next?", "Was that fair?", "What if they say no?"],
            "wrapup": "What's the worst customer experience you've had?",
        },
    ],
    "ranking": [
        {
            "topic": "Work perks",
            "level": _DEFAULT_LEVEL,
            "warmup": "What perk does your current job have?",
            "words": ["perk", "vacation days", "flexible hours", "raise", "benefits", "a bonus"],
            "main_instruction": "Rank them from best to worst and explain your choice.",
            "main_items": [
                "Rank these from best to worst: extra vacation days, a higher salary, flexible hours, a gym membership, free lunches.",
            ],
            "phrases": ["For me, … comes first because…", "I'd put … last since…", "It depends on…", "I'd rather have…"],
            "follow_ups": ["Why that order?", "Would everyone agree?", "What would you add to the list?"],
            "wrapup": "Which perk would make you change jobs?",
        },
        {
            "topic": "Apps you can't live without",
            "level": _DEFAULT_LEVEL,
            "warmup": "What's the first app you open in the morning?",
            "words": ["essential", "waste of time", "notifications", "productivity", "scroll", "addictive"],
            "main_instruction": "Rank them from best to worst and explain your choice.",
            "main_items": [
                "Rank these by importance: maps, a messenger, a music app, a food delivery app, a to-do list.",
            ],
            "phrases": ["I couldn't live without…", "I could easily drop…", "The most useful is…", "To be honest…"],
            "follow_ups": ["Why is that one first?", "Which one would you delete?", "What's missing from the list?"],
            "wrapup": "One app you'd invent if you could?",
        },
        {
            "topic": "Superpowers",
            "level": _DEFAULT_LEVEL,
            "warmup": "Which superhero do you like most?",
            "words": ["invisibility", "fly", "read minds", "time travel", "strength", "healing"],
            "main_instruction": "Rank them from best to worst and explain your choice.",
            "main_items": [
                "Rank these superpowers: invisibility, flying, reading minds, time travel, super strength.",
            ],
            "phrases": ["I'd choose … because…", "… sounds useless to me.", "The downside of … is…", "If I could…, I would…"],
            "follow_ups": ["Why that one?", "What would you use it for?", "Which is the most dangerous?"],
            "wrapup": "One superpower you'd give up, and why?",
        },
    ],
    "would_you_rather": [
        {
            "topic": "Impossible choices",
            "level": _DEFAULT_LEVEL,
            "warmup": "Do you make decisions quickly or slowly?",
            "words": ["rather", "give up", "choose", "trade-off", "forever", "would you rather"],
            "main_instruction": "Take turns answering and explaining your choice.",
            "main_items": [
                "Would you rather be rich but lonely, or poor but surrounded by friends?",
                "Would you rather always be 10 minutes early or 10 minutes late?",
                "Would you rather never use the internet again, or never travel again?",
                "Would you rather have a job you love that pays little, or a boring job that pays well?",
                "Would you rather live in the mountains or by the sea?",
            ],
            "phrases": ["I'd rather … because…", "Definitely …", "It depends, but…", "No contest — …"],
            "follow_ups": ["Why that one?", "Would your family agree?", "What's the catch?"],
            "wrapup": "One 'would you rather' you'd ask the group?",
        },
        {
            "topic": "Everyday picks",
            "level": _DEFAULT_LEVEL,
            "warmup": "Coffee or tea?",
            "words": ["would you rather", "prefer", "go for", "it's a no-brainer", "tough call", "either way"],
            "main_instruction": "Take turns answering and explaining your choice.",
            "main_items": [
                "Would you rather eat the same meal every day or never eat the same thing twice?",
                "Would you rather speak every language or play every instrument?",
                "Would you rather lose your phone or your keys?",
                "Would you rather always take the stairs or never walk again?",
                "Would you rather watch a movie or read the book?",
            ],
            "phrases": ["I'd go with …", "Easy — …", "That's a tough call, but…", "Honestly, neither!"],
            "follow_ups": ["Why not the other?", "What would change your answer?", "How about you?"],
            "wrapup": "One everyday choice you always struggle with?",
        },
        {
            "topic": "Future you",
            "level": _DEFAULT_LEVEL,
            "warmup": "Do you like thinking about the future?",
            "words": ["in the future", "imagine", "give up", "trade", "settle down", "look back"],
            "main_instruction": "Take turns answering and explaining your choice.",
            "main_items": [
                "Would you rather live 100 years in the past or 100 years in the future?",
                "Would you rather know the date you'll die, or the cause?",
                "Would you rather have more time or more money?",
                "Would you rather stay young forever or be wise instantly?",
                "Would you rather visit the future or fix the past?",
            ],
            "phrases": ["I'd pick … because…", "The past would be…", "Imagine …", "That would terrify me."],
            "follow_ups": ["What would you do there?", "Why is that better?", "What's the downside?"],
            "wrapup": "One thing you hope hasn't changed in 100 years?",
        },
    ],
    "story": [
        {
            "topic": "Firsts",
            "level": _DEFAULT_LEVEL,
            "warmup": "Can you remember your first day at school?",
            "words": ["for the first time", "nervous", "turn out", "embarrassing", "proud", "unforgettable"],
            "main_instruction": "Tell a short personal story starting from one of the starters.",
            "main_items": [
                "A time you did something for the first time.",
                "A first day that went completely wrong.",
                "The first friend you ever made.",
            ],
            "phrases": ["It all started when…", "I had no idea that…", "Looking back…", "And then…"],
            "follow_ups": ["What happened next?", "How did you feel?", "Would you do it again?"],
            "wrapup": "One 'first' you're still waiting for?",
        },
        {
            "topic": "Luck",
            "level": _DEFAULT_LEVEL,
            "warmup": "Do you consider yourself a lucky person?",
            "words": ["lucky", "a coincidence", "by chance", "turn out well", "close call", "fate"],
            "main_instruction": "Tell a short personal story starting from one of the starters.",
            "main_items": [
                "The luckiest thing that ever happened to you.",
                "A time a small accident led to something good.",
                "A moment you were extremely unlucky.",
            ],
            "phrases": ["Out of nowhere…", "It just so happened that…", "Luckily, …", "It was pure chance…"],
            "follow_ups": ["Then what?", "Was it luck or skill?", "How did it change things?"],
            "wrapup": "One thing you feel lucky about right now?",
        },
        {
            "topic": "Embarrassing moments",
            "level": _DEFAULT_LEVEL,
            "warmup": "Are you easily embarrassed?",
            "words": ["embarrassed", "blush", "awkward", "laugh it off", "make a fool of myself", "wish the floor would swallow me"],
            "main_instruction": "Tell a short personal story starting from one of the starters.",
            "main_items": [
                "The most embarrassing thing that ever happened to you.",
                "A time you said the wrong thing.",
                "A moment you wanted to disappear.",
            ],
            "phrases": ["I wanted to disappear when…", "Everyone just stared…", "To my horror…", "Luckily, …"],
            "follow_ups": ["What happened next?", "How did people react?", "Can you laugh about it now?"],
            "wrapup": "One embarrassing moment that's funny in hindsight?",
        },
    ],
    "taboo": [
        {
            "topic": "Things around you",
            "level": _DEFAULT_LEVEL,
            "warmup": "How would you describe your phone to an alien?",
            "words": ["object", "you use it to…", "made of…", "it looks like…", "it's a thing that…", "portable"],
            "main_instruction": "One person describes the word, others guess — don't say the forbidden words.",
            "main_items": [
                "Describe 'umbrella' without saying: rain, open, wet.",
                "Describe 'refrigerator' without saying: cold, food, kitchen.",
                "Describe 'toothbrush' without saying: teeth, clean, bathroom.",
                "Describe 'key' without saying: door, lock, open.",
                "Describe 'candle' without saying: fire, light, wax.",
            ],
            "phrases": ["It's a thing that…", "You use it to…", "It's made of…", "It's bigger than…"],
            "follow_ups": ["What was the hardest word?", "How would you describe it?", "Try a harder one."],
            "wrapup": "One object that's hard to describe?",
        },
        {
            "topic": "Jobs",
            "level": _DEFAULT_LEVEL,
            "warmup": "What did you want to be when you were a child?",
            "words": ["profession", "he/she works with…", "you need to…", "salary", "uniform", "colleague"],
            "main_instruction": "One person describes the word, others guess — don't say the forbidden words.",
            "main_items": [
                "Describe 'doctor' without saying: hospital, patient, medicine.",
                "Describe 'teacher' without saying: school, student, lesson.",
                "Describe 'firefighter' without saying: fire, water, rescue.",
                "Describe 'chef' without saying: cook, kitchen, food.",
                "Describe 'pilot' without saying: plane, fly, airport.",
            ],
            "phrases": ["This person works in…", "Their job is to…", "They wear…", "They help people who…"],
            "follow_ups": ["How did you guess?", "Would you do that job?", "What's a related word?"],
            "wrapup": "One job you'd never do?",
        },
        {
            "topic": "Places",
            "level": _DEFAULT_LEVEL,
            "warmup": "City or countryside?",
            "words": ["somewhere you…", "you go there to…", "it's crowded with…", "a place where…", "located in…", "open-air"],
            "main_instruction": "One person describes the word, others guess — don't say the forbidden words.",
            "main_items": [
                "Describe 'beach' without saying: sand, sea, sun.",
                "Describe 'library' without saying: book, read, quiet.",
                "Describe 'gym' without saying: exercise, weights, fit.",
                "Describe 'airport' without saying: plane, luggage, fly.",
                "Describe 'cinema' without saying: film, screen, ticket.",
            ],
            "phrases": ["It's a place where…", "People go there to…", "You'll see… there.", "It's usually…"],
            "follow_ups": ["What gave it away?", "Would you go there now?", "Describe a different one."],
            "wrapup": "One place that's hard to describe in English?",
        },
    ],
    "dilemma": [
        {
            "topic": "The wallet",
            "level": _DEFAULT_LEVEL,
            "warmup": "Have you ever lost something valuable?",
            "words": ["find", "keep", "hand in", "conscience", "reward", "do the right thing"],
            "main_instruction": "Discuss the dilemma and defend your choice.",
            "main_items": [
                "Scenario: You find a wallet with a lot of money and no ID.",
                "What would you do?",
                "Would your answer change if you were broke?",
                "What if it belonged to a child?",
            ],
            "phrases": ["I would probably…", "The right thing is…", "It would be tempting to…", "I'd feel guilty if…"],
            "follow_ups": ["Why would you do that?", "Is that always right?", "What would others think?"],
            "wrapup": "One rule you always follow, no matter what?",
        },
        {
            "topic": "The confession",
            "level": _DEFAULT_LEVEL,
            "warmup": "Do you think honesty is always the best policy?",
            "words": ["confess", "lie", "keep a secret", "hurt feelings", "consequences", "come clean"],
            "main_instruction": "Discuss the dilemma and defend your choice.",
            "main_items": [
                "Scenario: A friend asks if you like their new haircut — you don't.",
                "Do you tell the truth?",
                "What if it's about something more serious?",
                "Is a kind lie better than a painful truth?",
            ],
            "phrases": ["Honestly, …", "I'd rather…", "It depends on…", "A white lie is…"],
            "follow_ups": ["Why is that better?", "How would they feel?", "Where's the line?"],
            "wrapup": "One truth you wish people would tell you more?",
        },
        {
            "topic": "The promotion",
            "level": _DEFAULT_LEVEL,
            "warmup": "Do you prefer a safe job or an exciting risk?",
            "words": ["promotion", "risk", "comfort zone", "ambition", "stability", "regret"],
            "main_instruction": "Discuss the dilemma and defend your choice.",
            "main_items": [
                "Scenario: You're offered a big promotion, but it means moving to another city far from family.",
                "Do you take it?",
                "What if the salary is double?",
                "What if you'd have to work 60 hours a week?",
            ],
            "phrases": ["I'd probably take it because…", "It's not worth it if…", "Family comes first for me.", "It depends on…"],
            "follow_ups": ["Why is that your choice?", "What would make you change your mind?", "Would you regret it?"],
            "wrapup": "One big decision you're glad you made?",
        },
    ],
    "speed_dating": [
        {
            "topic": "Quick chats",
            "level": _DEFAULT_LEVEL,
            "warmup": "Do you like meeting new people?",
            "words": ["small talk", "switch partners", "a round", "keep it short", "introduce yourself", "a topic"],
            "main_instruction": "Talk 3 minutes per round, then switch partners.",
            "main_items": [
                "Talk about your dream vacation.",
                "The best advice you ever got.",
                "A skill you want to learn.",
                "Your favourite way to spend a Sunday.",
                "Something that always makes you laugh.",
            ],
            "phrases": ["By the way, …", "What about you?", "That's interesting because…", "Can I ask…?"],
            "follow_ups": ["Tell me more.", "Why is that?", "How did you get into it?"],
            "wrapup": "Which partner surprised you the most?",
        },
        {
            "topic": "Two truths",
            "level": _DEFAULT_LEVEL,
            "warmup": "What's something most people don't know about you?",
            "words": ["actually", "surprise", "guess", "get to know", "a fun fact", "not many people know"],
            "main_instruction": "Talk 3 minutes per round, then switch partners.",
            "main_items": [
                "Tell two truths and one lie about yourself.",
                "Talk about a food you hated as a child.",
                "A place you'd move to tomorrow.",
                "Something you're secretly good at.",
                "The last thing that made you really happy.",
            ],
            "phrases": ["Fun fact: …", "Believe it or not, …", "You'd never guess that…", "That's so you!"],
            "follow_ups": ["Wait, really?", "Which one is the lie?", "How did that happen?"],
            "wrapup": "One thing you learned about someone today?",
        },
        {
            "topic": "Food & fun",
            "level": _DEFAULT_LEVEL,
            "warmup": "Sweet or savoury?",
            "words": ["favourite", "treat", "hang out", "a good time", "laugh", "relax"],
            "main_instruction": "Talk 3 minutes per round, then switch partners.",
            "main_items": [
                "Describe your perfect meal.",
                "A fun tradition from your family.",
                "The best party you've been to.",
                "A food you could eat every day.",
                "What makes you laugh out loud?",
            ],
            "phrases": ["My guilty pleasure is…", "That reminds me of…", "I'm a big fan of…", "No way, me too!"],
            "follow_ups": ["Tell me more.", "When was that?", "What's the recipe?"],
            "wrapup": "One fun thing you're looking forward to?",
        },
    ],
}


def bank_lesson(format: str, exclude_topics: set[str] | None = None, offset: int = 0) -> dict | None:
    """Первый неиспользованный план заданного формата; None — нет банка для формата.

    `exclude` — уже использованные темы (их пропускаем). `offset` сдвигает старт
    по списку, чтобы не всегда брать первый план формата.
    """
    exclude = exclude_topics or set()
    lessons = LESSONS.get(format) or []
    if not lessons:
        return None
    n = len(lessons)
    for i in range(n):
        lesson = lessons[(i + offset) % n]
        if lesson["topic"] not in exclude:
            return lesson
    # Весь формат исчерпан (маловероятно) — циклически берём первый.
    return lessons[offset % n]


def valid_formats() -> list[str]:
    """Форматы, для которых есть готовый банк (должны совпадать с ALL_FORMATS)."""
    return [f for f in ALL_FORMATS if LESSONS.get(f)]
