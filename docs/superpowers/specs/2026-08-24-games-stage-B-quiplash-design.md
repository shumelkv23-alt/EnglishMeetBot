# Активности — Этап B: Quiplash English

Дата: 2026-08-24

## Цель

Игра «самый смешной/крутой ответ»: бот даёт английские промпты, участники тайно
пишут ответы, затем голосуют за лучшие пары. Победитель получает очки.

## Промпты (захардкожены)

```
"The worst thing to say on a first date is: ___"
"A very bad name for a café is: ___"
"An excuse your dog could give for eating your homework: ___"
```

## Механика

1. `/quiplash` → карточка «Кто играет?» (Этап A).
2. Когда все отметились, бот шлёт промпт №1 в группу и **каждому в личку** карточку
   с текстовым полем ответа (тайно) + кнопка «Отправить».
3. Ответы (`submit_quiplash_answer`) сохраняются в сессию.
4. Когда все ответили → бот шлёт в группу пару «Ответ A vs Ответ B» с кнопками
   «A» / «B» (голосование), затем следующую пару, пока не проголосуют по всем.
5. Подсчёт: за каждый промпт победитель пары +1 «голос»; итог по раундам —
   топ-1 +3 XP, топ-2 +1 XP (в `leaderboard_ledger`).

## Состояние сессии (GameSession.state)

```python
{
  "players": [user_id, ...],
  "prompt_index": int,
  "current_prompt": str,
  "answers": {user_id: str},   # ответы на текущий промпт
  "pair_votes": {winner_user_id: int},  # очки за раунды
}
```

## Модули

- `app/services/games/quiplash.py` — промпты, карточка ответа, карточка пары, подсчёт.

## Интерфейсы

- `QUIPLASH_PROMPTS: list[str]`
- `build_quiplash_answer_card(prompt, action_url) -> dict`
- `build_quiplash_pair_card(a_text, b_text, action_url) -> dict`
- `record_answer(session, user_id, answer) -> bool`
- `tally(session) -> dict` (итог очков)

## Вне скоупа

- Мульти-промпты с продолжением (базовая версия — 1 промпт за запуск, расширяемо).
