# Contributing

Fork the repository, create a branch, and open a pull request against `main`.

1. Keep `scripts/change_neighbor.py` and `play/resources/change_neighbor.py` byte-identical.
2. Run `python3 -m unittest discover -s tests -v` before you push.
3. Do not commit `__pycache__`, `.pyc`, `.DS_Store`, or Rote sidecars (`.rote-flow-lint.json`, `.rote-release.lock`).
4. Keep recommendations cautious: files **may deserve review**. Do not claim a change is required or incomplete.
5. Do not add network calls, adapters, or target-repo code execution.

Play frontmatter `version` is the Play version. `rote play info` may show `0.80.0`; that is `rote_version`.
