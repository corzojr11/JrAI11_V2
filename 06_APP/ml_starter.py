# ml_starter.py
import sqlite3
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, roc_auc_score
import joblib
import os
from datetime import datetime, timedelta

DB_PATH = "data/backtest.db"
MODEL_PATH = "ml_model.pkl"

def cargar_datos():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM picks WHERE resultado != 'pendiente'", conn)
    conn.close()
    # Convertir fecha
    df['fecha'] = pd.to_datetime(df['fecha'])
    # Crear variable objetivo: 1 si ganada, 0 si perdida (ignoramos medias por ahora)
    df = df[df['resultado'].isin(['ganada', 'perdida'])]
    df['objetivo'] = (df['resultado'] == 'ganada').astype(int)
    return df

def preparar_features(df):
    # Codificar variables categóricas
    df_encoded = pd.get_dummies(df, columns=['ia', 'mercado'], prefix=['ia', 'mercado'])
    # Seleccionar features
    feature_cols = [col for col in df_encoded.columns if col.startswith('ia_') or col.startswith('mercado_')]
    feature_cols.extend(['cuota', 'confianza'])
    X = df_encoded[feature_cols].fillna(0)
    y = df_encoded['objetivo']
    return X, y, feature_cols

def walk_forward_train(X, y, dates, n_splits=5, test_days=30):
    resultados = []
    fechas = dates.sort_values().unique()
    total_dias = (fechas[-1] - fechas[0]).days
    train_days = total_dias - n_splits * test_days
    if train_days < test_days:
        print("⚠️ Pocos datos. Usando validación simple.")
        # Entrenar con todo y evaluar con el último 20%
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        model = RandomForestClassifier(n_estimators=100, random_state=42)
        model.fit(X_train, y_train)
        pred = model.predict(X_test)
        acc = accuracy_score(y_test, pred)
        roc = roc_auc_score(y_test, model.predict_proba(X_test)[:,1])
        print(f"✅ Accuracy: {acc:.3f}, ROC AUC: {roc:.3f}")
        joblib.dump(model, MODEL_PATH)
        return model, feature_cols

    # Walk-forward real
    for i in range(n_splits):
        test_start = fechas[0] + timedelta(days=train_days + i*test_days)
        test_end = test_start + timedelta(days=test_days)
        train_end = test_start - timedelta(days=1)

        train_idx = dates <= train_end
        test_idx = (dates >= test_start) & (dates <= test_end)

        if train_idx.sum() == 0 or test_idx.sum() == 0:
            continue

        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]

        model = RandomForestClassifier(n_estimators=100, random_state=42)
        model.fit(X_train, y_train)
        pred = model.predict(X_test)
        acc = accuracy_score(y_test, pred)
        roc = roc_auc_score(y_test, model.predict_proba(X_test)[:,1]) if len(np.unique(y_test)) > 1 else 0

        resultados.append({
            'ventana': i+1,
            'train_desde': dates[train_idx].min(),
            'train_hasta': train_end,
            'test_desde': test_start,
            'test_hasta': test_end,
            'n_train': train_idx.sum(),
            'n_test': test_idx.sum(),
            'accuracy': acc,
            'roc_auc': roc
        })

    df_res = pd.DataFrame(resultados)
    print("\n📊 Resultados walk-forward ML:")
    print(df_res[['ventana', 'n_train', 'n_test', 'accuracy', 'roc_auc']].to_string(index=False))
    print(f"\n📈 Accuracy promedio: {df_res['accuracy'].mean():.3f}")
    print(f"📈 ROC AUC promedio: {df_res['roc_auc'].mean():.3f}")

    # Entrenar modelo final con todos los datos
    final_model = RandomForestClassifier(n_estimators=100, random_state=42)
    final_model.fit(X, y)
    joblib.dump(final_model, MODEL_PATH)
    print(f"✅ Modelo final guardado en {MODEL_PATH}")
    return final_model, feature_cols

if __name__ == "__main__":
    df = cargar_datos()
    if df.empty:
        print("❌ No hay datos resueltos en la BD.")
    else:
        X, y, feature_cols = preparar_features(df)
        model, _ = walk_forward_train(X, y, df['fecha'])
        # Mostrar importancia de features
        importancias = pd.DataFrame({
            'feature': feature_cols,
            'importancia': model.feature_importances_
        }).sort_values('importancia', ascending=False)
        print("\n🔍 Importancia de features:")
        print(importancias.head(10).to_string(index=False))