"""Map basket categories to ABS CPI expenditure classes and groups.

Codes come from the ABS codelist CL_CPI_INDEX v1.0.0 (dataflow ABS,CPI,2.0.0),
checked against the live API in Nov 2026. Each basket category is one CPI
*expenditure class*, which rolls up to one CPI *sub-group*. That gives us two
levels at which to compare our basket index with official CPI.
"""

from __future__ import annotations

from dataclasses import dataclass

FOOD_GROUP_CODE = "20001"  # Food and non-alcoholic beverages

CPI_GROUPS: dict[str, str] = {
    "30002": "Bread and cereal products",
    "30003": "Meat and seafoods",
    "30001": "Dairy and related products",
    "114120": "Fruit and vegetables",
    "131179": "Food products n.e.c.",
    "131180": "Non-alcoholic beverages",
}


@dataclass(frozen=True)
class CpiClass:
    code: str
    name: str
    group_code: str

    @property
    def group_name(self) -> str:
        return CPI_GROUPS[self.group_code]


# basket category slug -> CPI expenditure class
CATEGORY_TO_CPI: dict[str, CpiClass] = {
    "bread": CpiClass("40005", "Bread", "30002"),
    "cakes_biscuits": CpiClass("40006", "Cakes and biscuits", "30002"),
    "breakfast_cereals": CpiClass("40007", "Breakfast cereals", "30002"),
    "other_cereals": CpiClass("40008", "Other cereal products", "30002"),
    "beef_veal": CpiClass("40009", "Beef and veal", "30003"),
    "pork": CpiClass("131178", "Pork", "30003"),
    "lamb_goat": CpiClass("40010", "Lamb and goat", "30003"),
    "poultry": CpiClass("40012", "Poultry", "30003"),
    "other_meats": CpiClass("40014", "Other meats", "30003"),
    "fish_seafood": CpiClass("40015", "Fish and other seafood", "30003"),
    "milk": CpiClass("40001", "Milk", "30001"),
    "cheese": CpiClass("40002", "Cheese", "30001"),
    "ice_cream_dairy": CpiClass("40004", "Ice cream and other dairy products", "30001"),
    "fruit": CpiClass("114121", "Fruit", "114120"),
    "vegetables": CpiClass("114122", "Vegetables", "114120"),
    "eggs": CpiClass("40027", "Eggs", "131179"),
    "jams_spreads": CpiClass("40029", "Jams, honey and spreads", "131179"),
    "condiments": CpiClass("97549", "Food additives and condiments", "131179"),
    "oils_fats": CpiClass("97550", "Oils and fats", "131179"),
    "snacks_confectionery": CpiClass("115501", "Snacks and confectionery", "131179"),
    "other_food": CpiClass("40034", "Other food products n.e.c.", "131179"),
    "coffee_tea": CpiClass("40030", "Coffee, tea and cocoa", "131180"),
    "soft_drinks_juices": CpiClass("115520", "Waters, soft drinks and juices", "131180"),
}


def cpi_class_for(category: str) -> CpiClass:
    """Return the CPI class for a basket category, or raise KeyError with a helpful message."""
    try:
        return CATEGORY_TO_CPI[category]
    except KeyError:
        known = ", ".join(sorted(CATEGORY_TO_CPI))
        raise KeyError(f"Unknown category '{category}'. Known categories: {known}") from None
