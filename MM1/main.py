import math
from collections import Counter, deque
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# =========================
# Parametros generales
# =========================

RESULTADOS_DIR = Path("resultados")
SEMILLA_BASE = 12345

PARAMETROS_MM1 = {
    "mu": 10.0,  # clientes por hora
    "factores_lambda": [0.25, 0.50, 0.75, 1.00, 1.25],
    "tiempo_simulacion": 200.0,  # horas
    "corridas": 10,
    "tamanos_cola_finita": [0, 2, 5, 10, 50],
}


# =========================
# Utilidades
# =========================


def crear_directorio_resultados():
    RESULTADOS_DIR.mkdir(exist_ok=True)


def promedio_seguro(suma, cantidad):
    return suma / cantidad if cantidad > 0 else 0.0


def semilla_deterministica(*valores):
    """Construye una semilla reproducible a partir de enteros pequenos."""
    semilla = SEMILLA_BASE
    for valor in valores:
        semilla = (semilla * 131 + int(valor)) % (2**32 - 1)
    return semilla


# =========================
# Modelo M/M/1
# =========================


def calcular_teorico_mm1_infinito(lam, mu):
    """Valores teoricos de M/M/1 con cola infinita."""
    if lam >= mu:
        return {
            "estable": False,
            "rho": lam / mu,
            "L_teorico": np.nan,
            "Lq_teorico": np.nan,
            "W_teorico": np.nan,
            "Wq_teorico": np.nan,
        }

    rho = lam / mu
    return {
        "estable": True,
        "rho": rho,
        "L_teorico": rho / (1 - rho),
        "Lq_teorico": rho**2 / (1 - rho),
        "W_teorico": 1 / (mu - lam),
        "Wq_teorico": rho / (mu - lam),
    }


def calcular_teorico_mm1_finito(lam, mu, tamano_cola):
    """Probabilidad teorica de bloqueo de M/M/1/K."""
    rho = lam / mu
    K = tamano_cola + 1

    if math.isclose(rho, 1.0):
        p_bloqueo = 1 / (K + 1)
    else:
        p0 = (1 - rho) / (1 - rho ** (K + 1))
        p_bloqueo = p0 * rho**K

    return {
        "rho": rho,
        "K": K,
        "P_bloqueo_teorico": p_bloqueo,
    }


