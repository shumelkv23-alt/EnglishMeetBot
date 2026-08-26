"""Live-тест: один реальный запрос к Azati (платный — запускай осознанно).

Запуск: pytest -m live. Требует llm_api_key в .env, иначе скипается.
Юнит-покрытие генерации (с моком) уже есть в tests/test_llm_questions.py.
"""
import pytest

from app.config import get_settings

pytestmark = pytest.mark.live


def test_generate_real_personal_question():
    from app.services.llm_questions import generate_personal_question

    if not get_settings().llm_api_key:
        pytest.skip("llm_api_key не задан в .env")

    question = generate_personal_question(["кино и сериалы", "путешествия"])
    assert question is not None
    assert isinstance(question, str) and question.strip()
