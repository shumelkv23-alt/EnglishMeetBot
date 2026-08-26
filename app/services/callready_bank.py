"""Банк курса «Survival English for Calls» (порт приложения CallReady).

Статический учебный материал для режима обучения в личке: 12 модулей по темам
рабочих созвонов, 3 блока (этапа), фразбук «на крайний случай», 8 грамматических
тем со справочниками и 40 заданий с вариантами ответов.

Структуры соответствуют данным приложения CallReady 1:1 — это «source of truth»,
не LLM-генерация. Тексты правил и пояснений хранятся в лёгком HTML (<b>/<i>/<s>/
<h3>/<p>) и конвертируются в карточный markdown хелпером callready._md().
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Модули (12). Порядок — это маршрут курса.
#   id        — короткий ключ модуля;
#   icon      — эмодзи для карточки;
#   title/sub — название и подзаголовок (EN);
#   grammar   — название грамматического навыка;
#   rule/ru_rule — правило (EN/RU, лёгкий HTML);
#   terms     — 6 терминов: [english, русский, пример употребления].
# ---------------------------------------------------------------------------
MODULES: list[dict] = [
    {
        "id": "start",
        "icon": "👋",
        "title": "Start & participate",
        "sub": "Open a call, join in, ask a question.",
        "grammar": "Be + simple questions",
        "rule": "Use <b>Can I …?</b> for a simple request. Use <b>Could I …?</b> when you want to sound softer.",
        "ru_rule": "<b>Can I…?</b> — простая просьба. <b>Could I…?</b> звучит мягче и вежливее; это безопасный выбор на созвоне.",
        "terms": [
            ["agenda", "повестка встречи", "What is on the agenda today?"],
            ["join the call", "подключиться к созвону", "Thanks for joining the call."],
            ["share an update", "дать обновление", "Can I share a quick update?"],
            ["point", "пункт / мысль", "I would like to add one point."],
            ["come back to", "вернуться к теме", "Could we come back to this later?"],
            ["goal", "цель", "The goal of this call is to make a decision."],
        ],
    },
    {
        "id": "status",
        "icon": "📍",
        "title": "Status & deadlines",
        "sub": "Give a clear update without long explanations.",
        "grammar": "Present Continuous + time",
        "rule": "Use <b>We are working on …</b> for work in progress. Use <b>by Friday</b> for a deadline.",
        "ru_rule": "<b>We are working on…</b> — говорим о том, что делаем прямо сейчас. <b>by Friday</b> означает «не позднее пятницы».",
        "terms": [
            ["blocker", "препятствие", "We have one blocker at the moment."],
            ["deadline", "срок", "The deadline is Friday."],
            ["almost complete", "почти готово", "The task is almost complete."],
            ["priority", "приоритет", "This is our top priority."],
            ["next step", "следующий шаг", "The next step is testing."],
            ["follow up", "вернуться с ответом позже", "I will follow up tomorrow."],
        ],
    },
    {
        "id": "clarify",
        "icon": "🔎",
        "title": "Clarify & confirm",
        "sub": "Understand correctly and avoid assumptions.",
        "grammar": "Polite questions",
        "rule": "After <b>Could you tell me …</b>, use normal word order: <b>when it is due</b>, not “when is it due”.",
        "ru_rule": "После <b>Could you tell me…</b> порядок слов обычный: <b>when it is due</b>, а не вопросительный <b>when is it due</b>.",
        "terms": [
            ["clarify", "уточнить", "Could you clarify what you mean?"],
            ["confirm", "подтвердить", "Can you confirm the date?"],
            ["requirement", "требование", "I need to check the requirement."],
            ["scope", "объём работ", "Is this in scope?"],
            ["assumption", "предположение", "That is an assumption, not a decision."],
            ["summarize", "подвести итог", "Let me summarize the next steps."],
        ],
    },
    {
        "id": "decide",
        "icon": "🤝",
        "title": "Agree & decide",
        "sub": "Suggest, disagree politely, make a decision.",
        "grammar": "Could / should / might",
        "rule": "Use <b>might</b> for a careful possibility: “This might cause a delay.” Use <b>could</b> for a polite option.",
        "ru_rule": "<b>might</b> — осторожное «может быть»: не звучит категорично. <b>could</b> — вежливый вариант или предложение.",
        "terms": [
            ["concern", "опасение", "I have one concern."],
            ["option", "вариант", "Could we consider another option?"],
            ["trade-off", "компромисс между скоростью и качеством", "There is a trade-off between speed and quality."],
            ["recommend", "рекомендовать", "I would recommend option A."],
            ["agree", "соглашаться", "I agree with that approach."],
            ["impact", "влияние", "What is the impact on the timeline?"],
        ],
    },
    {
        "id": "recover",
        "icon": "🛟",
        "title": "Problems & recovery",
        "sub": "Handle confusion, tech issues and missing details.",
        "grammar": "Need to / can’t / if",
        "rule": "Say <b>I need to check</b>, not “I need check”. For a condition: <b>If the issue continues, we can …</b>",
        "ru_rule": "После <b>need</b> почти всегда нужен <b>to</b>: <b>I need to check</b>. <b>If</b> вводит условие: «если проблема продолжится…».",
        "terms": [
            ["issue", "проблема", "We have an issue with access."],
            ["unstable", "нестабильный", "My connection is unstable."],
            ["repeat", "повторить", "Could you repeat that, please?"],
            ["access", "доступ", "I do not have access yet."],
            ["workaround", "временное решение", "We found a workaround."],
            ["reschedule", "перенести", "Could we reschedule this discussion?"],
        ],
    },
    {
        "id": "explain",
        "icon": "🗣️",
        "title": "Explain & close",
        "sub": "Present your point and finish a call well.",
        "grammar": "Linking ideas",
        "rule": "Use <b>because</b> to give a reason; use <b>so</b> to give a result. Keep one idea per sentence.",
        "ru_rule": "<b>because</b> объясняет причину, <b>so</b> — результат. На созвоне лучше одна короткая мысль в одном предложении.",
        "terms": [
            ["result", "результат", "The result is positive."],
            ["benefit", "преимущество", "The main benefit is speed."],
            ["timeline", "график", "The timeline has changed."],
            ["action item", "договорённость после встречи", "Let’s confirm the action items."],
            ["recap", "кратко подвести итог", "To recap, we agreed to start Monday."],
            ["feedback", "обратная связь", "Thank you for your feedback."],
        ],
    },
    {
        "id": "simulate",
        "icon": "🎯",
        "title": "Call simulations",
        "sub": "Use everything in short realistic situations.",
        "grammar": "Mixed review",
        "rule": "A clear short answer is enough: status + reason + next step.",
        "ru_rule": "Формула понятного ответа: <b>статус + причина + следующий шаг</b>. Не нужно строить длинное сложное предложение.",
        "terms": [
            ["get back to you", "вернуться с ответом", "I will get back to you by tomorrow."],
            ["make sure", "убедиться", "Let me make sure I understand."],
            ["available", "доступный", "I am available after 3 pm."],
            ["decision", "решение", "We need a decision today."],
            ["delay", "задержка", "There may be a short delay."],
            ["owner", "ответственный", "Who is the owner of this task?"],
        ],
    },
    {
        "id": "schedule",
        "icon": "🗓️",
        "title": "Schedule & availability",
        "sub": "Arrange time, move meetings, set expectations.",
        "grammar": "Prepositions of time",
        "rule": "Use <b>at</b> for a time, <b>on</b> for a day, and <b>by</b> for a deadline.",
        "ru_rule": "<b>at 3 pm</b> — точное время; <b>on Monday</b> — день; <b>by Friday</b> — сделать не позднее пятницы.",
        "terms": [
            ["available", "доступен", "I am available after 3 pm."],
            ["reschedule", "перенести", "Could we reschedule our meeting?"],
            ["time zone", "часовой пояс", "What time zone are you in?"],
            ["slot", "временной слот", "I can offer a 30-minute slot."],
            ["calendar invite", "приглашение в календаре", "I will send a calendar invite."],
            ["work for you", "подходить", "Does Tuesday work for you?"],
        ],
    },
    {
        "id": "collaborate",
        "icon": "🧩",
        "title": "Collaboration",
        "sub": "Work together across teams and roles.",
        "grammar": "Have to / need to",
        "rule": "Use <b>need to</b> for something necessary; use <b>have to</b> for a required action or rule.",
        "ru_rule": "<b>need to</b> — «нужно сделать»; <b>have to</b> — обязательное действие или правило. Оба варианта требуют <b>to + verb</b>.",
        "terms": [
            ["stakeholder", "заинтересованная сторона", "We need feedback from the stakeholder."],
            ["align on", "согласовать общее понимание", "Let’s align on the priorities."],
            ["hand over", "передать работу", "I will hand this over to the design team."],
            ["dependency", "зависимость", "This task has one dependency."],
            ["support", "поддержать / помощь", "Could you support us with this?"],
            ["ownership", "ответственность", "Who has ownership of this item?"],
        ],
    },
    {
        "id": "feedback",
        "icon": "💬",
        "title": "Feedback & requests",
        "sub": "Ask for help and give feedback politely.",
        "grammar": "Would / could for politeness",
        "rule": "Use <b>Would you mind + -ing</b> for a very polite request: “Would you mind sharing the file?”",
        "ru_rule": "После <b>Would you mind</b> используем глагол с <b>-ing</b>: <b>sharing</b>, <b>checking</b>. Так просьба звучит мягко.",
        "terms": [
            ["review", "проверить", "Could you review this document?"],
            ["comment", "комментарий", "I left a comment in the file."],
            ["suggestion", "предложение", "I have a small suggestion."],
            ["appreciate", "быть признательным", "I would appreciate your feedback."],
            ["specific", "конкретный", "Could you be more specific?"],
            ["improve", "улучшить", "This could improve the process."],
        ],
    },
    {
        "id": "demo",
        "icon": "📊",
        "title": "Demo & presentation",
        "sub": "Show a result and tell a short clear story.",
        "grammar": "Present Perfect basics",
        "rule": "Use <b>We have completed …</b> for a result that matters now. Use Past Simple with a finished time: “We completed it yesterday.”",
        "ru_rule": "<b>We have completed</b> — важен результат сейчас. Если есть точное завершённое время — <b>yesterday / last week</b> — используем Past Simple.",
        "terms": [
            ["walk through", "коротко показать по шагам", "I will walk you through the update."],
            ["highlight", "выделить главное", "Let me highlight the key change."],
            ["release", "релиз / выпуск", "The release is planned for Friday."],
            ["outcome", "итог", "The outcome was positive."],
            ["demo", "демонстрация", "I will give a quick demo."],
            ["question", "вопрос", "Please stop me if you have a question."],
        ],
    },
    {
        "id": "email",
        "icon": "✉️",
        "title": "Follow-up & written calls",
        "sub": "Turn a call into a clear written follow-up.",
        "grammar": "Future commitments",
        "rule": "Use <b>I’ll</b> for a decision made now; use <b>I’m going to</b> for an existing plan.",
        "ru_rule": "<b>I’ll send it</b> — решил прямо сейчас. <b>I’m going to send it</b> — уже есть такой план. В рабочих сообщениях оба варианта полезны.",
        "terms": [
            ["follow-up", "итоговое сообщение после встречи", "I will send a follow-up after the call."],
            ["attach", "прикрепить", "I attached the document."],
            ["cc", "добавить в копию", "Please cc Anna on the email."],
            ["action item", "задача по итогам встречи", "I noted the action items."],
            ["reply", "ответить", "Could you reply by Thursday?"],
            ["update", "обновление", "I will keep you updated."],
        ],
    },
]

# ---------------------------------------------------------------------------
# Блоки (3 этапа). grammar — индексы грамматических тем (GRAMMAR_TOPICS).
# ---------------------------------------------------------------------------
BLOCKS: list[dict] = [
    {"id": "foundation", "title": "Block 1 · Call foundations", "modules": ["start", "status", "clarify", "decide"], "grammar": [0, 1, 2]},
    {"id": "delivery", "title": "Block 2 · Delivery communication", "modules": ["recover", "explain", "simulate", "schedule"], "grammar": [3, 4, 5]},
    {"id": "collaboration", "title": "Block 3 · Working with others", "modules": ["collaborate", "feedback", "demo", "email"], "grammar": [6, 7]},
]

# ---------------------------------------------------------------------------
# Фразбук «на крайний случай»: категория → фразы.
# ---------------------------------------------------------------------------
BACKUP: dict[str, list[str]] = {
    "I didn't understand": [
        "Sorry, I didn’t catch that.",
        "Could you say that again, please?",
        "Could you give me an example?",
        "Let me make sure I understood correctly: …",
    ],
    "I need time": [
        "Let me check and get back to you.",
        "I need a little more time to look into it.",
        "Can I come back to you by tomorrow?",
    ],
    "Technical problem": [
        "My connection is unstable.",
        "You froze for a moment. Could you repeat that?",
        "Could you put that in the chat, please?",
    ],
    "Polite disagreement": [
        "I see your point, but I have one concern.",
        "I’m not sure this will work because …",
        "Could we consider another option?",
    ],
    "Close the call": [
        "To recap, we agreed that …",
        "The next step is …",
        "Please let me know if I missed anything.",
    ],
}

# ---------------------------------------------------------------------------
# Грамматические темы (8). tasks — индексы в GRAMMAR_TASKS.
# ---------------------------------------------------------------------------
GRAMMAR_TOPICS: list[dict] = [
    {
        "title": "Questions & word order",
        "ru": "Как задавать простые и косвенные вопросы без «ломаного» порядка слов.",
        "rule": "Can I ask a question? · Could you tell me when it is due?",
        "tasks": [0, 3, 24, 25],
    },
    {
        "title": "Present Simple & Continuous",
        "ru": "Разница между регулярными действиями и тем, что происходит сейчас.",
        "rule": "We usually meet on Mondays. · We are working on it.",
        "tasks": [0, 12, 13, 26, 27],
    },
    {
        "title": "Past & Present Perfect",
        "ru": "Как давать статус о завершённой работе и говорить о результате.",
        "rule": "We finished it yesterday. · We have completed the first step.",
        "tasks": [4, 9, 14, 28, 29],
    },
    {
        "title": "Future, deadlines & time",
        "ru": "Планы, обещания и предлоги времени на созвонах.",
        "rule": "I’ll send it by Friday. · The call is on Monday at 3 pm.",
        "tasks": [1, 7, 15, 20, 30, 31],
    },
    {
        "title": "Modal verbs",
        "ru": "Вежливые просьбы, предложения и возможности.",
        "rule": "Could you repeat that? · We can reschedule.",
        "tasks": [2, 6, 10, 16, 22, 32, 33],
    },
    {
        "title": "Need to & have to",
        "ru": "Как корректно сказать, что действие необходимо.",
        "rule": "I need to check the details first.",
        "tasks": [5, 17, 21, 34, 35],
    },
    {
        "title": "Polite requests",
        "ru": "Мягкие формулировки без приказного тона.",
        "rule": "Would you mind sharing the file?",
        "tasks": [8, 18, 36, 37],
    },
    {
        "title": "Linking ideas",
        "ru": "Как коротко объяснять причины и последствия.",
        "rule": "The file is late because the review took longer.",
        "tasks": [11, 19, 23, 38, 39],
    },
]

# ---------------------------------------------------------------------------
# Справочники по грамматике (8, HTML) — по одному на тему.
# ---------------------------------------------------------------------------
GRAMMAR_GUIDES: list[str] = [
    "<h3>Как строить вопросы на созвоне</h3><p>В обычном вопросе вспомогательный глагол идёт перед подлежащим: <b>Do we need…?</b>, <b>Is the file ready?</b>. Но после вежливого вступления <b>Could you tell me…?</b> вопрос превращается в часть предложения: <b>Could you tell me when it is due?</b>, не <s>when is it due</s>.</p><p><b>Безопасная формула:</b> Could you + base verb …? / Can I + base verb …? / Do you mean that …?</p><p><b>Типичная ловушка:</b> не добавляйте <i>do/does</i> после <i>could</i>: <s>Could you to explain?</s> → <b>Could you explain?</b></p>",
    "<h3>Routine vs. work in progress</h3><p><b>Present Simple</b> описывает регулярность, факт или процесс в целом: <b>We usually meet on Mondays.</b> <b>The team owns this task.</b> <b>Present Continuous</b> описывает действие прямо сейчас или временную работу: <b>We are testing the release.</b></p><p><b>Маркеры:</b> usually, every week → Simple; now, at the moment, currently → Continuous.</p><p><b>Ловушка:</b> не говорите <s>We working</s>. Нужен глагол <b>be</b>: <b>We are working.</b></p>",
    "<h3>Статусы о прошлом и о результате</h3><p><b>Past Simple</b> — законченное действие в законченное время: <b>We finished the review yesterday.</b> <b>She sent the invite last week.</b></p><p><b>Present Perfect</b> — важен результат сейчас, время не называем: <b>We have completed the first step.</b> <b>I have updated the document.</b></p><p><b>Ловушка:</b> не смешивайте Present Perfect с <i>yesterday / last week</i>. С ними нужен Past Simple.</p>",
    "<h3>Планы, дедлайны и время</h3><p><b>I’ll</b> — решение или обещание в момент разговора: <b>I’ll send the link after the call.</b> <b>I’m going to</b> — существующий план: <b>I’m going to check it tomorrow.</b></p><p><b>Время:</b> at 3 pm, on Monday, in July. <b>by Friday</b> означает «не позднее пятницы», а <b>until Friday</b> — «вплоть до пятницы».</p>",
    "<h3>Модальные глаголы без лишних слов</h3><p>После <b>can, could, should, might</b> всегда идёт глагол в базовой форме: <b>We can reschedule.</b> <b>Could you repeat that?</b></p><p><b>could</b> делает просьбу мягче; <b>might</b> выражает осторожную возможность; <b>should</b> — рекомендацию.</p><p>Не нужно <i>to</i>: <s>could to repeat</s> → <b>could repeat</b>.</p>",
    "<h3>Need to и have to</h3><p><b>Need to</b> — практическая необходимость: <b>I need to check the details.</b> <b>Have to</b> — обязанность, правило или внешнее требование: <b>We have to follow the process.</b></p><p>Оба выражения требуют <b>to + глагол</b>. Отрицание: <b>don’t have to</b> = «не обязательно», <b>can’t</b> = «нельзя/невозможно».</p>",
    "<h3>Вежливость без сложной грамматики</h3><p>Вместо приказа используйте <b>Could you…?</b>, <b>Would you mind + -ing?</b>, <b>Could we…?</b>. Например: <b>Would you mind sharing the file?</b></p><p>Полезное смягчение: <b>Could you possibly…?</b>, <b>When you have a moment…</b>, <b>I would appreciate…</b>.</p>",
    "<h3>Связная мысль: причина, результат, контраст</h3><p><b>because</b> вводит причину: <b>The file is late because the review took longer.</b> <b>so</b> вводит результат: <b>The review took longer, so the file is late.</b></p><p><b>however</b> показывает контраст: <b>The option is faster. However, it is less reliable.</b> Начинайте с коротких предложений: одна мысль — одно предложение.</p>",
]

# ---------------------------------------------------------------------------
# Грамматические задания (40). Каждое: [вопрос, [варианты], верный_индекс, пояснение].
# ---------------------------------------------------------------------------
GRAMMAR_TASKS: list[list] = [
    ["Choose the correct status update.", ["We working on it now.", "We are working on it now.", "We are work on it now."], 1, 'Use <b>are + verb-ing</b> for work in progress: “We are working …”'],
    ["Choose the correct deadline phrase.", ["I will send it in Friday.", "I will send it by Friday.", "I will send it at Friday."], 1, "Use <b>by Friday</b> when something must be finished no later than Friday."],
    ["Complete the polite request: “Could you ___ that again, please?”", ["repeat", "to repeat", "repeating"], 0, "After <b>could</b>, use the base verb: <b>repeat</b>."],
    ["Choose the natural clarification question.", ["Could you tell me when is it due?", "Could you tell me when it is due?", "Could you tell me when due it is?"], 1, "After “Could you tell me…”, use normal word order: <b>when it is due</b>."],
    ["Choose the correct past update.", ["We finish the task yesterday.", "We finished the task yesterday.", "We have finished the task yesterday."], 1, "With a finished time such as <b>yesterday</b>, use Past Simple: <b>finished</b>."],
    ["Complete: “I need ___ the details first.”", ["check", "to check", "checking"], 1, "After <b>need</b>, use <b>to + verb</b>: “need to check”."],
    ["Choose the polite suggestion.", ["We consider another option.", "Could we consider another option?", "Could we to consider another option?"], 1, "Use <b>Could we + base verb</b> for a soft suggestion."],
    ["Complete: “The call is ___ Monday at 3 pm.”", ["in", "on", "by"], 1, "Use <b>on</b> with days: <b>on Monday</b>. Use <b>at</b> with a time."],
    ["Choose the correct form.", ["Would you mind share the file?", "Would you mind to share the file?", "Would you mind sharing the file?"], 2, "After <b>Would you mind</b>, use <b>verb-ing</b>: “sharing”."],
    ["Choose the best result-focused update.", ["We have completed the first step.", "We have complete the first step.", "We completed the first step last week."], 0, "<b>We have completed</b> emphasizes the current result. Past Simple is also correct with a finished time such as “last week”."],
    ["Complete: “If the issue continues, we ___ reschedule.”", ["can", "are", "to"], 0, "After <b>if</b>, a simple practical option works well: “we can reschedule”."],
    ["Choose the correct reason.", ["The file is late because the review took longer.", "The file is late so the review took longer.", "The file is late because of the review took longer."], 0, "Use <b>because + subject + verb</b> to explain a reason."],
    ["Choose the correct routine.", ["We are usually meet on Mondays.", "We usually meet on Mondays.", "We usually meeting on Mondays."], 1, "For a regular schedule, use Present Simple: <b>We usually meet</b>."],
    ["Complete: “She ___ the document right now.”", ["reviews", "is reviewing", "review"], 1, "Use <b>is reviewing</b> for an action happening now."],
    ["Choose the correct current result.", ["I have sent the follow-up.", "I have send the follow-up.", "I sent the follow-up now."], 0, "Present Perfect uses <b>have + past participle</b>: <b>have sent</b>."],
    ["Choose the correct arrangement.", ["I meeting them tomorrow.", "I am meeting them tomorrow.", "I am meet them tomorrow."], 1, "Present Continuous can describe an arranged future event: <b>I am meeting</b>."],
    ["Complete: “We ___ need more time.”", ["might", "might to", "are might"], 0, "After <b>might</b>, use the base verb: <b>might need</b>."],
    ["Choose the correct obligation.", ["We have to update the tracker.", "We have update the tracker.", "We have to updating the tracker."], 0, "<b>Have to + base verb</b>: “have to update”."],
    ["Choose the natural request.", ["Send me the file.", "Could you send me the file, please?", "You could send me the file?"], 1, "A clear polite request is <b>Could you + base verb, please?</b>"],
    ["Complete the result: “The review took longer, ___ we moved the deadline.”", ["because", "so", "however"], 1, "Use <b>so</b> before a result or consequence."],
    ["Choose the correct time phrase.", ["The demo starts in 2 pm.", "The demo starts at 2 pm.", "The demo starts by 2 pm."], 1, "Use <b>at</b> with a precise clock time."],
    ["Choose the correct negative.", ["We do not have to join the call.", "We not have to join the call.", "We do not to have join the call."], 0, "Use <b>do not have to + verb</b>. It means the action is not necessary."],
    ["Complete: “Could we ___ this after lunch?”", ["discuss", "to discuss", "discussing"], 0, "After <b>Could we</b>, use the base verb: “discuss”."],
    ["Choose the correct contrast.", ["The option is fast, because it is risky.", "The option is fast; however, it is risky.", "The option is fast, so it is risky."], 1, "<b>However</b> introduces contrast; use punctuation or a new sentence around it."],
    ["Choose the correct direct question.", ["What we need to decide?", "What do we need to decide?", "What do need we to decide?"], 1, "In a direct Present Simple question, use <b>do + subject + verb</b>."],
    ["Complete: “Do you know ___ owns this task?”", ["who", "what", "where"], 0, "Use <b>who</b> for a person: “who owns this task”."],
    ["Choose the correct regular process.", ["The team checks the dashboard every morning.", "The team is checking the dashboard every morning.", "The team check the dashboard every morning."], 0, "A routine uses Present Simple. With <b>the team</b>, add <b>-s</b>: “checks”."],
    ["Choose the current action.", ["I prepare the update at the moment.", "I am preparing the update at the moment.", "I prepared the update at the moment."], 1, "“At the moment” signals Present Continuous: <b>am preparing</b>."],
    ["Choose the correct finished-time update.", ["We have deployed it last night.", "We deployed it last night.", "We have deploy it last night."], 1, "“Last night” is finished time, so use Past Simple: <b>deployed</b>."],
    ["Complete: “We have ___ the issue.”", ["solve", "solved", "solving"], 1, "Present Perfect = <b>have + past participle</b>: “have solved”."],
    ["Choose the correct deadline.", ["Can you finish it until Thursday?", "Can you finish it by Thursday?", "Can you finish it on Thursday?"], 1, "<b>By Thursday</b> means no later than Thursday."],
    ["Choose the correct plan.", ["I will going to send a recap.", "I am going to send a recap.", "I going to send a recap."], 1, "A plan uses <b>am/is/are going to + verb</b>."],
    ["Complete: “You ___ check the numbers before the demo.”", ["should", "should to", "are should"], 0, "Use <b>should + base verb</b> for advice."],
    ["Choose the careful possibility.", ["This might cause a delay.", "This might to cause a delay.", "This is might cause a delay."], 0, "<b>Might + base verb</b> expresses a careful possibility."],
    ["Complete: “I don’t ___ access to that folder.”", ["have", "to have", "having"], 0, "Use <b>have</b> for possession: “I don’t have access”."],
    ["Choose the correct necessity.", ["We need to discuss this today.", "We need discuss this today.", "We need to discussing this today."], 0, "<b>Need to + base verb</b>: “need to discuss”."],
    ["Choose the polite wording.", ["Would you mind to join five minutes early?", "Would you mind joining five minutes early?", "Would you mind join five minutes early?"], 1, "After <b>would you mind</b>, use verb-ing: “joining”."],
    ["Complete: “I would appreciate it if you ___ the document.”", ["review", "reviewed", "will review"], 1, "After “I would appreciate it if…”, Past Simple often makes the request softer: <b>reviewed</b>."],
    ["Choose the correct cause.", ["Because the owner is away, we need to wait.", "So the owner is away, we need to wait.", "However the owner is away, we need to wait."], 0, "Use <b>because</b> to introduce the reason."],
    ["Choose the clear result.", ["The scope changed because we updated the estimate.", "The scope changed, so we updated the estimate.", "The scope changed; however, we updated the estimate."], 1, "Use <b>so</b> for the result: scope changed → we updated the estimate."],
]


# ---------------------------------------------------------------------------
# Справочные хелперы (без БД) — для engine и тестов.
# ---------------------------------------------------------------------------

def module_by_id(module_id: str) -> dict | None:
    """Модуль по id, иначе None."""
    for m in MODULES:
        if m["id"] == module_id:
            return m
    return None


def module_index(module_id: str) -> int:
    """Порядковый индекс модуля в маршруте; -1, если нет."""
    for i, m in enumerate(MODULES):
        if m["id"] == module_id:
            return i
    return -1


def block_for_module(module_id: str) -> dict | None:
    """Блок, к которому относится модуль (по списку modules), иначе None."""
    for b in BLOCKS:
        if module_id in b["modules"]:
            return b
    return None
