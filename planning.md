# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->

Parse listings across all data and return all of the clothing listings that match the users prompts criteria best. Use all data provided in the description if possible, if something isn't specified, then ignore that field.

ex. "Faded Band Tee — $22, Depop, Good condition."

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `description` (str): Every physical attribute about the clothing
- `size` (str): The clothing items size
- `max_price` (float) The price that the clothing item should either match or be below

**What it returns:**
<!-- Describe the return value — what fields does a result contain? -->

Returns all listings that follow every parameter provided by the prompt.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if no listings match? -->

Alert the user that no listings have been found that follow their description. If search_listings returns nothing, FitFindr tells the user what to try differently and stops — it does not call suggest_outfit with empty input.

### Tool 2: suggest_outfit

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->

As an AI stylist, you have the ability to curate and assemble outfits based off a clothing item provided and style of the user. Following search_listings, you should choose the top matched clothing item returned and analyze the clothing in the users wardrobe; Then, suggest an outfit that uses the previous listing and the clothing in the users wardrobe that best match the users style and parameters. 

ex. "Pair this with your wide-leg jeans and platform Docs for a classic 90s grunge look. Roll the sleeves once and tuck the front corner slightly for shape."

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `new_item` (dict): The clothing item/listing from search listings
- `wardrobe` (dict): The users wardrobe 

**What it returns:**
<!-- Describe the return value -->

A curated outfit based off of the users preferences and specifications

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the wardrobe is empty or no outfit can be suggested? -->

Explain the issue to the user and what went wrong. Allow the user to restart at the same step just use a new input.

---

### Tool 3: create_fit_card

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->

Curate a message that summarizes the selected listed item. This message is should be like the messages that accompany a link when shared with others,

ex. "thrifted this faded band tee off depop for $22 and honestly it was made for my wide-legs 🖤 full look in my stories"

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `outfit` (str): The outfit suggestion created in the last step
- `selected_item` (dict): The listing dict chosen from search results

**What it returns:**
<!-- Describe the return value -->

Returns a message/summary of the selected clothing item and how it pairs with the users wardrobe. This should also connect to the users social media plug

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the outfit data is incomplete? -->

Explain the issue to the user and what went wrong. Allow the user to restart at the same step just use a new input.

---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

---

## Planning Loop

**How does your agent decide which tool to call next?**

The planning loop in `run_agent()` follows a fixed, sequential pipeline — there is no branching LLM-driven "should I call this tool?" step. The agent always attempts the same three tools in the same order; the only decision point is whether to halt early.

**Step-by-step logic:**

1. **Start a session** — `_new_session(query, wardrobe)` spins up a fresh dict that'll hold everything for this run. Nothing carries over between calls.

2. **Break down the query** — pull `description`, `size`, and `max_price` out of whatever the user typed. Price comes from a `\$(\d+(\.\d+)?)` regex, size gets matched against the usual tokens (XS through XXL), and the leftover text becomes the description. All three land in `session["parsed"]`.

3. **Search for listings** — feed `description`, `size`, and `max_price` into `search_listings()` and stash the results in `session["search_results"]`. If nothing comes back, write a message into `session["error"]` and bail — no point calling the other two tools on an empty list.

4. **Grab the best match** — `session["search_results"][0]` is the top hit by relevance; save it to `session["selected_item"]` so the next steps have something to work with.

5. **Build an outfit** — pass `selected_item` and the user's `wardrobe` into `suggest_outfit()`. The result goes into `session["outfit_suggestion"]`.

6. **Write the fit card** — `create_fit_card()` gets `outfit_suggestion` and `selected_item` and produces the final shareable caption, saved to `session["fit_card"]`.

7. **Hand it back** — the caller reads `session["error"]` first; if it's clear, `session["fit_card"]` is the output.

**How it knows it's done:** either `create_fit_card` finishes and we're on the happy path, or an empty search result flips `session["error"]` and we exit early. No retries, no loops.

---

## State Management

**How does information from one tool get passed to the next?**

All state lives in a single `session` dict created by `_new_session()` at the start of each `run_agent()` call. There is no global state and no external storage — the dict is passed by reference through every step of the loop and returned at the end.

**Fields and their lifecycle:**

| Field | Set by | Read by | Purpose |
|-------|--------|---------|---------|
| `session["query"]` | `_new_session()` | (reference only) | Original user string, kept for debugging |
| `session["parsed"]` | Query parsing (Step 2) | `search_listings` call (Step 3) | Dict with `description`, `size`, `max_price` keys |
| `session["search_results"]` | `search_listings()` (Step 3) | Early-exit check + Step 4 | Full list of matching listing dicts, sorted by score |
| `session["selected_item"]` | Step 4 (index 0 of search_results) | `suggest_outfit()` + `create_fit_card()` | The single listing dict the rest of the run operates on |
| `session["wardrobe"]` | `_new_session()` (passed in from caller) | `suggest_outfit()` (Step 5) | User's wardrobe dict with an `items` list |
| `session["outfit_suggestion"]` | `suggest_outfit()` (Step 5) | `create_fit_card()` (Step 6) | LLM-generated outfit string |
| `session["fit_card"]` | `create_fit_card()` (Step 6) | Caller / Gradio UI | Final sharable caption string |
| `session["error"]` | Early-exit condition (Step 3) | Caller / Gradio UI | Non-None string signals the run ended early |

