"""Приглашения: персональные, пост в Space, эскалация организатору (REQ-5, REQ-9.5)."""
from app.schemas import Activity


def _theme_from_activity(activity: Activity | None) -> str | None:
    """Тема встречи из Activity (ENG-8) или None."""
    if activity is None:
        return None
    content = activity.content or {}
    title = content.get("title") or content.get("kind")
    return title if isinstance(title, str) and title else None


def build_invite_text(day: str, time: str, theme: str | None) -> str:
    """Персональное приглашение: время + тема (REQ-5.1)."""
    base = f"Встреча по английскому: {day} в {time} 📅"
    if theme:
        return f"{base}\n\nТема встречи: {theme}"
    return base


def build_escalation_text() -> str:
    """Сообщение организатору при не набранном кворуме (REQ-9.5, REQ-3.5)."""
    return (
        "Не получилось выбрать время встречи на эту неделю: кворум не набран. "
        "Реши вручную или задай новые слоты, пожалуйста. 🙏"
    )