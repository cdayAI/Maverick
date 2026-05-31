"""Built-in fallback prompt-injection rules.

When ``agent-shield`` (the full SDK with F1 0.988 detection) isn't
installed, we still want *some* safety, not a wide-open no-op. This
module provides a small but real set of regex rules covering the
highest-impact attack categories from the agent-shield README:

  - prompt injection / instruction hijacking (ignore-previous, override-system)
  - role hijacking (DAN, developer mode, jailbreak templates)
  - data exfiltration markers (markdown image leaks, base64 url params)
  - tool-abuse markers (rm -rf, /etc/passwd, .env exfil)

The full agent-shield SDK detects ~115 patterns; this fallback covers
~20 of the most common ones. Good enough to block the obvious attacks;
weak against sophisticated obfuscation (homoglyphs, base64-wrapped
payloads, etc.). The installer's smoke test makes this gap visible to
users via the "agent-shield not installed" warning.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Rule:
    name: str
    severity: str           # "low" | "medium" | "high" | "critical"
    pattern: re.Pattern
    description: str


def _compile(p: str) -> re.Pattern:
    return re.compile(p, re.IGNORECASE)


# Severity guidance:
#   low      -> notice; never blocks at any profile
#   medium   -> blocks at 'strict' (threshold='medium')
#   high     -> blocks at 'balanced' (threshold='high') and stricter
#   critical -> blocks at all enforcing profiles (incl. 'permissive')
RULES: list[Rule] = [
    # Prompt injection / override
    Rule("ignore_previous", "high",
         _compile(r"\b(ignore|disregard|forget)\s+(all|every|the)?\s*(previous|prior|above|earlier|preceding)\s+(instructions?|prompts?|rules?|context)"),
         "Classic prompt-injection: instruction override"),
    Rule("override_system", "high",
         _compile(r"\b(override|bypass|disable)\s+(the\s+)?(system|safety|guardrails?)\s+(prompt|rules?|filter)"),
         "System-prompt override attempt"),
    Rule("chatml_injection", "critical",
         _compile(r"(<\|im_start\|>|<\|im_end\|>|<\|system\|>|\[INST\]|\[\/INST\])"),
         "ChatML / LLaMA delimiter injection"),
    Rule("system_prompt_leak", "medium",
         _compile(r"\b(reveal|show|print|repeat|output)\s+(your|the)?\s*(system|original|initial)\s+(prompt|instructions?|context)"),
         "System prompt extraction attempt"),

    # Role hijacking
    Rule("dan_jailbreak", "critical",
         _compile(r"\b(DAN|do anything now|developer mode|jailbreak|unfiltered\s+ai)\b"),
         "DAN / developer-mode jailbreak"),
    Rule("persona_takeover", "high",
         _compile(r"\byou\s+are\s+now\s+(an?\s+)?(unrestricted|uncensored|amoral|evil)\s+(ai|assistant|model)"),
         "Persona takeover"),

    # Data exfiltration
    Rule("markdown_image_exfil", "high",
         _compile(r"!\[[^\]]*\]\(https?:\/\/[^)]+\?[^)]*(token|key|password|secret|api)"),
         "Markdown image URL with credentials in query"),
    Rule("base64_url_exfil", "medium",
         _compile(r"https?:\/\/[^\s]+\?[^=]*=[A-Za-z0-9+\/]{40,}={0,2}"),
         "URL parameter with base64 payload"),

    # Tool abuse markers (these trigger on tool-call args, not free text)
    Rule("rm_rf_root", "critical",
         _compile(r"\brm\s+-rf\s+(\/|~|\$HOME)(\s|$|\/)"),
         "rm -rf against /, ~, or $HOME"),
    Rule("sensitive_file_read", "high",
         _compile(r"(\/etc\/(passwd|shadow|ssh)|~\/\.ssh\/|~\/\.aws\/credentials|\.env\b)"),
         "Read of /etc/passwd, ssh keys, AWS creds, or .env"),
    Rule("curl_pipe_shell", "critical",
         _compile(r"(curl|wget)\s+[^|]+\|\s*(sh|bash|zsh|python)\b"),
         "curl-pipe-to-shell remote code execution"),
    Rule("reverse_shell", "critical",
         _compile(r"(bash\s+-i\s+>&\s+\/dev\/tcp\/|nc\s+-e\s+\/bin\/(sh|bash))"),
         "Reverse shell payload"),

    # Social engineering markers
    Rule("urgency_authority", "medium",
         _compile(r"\bthis\s+is\s+(an?\s+)?(emergency|urgent|critical)\b.*\b(execute|run|do)\s+(immediately|now|asap)"),
         "Urgency + authority pressure"),
    Rule("false_preapproval", "medium",
         _compile(r"\b(the\s+user|admin|operator)\s+(has\s+)?already\s+(approved|authorized|allowed)"),
         "False pre-approval claim"),

    # Obfuscation hints (broad, low severity)
    Rule("zero_width_chars", "low",
         _compile(r"[​-‏ - ⁠-⁯]"),
         "Zero-width / bidi characters"),
]


SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _threshold_to_min_severity(threshold: str) -> int:
    # Normalize: block_threshold comes from user-typed TOML. A non-lowercase or
    # padded spelling ("Medium", " high ") missed the lookup and silently fell
    # back to "high", strengthening the gate past the operator's intent.
    return SEVERITY_ORDER.get(str(threshold).strip().lower(), SEVERITY_ORDER["high"])


def scan(
    text: str,
    block_threshold: str = "high",
) -> tuple[bool, str, list[str]]:
    """Run all rules over ``text``.

    Returns (blocked, max_severity, matched_rule_names).
    Blocked = True iff any rule fired at or above the configured threshold.
    """
    threshold_idx = _threshold_to_min_severity(block_threshold)
    matched: list[str] = []
    max_idx = -1
    max_sev = "none"
    for r in RULES:
        if r.pattern.search(text):
            matched.append(r.name)
            idx = SEVERITY_ORDER[r.severity]
            if idx > max_idx:
                max_idx = idx
                max_sev = r.severity
    blocked = max_idx >= threshold_idx and len(matched) > 0
    return blocked, max_sev, matched
