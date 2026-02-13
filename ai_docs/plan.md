# classy-slack-notifier: Implementation Plan

This plan breaks the design in `design.md` into concrete, ordered implementation steps. Each phase produces a testable checkpoint. Dependencies between phases are called out explicitly.

---

## Phase 0: Project Scaffolding

**Goal:** Set up the Python package structure, dependencies, tooling, and example config so that subsequent phases have a working skeleton to build on.

### 0.1 Create `pyproject.toml`
- Define project metadata (name, version `0.1.0`, description, Python `>=3.11` requirement).
- Declare runtime dependencies: `slack-bolt`, `slack-sdk`, `requests`, `pyyaml`.
- Declare dev dependencies: `pytest`, `pytest-mock`.
- Set the console entry point: `classy-slack-notifier = "classy_slack_notifier.main:main"`.
- Configure pytest (testpaths, etc.).

### 0.2 Create package directory structure
```
src/classy_slack_notifier/__init__.py   (empty)
src/classy_slack_notifier/main.py       (stub: `def main(): pass`)
tests/                                  (empty directory with __init__.py)
```

### 0.3 Create `config.example.yaml`
- Copy the full config schema from the design doc with all fields and inline comments.
- This serves as documentation and a starting point for users.

### 0.4 Create `.gitignore`
- Standard Python ignores: `__pycache__`, `*.pyc`, `.venv/`, `dist/`, `*.egg-info/`, `.mypy_cache/`.

### 0.5 Create `systemd/classy-slack-notifier.service`
- Copy the unit file from the design doc verbatim.

**Checkpoint:** `pip install -e .` succeeds; `classy-slack-notifier` entry point runs and exits cleanly.

---

## Phase 1: Data Models (`models.py`)

**Goal:** Define shared data structures that all other modules depend on. This has zero external dependencies and is the natural starting point.

### 1.1 Implement `models.py`
- `FilterAction` enum with values `SKIP`, `CLASSIFY`, `FORCE_NOTIFY`.
- `SlackMessage` dataclass with fields: `channel`, `channel_id`, `sender`, `sender_id`, `text`, `thread_ts` (optional), `is_dm` (bool), `is_mention` (bool).
- `Classification` dataclass with fields: `urgency` (int), `reason` (str).
- `FilterResult` dataclass with fields: `action` (FilterAction), `rule` (str).

### 1.2 Write `tests/test_models.py`
- Verify dataclass instantiation with valid values.
- Verify `FilterAction` enum members and their string values.
- Verify default values for optional fields on `SlackMessage`.

**Checkpoint:** `pytest tests/test_models.py` passes.

---

## Phase 2: Configuration (`config.py`)

**Goal:** Load, validate, and provide defaults for the YAML config file. This depends on `models.py` only for the `FilterAction` enum values used in validation.

### 2.1 Implement `config.py`
- Define a `Config` dataclass (or plain class) holding all typed config fields with defaults matching the design:
  - `model`: str = `"llama3.2:3b"`
  - `ollama_url`: str = `"http://localhost:11434"`
  - `ollama_timeout`: int = `3`
  - `urgency_threshold`: int = `3`
  - `system_prompt`: str = (default prompt from design)
  - `rules`: dict with keys `self`, `bots`, `mentions`, `dms`, `default` → `FilterAction`
  - `channels`: dict[str, FilterAction]
  - `keywords`: list of `{"pattern": str, "action": FilterAction}`
  - `notification_timeout`: int = `10`
- Implement `load_config(path: str) -> Config`:
  - Read and parse YAML.
  - Merge with defaults (missing keys get default values).
  - Validate:
    - `rules` values must be valid `FilterAction` strings.
    - `channels` values must be valid `FilterAction` strings.
    - `keywords` entries must each have `pattern` (str) and `action` (valid action).
    - `urgency_threshold` must be int in 1–5.
    - `ollama_timeout` must be positive number.
  - Log warnings for unknown top-level keys.
  - Raise clear errors on invalid values, identifying the offending field.
- Support config path resolution order: `--config` CLI arg > `CLASSY_CONFIG_PATH` env var > `~/.config/classy-slack-notifier/config.yaml`.

### 2.2 Write `tests/test_config.py`
- Test loading a valid config file (use `tmp_path` fixture to write a temp YAML).
- Test default values are applied for missing fields.
- Test validation errors for:
  - Invalid action string in `rules`.
  - `urgency_threshold` out of range.
  - Missing `pattern` or `action` in a keywords entry.
  - `ollama_timeout` <= 0.
- Test that unknown keys produce a logged warning but don't fail.

**Checkpoint:** `pytest tests/test_config.py` passes.

---

## Phase 3: Pre-Filter (`filters.py`)

