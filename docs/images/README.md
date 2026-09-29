# Demo assets

## `cowork-demo.gif`

The recording embedded at the top of the root [README](../../README.md), under
**See it in action**.

It is a screen capture of a real Claude Cowork session driving this MCP server —
not a mock-up. Match the house format set by
[open-ledger](https://github.com/Attri-Inc/open-ledger):

| Property | Target |
|---|---|
| Format | GIF (`GIF89a`, looping) |
| Dimensions | 1280 × 832 |
| Frames | ~70–80 |
| File size | under ~700 KB (GitHub renders it inline; keep it light) |

### Recording it

1. Seed a fresh database so the demo company is in a known state:
   ```bash
   python scripts/seed.py
   ```
2. Register OpenHR as a connector in Cowork — see
   [docs/claude-connector.md](../claude-connector.md#3c-connect-to-claude-cowork).
3. Drive one coherent story rather than a tour of every tool. A good arc, all of
   which the seeded data supports:
   - *"Who's out on leave this week?"* — `get_leave_calendar`
   - *"How much earned leave does Dev have left?"* — `get_leave_balance`
   - *"Book him two days on 22–23 October."* — `request_leave`
   - *"Now give him twenty-five days."* — the refusal quotes the exact balance,
     which is the whole point of the project
   - *"Is Karan cleared to leave?"* — `get_exit_checklist` shows the access card
     still outstanding
4. Crop to the conversation pane, export at the dimensions above, and save as
   `cowork-demo.gif` in this directory.

No other change is needed — the README already points here.
