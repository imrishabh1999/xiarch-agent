"""Recovery policy: maps (tool, failure category) -> action. Kept as a table so it is easy to read,
test and explain. Escalation after a step runs out of attempts is handled by the executor:
search -> cache fallback; no usable evidence at all -> one replan; still nothing -> partial report."""

# failure category = the text before ':' in the critic's reason
POLICY = {
    # (tool, category)                : action
    ("web_search", "timeout"):        "retry",          # transient: same call again, with backoff
    ("web_search", "http_500"):       "retry",
    ("web_search", "search_error"):   "retry",
    ("web_search", "crash"):          "retry",
    ("web_search", "malformed"):      "retry",          # garbage is often a one-off bad response
    ("web_search", "empty"):          "reformulate",    # same query will give the same nothing
    ("web_search", "stale"):          "reformulate",
    ("web_search", "invalid_args"):   "reformulate",
    ("reason", "too_few"):            "gather_more",    # one broader search, then reason again
    ("reason", "ungrounded"):         "retry_with_feedback",
    ("reason", "stale"):              "retry_with_feedback",
    ("reason", "duplicate"):          "retry_with_feedback",
    ("reason", "malformed"):          "retry_with_feedback",
    ("reason", "reason_failed"):      "retry",
    ("*", "bind_failed"):             "rebind",          # give the LLM the validation error
    ("*", "invalid_args"):            "rebind",
}


def category(reason: str) -> str:
    return (reason or "error").split(":", 1)[0].strip()


def decide(tool: str, reason: str) -> str:
    cat = category(reason)
    return POLICY.get((tool, cat)) or POLICY.get(("*", cat)) or "retry"
