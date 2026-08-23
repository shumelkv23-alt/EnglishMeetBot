"""Live-тест: один реальный запрос к OpenRouter (платный — запускай осознанно).

Запуск: pytest -m live. Требует OPENROUTER_API_KEY в .env, иначе скипается.
Юнит-покрытие генерации (с моком) уже есть в tests/test_llm_questions.py.
"""
import pytest

from app.config import get_settings

pytestmark = pytest.mark.live


def test_generate_real_personal_question():
    from app.services.llm_questions import generate_personal_question

    if not get_settings().openrouter_api_key:
        pytest.skip("OPENROUTER_API_KEY не задан в .env")

    question = generate_personal_question(["кино и сериалы", "путешествия"])
    assert question is not None
    assert isinstance(question, str) and question.strip()
