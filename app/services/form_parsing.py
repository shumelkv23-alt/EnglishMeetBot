# app/services/form_parsing.py
"""Нормализация formInputs Google Chat в {name: [values]}.

Сюда не импортируется ничего из app — хелпер живёт отдельно,
чтобы не плодить циклические импорты между сервисами.
"""


def parse_form_inputs(form_inputs: dict) -> dict[str, list[str]]:
    """Нормализовать formInputs в {name: [values]} для обоих форматов Google.

    Плоский:  {"name": {"stringInputs": {"value": [...]}}}
    Add-on:   {"name": {"": {"stringInputs": {"value": [...]}}}}

    Пустые и нестроковые значения отбрасываются; поля без значений
    не попадают в результат.
    """
    result: dict[str, list[str]] = {}
    for name, field in (form_inputs or {}).items():
        if not isinstance(field, dict):
            continue
        si = field.get("stringInputs")
        if not isinstance(si, dict):
            inner = field.get("")
            si = inner.get("stringInputs") if isinstance(inner, dict) else None
        if not isinstance(si, dict):
            continue
        values = [v.strip() for v in si.get("value", []) if isinstance(v, str) and v.strip()]
        if values:
            result[name] = values
    return result
