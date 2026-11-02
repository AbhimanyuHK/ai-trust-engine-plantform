"""Leakage-aware daily revenue forecasting using XGBoost."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error,mean_squared_error
from xgboost import XGBRegressor
from trust_engine.common.infrastructure.db import connection

@dataclass
class ForecastResult:
    rows: pd.DataFrame
    model_name: str
    model_version: str
    mae: float
    rmse: float

def load_daily_revenue(partner_id: str | None=None) -> pd.DataFrame:
    sql="""SELECT TRANSACTION_DATE AS DS,PARTNER_ID,SUM(AMOUNT) AS Y FROM CORE.TRANSACTIONS WHERE TRANSACTION_DATE IS NOT NULL"""
    params: tuple[Any,...]=()
    if partner_id: sql+=" AND PARTNER_ID=%s"; params=(partner_id,)
    sql+=" GROUP BY TRANSACTION_DATE,PARTNER_ID ORDER BY TRANSACTION_DATE"
    with connection() as conn,conn.cursor() as cur:
        cur.execute(sql,params); frame=cur.fetch_pandas_all()
    if frame is None or frame.empty: return pd.DataFrame(columns=["DS","PARTNER_ID","Y"])
    frame.columns=[c.upper() for c in frame.columns]
    return frame

def _features(frame: pd.DataFrame) -> pd.DataFrame:
    result=frame.sort_values("DS").copy()
    for lag in (1,3,7,12): result[f"LAG_{lag}"]=result["Y"].shift(lag)
    for window in (7,30): result[f"ROLLING_{window}"]=result["Y"].shift(1).rolling(window).mean()
    dates=pd.to_datetime(result["DS"])
    result["DAY_OF_WEEK"],result["MONTH"],result["DAY_OF_YEAR"]=dates.dt.dayofweek,dates.dt.month,dates.dt.dayofyear
    return result.dropna().reset_index(drop=True)

def train_and_forecast(history: pd.DataFrame,horizon_days: int=60,partner_id: str | None=None) -> ForecastResult:
    if not 1<=horizon_days<=180: raise ValueError("horizon_days must be between 1 and 180")
    if history.empty: raise ValueError("No transaction history available")
    if partner_id and "PARTNER_ID" in history: history=history[history["PARTNER_ID"]==partner_id]
    daily=history.groupby("DS",as_index=False)["Y"].sum().sort_values("DS")
    daily["DS"]=pd.to_datetime(daily["DS"])
    daily=daily.set_index("DS").asfreq("D",fill_value=0).rename_axis("DS").reset_index()
    features=_features(daily)
    if len(features)<40: raise ValueError("At least 40 feature-complete daily observations are required")
    cols=[c for c in features.columns if c not in {"DS","Y"}]
    split=max(1,int(len(features)*0.8)); train,valid=features.iloc[:split],features.iloc[split:]
    if valid.empty: train,valid=features.iloc[:-1],features.iloc[-1:]
    model=XGBRegressor(n_estimators=300,max_depth=5,learning_rate=0.04,subsample=0.9,colsample_bytree=0.9,objective="reg:squarederror",random_state=42,n_jobs=4)
    model.fit(train[cols],train["Y"]); pred=model.predict(valid[cols])
    mae=float(mean_absolute_error(valid["Y"],pred)); rmse=float(np.sqrt(mean_squared_error(valid["Y"],pred)))
    values=list(daily["Y"].astype(float)); last_date=pd.Timestamp(daily["DS"].max()); output=[]
    for step in range(1,horizon_days+1):
        date=last_date+pd.Timedelta(days=step)
        row={f"LAG_{lag}":values[-lag] for lag in (1,3,7,12)}
        row.update({f"ROLLING_{w}":float(np.mean(values[-w:])) for w in (7,30)})
        row.update({"DAY_OF_WEEK":date.dayofweek,"MONTH":date.month,"DAY_OF_YEAR":date.dayofyear})
        value=max(0.0,float(model.predict(pd.DataFrame([row])[cols])[0])); values.append(value)
        output.append({"FORECAST_DATE":date.date(),"PARTNER_ID":partner_id,"PREDICTED_REVENUE":round(value,2),"PREDICTED_DEMAND":None,"PREDICTED_ROYALTY":None,"HORIZON_DAYS":horizon_days,"MODEL_NAME":"xgboost","MODEL_VERSION":"1"})
    return ForecastResult(pd.DataFrame(output),"xgboost","1",mae,rmse)

def persist_forecast(result: ForecastResult,run_id: str,royalty_rate: float | None=None) -> int:
    if royalty_rate is not None and not 0<=royalty_rate<=1: raise ValueError("royalty_rate must be a decimal between 0 and 1")
    rows=result.rows.copy()
    rows["PREDICTED_ROYALTY"]=rows["PREDICTED_REVENUE"]*royalty_rate if royalty_rate is not None else None
    values=[(r.FORECAST_DATE,r.PARTNER_ID,r.HORIZON_DAYS,r.MODEL_NAME,r.PREDICTED_DEMAND,r.PREDICTED_REVENUE,r.PREDICTED_ROYALTY,r.MODEL_VERSION,run_id) for r in rows.itertuples(index=False)]
    sql="""INSERT INTO FORECAST.DEMAND_FORECAST (FORECAST_DATE,PARTNER_ID,HORIZON_DAYS,MODEL_NAME,PREDICTED_DEMAND,PREDICTED_REVENUE,PREDICTED_ROYALTY,MODEL_VERSION,RUN_ID) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
    with connection() as conn,conn.cursor() as cur:
        cur.executemany(sql,values)
        return int(cur.rowcount or len(values))
