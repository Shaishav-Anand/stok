"""
ML Forecasting Service
Uses Facebook Prophet for time-series demand forecasting.
Falls back to linear trend if Prophet fails or data is too sparse.
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict
import warnings
warnings.filterwarnings("ignore")


def prophet_forecast(sales_df: pd.DataFrame, horizon: int = 30) -> Dict:
    """
    Run Facebook Prophet forecast.
    Returns actual + forecast arrays with confidence intervals.
    """
    try:
        from prophet import Prophet

        df = sales_df.sort_values("date").copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.groupby("date")["quantity_sold"].sum().reset_index()
        df.columns = ["ds", "y"]
        df["y"] = df["y"].clip(lower=0)

        if len(df) < 10:
            raise ValueError("Not enough data for Prophet (need 10+ days)")

        model = Prophet(
            yearly_seasonality=len(df) > 365,
            weekly_seasonality=len(df) > 14,
            daily_seasonality=False,
            interval_width=0.90,
            changepoint_prior_scale=0.05,  # conservative — avoids overfitting
        )
        model.fit(df, iter=300)

        future = model.make_future_dataframe(periods=horizon, freq="D")
        forecast = model.predict(future)

        # Split actual vs future
        last_actual_date = df["ds"].max()
        actual_rows = df.tail(14)
        forecast_rows = forecast[forecast["ds"] > last_actual_date].head(horizon)

        actual = [
            {"date": str(r["ds"].date()), "value": int(r["y"])}
            for _, r in actual_rows.iterrows()
        ]
        forecast_out = [
            {
                "date": str(r["ds"].date()),
                "value": round(max(0, r["yhat"]), 1),
                "lower": round(max(0, r["yhat_lower"]), 1),
                "upper": round(max(0, r["yhat_upper"]), 1)
            }
            for _, r in forecast_rows.iterrows()
        ]

        # Cross-validation accuracy on last 20% of data
        test_size = max(1, len(df) // 5)
        train = df.iloc[:-test_size]
        test = df.iloc[-test_size:]

        m2 = Prophet(yearly_seasonality=False, weekly_seasonality=len(train) > 14,
                     daily_seasonality=False, interval_width=0.90)
        m2.fit(train, iter=200)
        future2 = m2.make_future_dataframe(periods=test_size, freq="D")
        pred2 = m2.predict(future2).tail(test_size)

        mape = np.mean(np.abs(
            (test["y"].values - pred2["yhat"].values) /
            np.maximum(test["y"].values, 1)
        )) * 100
        accuracy = round(max(0, 100 - mape), 1)

        return {
            "actual": actual,
            "forecast": forecast_out,
            "model": "prophet",
            "accuracy": accuracy
        }

    except Exception as e:
        print(f"[Forecast] Prophet failed ({e}), falling back to linear trend")
        return linear_forecast(sales_df, horizon)


def linear_forecast(sales_df: pd.DataFrame, horizon: int = 30) -> Dict:
    """Linear trend fallback when Prophet can't run."""
    if len(sales_df) < 3:
        velocity = float(sales_df["quantity_sold"].mean()) if not sales_df.empty else 0
        today = datetime.now().date()
        forecast = [
            {
                "date": str(today + timedelta(days=i)),
                "value": round(max(0, velocity), 1),
                "lower": round(max(0, velocity * 0.8), 1),
                "upper": round(velocity * 1.2, 1)
            }
            for i in range(1, horizon + 1)
        ]
        actual = [
            {"date": str(pd.to_datetime(r["date"]).date()), "value": int(r["quantity_sold"])}
            for _, r in sales_df.iterrows()
        ] if not sales_df.empty else []
        return {"actual": actual, "forecast": forecast, "model": "moving_average", "accuracy": None}

    df = sales_df.sort_values("date").copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.groupby("date")["quantity_sold"].sum().reset_index()
    df.columns = ["date", "y"]
    df["t"] = (df["date"] - df["date"].min()).dt.days

    t = df["t"].values
    y = df["y"].values
    coeffs = np.polyfit(t, y, 1)
    slope, intercept = coeffs
    y_pred_all = slope * t + intercept
    std = (y - y_pred_all).std()

    actual = [
        {"date": str(r["date"].date()), "value": int(r["y"])}
        for _, r in df.tail(14).iterrows()
    ]

    last_t = int(df["t"].max())
    today = df["date"].max().date()
    forecast = [
        {
            "date": str(today + timedelta(days=i)),
            "value": round(max(0, slope * (last_t + i) + intercept), 1),
            "lower": round(max(0, slope * (last_t + i) + intercept - 1.645 * std), 1),
            "upper": round(slope * (last_t + i) + intercept + 1.645 * std, 1)
        }
        for i in range(1, horizon + 1)
    ]

    test_size = max(1, len(df) // 3)
    test = df.tail(test_size)
    pred = slope * test["t"].values + intercept
    mape = np.mean(np.abs((test["y"].values - pred) / np.maximum(test["y"].values, 1))) * 100
    accuracy = round(max(0, 100 - mape), 1)

    return {"actual": actual, "forecast": forecast, "model": "linear_trend", "accuracy": accuracy}


def get_forecast_for_sku(sku_id: str, db) -> Dict:
    """
    Get forecast from cache or compute fresh with Prophet.
    Cache valid for 6 hours.
    """
    import models
    cache = db.query(models.ForecastCache).filter(
        models.ForecastCache.sku_id == sku_id
    ).first()

    if cache and cache.valid_until and cache.valid_until > datetime.utcnow():
        return {
            "forecast_json": cache.forecast_json,
            "model_used": cache.model_used,
            "accuracy_pct": cache.accuracy_pct,
            "computed_at": cache.computed_at,
        }

    sales = db.query(models.SalesHistory).filter(
        models.SalesHistory.sku_id == sku_id
    ).all()

    sales_df = pd.DataFrame([{
        "date": pd.to_datetime(s.date),
        "quantity_sold": s.quantity_sold
    } for s in sales])

    result = prophet_forecast(sales_df) if len(sales_df) >= 10 else linear_forecast(sales_df)

    import uuid
    if cache:
        cache.forecast_json = result
        cache.model_used = result["model"]
        cache.accuracy_pct = result.get("accuracy")
        cache.computed_at = datetime.utcnow()
        cache.valid_until = datetime.utcnow() + timedelta(hours=6)
    else:
        db.add(models.ForecastCache(
            id=str(uuid.uuid4()),
            sku_id=sku_id,
            forecast_json=result,
            model_used=result["model"],
            accuracy_pct=result.get("accuracy"),
            valid_until=datetime.utcnow() + timedelta(hours=6),
        ))

    db.commit()
    return {
        "forecast_json": result,
        "model_used": result["model"],
        "accuracy_pct": result.get("accuracy"),
        "computed_at": datetime.utcnow()
    }
