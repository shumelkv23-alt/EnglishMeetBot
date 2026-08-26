"""Генераторы контента карточки: шаблон (контент-банк) и LLM (Azati)."""
from app.cards.generator.template import build_template_content
from app.cards.generator.llm import generate_llm_content

__all__ = ["build_template_content", "generate_llm_content"]
