# classy-slack-notifier

Simple & lightweight utility that watches for incoming Slack notifications via Slack's "socket mode" and
passes notifications off to a local LLM model via Ollama for priority classifications. Built primarily for
Linux systems which use `libnotify`.

Includes options for channels which will _never_ notify, and options for when to _always_ notify, etc.

## Configuration

Easily configurable via a config file to allow:
- prompt customization
- priority level customization
- notification customization based on priority level
- Ollama model selection  
