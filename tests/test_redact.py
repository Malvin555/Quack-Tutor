from quack.redact import redact


def test_key_value_quoted():
    out = redact('password = "hunter2"')
    assert "hunter2" not in out and "***REDACTED_SECRET***" in out


def test_key_value_env_style():
    out = redact("API_KEY=abc123def456ghi789")
    assert "abc123def456ghi789" not in out


def test_openai_and_openrouter_keys():
    assert "REDACTED_OPENAI_KEY" in redact("sk-" + "A1b2C3d4E5f6G7h8I9j0K1")
    assert "REDACTED_OPENAI_KEY" in redact("sk-or-v1-" + "a1b2c3d4e5f6a7b8c9d0e1f2")


def test_github_token():
    assert "REDACTED_GITHUB_TOKEN" in redact("ghp_" + "a" * 36)


def test_slack_token():
    assert "REDACTED_SLACK_TOKEN" in redact("xoxb-123456-abcdef-ghijkl")


def test_private_key_keeps_line_count():
    text = "a\n-----BEGIN RSA PRIVATE KEY-----\nMIIB\nabc\n-----END RSA PRIVATE KEY-----\nb"
    out = redact(text)
    assert "MIIB" not in out and "REDACTED_PRIVATE_KEY" in out
    assert out.count("\n") == text.count("\n")


def test_aws_key():
    assert "REDACTED_AWS_KEY" in redact("AKIA" + "ABCDEFGHIJKLMNOP")


def test_noop_keeps_code_intact():
    code = "token = get_token(user)\nSESSIONS[token] = time.time()\nmax_tokens = 5000\n"
    assert redact(code) == code
