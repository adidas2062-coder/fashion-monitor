import subprocess

from collectors import musinsa_partners


class Completed:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_chrome_empty_osascript_uses_pyotp_fallback(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd[0])
        if cmd[0] == "pgrep":
            return Completed(stdout="123\n", returncode=0)
        return Completed(stdout="", returncode=0)

    monkeypatch.setattr(musinsa_partners.subprocess, "run", fake_run)
    monkeypatch.setattr(musinsa_partners, "_get_totp_from_secret", lambda keyword: "654321")

    assert musinsa_partners._get_totp_from_chrome("juwon5165") == "654321"
    assert calls.count("osascript") == 3


def test_chrome_off_goes_directly_to_pyotp_fallback(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd[0])
        if cmd[0] == "pgrep":
            return Completed(stdout="", returncode=1)
        raise AssertionError("osascript should not be called when Chrome is off")

    monkeypatch.setattr(musinsa_partners.subprocess, "run", fake_run)
    monkeypatch.setattr(musinsa_partners, "_get_totp_from_secret", lambda keyword: "111222")

    assert musinsa_partners._get_totp_from_chrome("juwon5165") == "111222"
    assert calls == ["pgrep"]


def test_chrome_and_pyotp_both_fail_returns_none(monkeypatch):
    def fake_run(cmd, **kwargs):
        if cmd[0] == "pgrep":
            return Completed(stdout="123\n", returncode=0)
        raise subprocess.SubprocessError("osascript failed")

    monkeypatch.setattr(musinsa_partners.subprocess, "run", fake_run)
    monkeypatch.setattr(musinsa_partners, "_get_totp_from_secret", lambda keyword: None)

    assert musinsa_partners._get_totp_from_chrome("juwon5165") is None


def test_secret_for_keyword_supports_aliases_and_env_override(monkeypatch):
    monkeypatch.setattr(musinsa_partners.config, "MUSINSA_TOTP_SECRET", "CONFIG_MUSINSA")
    monkeypatch.setenv("EDINBURGH_TOTP_SECRET", "ENV_EDINBURGH")

    assert musinsa_partners._secret_for_keyword("musinsa") == "CONFIG_MUSINSA"
    assert musinsa_partners._secret_for_keyword("edinburgh") == "ENV_EDINBURGH"