def simular_mm1(lam, mu, tiempo_simulacion, rng, tamano_cola=None, registrar_historial=True):
    """
    Simula una cola M/M/1 por eventos discretos.

    tamano_cola=None representa cola infinita. Si es entero, representa solo
    los lugares de espera; la capacidad total del sistema es tamano_cola + 1.

    registrar_historial=False evita armar la traza evento-a-evento (costosa) cuando
    solo interesan las medidas finales.
    """
    tiempo = 0.0
    proxima_llegada = rng.exponential(1 / lam)
    proxima_salida = math.inf

    servidor_ocupado = False
    cola = deque()
    llegada_en_servicio = None
    inicio_servicio_actual = None

    clientes_sistema = 0
    area_l = 0.0
    area_lq = 0.0
    area_utilizacion = 0.0
    ultimo_tiempo = 0.0

    llegadas = 0
    aceptados = 0
    denegados = 0
    completados = 0
    suma_w = 0.0
    suma_wq = 0.0

    tiempo_por_q = Counter()
    historial = []

    while True:
        siguiente_evento = min(proxima_llegada, proxima_salida)
        if siguiente_evento > tiempo_simulacion:
            delta_final = tiempo_simulacion - ultimo_tiempo
            if delta_final > 0:
                q_actual = len(cola)
                area_l += clientes_sistema * delta_final
                area_lq += q_actual * delta_final
                area_utilizacion += int(servidor_ocupado) * delta_final
                tiempo_por_q[q_actual] += delta_final
            break

        tiempo = siguiente_evento
        delta = tiempo - ultimo_tiempo
        q_actual = len(cola)
        area_l += clientes_sistema * delta
        area_lq += q_actual * delta
        area_utilizacion += int(servidor_ocupado) * delta
        tiempo_por_q[q_actual] += delta
        ultimo_tiempo = tiempo

        if proxima_llegada <= proxima_salida:
            llegadas += 1
            proxima_llegada = tiempo + rng.exponential(1 / lam)
            capacidad = math.inf if tamano_cola is None else tamano_cola + 1

            if clientes_sistema >= capacidad:
                denegados += 1
            else:
                aceptados += 1
                clientes_sistema += 1
                if not servidor_ocupado:
                    servidor_ocupado = True
                    llegada_en_servicio = tiempo
                    inicio_servicio_actual = tiempo
                    proxima_salida = tiempo + rng.exponential(1 / mu)
                else:
                    cola.append(tiempo)
        else:
            completados += 1
            clientes_sistema -= 1
            suma_w += tiempo - llegada_en_servicio
            suma_wq += inicio_servicio_actual - llegada_en_servicio

            if cola:
                llegada_en_servicio = cola.popleft()
                inicio_servicio_actual = tiempo
                proxima_salida = tiempo + rng.exponential(1 / mu)
            else:
                servidor_ocupado = False
                llegada_en_servicio = None
                inicio_servicio_actual = None
                proxima_salida = math.inf

        if registrar_historial:
            tiempo_transcurrido = max(tiempo, 1e-12)
            historial.append(
                {
                    "tiempo": tiempo,
                    "L_t": area_l / tiempo_transcurrido,
                    "Lq_t": area_lq / tiempo_transcurrido,
                    "W_t": promedio_seguro(suma_w, completados),
                    "Wq_t": promedio_seguro(suma_wq, completados),
                    "utilizacion_t": area_utilizacion / tiempo_transcurrido,
                }
            )

    probabilidades_q = {
        q: tiempo_q / tiempo_simulacion for q, tiempo_q in sorted(tiempo_por_q.items())
    }

    return {
        "L": area_l / tiempo_simulacion,
        "Lq": area_lq / tiempo_simulacion,
        "W": promedio_seguro(suma_w, completados),
        "Wq": promedio_seguro(suma_wq, completados),
        "utilizacion": area_utilizacion / tiempo_simulacion,
        "prob_denegacion": promedio_seguro(denegados, llegadas),
        "llegadas": llegadas,
        "aceptados": aceptados,
        "denegados": denegados,
        "completados": completados,
        "probabilidades_q": probabilidades_q,
        "historial": pd.DataFrame(historial) if registrar_historial else None,
    }