**Goal:** Implement the rules-based pre-filter. Depends on `models.py` and `config.py`.

### 3.1 Implement `filters.py`
- `def pre_filter(msg: SlackMessage, config: Config) -> FilterResult`
- Implement the evaluation order from the design, returning on first match:
  1. **self** — compare `msg.sender_id` against a configured "own user ID" (stored in config or passed separately; see note below).
  2. **bots** — check a `is_bot` field (will need to be added to `SlackMessage` or passed as part of the event metadata; design says "messages from bot users" — revisit `SlackMessage` in Phase 1 if needed and add `is_bot: bool = False`).
  3. **keywords** — iterate `config.keywords` in order. For each entry:
     - If pattern starts with `regex:`, compile and search against `msg.text` (case-insensitive).
     - Otherwise, case-insensitive substring match against `msg.text`.
     - Return the keyword's action on first match.
  4. **mentions** — check `msg.is_mention`.
  5. **dms** — check `msg.is_dm`.
  6. **channels** — look up `msg.channel` in `config.channels`.
  7. **default** — return `config.rules["default"]` action.

**Note on "self" detection:** The bot's own user ID needs to be known at runtime. Add a `bot_user_id` field to `Config` (populated during Slack listener init via `auth.test` API call) or pass it as a parameter to `pre_filter`. Passing it as a parameter is cleaner since it's not a config-file concern.

