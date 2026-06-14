"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

_MODEL = "llama-3.3-70b-versatile"


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform
    """
    listings = load_listings()

    # Filter by price
    if max_price is not None:
        listings = [l for l in listings if l["price"] <= max_price]

    # Filter by size (case-insensitive substring match)
    if size is not None:
        size_lower = size.lower()
        listings = [l for l in listings if size_lower in l["size"].lower()]

    # Score each listing by keyword overlap with description
    keywords = set(re.sub(r"[^a-z0-9\s]", "", description.lower()).split())

    def score(listing: dict) -> int:
        searchable = " ".join([
            listing.get("title", ""),
            listing.get("description", ""),
            listing.get("category", ""),
            " ".join(listing.get("style_tags", [])),
            " ".join(listing.get("colors", [])),
            listing.get("brand", "") or "",
        ]).lower()
        return sum(1 for word in keywords if word in searchable)

    scored = [(score(l), l) for l in listings]
    scored = [(s, l) for s, l in scored if s > 0]
    scored.sort(key=lambda x: x[0], reverse=True)

    return [l for _, l in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offers general styling advice for the item.
    """
    client = _get_groq_client()

    item_summary = (
        f"{new_item.get('title')} — ${new_item.get('price')}, "
        f"{new_item.get('platform')}, {new_item.get('condition')} condition. "
        f"Style tags: {', '.join(new_item.get('style_tags', []))}. "
        f"Colors: {', '.join(new_item.get('colors', []))}."
    )

    wardrobe_items = wardrobe.get("items", [])

    if not wardrobe_items:
        return (
            "Your wardrobe is empty, so I can't suggest specific outfit combinations. "
            "Add some items you already own (like jeans, sneakers, or a go-to jacket) "
            "and I'll put together looks using what you actually have."
        )

    wardrobe_text = "\n".join(
        f"- {item.get('name')} ({', '.join(item.get('style_tags', []))})"
        for item in wardrobe_items
    )
    prompt = (
        f"You are a personal stylist. A user just found this thrifted item:\n\n"
        f"{item_summary}\n\n"
        f"Here's what's already in their wardrobe:\n{wardrobe_text}\n\n"
        f"Suggest 1–2 complete outfits using the new item and specific pieces "
        f"from their wardrobe. Be specific — name the exact wardrobe pieces, "
        f"describe the overall vibe, and add one small styling tip per look."
    )

    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )

    return response.choices[0].message.content.strip()


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, returns a descriptive error message string.

    The caption:
    - Feels casual and authentic (like a real OOTD post, not a product description)
    - Mentions the item name, price, and platform naturally (once each)
    - Captures the outfit vibe in specific terms
    - Sounds different each time (higher LLM temperature)
    """
    if not outfit or not outfit.strip():
        return "Couldn't generate a fit card — outfit suggestion was empty."

    client = _get_groq_client()

    title = new_item.get("title", "this piece")
    price = new_item.get("price", "")
    platform = new_item.get("platform", "")

    prompt = (
        f"Write a 2–4 sentence Instagram/TikTok caption for this outfit:\n\n"
        f"Item: {title} — ${price} from {platform}\n"
        f"Outfit: {outfit}\n\n"
        f"Rules:\n"
        f"- Sound like a real person posting an OOTD, not a brand or stylist\n"
        f"- Mention the item name, price, and platform once each, naturally\n"
        f"- Capture the specific vibe of the outfit\n"
        f"- Keep it short, casual, and lowercase\n"
        f"- No hashtags"
    )

    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=1.0,
    )

    return response.choices[0].message.content.strip()