def ejecutar_experimentos_mm1(parametros):
    corridas = []
    probabilidades = []
    denegacion = []
    historiales = []

    mu = parametros["mu"]
    configuraciones = [("infinita", None)]
    configuraciones += [
        (f"finita_{tamano}", tamano)
        for tamano in parametros["tamanos_cola_finita"]
    ]

    for indice_config, (tipo_cola, tamano_cola) in enumerate(configuraciones):
        for indice_factor, factor in enumerate(parametros["factores_lambda"]):
            lam = factor * mu
            for corrida in range(1, parametros["corridas"] + 1):
                semilla = semilla_deterministica(indice_config, indice_factor, corrida)
                rng = np.random.default_rng(semilla)
                resultado = simular_mm1(
                    lam,
                    mu,
                    parametros["tiempo_simulacion"],
                    rng,
                    tamano_cola=tamano_cola,
                    registrar_historial=(corrida == 1),
                )

                fila = {
                    "modelo": "MM1",
                    "tipo_cola": tipo_cola,
                    "tamano_cola": "infinita" if tamano_cola is None else tamano_cola,
                    "capacidad_total": "infinita" if tamano_cola is None else tamano_cola + 1,
                    "corrida": corrida,
                    "lambda": lam,
                    "mu": mu,
                    "lambda_sobre_mu": factor,
                    "L": resultado["L"],
                    "Lq": resultado["Lq"],
                    "W": resultado["W"],
                    "Wq": resultado["Wq"],
                    "utilizacion": resultado["utilizacion"],
                    "prob_denegacion": resultado["prob_denegacion"],
                    "llegadas": resultado["llegadas"],
                    "aceptados": resultado["aceptados"],
                    "denegados": resultado["denegados"],
                    "completados": resultado["completados"],
                }
                corridas.append(fila)

                for q, prob in resultado["probabilidades_q"].items():
                    probabilidades.append(
                        {
                            "tipo_cola": tipo_cola,
                            "tamano_cola": fila["tamano_cola"],
                            "corrida": corrida,
                            "lambda_sobre_mu": factor,
                            "lambda": lam,
                            "Q": q,
                            "P_Q_n": prob,
                        }
                    )

                if tamano_cola is not None:
                    teorico_finito = calcular_teorico_mm1_finito(lam, mu, tamano_cola)
                    denegacion.append(
                        {
                            "tamano_cola": tamano_cola,
                            "capacidad_total": tamano_cola + 1,
                            "lambda_sobre_mu": factor,
                            "lambda": lam,
                            "corrida": corrida,
                            "prob_denegacion": resultado["prob_denegacion"],
                            "P_bloqueo_teorico": teorico_finito["P_bloqueo_teorico"],
                        }
                    )

                if corrida == 1:
                    historial = resultado["historial"].copy()
                    historial["tipo_cola"] = tipo_cola
                    historial["tamano_cola"] = fila["tamano_cola"]
                    historial["lambda_sobre_mu"] = factor
                    historiales.append(historial)

    df_corridas = pd.DataFrame(corridas)
    df_promedios = (
        df_corridas.groupby(
            ["tipo_cola", "tamano_cola", "capacidad_total", "lambda_sobre_mu", "lambda", "mu"],
            as_index=False,
        )
        .agg(
            L=("L", "mean"),
            Lq=("Lq", "mean"),
            W=("W", "mean"),
            Wq=("Wq", "mean"),
            utilizacion=("utilizacion", "mean"),
            prob_denegacion=("prob_denegacion", "mean"),
            llegadas=("llegadas", "mean"),
            aceptados=("aceptados", "mean"),
            denegados=("denegados", "mean"),
            completados=("completados", "mean"),
        )
        .reset_index(drop=True)
    )

    teoricos = []
    for _, fila in df_promedios.iterrows():
        if fila["tipo_cola"] == "infinita":
            teorico = calcular_teorico_mm1_infinito(fila["lambda"], fila["mu"])
            teoricos.append(teorico)
        else:
            teoricos.append(
                {
                    "estable": True,
                    "rho": fila["lambda_sobre_mu"],
                    "L_teorico": np.nan,
                    "Lq_teorico": np.nan,
                    "W_teorico": np.nan,
                    "Wq_teorico": np.nan,
                }
            )
    df_promedios = pd.concat([df_promedios, pd.DataFrame(teoricos)], axis=1)

    df_probabilidades = pd.DataFrame(probabilidades)
    df_probabilidades = (
        df_probabilidades.groupby(
            ["tipo_cola", "tamano_cola", "lambda_sobre_mu", "lambda", "Q"],
            as_index=False,
        )["P_Q_n"]
        .mean()
        .sort_values(["tipo_cola", "lambda_sobre_mu", "Q"])
    )
    df_denegacion = pd.DataFrame(denegacion)
    df_historiales = pd.concat(historiales, ignore_index=True)

    df_corridas.to_csv(RESULTADOS_DIR / "mm1_resultados_corridas.csv", index=False)
    df_promedios.to_csv(RESULTADOS_DIR / "mm1_resultados_promedios.csv", index=False)
    df_probabilidades.to_csv(RESULTADOS_DIR / "mm1_probabilidades_cola.csv", index=False)
    df_denegacion.to_csv(RESULTADOS_DIR / "mm1_denegacion.csv", index=False)
    df_historiales.to_csv(RESULTADOS_DIR / "mm1_evolucion_temporal.csv", index=False)

    return df_corridas, df_promedios, df_probabilidades, df_denegacion, df_historiales


