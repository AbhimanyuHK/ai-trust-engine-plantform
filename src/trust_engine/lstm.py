"""Backward-compatible import path; implementation lives in forecasting."""
from trust_engine.forecasting.lstm_model import train_lstm
__all__ = ["train_lstm"]
