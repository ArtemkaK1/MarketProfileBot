from types import SimpleNamespace
from zoneinfo import ZoneInfo

from market_profile_bot.config import Settings
from market_profile_bot.models import Direction
from market_profile_bot.mt5_executor import MT5Executor


def settings() -> Settings:
    return Settings(
        webhook_secret="secret",
        mt5_login=None,
        mt5_password=None,
        mt5_server=None,
        mt5_symbol="GER40",
        mt5_volume=0.1,
        mt5_deviation=20,
        mt5_magic=404011,
        mt5_sl_points=None,
        mt5_tp_points=None,
        dry_run=True,
        auto_trade=False,
        timezone=ZoneInfo("Europe/Berlin"),
    )


def test_take_profit_for_one_to_one_rr():
    executor = MT5Executor(settings())

    assert executor._take_profit_for_rr(100.0, 95.0, Direction.LONG, 1.0) == 105.0
    assert executor._take_profit_for_rr(100.0, 105.0, Direction.SHORT, 1.0) == 95.0


def test_risk_volume_uses_one_percent_equity_and_volume_step():
    executor = MT5Executor(settings())
    account_info = SimpleNamespace(equity=10_000.0, balance=10_000.0)
    symbol_info = SimpleNamespace(
        trade_tick_size=1.0,
        trade_tick_value=1.0,
        point=1.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
    )

    volume = executor._risk_volume(
        price=100.0,
        sl=90.0,
        risk_percent=1.0,
        account_info=account_info,
        symbol_info=symbol_info,
    )

    assert volume == 10.0
