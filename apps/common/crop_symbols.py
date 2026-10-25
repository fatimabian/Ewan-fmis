"""Consistent, recognizable symbols for Rosario crop commodities."""

CROP_SYMBOLS = {
    "rice": "🌾",
    "corn": "🌽",
    "coconut": "🥥",
    "high value crops": "🌱",
    "livestock": "🐄",
    "poultry": "🐔",
    "banana": "🍌",
    "mango": "🥭",
    "calamansi": "🍊",
    "coffee": "☕",
    "cacao": "🫘",
    "cassava": "🍠",
    "sweet potato": "🍠",
    "peanut": "🥜",
    "mung bean": "🫘",
    "eggplant": "🍆",
    "tomato": "🍅",
    "string beans": "🫘",
    "squash": "🎃",
    "bitter gourd": "🥒",
    "chili pepper": "🌶️",
    "leafy vegetables": "🥬",
    "carabao": "🐃",
    "cattle": "🐄",
    "swine": "🐖",
    "goat": "🐐",
    "sheep": "🐑",
    "chicken": "🐔",
    "rhode island red": "🐔",
    "plymouth rock": "🐔",
    "leghorn": "🐔",
    "gamefowl": "🐓",
    "duck": "🦆",
    "quail": "🐦",
    "turkey": "🦃",
    "rabbit": "🐇",
}


def crop_symbol(crop_name):
    normalized = (crop_name or "").strip().lower()
    if normalized in CROP_SYMBOLS:
        return CROP_SYMBOLS[normalized]
    for name, symbol in CROP_SYMBOLS.items():
        if name in normalized:
            return symbol
    return "🌱"
