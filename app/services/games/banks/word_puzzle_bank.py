"""Банк фраз для «Словесного пазла» (Word Puzzle).

Каждая фраза разбита на осмысленные куски (chunks) — не просто по словам, а по
грамматическим блокам (подлежащее, глагол, дополнение, обстоятельство), чтобы
собирать было интереснее. Порядок кусков в списке = правильный порядок фразы.

~300 фраз разного уровня и тематики (рутины, еда, путешествия, работа, погода,
времена, модальные глаголы, условные предложения и т.д.).
"""
import random

PHRASES = [
    # --- Present simple: routines & facts ---
    ["I", "get up", "at seven o'clock."],
    ["She", "goes", "to work", "every day."],
    ["He", "plays", "the guitar", "every evening."],
    ["We", "live", "in a small town."],
    ["They", "go", "to school", "by bus."],
    ["My father", "reads", "the newspaper", "every morning."],
    ["The shop", "opens", "at nine."],
    ["I", "drink", "coffee", "with milk."],
    ["She", "speaks", "three languages."],
    ["It", "rains", "a lot", "in autumn."],
    ["The children", "play", "in the garden."],
    ["We", "cook", "dinner", "together", "on Sundays."],
    ["The cat", "sat", "on the mat."],
    ["The earth", "goes", "around the sun."],
    ["Water", "boils", "at a hundred degrees."],
    ["I", "usually", "walk", "to work."],
    ["She", "rarely", "eats", "fast food."],
    ["He", "always", "arrives", "on time."],
    ["The museum", "opens", "at ten", "and closes", "at six."],

    # --- Present simple: negatives ---
    ["I", "don't like", "spicy food."],
    ["He", "doesn't eat", "meat."],
    ["She", "doesn't watch", "TV", "very often."],
    ["We", "don't have", "a car."],
    ["They", "don't understand", "the question."],
    ["My sister", "doesn't drink", "coffee."],
    ["I", "don't know", "the answer."],
    ["He", "doesn't play", "football", "on Fridays."],

    # --- Present simple: questions ---
    ["Do", "you", "like", "chocolate?"],
    ["Does", "she", "work", "here?"],
    ["Where", "do", "you", "live?"],
    ["What", "time", "does", "the train", "leave?"],
    ["How", "often", "do", "you", "exercise?"],
    ["Do", "you", "speak", "English?"],
    ["Does", "your brother", "speak", "English?"],

    # --- Past simple ---
    ["I", "visited", "my grandmother", "last weekend."],
    ["She", "bought", "a new dress", "yesterday."],
    ["We", "went", "to the beach", "in July."],
    ["He", "finished", "his homework", "before dinner."],
    ["They", "watched", "a movie", "last night."],
    ["I", "met", "an old friend", "on the street."],
    ["The concert", "started", "at eight o'clock."],
    ["She", "cooked", "a delicious meal", "for us."],
    ["We", "traveled", "to Spain", "last summer."],
    ["I", "didn't see", "him", "at the party."],
    ["She", "didn't call", "me", "yesterday."],
    ["We", "didn't like", "the film."],
    ["Did", "you", "enjoy", "the trip?"],
    ["Where", "did", "you", "buy", "that shirt?"],
    ["The phone", "rang", "while I was cooking."],
    ["I", "was reading", "when she called."],
    ["They", "were dancing", "when the music stopped."],
    ["We", "had already left", "when the guests arrived."],
    ["She", "used to live", "in London."],
    ["He", "used to smoke", "but he quit", "last year."],

    # --- Future ---
    ["I", "will call", "you", "tomorrow."],
    ["She", "is going to", "study", "medicine."],
    ["We", "will meet", "at the station", "at five."],
    ["It", "is going to", "rain", "soon."],
    ["They", "are going to", "move", "to another city."],
    ["I", "will help", "you", "with your bags."],
    ["He", "is going to", "start", "a new job", "next month."],
    ["This time next year", "I will be studying", "at university."],
    ["By five o'clock", "they will have finished", "the work."],
    ["I", "will be waiting", "for you", "at the airport."],

    # --- Present continuous ---
    ["I", "am reading", "an interesting book."],
    ["She", "is cooking", "dinner", "right now."],
    ["They", "are playing", "chess", "in the living room."],
    ["He", "is working", "on a project", "this week."],
    ["We", "are waiting", "for the bus."],
    ["The baby", "is sleeping", "upstairs."],
    ["I", "am learning", "to drive."],

    # --- Present perfect ---
    ["I", "have visited", "Paris", "twice."],
    ["She", "has finished", "her work."],
    ["We", "have lived", "here", "for five years."],
    ["He", "has never", "eaten", "sushi."],
    ["They", "have just", "arrived."],
    ["I", "have known", "her", "since school."],
    ["I", "have never", "been", "to Paris."],
    ["She", "has been", "to the gym", "twice today."],

    # --- Modals ---
    ["I", "can swim", "very well."],
    ["She", "can speak", "four languages."],
    ["You", "should drink", "more water."],
    ["We", "must finish", "this project", "by Friday."],
    ["He", "could play", "the piano", "when he was five."],
    ["You", "must wear", "a seatbelt", "in the car."],
    ["I", "might go", "to the gym", "later."],
    ["She", "would like", "a cup of tea."],
    ["You", "mustn't smoke", "in here."],
    ["You", "don't have to", "come", "if you are busy."],
    ["We", "ought to", "leave", "now."],
    ["You", "had better", "hurry", "or you will miss the bus."],
    ["Students", "have to", "wear", "a uniform."],
    ["May", "I", "come in?"],
    ["Could", "you", "repeat", "that", "please?"],
    ["You", "can borrow", "my car", "if you need it."],
    ["I", "was able to", "finish", "the work", "on time."],

    # --- Comparatives & superlatives ---
    ["My house", "is bigger", "than yours."],
    ["This book", "is more interesting", "than the last one."],
    ["She", "is the tallest", "in her class."],
    ["Winter", "is colder", "than autumn."],
    ["This", "is the best", "restaurant", "in town."],
    ["He", "runs faster", "than me."],
    ["The more", "you practice", "the better", "you get."],
    ["This one", "is", "the cheapest", "of all."],
    ["She", "is", "as tall", "as her brother."],
    ["It", "was", "the worst", "day", "of my life."],

    # --- There is / there are ---
    ["There", "is", "a cat", "on the roof."],
    ["There", "are", "many books", "on the shelf."],
    ["There", "is", "some milk", "in the fridge."],
    ["There", "are", "no seats", "on the bus."],
    ["There", "was", "a storm", "last night."],

    # --- Imperatives ---
    ["Please", "close", "the door."],
    ["Turn", "left", "at the corner."],
    ["Don't forget", "to lock", "the door."],
    ["Take", "an umbrella", "with you."],
    ["Listen", "carefully", "to the instructions."],
    ["Come", "to my party", "on Saturday."],
    ["Let's", "go", "for a walk."],
    ["Please", "send", "me", "the details", "by email."],

    # --- Conditionals ---
    ["If", "it rains", "we will stay", "at home."],
    ["If", "you study hard", "you will pass", "the exam."],
    ["I will buy", "a new phone", "if I save", "enough money."],
    ["If", "I were you", "I would talk", "to the manager."],
    ["You will feel better", "if you rest."],
    ["If", "I had more time", "I would learn", "another language."],
    ["If", "you heat ice", "it melts."],
    ["We", "will go", "to the park", "unless it rains."],
    ["If", "she had studied", "she would have passed."],

    # --- Wh- questions ---
    ["What", "are", "you", "doing?"],
    ["Who", "is", "that man", "over there?"],
    ["When", "does", "the movie", "start?"],
    ["Why", "are", "you", "late?"],
    ["How", "much", "does", "it", "cost?"],
    ["Which", "color", "do", "you", "prefer?"],
    ["Have", "you", "ever", "been", "to Japan?"],
    ["What", "were", "you", "doing", "at eight last night?"],
    ["How", "long", "have", "you", "lived here?"],
    ["Can", "you", "speak", "more slowly", "please?"],
    ["Would", "you", "mind", "opening the window?"],

    # --- Routines ---
    ["I", "brush", "my teeth", "twice a day."],
    ["She", "takes", "the dog", "for a walk", "every evening."],
    ["We", "have dinner", "at seven."],
    ["He", "goes to bed", "late", "on weekends."],
    ["I", "get up", "early", "on weekdays."],

    # --- Travel ---
    ["I", "would like", "to book", "a hotel room."],
    ["The train", "leaves", "from platform two."],
    ["We", "are staying", "in a small hotel", "near the beach."],
    ["Could", "you", "show me", "the way", "to the museum?"],
    ["The flight", "was delayed", "because of the weather."],
    ["I", "have lost", "my passport."],
    ["We", "are planning", "a trip", "to Italy."],
    ["The city", "is famous", "for its old churches."],
    ["Excuse me", "where is", "the nearest bank?"],
    ["Go", "straight ahead", "and turn right."],
    ["The post office", "is", "opposite the station."],
    ["How far", "is it", "to the airport?"],
    ["I", "am lost", "can you help me?"],
    ["We", "arrived", "at the airport", "just in time."],

    # --- Food & cooking ---
    ["Could", "I", "have", "the menu", "please?"],
    ["I", "am allergic", "to nuts."],
    ["This soup", "tastes", "delicious."],
    ["We", "need", "some eggs", "and flour", "for the cake."],
    ["She", "is making", "a salad", "for lunch."],
    ["The restaurant", "was", "fully booked", "on Friday."],
    ["I", "would like", "a glass of water", "please."],
    ["Breakfast", "is", "the most important meal", "of the day."],
    ["I", "prefer", "tea", "to coffee."],
    ["The cake", "smells", "amazing."],
    ["We", "ordered", "pizza", "for dinner."],
    ["Could", "we", "have", "the bill", "please?"],
    ["The soup", "was", "too salty."],

    # --- Weather ---
    ["It", "is snowing", "outside."],
    ["The weather", "is getting", "warmer", "every day."],
    ["It", "was", "very windy", "yesterday."],
    ["The sun", "is shining", "brightly."],
    ["It", "looks like", "it is going to rain."],
    ["The temperature", "will drop", "below zero", "tonight."],
    ["It", "is raining", "outside", "today."],

    # --- Work & office ---
    ["I", "have", "a meeting", "at ten o'clock."],
    ["She", "works", "from home", "on Mondays."],
    ["The report", "must be finished", "by tomorrow."],
    ["We", "are hiring", "a new designer."],
    ["He", "got", "a promotion", "last month."],
    ["My boss", "is", "on vacation", "this week."],
    ["The project", "is behind", "schedule."],
    ["I", "have", "a lot of work", "to do."],

    # --- Health ---
    ["I", "have", "a headache."],
    ["You", "should see", "a doctor."],
    ["She", "feels", "much better", "today."],
    ["He", "broke", "his leg", "while skiing."],
    ["Regular exercise", "keeps", "you healthy."],
    ["I", "need", "to lose", "some weight."],
    ["I", "go", "to the gym", "three times a week."],
    ["Running", "is good", "for your heart."],
    ["She", "recovered", "quickly", "from the flu."],
    ["You", "should get", "enough sleep", "every night."],

    # --- Shopping ---
    ["How much", "does", "this jacket", "cost?"],
    ["I", "am looking for", "a birthday gift", "for my sister."],
    ["These shoes", "are", "too small."],
    ["The shop", "is closed", "on Sundays."],
    ["Could", "I", "try", "this on?"],
    ["I", "bought", "a new laptop", "last week."],
    ["The shop assistant", "was", "very helpful."],

    # --- Hobbies & free time ---
    ["In my free time", "I like", "to paint."],
    ["She", "enjoys", "playing", "the piano."],
    ["We", "go hiking", "every summer."],
    ["He", "is crazy", "about football."],
    ["I", "collect", "old coins."],
    ["They", "spend", "hours", "playing video games."],

    # --- Family & home ---
    ["My family", "lives", "in a big city."],
    ["We", "have", "two cats", "and a dog."],
    ["My grandmother", "makes", "the best pies."],
    ["They", "are moving", "to a new house", "next month."],
    ["Our neighbors", "are", "very friendly."],
    ["The kitchen", "is", "the heart of our home."],
    ["My brother", "lives", "in London."],

    # --- Reported speech ---
    ["She", "said", "that she was tired."],
    ["He", "told me", "to wait", "outside."],
    ["They", "asked", "if I could help."],
    ["She", "wondered", "where he had gone."],

    # --- Passive ---
    ["The book", "was written", "in 1990."],
    ["English", "is spoken", "all over the world."],
    ["The house", "was built", "a hundred years ago."],
    ["The letter", "was sent", "yesterday."],
    ["The cake", "was made", "by my mother."],

    # --- Everyday expressions ---
    ["I", "am looking forward to", "seeing you."],
    ["It", "was", "nice", "to meet you."],
    ["Sorry", "I", "am late."],
    ["Thank you", "for", "your help."],
    ["Let me", "introduce", "myself."],
    ["Have", "a nice day!"],
    ["See you", "next week!"],
    ["I", "beg", "your pardon?"],
    ["We", "will see", "each other", "soon."],

    # --- Opinions & feelings ---
    ["I", "am afraid", "of spiders."],
    ["She", "is proud", "of her children."],
    ["He", "is interested", "in history."],
    ["I", "am tired", "of waiting."],
    ["This movie", "is", "boring."],
    ["I", "think", "it is a good idea."],
    ["In my opinion", "the plan", "won't work."],
    ["I", "can't stand", "waiting", "in line."],

    # --- Phrasal verbs ---
    ["He", "gave up", "smoking", "last year."],
    ["She", "looked after", "the children", "all day."],
    ["We", "ran out of", "milk."],
    ["They", "put off", "the meeting", "until Monday."],
    ["I", "am looking for", "my keys."],

    # --- Education ---
    ["I", "am studying", "for my exams."],
    ["She", "graduated", "from university", "in June."],
    ["The teacher", "explained", "the lesson", "clearly."],
    ["We", "learn", "a new word", "every day."],
    ["He", "passed", "the test", "with a high score."],

    # --- Nature & environment ---
    ["The forest", "is home", "to many animals."],
    ["We", "should protect", "the environment."],
    ["The river", "flows", "through the city."],
    ["Spring", "is", "my favorite season."],
    ["The leaves", "fall", "in autumn."],

    # --- Technology ---
    ["I", "spend", "too much time", "on my phone."],
    ["The computer", "is not working", "today."],
    ["She", "forgot", "her password."],
    ["We", "downloaded", "a new app", "yesterday."],
    ["The internet", "is", "very slow", "this evening."],

    # --- Money ---
    ["I", "am saving", "money", "for a new car."],
    ["He", "spends", "a lot of money", "on clothes."],
    ["The tickets", "cost", "twenty pounds."],
    ["We", "pay", "the rent", "at the beginning of the month."],

    # --- Time ---
    ["The meeting", "lasts", "about an hour."],
    ["We", "have known each other", "for ten years."],
    ["He", "has been waiting", "since noon."],
    ["It", "took", "me", "an hour", "to get here."],
    ["The movie", "starts", "in twenty minutes."],

    # --- Suggestions & offers ---
    ["Why", "don't we", "watch", "a movie?"],
    ["How about", "having", "lunch", "together?"],
    ["Shall", "we", "start", "the meeting?"],
    ["I", "would rather", "stay", "at home."],

    # --- More everyday situations ---
    ["I", "overslept", "and missed", "the bus."],
    ["The traffic", "was", "terrible", "this morning."],
    ["She", "is late", "for work", "again."],
    ["We", "are having", "a party", "on Friday."],
    ["I", "need", "to buy", "some groceries."],
    ["He", "forgot", "to bring", "his umbrella."],
    ["The phone", "is ringing", "can you answer it?"],
    ["I", "was surprised", "by the news."],
    ["This chair", "is", "more comfortable", "than that one."],
    ["We", "are expecting", "guests", "this evening."],
    ["I", "am thinking", "about moving", "to the countryside."],
    ["He", "promised", "to call", "me back."],
    ["The children", "are looking forward to", "the holidays."],
    ["She", "kept", "working", "until midnight."],
    ["They", "are thinking of", "buying", "a house."],
    ["The baby", "started", "to cry", "at night."],
    ["He", "looks", "tired", "these days."],
    ["We", "should", "check", "the weather", "before we leave."],
    ["She", "insisted on", "paying", "for dinner."],
    ["The concert", "was", "amazing."],
    ["He", "was", "born", "in 2005."],

    # --- Plans & wishes ---
    ["I", "want", "to improve", "my English."],
    ["She", "hopes", "to travel", "the world", "one day."],
    ["He", "plans", "to study", "abroad", "next year."],
    ["We", "decided", "to stay", "at home."],
    ["I", "want", "to travel", "around the world."],

    # --- Abilities & descriptions ---
    ["She", "is good", "at math."],
    ["I", "am bad", "at remembering", "names."],
    ["He", "speaks", "English", "fluently."],
    ["The exam", "was", "easier", "than I expected."],
]


def random_word_puzzle() -> list[str]:
    """Случайная фраза (список кусков в правильном порядке)."""
    return list(random.choice(PHRASES))
