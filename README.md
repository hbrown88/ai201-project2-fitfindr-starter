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

## How the Planning Loop Works

The agent runs a **fixed, sequential pipeline** — not a dynamic loop where the LLM decides which tool to call next. Every run attempts the same three tools in the same order. The only real decision point is whether to halt early.

### Step 1 — Parse the query (no LLM)

Before calling any tool, `run_agent()` extracts three parameters from the user's raw text using regex:

- **Price** — matched with `\$(\d+(\.\d+)?)`. If found, the match is stripped from the text before the next step.
- **Size** — scanned against a fixed token list (`XS`, `S`, `M`, `L`, `XL`, `XXL`) using whole-word matching. The first match wins and is stripped from the text.
- **Description** — whatever text is left after removing price and size. This is the search keyword string.

This means the agent never calls the LLM just to understand what the user typed. A query like `"vintage graphic tee under $30, size M"` becomes `description="vintage graphic tee,"`, `size="M"`, `max_price=30.0` before any tool is called.

### Step 2 — Search for listings

`search_listings(description, size, max_price)` filters the 40-item mock dataset and scores each listing by keyword overlap with the description. It returns a ranked list.

**Decision: what if nothing matches?**
If the result list is empty, the agent sets `session["error"]` to a helpful message and returns immediately. It does not call `suggest_outfit` on an empty input — that would either crash or produce a nonsense outfit.

### Step 3 — Select the top result

The agent takes `search_results[0]` — the highest-scoring listing — as `selected_item`. There is no LLM involved in ranking or selection; the score is pure keyword overlap from Step 2.

### Step 4 — Suggest an outfit (LLM call #1)

`suggest_outfit(selected_item, wardrobe)` builds a prompt from the listing's title, price, platform, style tags, and colors, then calls `llama-3.3-70b-versatile` via Groq.

**Decision: what if the wardrobe is empty?**
If `wardrobe["items"]` is empty, the function returns a fixed string immediately — no LLM call — explaining that outfit combinations require wardrobe items and telling the user what to add. This is a fast, cheap exit that gives the user actionable feedback rather than a generic "no results" message.

If the wardrobe has items, the prompt lists them and asks the LLM to name specific pieces in the suggestion.

### Step 5 — Create the fit card (LLM call #2)

`create_fit_card(outfit_suggestion, selected_item)` passes the outfit string and the listing's title/price/platform to the LLM and asks it to write a 2–4 sentence OOTD caption. Temperature is set to 1.0 here (vs. 0.7 for outfit suggestions) so captions feel distinct each run.

**Decision: what if the outfit string is empty?**
`create_fit_card` checks whether its `outfit` argument is empty or blank before calling the LLM. If it is, it returns a descriptive error string rather than sending a useless prompt.

### Step 6 — Return the session

The caller (Gradio's `handle_query`) reads `session["error"]` first. If it's `None`, the run succeeded and `session["fit_card"]` is the final output. If it's set, only the error message is shown.

### Where the LLM is and isn't used

| Step | LLM? | Why / Why not |
|------|-------|---------------|
| Parse query | No | Regex is faster, cheaper, and more predictable for extracting price and size |
| Search listings | No | Keyword scoring over a fixed dataset doesn't need language understanding |
| Select top result | No | Rank 0 of the sorted list is deterministic |
| Suggest outfit | Yes | Needs language to compose a coherent, personalized recommendation |
| Create fit card | Yes | Caption writing benefits from stylistic variation |

---

## What Happens When Things Go Wrong

| Situation | What the agent does |
|-----------|---------------------|
| Empty query | `handle_query` returns early before calling `run_agent` |
| No listings match | Sets `session["error"]`, skips `suggest_outfit` and `create_fit_card`, returns immediately |
| Wardrobe is empty | `suggest_outfit` returns a plain string (no LLM call) telling the user to add items |
| `create_fit_card` receives an empty outfit string | Returns a descriptive error string without calling the LLM |

---

## State Management

All state lives in a single `session` dict created at the start of each `run_agent()` call. Nothing is global; nothing persists between calls.

```
session = {
    "query":             # original user string
    "parsed":            # { description, size, max_price } from regex
    "search_results":    # ranked list from search_listings()
    "selected_item":     # search_results[0]
    "wardrobe":          # passed in from caller
    "outfit_suggestion": # string from suggest_outfit()
    "fit_card":          # string from create_fit_card()
    "error":             # None on success, message string on early exit
}
```

Each tool reads from the session and writes only to its own field. No tool modifies data written by a prior tool.

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

## AI Usage

### Instance 1: Implementing `suggest_outfit` from the Tool 2 spec

**Input given:** The Tool 2 block from `planning.md` — the description ("analyze the clothing in the users wardrobe; then, suggest an outfit"), the input parameters (`new_item: dict`, `wardrobe: dict`), the return value description, and the failure mode ("if the wardrobe is empty, explain the issue").

**What it produced:** A two-branch function. When the wardrobe had items, it built a prompt listing each wardrobe piece by name and style tags, then asked the LLM to name specific pieces in the suggestion. When the wardrobe was empty, it built a *different* prompt asking the LLM for general styling advice — "what kinds of pieces pair well with this, what vibe it suits, and how to wear it."

**What I changed:** The empty-wardrobe branch still called the LLM, which costs a round-trip and returns outfit ideas framed as if the user has clothes. I overrode this to return a plain string immediately — no API call — that tells the user specifically what to add ("jeans, sneakers, or a go-to jacket") and why the suggestion can't be generated yet. This is faster, cheaper, and gives the user something actionable instead of hypothetical outfit ideas for a wardrobe they don't have.

---

### Instance 2: Implementing `run_agent` from the Architecture diagram and State Management table

**Input given:** The Architecture diagram in `planning.md` (the ASCII flowchart showing `_new_session → parse → search_listings → [early exit or] select → suggest_outfit → create_fit_card → return`) plus the State Management table mapping each session field to which step sets it and which reads it.

**What it produced:** A working sequential pipeline that parsed the query with regex, ran the three tools in order, stored results in the session dict, and returned early with `session["error"]` if `search_listings` returned nothing.

**What I changed:** The generated code called `create_fit_card` unconditionally after `suggest_outfit`, including when the wardrobe was empty. In that case `create_fit_card` received the "Your wardrobe is empty" message string as its `outfit` argument, treated it as a real outfit, and hallucinated pairings from the example items mentioned in the message ("jeans, sneakers, go-to jacket"). I added an early return in `run_agent` after `suggest_outfit` that skips `create_fit_card` entirely when `session["wardrobe"]["items"]` is empty — because there's no actual outfit to caption.

---

## Demo

The demo covers the three main paths through the planning loop:

1. **Happy path** — query with size and price filter, example wardrobe → all three panels populate
2. **No-results path** — query that matches nothing (e.g., `"designer ballgown size XXS under $5"`) → error message in the first panel, other panels blank
3. **Empty wardrobe path** — valid query, empty wardrobe → listing found, outfit panel shows the "add some items" message instead of a styled suggestion

To reproduce:
- Start the app with `python app.py`
- Use the example queries pre-loaded in the UI, or type your own
- Toggle the wardrobe radio between "Example wardrobe" and "Empty wardrobe (new user)" to see path 3
