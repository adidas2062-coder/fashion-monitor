import pytest

from collectors import download_sales


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def count(self):
        if self.selector == 'input[name="id"]':
            return 1
        if self.selector == 'input[name="code"]':
            return 1 if self.page.code_visible else 0
        return 1

    def fill(self, value):
        if self.selector == 'input[name="code"]':
            self.page.filled_code = value

    def click(self):
        if self.selector == 'button[type="submit"]':
            self.page.submit_count += 1
            if self.page.submit_count == 1:
                self.page.code_visible = True
            elif self.page.submit_count == 2 and not self.page.reject_code:
                self.page.code_visible = False

    def all(self):
        return []


class FakePage:
    url = "https://partner-sso.one.musinsa.com/oauth/login"

    def __init__(self, reject_code=False):
        self.reject_code = reject_code
        self.code_visible = False
        self.submit_count = 0
        self.filled_code = None

    def wait_for_load_state(self, *args, **kwargs):
        return None

    def locator(self, selector):
        return FakeLocator(self, selector)


def test_sso_login_raises_when_totp_code_unavailable(monkeypatch):
    page = FakePage()
    monkeypatch.setattr(download_sales.time, "sleep", lambda *_: None)
    monkeypatch.setattr(download_sales, "_secret_for_keyword", lambda _keyword: "")
    monkeypatch.setattr(download_sales, "_get_totp_from_chrome", lambda keyword: None)

    with pytest.raises(RuntimeError, match="TOTP 코드 획득 실패"):
        download_sales._sso_login(page, "user", "password", "user")


def test_sso_login_raises_when_totp_code_is_rejected(monkeypatch):
    page = FakePage(reject_code=True)
    monkeypatch.setattr(download_sales.time, "sleep", lambda *_: None)
    monkeypatch.setattr(download_sales, "_secret_for_keyword", lambda _keyword: "SECRET")
    monkeypatch.setattr(download_sales, "_get_totp_from_pyotp", lambda secret: "123456")

    with pytest.raises(RuntimeError, match=r"\[2FA\] 코드 거부됨"):
        download_sales._sso_login(page, "user", "password", "user")


def test_sso_login_does_not_raise_when_totp_is_accepted(monkeypatch):
    page = FakePage(reject_code=False)
    monkeypatch.setattr(download_sales.time, "sleep", lambda *_: None)
    monkeypatch.setattr(download_sales, "_secret_for_keyword", lambda _keyword: "SECRET")
    monkeypatch.setattr(download_sales, "_get_totp_from_pyotp", lambda secret: "123456")

    download_sales._sso_login(page, "user", "password", "user")

    assert page.filled_code == "123456"
    assert page.code_visible is False
