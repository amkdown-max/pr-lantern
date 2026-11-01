# Contributing

Please keep changes small enough to review and include a reproducible example for bugs.

Run the checks from a checkout with Python 3.10 or later:

```sh
python -m pip install . ruff
python -m unittest discover -s tests -v
python -m ruff check .
```

Tests must not require network access or GitHub credentials. Mock the GitHub CLI boundary and exercise the observable behavior of snapshots and reports.

AI-assisted contributions are welcome. Disclose the assistance, verify the result, and report which checks you actually ran. Do not claim a human review that did not happen. The same correctness and reviewability requirements apply to every contribution.

Do not include authentication tokens, local state files, or private repository data in issues or pull requests.
