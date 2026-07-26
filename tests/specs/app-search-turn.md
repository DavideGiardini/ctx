# Contract — a search turn driven through the app

What this pins: one user submit can now append **more than two** nodes, because tool
output lands in the conversation line at the moment the tool ran. The doubles
(`HarnessProvider`, `HarnessSearch`) make that drivable with no network.

Scope note: this is deliberately scoped down. The change under test is ~90 lines of
test scaffolding plus a one-line injection parameter, so the contract covers only the
two claims a realistic regression to *this* change could break: the chronological node
shape of a triggered turn, and the untouched shape of an untriggered one. The `FETCH`,
`SEARCHFAIL` and `SEARCHLOOP` scripts are verified by a later end-to-end QA pass and are
intentionally absent here.

Terminology: *the turn's slice* means the nodes from the user node carrying the
submitted text through to the end of `app.core.nodes`. Assertions are made on that
slice rather than on the whole list, so incidental preamble (included context,
breadcrumbs) cannot make or break the ordering claim.

---

C1. A triggered turn appends lead-in, tool output, and answer in chronological order
  Given:  a `ChatApp` wired to `HarnessProvider` and `HarnessSearch`, with the web
          tools reachable (the `search_enabled` fixture), and an empty conversation.
  When:   the user submits a message carrying the `SEARCH` trigger word, and the turn
          is awaited to completion.
  Expect: the turn's slice of `app.core.nodes` is exactly four nodes, in this order:
          1. the user node — `node_type == "message"`, `role == "user"`;
          2. an assistant node — `node_type == "message"`, `role == "assistant"`,
             `content` beginning with the round-1 lead-in `"Let me look that up."`;
          3. a search node — `node_type == "search"`;
          4. a second assistant node — `node_type == "message"`,
             `role == "assistant"`, `content == "".join(CANNED_RESPONSE)`.
          And afterwards `app.core.streaming is False`.
  Rationale: the whole point of routing tool results through the graph is that the
          line reads in the order things actually happened — lead-in, then what the
          search returned, then the answer written on top of it. A search node that
          lands after both assistant nodes (or a single merged assistant node
          swallowing both rounds) tells the reader a false story about the turn, so
          position, not mere presence, is the assertion.

C2. An untriggered turn is exactly the pre-change two-node turn
  Given:  the same wiring as C1 — including the web tools being reachable, so the
          only thing distinguishing this case is the message text.
  When:   the user submits a message containing no trigger word, and the turn is
          awaited to completion.
  Expect: the turn's slice is exactly two nodes — the user node
          (`node_type == "message"`, `role == "user"`) followed by one assistant node
          (`node_type == "message"`, `role == "assistant"`,
          `content == "".join(CANNED_RESPONSE)`) — and **no** node anywhere in
          `app.core.nodes` has `node_type == "search"`. Afterwards
          `app.core.streaming is False`.
  Rationale: adding a tool path must not change ordinary chat. This is also the guard
          against a too-loose trigger match: the trigger vocabulary is `SEARCH`,
          `SEARCHFAIL`, `SEARCHLOOP`, `FETCH`, and `SEARCHFAIL` contains `SEARCH` as a
          substring, so sloppy matching is a live risk. Pinning that an ordinary
          sentence triggers nothing — while tools *are* on offer, so a stray match
          would really fire — is the cheapest half of that guard.

No further items. A third item was considered (asserting what the search node's
`content` and `role` are, so an empty tool node would be caught) and dropped: the
interface does not state either, so any expected value would be invented rather than
derived. See the ambiguities below.

---

## Ambiguities / what I could not pin

1. **The search node's `role` and `content` are unspecified.** The interface tells me
   only that `node_type == "search"`. I therefore assert nothing about the rendered
   text of the tool result or which role owns it, which means a regression that
   appends a *correctly positioned but empty* search node would pass C1. If the
   intended shape is defined (e.g. "role is `assistant`, content lists the hit titles
   and URLs from `HARNESS_HITS`"), tell me and I will add that assertion to C1 rather
   than a new test.
2. **Whether the round-2 answer of a tool turn is the same canned text as an ordinary
   turn.** `CANNED_RESPONSE` is documented as what an *ordinary* (non-tool) turn
   streams, while the `SEARCH` script is described only as "round 2 streams the canned
   answer". I read those as the same single canned answer and assert
   `content == "".join(CANNED_RESPONSE)` in both C1 and C2. If the tool turn has its
   own distinct final text, C1's fourth assertion is wrong and needs that constant
   exported instead.
3. **Whether a submitted message reaches the user node verbatim.** I locate the turn's
   slice by finding the last user node whose `content` contains the submitted text,
   rather than equalling it, so a wrapper or trailing decoration around the submitted
   text does not misidentify the slice.
