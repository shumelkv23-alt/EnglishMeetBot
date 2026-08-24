# Активности — Этап C: Guesspionage English

Дата: 2026-08-24

## Цель

Игра «угадай процент»: бот задаёт вопрос-процент, один игрок называет число,
остальные голосуют «выше/ниже», бот открывает правильный ответ и начисляет очки.

## Вопросы (захардкожены, вопрос → процент)

```
"What percentage of people have peed in a shower?" -> 70
"What percentage of people wear socks when they sleep?" -> 16
"What percentage of people have Googled themselves?" -> 65
"What percentage of people prefer smooth peanut butter to crunchy?" -> 62
"What percentage of people believe there are aliens?" -> 85
```

## Механика

1. `/guesspionage` → карточка «Кто играет?» (Этап A).
2. Бот берёт вопрос по очереди и назначает «называющего» (по кругу).
3. Называющий пишет свой процент (карточка с полем, в личку).
4. Остальные голосуют **Higher / Lower** (кнопки в группе).
5. Бот открывает правильный процент и считает очки:
   - называющему: ±5% → 3, ±10% → 2, иначе 1;
   - остальным: +1 за верное «выше/ниже».
6. Очки в `leaderboard_ledger`.

## Состояние сессии

```python
{
  "players": [user_id, ...],
  "question_index": int,
  "guesser": user_id,          # кто сейчас называет процент
  "guess": int | None,
  "higher": set[user_id],
  "lower": set[user_id],
}
```

## Модули

- `app/services/games/guesspionage.py` — вопросы, карточки, подсчёт.

## Интерфейсы

- `GUESS_QUESTIONS: list[tuple[str, int]]`
- `build_guesspionage_higher_lower_card(question, action_url) -> dict`
- `score_round(session, question, guess, higher, lower) -> dict` (очки за раунд)

## Вне скоупа

- Реальные опросы/статистика — проценты «фейковые» (ведущий заранее задал).
