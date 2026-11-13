These are frozen public HTML5 character-reference and Unicode case-mapping data,
generated from the existing Python3.11 standard-library contract. They contain no
candidate, account, application or browser data. The reference Unicode version is
recorded in `reference.json`; runtime Rust never imports Python or fetches these files.

Source references: [Python character references](https://docs.python.org/3.11/library/html.html),
[HTML5 entity data](https://docs.python.org/3.11/library/html.entities.html),
[Python Unicode database](https://docs.python.org/3.11/library/unicodedata.html).
The Python distribution's license notices are retained in `LICENSE-python.txt` and
apply to these generated reference data, without changing the parent repository license.

Regenerate and verify only with the pinned reference interpreter:

```sh
uv run --no-project --python .venv/bin/python python -m rust.scripts.export_html_contract
uv run --no-project --python .venv/bin/python python -m rust.scripts.export_html_contract --check
```

A reference-version change requires the full differential corpus before acceptance.
