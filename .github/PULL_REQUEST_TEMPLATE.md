## Summary

<!-- What does this PR change, and why? -->

## Related issue

<!-- e.g. Closes #123 -->

## Checklist

- [ ] Tests added/updated for the change
- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] `mypy . --ignore-missing-imports` passes
- [ ] `pytest` passes
- [ ] `python scripts/seed.py && python scripts/smoke_test.py` passes
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] No float introduced into a stored or computed quantity
- [ ] No core invariant weakened (leave balances, single-holder asset custody, forward-only state machines, append-only history, same-transaction audit rows)