**Data flow between tools:**

- `search_listings` → `suggest_outfit`: `session["selected_item"]` is the listing dict returned by `search_listings` at rank 0. It contains fields like `title`, `style_tags`, `colors`, `category`, and `price` that `suggest_outfit` uses to build its LLM prompt.
- `suggest_outfit` → `create_fit_card`: `session["outfit_suggestion"]` (a plain string) is passed as the `outfit` argument. `session["selected_item"]` is also passed again so `create_fit_card` can reference the item's name, price, and platform in the caption.
- No tool mutates data written by a prior tool — each tool reads from the session and writes only to its own designated field.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Explain to the user the fields that were missing and request a new response |
| suggest_outfit | Wardrobe is empty | Explain to the user the specific problem and solution |
| create_fit_card | Outfit input is missing or incomplete | Explain to the user the specific problem and solution |

---

## Architecture

```
User query + wardrobe
        |
        v
Planning Loop
        |
        |-- _new_session(query, wardrobe)
        |       Session: query = "...", wardrobe = {...}
        |
        |-- Parse query (description, size, max_price)
        |       Session: parsed = { description, size, max_price }
        |
        |-- search_listings(description, size, max_price)
        |       |-- [ERROR] no results → session.error = "No listings matched..." ──→ return session
        |       |
        |       results = [item, ...]
        |       Session: search_results = [...]
        |       Session: selected_item = search_results[0]
        |
        |-- suggest_outfit(selected_item, wardrobe)
        |       |-- [ERROR] wardrobe empty → session.error = "Can't suggest outfit..." ──→ return session
        |       |
        |       Session: outfit_suggestion = "..."
        |
        └── create_fit_card(outfit_suggestion, selected_item)
                |-- [ERROR] missing data → session.error = "Can't create fit card..." ──→ return session
                |
                Session: fit_card = "..."
                        |
                        v
                Return session
```

---

## AI Tool Plan

<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

Which AI tool you plan to use - I will use Claude to analyze the planning.md and create/implement the methods based on everything in this spec.
What you'll give it as input - The planning.md folder and the rest of the code for more context. The AI should take in input regarding the users wardrobe and questions about listings.
What you expect it to produce - Claude will produce the code and structure for the code. The AI will return outfits, filtered listings, and outfit cards.
How you'll verify the output matches your spec before moving on - QA test with Claude Code and actually using the AI to make sure all features work.

**Milestone 3 — Individual tool implementations:**

I'll give Claude each tool's spec (inputs, return value, failure mode) one at a time and ask it to implement the function using the data loader. For `search_listings`, I'll test it against at least 3 queries (one with all fields, one missing size, one with no matches) before moving on. Same process for `suggest_outfit` and `create_fit_card`.

**Milestone 4 — Planning loop and state management:**

I'll give Claude the Architecture diagram and State Management table and ask it to implement `run_agent()` and `_new_session()`. I'll verify by running two end-to-end queries — one that hits the happy path and one that triggers the early exit — and checking that `session["fit_card"]` and `session["error"]` are set correctly.

---

## A Complete Interaction (Step by Step)

You are an AI stylist that has the ability to find clothing listing, suggest outfits, create outfit cards. As a stylist, you need to recognize and learn the users style to solve queries based on the users input.

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**

The agent parses the query and pulls out: `description = "vintage graphic tee"`, `max_price = 30.0`, `size = None` (not specified). It calls `search_listings(description="vintage graphic tee", size=None, max_price=30.0)`. Results come back — say 4 listings — sorted by relevance. The top result is "Faded Nirvana Tee — $24, Depop, Good condition." That gets saved as `selected_item`.

**Step 2:**

With `selected_item` in hand, the agent calls `suggest_outfit(selected_item, wardrobe)`. The wardrobe has baggy jeans and chunky sneakers already in it. The tool returns: "Pair the Nirvana tee with your baggy jeans and chunky sneakers — tuck the front corner slightly and leave the rest loose for that 90s feel."

**Step 3:**

The agent calls `create_fit_card(outfit_suggestion, selected_item)` to turn the outfit into a shareable caption. It returns: "found this faded nirvana tee on depop for $24 and it was made for my baggies 🖤 full look dropping soon." The session is returned with `fit_card` set and `error` as None.

**Final output to user:**

The Gradio UI displays the fit card caption and the outfit suggestion side by side. The user sees the listing details (title, price, platform), the styled outfit recommendation, and the ready-to-copy caption.
