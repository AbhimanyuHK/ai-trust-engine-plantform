"""Optional sequence-model forecast; install the 'lstm' extra to enable TensorFlow."""
from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error,mean_squared_error
from sklearn.preprocessing import MinMaxScaler
from trust_engine.forecasting import ForecastResult

def train_lstm(history: pd.DataFrame,horizon_days: int=60,sequence_length: int=30,
               epochs: int=30) -> ForecastResult:
    try:
        from tensorflow.keras import Sequential
        from tensorflow.keras.layers import LSTM,Dense,Input
        from tensorflow.keras.callbacks import EarlyStopping
    except ImportError as exc:
        raise RuntimeError("Install TensorFlow with: pip install -e '.[lstm]'") from exc
    if history.empty:
        raise ValueError("No transaction history available")
    if not 1<=horizon_days<=180 or sequence_length<7:
        raise ValueError("Invalid forecast horizon or sequence length")
    daily=history.groupby("DS",as_index=False)["Y"].sum().sort_values("DS")
    daily["DS"]=pd.to_datetime(daily["DS"])
    daily=daily.set_index("DS").asfreq("D",fill_value=0).rename_axis("DS").reset_index()
    values=daily["Y"].astype("float32").to_numpy().reshape(-1,1)
    if len(values)<sequence_length+30:
        raise ValueError("Insufficient daily history for LSTM training")
    split=max(sequence_length+1,int(len(values)*0.8))
    scaler=MinMaxScaler()
    scaler.fit(values[:split])
    scaled=scaler.transform(values)
    X=[]; y=[]
    for i in range(sequence_length,len(scaled)):
        X.append(scaled[i-sequence_length:i,0])
        y.append(scaled[i,0])
    X=np.asarray(X,dtype="float32").reshape(-1,sequence_length,1)
    y=np.asarray(y,dtype="float32")
    train_end=split-sequence_length
    model=Sequential([Input(shape=(sequence_length,1)),LSTM(48),Dense(16,activation="relu"),Dense(1)])
    model.compile(optimizer="adam",loss="mse")
    model.fit(X[:train_end],y[:train_end],validation_data=(X[train_end:],y[train_end:]),
      epochs=epochs,batch_size=32,verbose=0,
      callbacks=[EarlyStopping(patience=5,restore_best_weights=True)])
    valid_pred=scaler.inverse_transform(model.predict(X[train_end:],verbose=0))
    valid_actual=scaler.inverse_transform(y[train_end:].reshape(-1,1))
    mae=float(mean_absolute_error(valid_actual,valid_pred))
    rmse=float(np.sqrt(mean_squared_error(valid_actual,valid_pred)))
    window=scaled[-sequence_length:].reshape(1,sequence_length,1)
    last_date=pd.Timestamp(daily["DS"].max()); output=[]
    for step in range(1,horizon_days+1):
        next_scaled=float(model.predict(window,verbose=0)[0,0])
        next_scaled=max(0.0,next_scaled)
        window=np.concatenate([window[:,1:,:],np.array([[[next_scaled]]],dtype="float32")],axis=1)
        revenue=max(0.0,float(scaler.inverse_transform([[next_scaled]])[0,0]))
        output.append({"FORECAST_DATE":(last_date+pd.Timedelta(days=step)).date(),
          "PARTNER_ID":None,"PREDICTED_REVENUE":round(revenue,2),
          "PREDICTED_DEMAND":None,"PREDICTED_ROYALTY":None,"HORIZON_DAYS":horizon_days,
          "MODEL_NAME":"lstm","MODEL_VERSION":"1"})
    return ForecastResult(pd.DataFrame(output),"lstm","1",mae,rmse)
