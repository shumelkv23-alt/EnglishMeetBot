# app/services/activity.py
"""Выбор активности и темы встречи — логика Кирилла.

Сюда вставляется генерация активности/темы для анонса в группу.
Пока возвращает None — в анонсе будет строка «Активность и тема уточняются»
(см. build_announcement_text в app/services/poll_logic.py).

Контракт (согласован с командой):
  вход:  meeting — объект MeetingInstance (SQLAlchemy) зафиксированной встречи
  выход: Activity | None — строка «активность + тема», готовая для показа,
         либо None. Результат кладётся в meeting.activity_type / activity_data
         и подставляется в текст анонса.

Типы активностей описаны в app/schemas.py (Activity): digest, guess_colleague.
"""
import logging

logger = logging.getLogger(__name__)


async def pick_activity(db, meeting) -> "str | None":  # noqa: F821 — meeting: MeetingInstance
    """Вернуть строку «активность + тема» для анонса или None.

    TODO(Кирилл): здесь будет логика подбора активности/темы на основе
    профилей участников встречи (digest / guess_colleague и т.п.).
    """
    # Пока активность не генерируем — в анонсе будет плейсхолдер.
    return None
