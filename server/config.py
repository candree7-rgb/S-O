"""
S-O Trading System - Configuration
===================================
Simplified config for Universal Backtester + Bybit execution.
All settings via environment variables.
"""

import os
from dataclasses import dataclass, field


@dataclass
class APIConfig:
    """Bybit API Configuration"""
    api_key: str = field(default_factory=lambda: os.getenv("BYBIT_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("BYBIT_API_SECRET", ""))
    testnet: bool = field(default_factory=lambda: os.getenv("USE_TESTNET", os.getenv("BYBIT_TESTNET", "true")).lower() == "true")

    @property
    def base_url(self) -> str:
        if self.testnet:
            return "https://api-testnet.bybit.com"
        return "https://api.bybit.com"


@dataclass
class RiskConfig:
    """Risk Management"""
    max_risk_per_trade_pct: float = field(default_factory=lambda: float(os.getenv("RISK_PER_TRADE_PCT", os.getenv("RISK_PER_TRADE", "2.0"))))
    default_leverage: int = field(default_factory=lambda: int(os.getenv("MAX_LEVERAGE", os.getenv("DEFAULT_LEVERAGE", "20"))))
    max_position_size_pct: float = field(default_factory=lambda: float(os.getenv("MAX_POSITION_SIZE_PCT", "5")))
    tp_mode: str = field(default_factory=lambda: os.getenv("TP_MODE", "single"))  # "single" or "split"
    max_longs: int = field(default_factory=lambda: int(os.getenv("MAX_LONGS", "4")))
    max_shorts: int = field(default_factory=lambda: int(os.getenv("MAX_SHORTS", "4")))


@dataclass
class Config:
    """Main Configuration"""
    api: APIConfig = field(default_factory=APIConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)

    # Webhook
    webhook_secret: str = field(default_factory=lambda: os.getenv("WEBHOOK_SECRET", ""))

    # Server
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8080")))


# Global config instance
config = Config()
