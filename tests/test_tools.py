"""
tests/test_tools.py

Pytest tests for each FitFindr tool.
LLM calls (suggest_outfit, create_fit_card) are mocked so tests run without
hitting the Groq API.
"""

import pytest
from unittest.mock import MagicMock, patch

from tools import search_listings, suggest_outfit, create_fit_card


# ── Shared fixtures ───────────────────────────────────────────────────────────

SAMPLE_ITEM = {
    "id": "test_001",
    "title": "Vintage Graphic Tee",
    "description": "A faded vintage band tee in great shape",
    "category": "tops",
    "style_tags": ["vintage", "graphic", "streetwear"],
    "size": "M",
    "condition": "good",
    "price": 22.0,
    "colors": ["black", "grey"],
    "brand": None,
    "platform": "depop",
}

SAMPLE_WARDROBE = {
    "items": [
        {
            "id": "w_001",
            "name": "Baggy straight-leg jeans, dark wash",
            "category": "bottoms",
            "colors": ["dark blue"],
            "style_tags": ["denim", "streetwear", "baggy"],
            "notes": "High-waisted",
        },
        {
            "id": "w_002",
            "name": "Chunky white sneakers",
            "category": "shoes",
            "colors": ["white"],
            "style_tags": ["streetwear", "chunky"],
            "notes": "",
        },
    ]
}

EMPTY_WARDROBE = {"items": []}


def _mock_groq_client(reply: str) -> MagicMock:
    """Build a mock Groq client that returns `reply` for any completion call."""
    choice = MagicMock()
    choice.message.content = reply
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


# ── search_listings ───────────────────────────────────────────────────────────

class TestSearchListings:

    def test_returns_results_for_matching_query(self):
        results = search_listings("vintage graphic tee")
        assert len(results) > 0
        assert all(isinstance(r, dict) for r in results)

    def test_results_sorted_by_relevance(self):
        # More specific query should surface the best match first
        results = search_listings("vintage band tee faded")
        assert len(results) > 0
        # Top result should contain at least one of the core keywords
        top_title = results[0]["title"].lower()
        top_tags = " ".join(results[0].get("style_tags", [])).lower()
        assert any(kw in top_title + top_tags for kw in ["vintage", "band", "tee", "faded"])

    # Failure mode: no listings match → must return empty list, not raise
    def test_returns_empty_list_when_nothing_matches(self):
        results = search_listings("designer ballgown encrusted", size="XXS", max_price=1.0)
        assert results == []

    def test_price_filter_excludes_over_budget_items(self):
        max_price = 20.0
        results = search_listings("vintage", max_price=max_price)
        assert all(r["price"] <= max_price for r in results)

    def test_size_filter_only_returns_matching_sizes(self):
        # Tops in the dataset use S/M/L — "S" is a safe size that exists
        results = search_listings("top shirt tee", size="S")
        assert len(results) > 0
        assert all("s" in r["size"].lower() for r in results)

    def test_no_size_or_price_filter_returns_all_matches(self):
        results_unfiltered = search_listings("vintage")
        results_filtered = search_listings("vintage", max_price=10.0)
        assert len(results_unfiltered) >= len(results_filtered)


# ── suggest_outfit ────────────────────────────────────────────────────────────

class TestSuggestOutfit:

    def test_returns_string_with_wardrobe(self):
        fake_reply = "Pair the tee with your baggy jeans and chunky sneakers for a 90s street look."
        with patch("tools._get_groq_client", return_value=_mock_groq_client(fake_reply)):
            result = suggest_outfit(SAMPLE_ITEM, SAMPLE_WARDROBE)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_wardrobe_items_referenced_in_prompt(self):
        """Wardrobe item names should be passed to the LLM prompt."""
        fake_reply = "Style it with your baggy jeans."
        with patch("tools._get_groq_client", return_value=_mock_groq_client(fake_reply)) as mock_get:
            suggest_outfit(SAMPLE_ITEM, SAMPLE_WARDROBE)
            call_args = mock_get.return_value.chat.completions.create.call_args
            prompt = call_args[1]["messages"][0]["content"]
            assert "Baggy straight-leg jeans" in prompt

    # Failure mode: empty wardrobe → must still return a non-empty string, not raise
    def test_empty_wardrobe_returns_general_advice(self):
        fake_reply = "This tee works great with wide-leg pants or cargo trousers."
        with patch("tools._get_groq_client", return_value=_mock_groq_client(fake_reply)):
            result = suggest_outfit(SAMPLE_ITEM, EMPTY_WARDROBE)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_wardrobe_does_not_raise(self):
        fake_reply = "General styling advice here."
        with patch("tools._get_groq_client", return_value=_mock_groq_client(fake_reply)):
            try:
                suggest_outfit(SAMPLE_ITEM, EMPTY_WARDROBE)
            except Exception as e:
                pytest.fail(f"suggest_outfit raised an exception on empty wardrobe: {e}")


# ── create_fit_card ───────────────────────────────────────────────────────────

class TestCreateFitCard:

    def test_returns_caption_string(self):
        outfit = "Baggy jeans, chunky sneakers, and this tee — 90s all the way."
        fake_reply = "found this vintage tee on depop for $22 and it was made for my baggies 🖤"
        with patch("tools._get_groq_client", return_value=_mock_groq_client(fake_reply)):
            result = create_fit_card(outfit, SAMPLE_ITEM)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_item_details_passed_to_prompt(self):
        """Title, price, and platform should appear in the LLM prompt."""
        outfit = "Some outfit description."
        fake_reply = "caption text"
        with patch("tools._get_groq_client", return_value=_mock_groq_client(fake_reply)) as mock_get:
            create_fit_card(outfit, SAMPLE_ITEM)
            call_args = mock_get.return_value.chat.completions.create.call_args
            prompt = call_args[1]["messages"][0]["content"]
            assert "Vintage Graphic Tee" in prompt
            assert "22" in prompt
            assert "depop" in prompt

    # Failure mode: empty outfit string → must return error message, not raise
    def test_empty_outfit_returns_error_string(self):
        result = create_fit_card("", SAMPLE_ITEM)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_outfit_does_not_call_llm(self):
        with patch("tools._get_groq_client", return_value=_mock_groq_client("")) as mock_get:
            create_fit_card("", SAMPLE_ITEM)
            mock_get.return_value.chat.completions.create.assert_not_called()

    # Failure mode: whitespace-only outfit → same guard should catch it
    def test_whitespace_outfit_returns_error_string(self):
        result = create_fit_card("   ", SAMPLE_ITEM)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_whitespace_outfit_does_not_call_llm(self):
        with patch("tools._get_groq_client", return_value=_mock_groq_client("")) as mock_get:
            create_fit_card("   ", SAMPLE_ITEM)
            mock_get.return_value.chat.completions.create.assert_not_called()
