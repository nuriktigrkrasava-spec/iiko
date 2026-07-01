"""Чистый расчёт теоретического фудкоста из техкарт и цен. Без зависимостей от приложения."""


def compute_recipe_foodcost(sales: list, recipes: dict, prices: dict) -> dict:
    """Теоретический фудкост из техкарт и цен.
    sales=[{productId,name,category,revenue,count}], recipes={pid:[{productId,amount}]}, prices={pid:cost}.
    base_rev — выручка блюд, у которых ЕСТЬ техкарта (их можно оценить).
    coverage_pct — доля ВСЕЙ выручки продаж, приходящаяся на полностью оценённые блюда.
    """
    total_sold_rev = 0.0
    base_rev = 0.0
    fact_sum = 0.0
    covered_rev = 0.0
    out_dishes = []
    for s in sales:
        rev = float(s.get("revenue", 0) or 0)
        cnt = float(s.get("count", 0) or 0)
        total_sold_rev += rev
        recipe = recipes.get(s.get("productId"))
        if not recipe:
            out_dishes.append({"name": s.get("name", ""), "category": s.get("category", ""),
                               "revenue": rev, "count": cnt, "cost_pct": None})
            continue
        base_rev += rev
        cost_per_portion = 0.0
        all_priced = True
        for ing in recipe:
            price = prices.get(ing.get("productId"))
            if price is None:
                all_priced = False
                continue
            cost_per_portion += float(ing.get("amount", 0) or 0) * float(price)
        dish_cost = cost_per_portion * cnt
        fact_sum += dish_cost
        if all_priced and recipe:
            covered_rev += rev
        out_dishes.append({
            "name": s.get("name", ""), "category": s.get("category", ""),
            "revenue": rev, "count": cnt,
            "cost_pct": (round(dish_cost / rev * 100, 1) if rev else None),
        })
    fact_pct = round(fact_sum / base_rev * 100, 1) if base_rev else None
    coverage_pct = round(covered_rev / total_sold_rev * 100, 1) if total_sold_rev else 0.0
    out_dishes.sort(key=lambda d: (d["cost_pct"] if d["cost_pct"] is not None else -1), reverse=True)
    return {"fact_sum": fact_sum, "base_rev": base_rev, "fact_pct": fact_pct,
            "coverage_pct": coverage_pct, "dishes": out_dishes}