### 3.2 Update `models.py` if needed
- Add `is_bot: bool = False` to `SlackMessage` if not already present (the design doc doesn't list it explicitly, but the filter needs it).

### 3.3 Write `tests/test_filters.py`
- Test each rule firing independently (one test per rule type):
  - Self message → action matches `rules.self`.
  - Bot message → action matches `rules.bots`.
  - Keyword substring match → correct action.
  - Keyword regex match → correct action.
  - Mention → action matches `rules.mentions`.
  - DM → action matches `rules.dms`.
  - Channel in `channels` map → correct action.
  - No match → default action.
- Test evaluation order (first-match-wins):
  - A bot message with a matching keyword: if `bots` is `skip`, keyword should NOT be reached.
  - A bot message with a matching keyword and `bots: classify`: keyword SHOULD be reached.
  - A DM that also matches a channel rule: DM should win.
- Test with different config action values (e.g., `bots: classify` instead of `skip`).

**Checkpoint:** `pytest tests/test_filters.py` passes.

---

## Phase 4: LLM Classifier (`llm_classifier.py`)

**Goal:** Implement the Ollama integration. Depends on `models.py` and `config.py`. No dependency on other components.

### 4.1 Implement `llm_classifier.py`
- `def classify(msg: SlackMessage, config: Config) -> Classification`
- Build the Ollama `/api/chat` request body:
  - `model`: from config.
  - `messages`: system prompt (from config) + user message (formatted: `Channel: ...\nSender: ...\nDM: yes/no\nMessage: ...`).
  - `format`: JSON schema object enforcing `{"urgency": int, "reason": str}`.
  - `stream: false`.
- Send POST request to `{config.ollama_url}/api/chat` with `config.ollama_timeout` as timeout.
- Parse the response JSON, extract `urgency` and `reason` from the `message.content` field.
- **Clamp** `urgency` to 1–5 range.
- **Error handling:**
  - `requests.ConnectionError`, `requests.Timeout` → log warning, return `Classification(urgency=config.urgency_threshold, reason="LLM unavailable — notifying as precaution")`.
  - Unexpected JSON structure → same fallback behavior.
  - Log all fallback activations at WARNING level.

### 4.2 Write `tests/test_classifier.py`
- Use `unittest.mock.patch` or `pytest-mock` to mock `requests.post`.
- Test successful classification: mock returns valid Ollama response → correct `Classification` returned.
- Test urgency clamping: mock returns urgency `0` → clamped to `1`; urgency `7` → clamped to `5`.
- Test timeout fallback: mock raises `requests.Timeout` → fallback classification returned.
- Test connection error fallback: mock raises `requests.ConnectionError` → fallback classification returned.
- Test malformed JSON fallback: mock returns non-JSON or missing fields → fallback classification.

**Checkpoint:** `pytest tests/test_classifier.py` passes.

---

## Phase 5: Notifier (`notifier.py`)

**Goal:** Implement desktop notifications via `notify-send`. No dependency on other components besides `models.py`.

### 5.1 Implement `notifier.py`
- `def notify(msg: SlackMessage, reason: str, urgency: int | None = None, config: Config) -> None`
- Build the notification:
  - **Title:** `Slack: #{msg.channel}` or `Slack: DM from @{msg.sender}` (if `msg.is_dm`).
  - **Body:** `{msg.text[:200]}` + `\n\n{reason}`.
  - **Urgency hint:** Map urgency score to libnotify level:
    - 1–2 → `low`
    - 3 → `normal`
    - 4–5 → `critical`
    - If urgency is `None` (force-notify case), use `normal`.
  - **Timeout:** `config.notification_timeout * 1000` (libnotify expects milliseconds).
- Execute: `subprocess.run(["notify-send", "--urgency=<level>", "--expire-time=<ms>", title, body])`.
- Log the notification at INFO level.

### 5.2 Write `tests/test_notifier.py`
- Mock `subprocess.run`.
- Test that correct arguments are passed to `notify-send` for:
  - A channel message with urgency 4 → `--urgency=critical`.
  - A DM → title uses `Slack: DM from @sender` format.
  - Force-notify (no urgency score) → `--urgency=normal`.
  - Low urgency → `--urgency=low`.
- Test message text truncation at 200 characters.
- Test timeout calculation (seconds → milliseconds).

**Checkpoint:** `pytest tests/test_notifier.py` passes.

---

## Phase 6: Slack Listener (`slack_listener.py`)

**Goal:** Implement the Socket Mode connection and event parsing. Depends on `models.py`. This is the primary integration point with external Slack APIs.

### 6.1 Implement `slack_listener.py`
- Create a class or module-level setup function that:
  - Initializes `slack_bolt.App` with the bot token (`SLACK_BOT_TOKEN` env var).
  - Initializes `slack_bolt.adapter.socket_mode.SocketModeHandler` with the app token (`SLACK_APP_TOKEN` env var).
  - Retrieves the bot's own user ID via `client.auth_test()` at startup (needed for self-message filtering).
- Implement event handler `handle_message_event(event, client)`:
  - **Deduplication:** Maintain a `collections.deque(maxlen=1000)` of recently seen event `client_msg_id` or `ts` values. Skip duplicates.
  - **Parse event into `SlackMessage`:**
    - `channel_id`: from `event["channel"]`.
    - `channel`: resolve via `client.conversations_info()` (with in-memory cache dict).
    - `sender_id`: from `event["user"]`.
    - `sender`: resolve via `client.users_info()` (with in-memory cache dict).
    - `text`: from `event["text"]`.
    - `thread_ts`: from `event.get("thread_ts")`.
    - `is_dm`: determine from `event["channel_type"]` (`"im"` or `"mpim"`).
    - `is_mention`: check if the bot user ID appears in `event["text"]` as `<@BOT_USER_ID>`.
    - `is_bot`: check `event.get("bot_id")` or `event.get("subtype") == "bot_message"`.
  - Return the constructed `SlackMessage` (or `None` if the event is unparseable / irrelevant subtype like `channel_join`).
- **Caching strategy:** Simple dicts for channel and user name resolution. No TTL for v1 — names rarely change, and the process restarts periodically. Log cache hits at DEBUG level.

### 6.2 Write `tests/test_slack_listener.py`
- Mock Slack `client` methods (`conversations_info`, `users_info`, `auth_test`).
- Test event parsing: provide a raw event dict → verify correct `SlackMessage` fields.
- Test DM detection: `channel_type: "im"` → `is_dm = True`.
- Test mention detection: text containing `<@U12345>` where U12345 is the bot user → `is_mention = True`.
- Test bot detection: event with `bot_id` → `is_bot = True`.
- Test deduplication: same event processed twice → second call returns `None`.
- Test unparseable event (missing `text` field, or subtype `channel_join`) → returns `None`.

**Checkpoint:** `pytest tests/test_slack_listener.py` passes.

---

## Phase 7: Main Entry Point & Pipeline (`main.py`)

**Goal:** Wire all components together into the complete message-handling pipeline. Depends on all previous phases.

### 7.1 Implement `main.py`
- `def main()`:
  - **Parse CLI args** using `argparse`:
    - `--config PATH` — override config file path.
    - `--log-level LEVEL` — override log level (DEBUG/INFO/WARNING/ERROR).
  - **Set up logging:** Configure `logging.basicConfig` with format including timestamp, level, module. Default level: INFO.
  - **Load config** via `config.load_config()`.
  - **Initialize Slack app and handler** via `slack_listener` module.
  - **Retrieve bot user ID** from the Slack `auth_test` call (done during listener init).
  - **Register the message handler** on the Slack app that implements the pipeline:
    ```
    event → parse → dedup → pre_filter → (skip | force_notify | classify → threshold check) → notify
    ```
  - **Signal handling:** Register `SIGTERM` and `SIGINT` handlers for graceful shutdown (call `handler.close()` or set a shutdown flag).
  - **Start** the Socket Mode handler (`handler.start()`).
- Implement the pipeline function `handle_message(event, client)` that orchestrates:
  1. Parse event into `SlackMessage` (via `slack_listener`).
  2. If `None`, return.
  3. Run `pre_filter(msg, config, bot_user_id)`.
  4. If `SKIP` → log debug, return.
  5. If `FORCE_NOTIFY` → call `notify(msg, reason=f"Matched rule: {result.rule}", config=config)`, log info, return.
  6. If `CLASSIFY` → call `classify(msg, config)`, log info with urgency/reason.
  7. If `classification.urgency >= config.urgency_threshold` → call `notify(msg, reason=classification.reason, urgency=classification.urgency, config=config)`.
- Add `if __name__ == "__main__": main()` block.
- Add a `__main__.py` file in the package so `python -m classy_slack_notifier` works.

### 7.2 Write `tests/test_main.py`
- Test the pipeline function in isolation (mock all component functions):
  - Message that gets SKIPped → verify `notify` not called, `classify` not called.
  - Message that gets FORCE_NOTIFYed → verify `notify` called, `classify` not called.
  - Message that gets CLASSIFYed above threshold → verify `classify` called, `notify` called.
  - Message that gets CLASSIFYed below threshold → verify `classify` called, `notify` not called.
- Test signal handling: verify graceful shutdown flag is set on SIGTERM.

**Checkpoint:** `pytest` (all tests) passes. The full application can be started with mock/real Slack tokens.

---

## Phase 8: Integration & Polish

**Goal:** Final verification, documentation, and packaging.

### 8.1 End-to-end manual testing
- Install the package in a venv (`pip install -e .`).
- Run with a real Slack workspace (or Slack sandbox) and Ollama running locally.
- Verify the complete flow: Slack message → filter → classify → notification appears.
- Test force-notify paths (DM, mention, keyword match).
- Test skip paths (self-message, bot message with default config).
- Test Ollama timeout/unavailable fallback (stop Ollama, send a message, verify notification still appears).

### 8.2 Update `README.md`
- Add installation instructions (`pip install .` or `pip install -e .`).
- Add configuration instructions (copy `config.example.yaml`, set Slack tokens in env file).
- Add systemd setup instructions.
- Add Slack app setup instructions (scopes, event subscriptions, Socket Mode).

### 8.3 Run full test suite
- `pytest` — all tests pass.
- Verify no import errors, no missing dependencies.

**Checkpoint:** Application is installable, configurable, and runs as a systemd user service.

---

## Dependency Graph

```
Phase 0 (scaffolding)
   │
   v
Phase 1 (models)
   │
   ├──────────────┬──────────────┐
   v              v              v
Phase 2        Phase 5        Phase 6
(config)       (notifier)     (slack_listener)
   │
   ├──────────┐
   v          v
Phase 3    Phase 4
(filters)  (classifier)
   │          │
   └────┬─────┘
        v
     Phase 7 (main)
        │
        v
     Phase 8 (integration)
```

**Parallelizable work:**
- Phases 3, 4, 5 can be developed in parallel once Phase 2 is complete.
- Phase 6 can be developed in parallel with Phases 2–5 (only depends on Phase 1).

---

## File Checklist

| File | Phase | Purpose |
|---|---|---|
| `pyproject.toml` | 0.1 | Package metadata and dependencies |
| `src/classy_slack_notifier/__init__.py` | 0.2 | Package marker |
| `src/classy_slack_notifier/main.py` | 0.2 (stub), 7.1 (full) | Entry point and pipeline |
| `src/classy_slack_notifier/__main__.py` | 7.1 | `python -m` support |
| `config.example.yaml` | 0.3 | Example configuration |
| `.gitignore` | 0.4 | Git ignores |
| `systemd/classy-slack-notifier.service` | 0.5 | systemd unit file |
| `src/classy_slack_notifier/models.py` | 1.1 | Shared data structures |
| `src/classy_slack_notifier/config.py` | 2.1 | Config loading and validation |
| `src/classy_slack_notifier/filters.py` | 3.1 | Pre-LLM rules engine |
| `src/classy_slack_notifier/llm_classifier.py` | 4.1 | Ollama classification |
| `src/classy_slack_notifier/notifier.py` | 5.1 | Desktop notifications |
| `src/classy_slack_notifier/slack_listener.py` | 6.1 | Slack Socket Mode integration |
| `tests/test_models.py` | 1.2 | Model tests |
| `tests/test_config.py` | 2.2 | Config tests |
| `tests/test_filters.py` | 3.3 | Filter tests |
| `tests/test_classifier.py` | 4.2 | Classifier tests |
| `tests/test_notifier.py` | 5.2 | Notifier tests |
| `tests/test_slack_listener.py` | 6.2 | Slack listener tests |
| `tests/test_main.py` | 7.2 | Pipeline integration tests |