def generar_graficos_mm1(df_promedios, df_probabilidades, df_denegacion, df_historiales):
    infinito = df_promedios[df_promedios["tipo_cola"] == "infinita"].sort_values(
        "lambda_sobre_mu"
    )

    metricas = ["L", "Lq", "W", "Wq", "utilizacion"]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    axes = axes.ravel()
    for i, metrica in enumerate(metricas):
        axes[i].plot(infinito["lambda_sobre_mu"], infinito[metrica], marker="o", label="Simulado")
        teorico_col = f"{metrica}_teorico"
        if teorico_col in infinito.columns:
            axes[i].plot(
                infinito["lambda_sobre_mu"],
                infinito[teorico_col],
                marker="x",
                linestyle="--",
                label="Teorico",
            )
        axes[i].set_title(metrica)
        axes[i].set_xlabel("lambda / mu")
        axes[i].grid(True, alpha=0.3)
        axes[i].legend()
    axes[-1].axis("off")
    fig.tight_layout()
    fig.savefig(RESULTADOS_DIR / "mm1_metricas_vs_lambda.png", dpi=150)
    plt.close(fig)

    promedio_denegacion = (
        df_denegacion.groupby(["tamano_cola", "lambda_sobre_mu"], as_index=False)
        .agg(
            prob_denegacion=("prob_denegacion", "mean"),
            P_bloqueo_teorico=("P_bloqueo_teorico", "mean"),
        )
        .sort_values(["tamano_cola", "lambda_sobre_mu"])
    )
    fig, ax = plt.subplots(figsize=(10, 6))
    for tamano, datos in promedio_denegacion.groupby("tamano_cola"):
        ax.plot(datos["lambda_sobre_mu"], datos["prob_denegacion"], marker="o", label=f"cola {tamano}")
    ax.set_title("Probabilidad de denegacion segun tamano de cola")
    ax.set_xlabel("lambda / mu")
    ax.set_ylabel("Probabilidad")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(RESULTADOS_DIR / "mm1_denegacion_por_tamano_cola.png", dpi=150)
    plt.close(fig)

    muestra_evolucion = df_historiales[
        (df_historiales["tipo_cola"] == "infinita")
        & (df_historiales["lambda_sobre_mu"] == 0.75)
    ]
    fig, axes = plt.subplots(3, 2, figsize=(14, 9))
    axes = axes.ravel()
    for i, metrica in enumerate(["L_t", "Lq_t", "W_t", "Wq_t", "utilizacion_t"]):
        axes[i].plot(muestra_evolucion["tiempo"], muestra_evolucion[metrica])
        axes[i].set_title(metrica)
        axes[i].set_xlabel("Tiempo")
        axes[i].grid(True, alpha=0.3)
    axes[-1].axis("off")
    fig.tight_layout()
    fig.savefig(RESULTADOS_DIR / "mm1_evolucion_temporal.png", dpi=150)
    plt.close(fig)

    muestra_prob = df_probabilidades[
        (df_probabilidades["tipo_cola"] == "infinita")
        & (df_probabilidades["lambda_sobre_mu"] == 0.75)
        & (df_probabilidades["Q"] <= 20)
    ]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(muestra_prob["Q"], muestra_prob["P_Q_n"])
    ax.set_title("Probabilidad de encontrar n clientes en cola P(Q=n)")
    ax.set_xlabel("n clientes en cola")
    ax.set_ylabel("P(Q=n)")
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(RESULTADOS_DIR / "mm1_probabilidad_cola.png", dpi=150)
    plt.close(fig)


# =========================
# Programa principal
# =========================


def imprimir_resumen(df_mm1_promedios, df_denegacion):
    print("\nRESUMEN FINAL - M/M/1")
    print("=" * 60)

    print("\nM/M/1 infinito: promedios principales")
    columnas_mm1 = ["lambda_sobre_mu", "L", "Lq", "W", "Wq", "utilizacion", "estable"]
    print(
        df_mm1_promedios[df_mm1_promedios["tipo_cola"] == "infinita"][columnas_mm1]
        .round(4)
        .to_string(index=False)
    )

    print("\nM/M/1 finito: denegacion promedio por tamano de cola y lambda/mu")
    resumen_denegacion = (
        df_denegacion.groupby(["tamano_cola", "lambda_sobre_mu"], as_index=False)[
            ["prob_denegacion", "P_bloqueo_teorico"]
        ]
        .mean()
        .round(4)
    )
    print(resumen_denegacion.to_string(index=False))

    print(f"\nArchivos guardados en: {RESULTADOS_DIR.resolve()}")


def main():
    crear_directorio_resultados()

    (
        _df_mm1_corridas,
        df_mm1_promedios,
        df_mm1_probabilidades,
        df_mm1_denegacion,
        df_mm1_historiales,
    ) = ejecutar_experimentos_mm1(PARAMETROS_MM1)
    generar_graficos_mm1(
        df_mm1_promedios,
        df_mm1_probabilidades,
        df_mm1_denegacion,
        df_mm1_historiales,
    )

    imprimir_resumen(df_mm1_promedios, df_mm1_denegacion)


if __name__ == "__main__":
    main()
