# Meridian Dynamics corpus authoring guide

Use `TEMPLATE.md` for each company document. Front matter is metadata for human
review and future fixture tooling; numbered headings are retrieval boundaries.
PDF fixtures are generated from the Markdown sources in `sources/`, preserving
the same headings as visible, extractable text.

Write for retrieval:

- Keep one topic in each section and make the section understandable on its own.
- Prefer 150–400 words per operational section. Split a section when two
  unrelated employee intents would otherwise share a chunk.
- Repeat the exact owning team, priority, target response, and escalation
  threshold in prose. Never leave a routable fact only in a heading or table.
- Include natural ticket language, such as “VPN keeps disconnecting,” beside
  the formal service name.
- Use concrete thresholds. State “an outage affecting 10 or more users is P1,”
  not “a major outage is urgent.”
- Cross-reference another policy by its `MD-IT-NNN` identifier.

Review before approval:

1. Confirm all front-matter fields and numbered sections are present and in
   order.
2. Confirm every named support team and taxonomy value exists in
   `taxonomy.json`.
3. Confirm every ticket grounding reference identifies a real document section
   that explicitly supports its labels.
4. Extract every PDF with `pypdf` and verify non-empty text and 1-based page
   numbering.
5. Treat generated documents and ticket labels as drafts until a FlowForge code
   owner completes gates G9.1–G9.4 and G1.5.

