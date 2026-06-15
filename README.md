# FitFindr

A secondhand shopping agent that takes a natural-language query, finds matching listings, and returns a styled outfit suggestion plus a shareable caption — all in one shot.

---

## Setup

```bash
pip install -r requirements.txt
```

Add a `.env` file in the project root with your Groq API key (free at [console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

Run the app:

```bash
python app.py
```

Then open the URL shown in your terminal (usually `http://localhost:7860`).

---

## Tool Inventory

### `search_listings(description, size, max_price)`

**Inputs:**
- `description` (`str`) — keywords describing the item (e.g. `"vintage graphic tee"`). After parsing, context phrases like "to go with my jeans" are stripped so only the target item's attributes drive the search.
- `size` (`str | None`) — size token to filter by, or `None` to skip size filtering. Matching is a case-insensitive substring check, so `"M"` matches listings sized `"S/M"` or `"M/L"`.
- `max_price` (`float | None`) — price ceiling (inclusive), or `None` to skip.

**Output:** `list[dict]` — matching listing dicts sorted by relevance score, highest first. Each dict contains: `id`, `title`, `description`, `category`, `style_tags` (list), `size`, `condition`, `price` (float), `colors` (list), `brand`, `platform`. Returns an empty list if nothing matches.

**Purpose:** Filters the 40-item mock dataset by price and size, then scores remaining listings by keyword overlap with `description`. Stop words (`"a"`, `"to"`, `"for"`, `"with"`, etc.) are removed from the keyword set before scoring so common filler doesn't inflate scores for unrelated items.

---

### `suggest_outfit(new_item, wardrobe)`

**Inputs:**
- `new_item` (`dict`) — a listing dict returned by `search_listings`.
- `wardrobe` (`dict`) — a wardrobe dict with an `"items"` key containing a list of wardrobe item dicts. Each wardrobe item has `"name"` and `"style_tags"`.

**Output:** `str` — a non-empty string. On the happy path, 1–2 outfit suggestions naming specific wardrobe pieces. If `wardrobe["items"]` is empty, returns a fixed explanatory string immediately without calling the LLM.

**Purpose:** Builds a prompt from the listing's title, price, platform, style tags, colors, and a formatted list of wardrobe pieces, then calls `llama-3.3-70b-versatile` at temperature 0.7 to compose a personalized outfit recommendation.

---

### `create_fit_card(outfit, new_item)`

**Inputs:**
- `outfit` (`str`) — the outfit suggestion string returned by `suggest_outfit`.
- `new_item` (`dict`) — the listing dict for the thrifted item.

**Output:** `str` — a 2–4 sentence OOTD-style caption mentioning the item name, price, and platform once each. If `outfit` is empty or blank, returns `"Couldn't generate a fit card — outfit suggestion was empty."` without calling the LLM.

**Purpose:** Formats the outfit suggestion into a casual, shareable social media caption. Runs at temperature 1.0 (higher than `suggest_outfit`) so captions sound distinct across runs.

---

## How the Planning Loop Works

`run_agent(query, wardrobe)` is a fixed sequential pipeline. There is no LLM deciding which tool to call — the same steps always run in the same order. The only branching is early exit when a step produces nothing useful.

### Step 1 — Initialize session

`_new_session(query, wardrobe)` creates a fresh dict with all fields set to empty/None. Nothing carries over between calls.

### Step 2 — Parse the query (no LLM)

Three extractions run on the raw query text, each modifying a copy of the string:

1. **Price** — `re.search(r"\$(\d+(?:\.\d+)?)", text)` pulls out dollar amounts. `"under $30"` → `max_price = 30.0`. The matched span is cut from the text before the next step.
2. **Size** — scanned against `["XXL", "XL", "XS", "S", "M", "L"]` using `(?<!')\b{token}\b` with `re.IGNORECASE`. The `(?<!')` lookbehind prevents false matches inside contractions — without it, `"I'm"` would match `M` because apostrophes are non-word characters and create a word boundary on both sides of the letter. First match wins and is stripped from the text.
3. **Context trim** — `re.sub(r"\b(to go with|to wear with|to match|that goes? with)\b.*", "", text)` removes everything from the first context phrase onward. This prevents "I'm looking for black shoes to go with my baggy blue jeans" from scoring against jeans listings instead of shoe listings.
4. **Description** — whatever text remains after all three strips, collapsed to a single space.

All four values are stored in `session["parsed"]`.

### Step 3 — Search, with early exit

`search_listings(description, size, max_price)` is called. The result list is stored in `session["search_results"]`.

**Conditional:** If the result list is empty, `session["error"]` is set to a user-facing message and `run_agent` returns immediately. `suggest_outfit` and `create_fit_card` are never called.

### Step 4 — Select top result

`session["search_results"][0]` is saved as `session["selected_item"]`. No LLM, no ranking logic — the result is already sorted by score from `search_listings`.

### Step 5 — Suggest outfit

`suggest_outfit(new_item=session["selected_item"], wardrobe=session["wardrobe"])` is called. The return value is stored in `session["outfit_suggestion"]`.

**Conditional:** If `session["wardrobe"]["items"]` is empty, `suggest_outfit` returns the fixed "Your wardrobe is empty" string instead of calling the LLM. Back in `run_agent`, a check on `session["wardrobe"].get("items")` catches this case: `session["fit_card"]` is set to `None` and the function returns early. `create_fit_card` is not called, because there is no real outfit to caption.

### Step 6 — Create fit card

`create_fit_card(outfit=session["outfit_suggestion"], new_item=session["selected_item"])` is called only when the wardrobe had items. The return value is stored in `session["fit_card"]`.

**Conditional inside the tool:** If `outfit` is empty or whitespace-only, the function returns an error string without calling the LLM.

### Step 7 — Return session

The caller reads `session["error"]` first. If it is `None`, the run succeeded and `session["fit_card"]` is the final output.

### Where the LLM is and isn't called

| Step | LLM? | Reason |
|------|-------|--------|
| Parse query | No | Regex is deterministic and cheaper for structured extraction |
| Search listings | No | Keyword scoring over a fixed dataset |
| Select top result | No | Rank 0 of a pre-sorted list |
| Suggest outfit | Yes (unless wardrobe empty) | Needs language to compose a personalized recommendation |
| Create fit card | Yes (unless skipped) | Caption writing benefits from stylistic variation across runs |

---

## State Management

All state lives in a single `session` dict created at the start of each `run_agent()` call. There is no global state and nothing persists between calls.

```python
session = {
    "query":             str,         # original user string, kept for debugging
    "parsed":            dict,        # {"description": str, "size": str|None, "max_price": float|None}
    "search_results":    list[dict],  # full ranked list from search_listings()
    "selected_item":     dict|None,   # search_results[0]; None until Step 4
    "wardrobe":          dict,        # passed in from caller, never mutated
    "outfit_suggestion": str|None,    # return value of suggest_outfit(); None until Step 5
    "fit_card":          str|None,    # return value of create_fit_card(); None until Step 6
    "error":             str|None,    # set on early exit; None on success
}
```

**How state flows between tools:**

- `session["parsed"]` → feeds `description`, `size`, `max_price` into `search_listings`.
- `session["search_results"][0]` → becomes `session["selected_item"]`, the single listing dict passed to both `suggest_outfit` and `create_fit_card`.
- `session["outfit_suggestion"]` → passed as the `outfit` argument to `create_fit_card`.
- `session["selected_item"]` is read twice: by `suggest_outfit` (for the item summary in the prompt) and by `create_fit_card` (for the title, price, and platform in the caption).

No tool writes to a field owned by another tool. `search_listings` returns a list; the agent writes it to `session["search_results"]`. `suggest_outfit` returns a string; the agent writes it to `session["outfit_suggestion"]`. Each tool is called once and is unaware of the session dict.

---

## Error Handling

| Location | Failure mode | What happens | Concrete example from testing |
|----------|-------------|--------------|-------------------------------|
| `handle_query` (app.py) | Query is empty or whitespace | Returns `("Please enter a search query.", "", "")` before calling `run_agent` | Submitting a blank text box — panel 1 shows the message, panels 2 and 3 stay blank |
| `run_agent` after `search_listings` | No listings match the query | Sets `session["error"]`, returns immediately — `suggest_outfit` and `create_fit_card` are never called | `"designer ballgown size XXS under $5"` → 0 results → panel 1 shows `"No listings matched your search — try different keywords or a higher budget."` |
| `suggest_outfit` | Wardrobe is empty | Returns a fixed string immediately without calling the LLM | `"vintage graphic tee under $30"` with empty wardrobe → outfit panel shows `"Your wardrobe is empty, so I can't suggest specific outfit combinations..."` |
| `run_agent` after `suggest_outfit` | Wardrobe was empty (detected from `session["wardrobe"].get("items")`) | Sets `session["fit_card"] = None`, returns early — `create_fit_card` is not called | Same case as above — fit card panel is blank. Without this guard, `create_fit_card` received the "wardrobe is empty" explanatory string and hallucinated outfit pairings from the example items mentioned in it |
| `create_fit_card` | `outfit` argument is empty or blank | Returns `"Couldn't generate a fit card — outfit suggestion was empty."` without calling the LLM | Triggered if `suggest_outfit` somehow returns an empty string — acts as a last-resort guard |

---

## Spec Reflection

### One way the spec helped

The Architecture diagram in `planning.md` explicitly showed the early-exit arrow branching off `search_listings` and returning directly to the caller with an error, bypassing `suggest_outfit` and `create_fit_card`. Having that drawn out made it obvious that the pipeline needs to treat an empty result list as a terminal state, not pass it downstream. Without the diagram, it would have been tempting to just call `suggest_outfit` with `None` and let that function deal with it — which would have buried the error in the wrong place.

### One way implementation diverged from the spec

The spec said `suggest_outfit` should "offer general styling advice for the item" when the wardrobe is empty — meaning the LLM would still be called, just with a different prompt asking for hypothetical pairing suggestions. The implementation replaced this with a fixed string returned immediately, skipping the LLM entirely.

The reason: during testing, the LLM-generated general advice still produced confident outfit suggestions ("pair with wide-leg jeans and chunky sneakers"), which looked identical to real wardrobe-based suggestions. A user with an empty wardrobe would see two outfit ideas and assume the agent was working off their actual clothes. The fixed string makes the limitation explicit and tells the user exactly what to do next.

---

## AI Usage

### Instance 1: Implementing `suggest_outfit` from the Tool 2 spec

**What I directed the AI to do:** I gave Claude the Tool 2 block from `planning.md` — the description, the input parameters (`new_item: dict`, `wardrobe: dict`), the return value, and the failure mode ("if the wardrobe is empty, explain the issue and allow the user to restart"). I asked it to implement the function using `_get_groq_client()` and the `_MODEL` constant already defined in the file.

**What it produced:** A two-branch function. The non-empty wardrobe branch was correct — it built a prompt listing each wardrobe piece by name and style tags and asked the LLM to name specific pieces in the suggestion. The empty-wardrobe branch called the LLM with a general prompt asking for hypothetical outfit ideas — "what kinds of pieces pair well with this, what vibe it suits."

**What I revised:** I replaced the empty-wardrobe branch entirely. Instead of calling the LLM, the function now returns a fixed string immediately: `"Your wardrobe is empty, so I can't suggest specific outfit combinations. Add some items you already own..."`. The reason was discovered during testing — the LLM's hypothetical suggestions were indistinguishable from real ones, so a new user would not realize they needed to add wardrobe items. The fixed string is honest about the limitation and actionable.

---

### Instance 2: Implementing `run_agent` from the Architecture diagram and State Management table

**What I directed the AI to do:** I gave Claude the Architecture diagram (the ASCII flowchart from `planning.md`) and the State Management table mapping each session field to which step sets and reads it. I asked it to implement `run_agent()` and `_new_session()` so the pipeline matched the diagram exactly.

**What it produced:** A working sequential pipeline that initialized the session, parsed the query with regex, ran the three tools in order, and returned early with `session["error"]` when `search_listings` returned nothing. The session fields were set correctly at each step.

**What I revised:** Two things. First, after running the full app against the query `"I'm looking for a pair of black shoes to go with my baggy blue jeans"`, the agent returned a polo shirt. Tracing through the parse step revealed that `\bM\b` matched the `m` in `"I'm"` (apostrophes are `\W` in Python regex, creating a false word boundary), which silently set `size="M"` and filtered out all shoes in the dataset — every shoe uses a numeric size like `"US 7"`. I fixed this by changing the regex to `(?<!')\b{token}\b` and added a context-phrase strip before building the description. Second, the generated code called `create_fit_card` unconditionally after `suggest_outfit`. During a verify runthrough I found that when the wardrobe was empty, `create_fit_card` received the "Your wardrobe is empty" message as its `outfit` argument and hallucinated outfit pairings from the example clothing mentioned in that message ("jeans, sneakers, go-to jacket"). I added an early return in `run_agent` that skips `create_fit_card` whenever `session["wardrobe"]["items"]` is empty.

---

## Project Structure

```
fitfindr/
├── agent.py          # planning loop — run_agent() and _new_session()
├── tools.py          # search_listings, suggest_outfit, create_fit_card
├── app.py            # Gradio UI and handle_query()
├── planning.md       # design spec written before implementation
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # wardrobe format + example wardrobe
└── utils/
    └── data_loader.py         # load_listings, get_example_wardrobe, get_empty_wardrobe
```

---

## Running Tests

```bash
pytest tests/
```

---

## Demo

The demo covers the three main paths through the planning loop:

1. **Happy path** — query with size and price filter, example wardrobe → all three panels populate with a listing, outfit suggestion, and fit card
2. **No-results path** — query that matches nothing (e.g. `"designer ballgown size XXS under $5"`) → error message in panel 1, panels 2 and 3 blank
3. **Empty wardrobe path** — valid query, empty wardrobe → listing found, outfit panel shows the "add some items" message, fit card panel blank

To reproduce:
- Start the app with `python app.py`
- Use the example queries pre-loaded in the UI, or type your own
- Toggle the wardrobe radio between "Example wardrobe" and "Empty wardrobe (new user)" to see path 3
