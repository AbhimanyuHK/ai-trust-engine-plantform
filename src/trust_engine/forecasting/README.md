# Forecasting

Owns structured transaction-based forecasting: load and calendarize normalized transaction history, engineer lag/rolling/calendar features, train and evaluate XGBoost, optionally train an LSTM, and persist predictions and model metadata in Snowflake.

Contract PDFs are not forecasting inputs. Forecasting consumes structured facts; workflows may pass approved contract terms or authoritative royalty rates as business context. The model must never infer commercial terms from raw PDFs.
