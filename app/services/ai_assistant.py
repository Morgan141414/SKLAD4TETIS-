"""AI assistant for warehouse purchase risk analysis."""
from __future__ import annotations
from typing import Any


def analyze_purchase_risk(
    purchase_requests: list[dict[str, Any]],
    price_history: list[dict[str, Any]],
    abc_xyz_data: list[dict[str, Any]],
    anthropic_api_key: str,
) -> dict[str, Any]:
    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_api_key)

    requests_text = "\n".join(
        f"- {r.get('product_name','?')} (SKU: {r.get('sku','?')}): "
        f"заказ {r.get('recommended_quantity','?')}, остаток {r.get('current_free_quantity','?')}, "
        f"точка заказа {r.get('reorder_point','?')}"
        for r in purchase_requests[:20]
    ) or "Нет заявок"

    price_text = ""
    if price_history:
        price_text = "\nИстория цен:\n" + "\n".join(
            f"- {p.get('product_name','?')}: {p.get('unit_price','?')} тг ({p.get('supplier_name','?')}, {str(p.get('received_at','?'))[:10]})"
            for p in price_history[:10]
        )

    abc_text = ""
    high_risk = [i for i in abc_xyz_data if i.get('abc_class') == 'A' and i.get('xyz_class') == 'Z']
    if high_risk:
        abc_text = "\nТовары AZ (высокая стоимость + нерегулярный спрос):\n" + "\n".join(
            f"- {i.get('product_name','?')}: доля {i.get('value_share_percent',0):.1f}%"
            for i in high_risk[:10]
        )

    prompt = f"""Ты — эксперт по складскому учёту медицинской организации. Проанализируй заявки на закупку и выяви риски.

Заявки:
{requests_text}
{price_text}
{abc_text}

Выяви: подозрительно большие объёмы, нестабильный спрос, резкий рост цен, дубли.
Дай общую оценку рисков: низкий / средний / высокий.
Отвечай на русском, будь конкретен."""

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text if msg.content else "Анализ недоступен"
    return {
        "analysis": text,
        "requests_analyzed": len(purchase_requests),
        "model": "claude-sonnet-4-6",
        "input_tokens": msg.usage.input_tokens,
        "output_tokens": msg.usage.output_tokens,
    }


def analyze_single_purchase(
    product_name: str,
    quantity: float,
    unit_price: float | None,
    supplier_name: str | None,
    price_history: list[dict[str, Any]],
    current_stock: float,
    reorder_point: float,
    abc_class: str | None,
    xyz_class: str | None,
    anthropic_api_key: str,
) -> dict[str, Any]:
    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_api_key)

    price_hist_text = ""
    if price_history:
        price_hist_text = "История цен:\n" + "\n".join(
            f"  {str(p.get('received_at',''))[:10]}: {p.get('unit_price','?')} тг ({p.get('supplier_name','?')})"
            for p in price_history[-5:]
        )

    abc_info = ""
    if abc_class or xyz_class:
        abc_info = f"\nАBC/XYZ: {abc_class or '?'}{xyz_class or '?'}"
        if xyz_class == 'Z':
            abc_info += " — нерегулярный спрос, риск переизбытка"
        if abc_class == 'A':
            abc_info += " — высокая стоимость"

    prompt = f"""Оцени риск закупки для медицинского склада:

Товар: {product_name}
Количество: {quantity}
{f"Цена: {unit_price} тг" if unit_price else ""}
{f"Поставщик: {supplier_name}" if supplier_name else ""}
Остаток: {current_stock}, Точка заказа: {reorder_point}
{abc_info}
{price_hist_text}

Дай краткую оценку (2-4 предложения). Завершится строкой: РЕШЕНИЕ: Одобрить / Требует проверки / Отклонить"""

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text if msg.content else ""
    decision = "Требует проверки"
    for line in text.split('\n'):
        if 'РЕШЕНИЕ:' in line:
            decision = line.split('РЕШЕНИЕ:')[-1].strip()
            break
    risk = "low" if "Одобрить" in decision else ("high" if "Отклонить" in decision else "medium")
    return {"analysis": text, "decision": decision, "risk_level": risk, "model": "claude-sonnet-4-6"}
