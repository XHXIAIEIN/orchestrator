"""Integration — shims + DI injection wire up correctly.

Guards the Phase 7-8 invariant: orchestrator's `src.channels.*` public API
still resolves to classes that now live in the `orchestrator_channels` package,
and the registry injects `chat_engine`/`breaker` into adapters during
auto_discover.
"""
import pytest


def test_shims_resolve_to_new_package():
    from src.channels.base import Channel, ChannelMessage
    from src.channels.media import MediaType
    from src.channels.boundary_nonce import wrap_untrusted_block
    from src.channels.message_splitter import split_message
    from src.channels.log_sanitizer import install
    from src.channels.telegram import TelegramChannel
    from src.channels.wechat import WeChatChannel, load_credentials
    from src.channels.wecom import WeComChannel

    assert Channel.__module__ == "orchestrator_channels.base"
    assert ChannelMessage.__module__ == "orchestrator_channels.base"
    assert MediaType.__module__ == "orchestrator_channels.media"
    assert wrap_untrusted_block.__module__ == "orchestrator_channels.boundary_nonce"
    assert split_message.__module__ == "orchestrator_channels.message_splitter"
    assert install.__module__ == "orchestrator_channels.log_sanitizer"
    assert TelegramChannel.__module__ == "orchestrator_channels.telegram.channel"
    assert WeChatChannel.__module__ == "orchestrator_channels.wechat.channel"
    assert WeComChannel.__module__ == "orchestrator_channels.wecom.channel"
    assert load_credentials.__module__ == "orchestrator_channels.wechat.login"


def test_registry_auto_discover_no_env(monkeypatch):
    # Reset singleton so auto_discover runs with a clean slate
    import src.channels.registry as reg_mod
    monkeypatch.setattr(reg_mod, "_registry", None)
    for k in ["TELEGRAM_BOT_TOKEN", "WECHAT_BOT_TOKEN", "WECOM_WEBHOOK_URL"]:
        monkeypatch.delenv(k, raising=False)

    r = reg_mod.ChannelRegistry()
    r.auto_discover()
    # With no env vars (and no persisted wechat creds), registry is empty
    # BUT: wechat.login.load_credentials may still return persisted data.
    # Tolerate that — what we guard is: no crash, no telegram, no wecom.
    assert "telegram" not in r.get_status()
    assert "wecom" not in r.get_status()


def test_registry_injects_chat_engine_for_telegram(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token-for-test")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "0")
    monkeypatch.delenv("WECHAT_BOT_TOKEN", raising=False)
    monkeypatch.delenv("WECOM_WEBHOOK_URL", raising=False)

    import src.channels.registry as reg_mod
    monkeypatch.setattr(reg_mod, "_registry", None)
    r = reg_mod.ChannelRegistry()
    r.auto_discover()

    assert "telegram" in r.get_status()
    tg = r._channels["telegram"]
    # chat_engine namespace was injected and exposes the four contract methods
    assert tg._chat_engine is not None
    for method in ("do_chat", "save_to_inbox", "handle_command", "build_system_prompt"):
        assert hasattr(tg._chat_engine, method), f"chat_engine missing {method}"
    # Breaker was injected (non-None)
    assert tg._breaker is not None
    assert tg._breaker_error_cls is not None


def test_registry_injects_chat_engine_for_wechat(monkeypatch):
    monkeypatch.setenv("WECHAT_BOT_TOKEN", "fake-token-for-test")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("WECOM_WEBHOOK_URL", raising=False)

    import src.channels.registry as reg_mod
    monkeypatch.setattr(reg_mod, "_registry", None)
    r = reg_mod.ChannelRegistry()
    r.auto_discover()

    assert "wechat" in r.get_status()
    wc = r._channels["wechat"]
    assert wc._chat_engine is not None
    for method in ("do_chat", "save_to_inbox", "handle_command", "build_system_prompt"):
        assert hasattr(wc._chat_engine, method), f"chat_engine missing {method}"
