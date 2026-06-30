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

PARAMETROS_INVENTARIO = {
    "horizonte": 365,           # dias simulados
    "stock_inicial": 100,
    "demanda_media": 20,        # demanda diaria media (Poisson)
    "lead_time_min": 1,         # lead time aleatorio ~ Uniforme entero [min, max]
    "lead_time_max": 3,
    "costo_fijo_orden": 500,    # K: costo fijo por emitir una orden
    "costo_incremental": 2,     # i: costo por cada unidad pedida
    "costo_mantenimiento": 5,   # h: costo por unidad en stock por dia
    "costo_faltante": 30,       # p: costo por unidad faltante (backorder) por dia
    "corridas": 10,
    # Politica (s, S): al revisar, si la posicion de inventario <= s se ordena
    # hasta el nivel maximo S (cantidad variable Z = S - posicion).
    "politicas": {
        "A": {"s": 30, "S": 90},
        "B": {"s": 40, "S": 120},
        "C": {"s": 50, "S": 150},
    },
}


# =========================
# Utilidades
# =========================


def crear_directorio_resultados():
    RESULTADOS_DIR.mkdir(exist_ok=True)


def semilla_deterministica(*valores):
    """Construye una semilla reproducible a partir de enteros pequenos."""
    semilla = SEMILLA_BASE
    for valor in valores:
        semilla = (semilla * 131 + int(valor)) % (2**32 - 1)
    return semilla


# =========================
# Modelo de inventario (politica s, S)
# =========================


def simular_inventario(
    s,
    S,
    horizonte,
    stock_inicial,
    demanda_media,
    lead_time_min,
    lead_time_max,
    costo_fijo_orden,
    costo_incremental,
    costo_mantenimiento,
    costo_faltante,
    rng,
    registrar_historial=True,
):
    """
    Simula una politica de inventario (s, S) con revision diaria.

    - Demanda diaria: Poisson de media demanda_media.
    - Faltante con backorder: el stock puede quedar negativo (pedidos pendientes
      de cliente) y se satisface con recepciones futuras.
    - Lead time aleatorio entero ~ Uniforme[lead_time_min, lead_time_max].
    - Costo de orden por pedido: K + i * Z, con Z = S - posicion de inventario.
    - Costo de mantenimiento: h * stock positivo (fin de dia).
    - Costo de faltante: p * stock negativo (fin de dia).
    """
    stock = stock_inicial  # puede ser negativo (backorder)
    pedidos_pendientes = []
    costo_orden_acum = 0.0
    costo_mant_acum = 0.0
    costo_falt_acum = 0.0
    registros = []

    for dia in range(1, horizonte + 1):
        # Recepcion de pedidos que llegan hoy
        for pedido in pedidos_pendientes:
            if pedido["dia_llegada"] == dia:
                stock += pedido["cantidad"]
        pedidos_pendientes = [p for p in pedidos_pendientes if p["dia_llegada"] > dia]

        # Demanda del dia (backorder: el stock puede quedar negativo)
        demanda = rng.poisson(demanda_media)
        stock -= demanda

        # Costos de tenencia / faltante sobre el stock de fin de dia
        stock_positivo = max(stock, 0)
        faltante = max(-stock, 0)
        costo_mant_dia = stock_positivo * costo_mantenimiento
        costo_falt_dia = faltante * costo_faltante

        # Revision (s, S): se ordena hasta S si la posicion cayo a s o menos
        costo_orden_dia = 0.0
        cantidad_pedida = 0
        inventario_en_posicion = stock + sum(p["cantidad"] for p in pedidos_pendientes)
        if inventario_en_posicion <= s:
            cantidad_pedida = S - inventario_en_posicion
            lead_time = int(rng.integers(lead_time_min, lead_time_max + 1))
            pedidos_pendientes.append(
                {"dia_llegada": dia + lead_time, "cantidad": cantidad_pedida}
            )
            costo_orden_dia = costo_fijo_orden + costo_incremental * cantidad_pedida

        costo_orden_acum += costo_orden_dia
        costo_mant_acum += costo_mant_dia
        costo_falt_acum += costo_falt_dia

        if registrar_historial:
            registros.append(
                {
                    "dia": dia,
                    "stock": stock,
                    "stock_positivo": stock_positivo,
                    "faltante": faltante,
                    "demanda": demanda,
                    "cantidad_pedida": cantidad_pedida,
                    "inventario_en_posicion": inventario_en_posicion,
                    "pedidos_pendientes": len(pedidos_pendientes),
                    "costo_orden_acum": costo_orden_acum,
                    "costo_mantenimiento_acum": costo_mant_acum,
                    "costo_faltante_acum": costo_falt_acum,
                    "costo_total_acum": costo_orden_acum + costo_mant_acum + costo_falt_acum,
                }
            )

    return {
        "costo_orden": costo_orden_acum,
        "costo_mantenimiento": costo_mant_acum,
        "costo_faltante": costo_falt_acum,
        "costo_total": costo_orden_acum + costo_mant_acum + costo_falt_acum,
        "historial": pd.DataFrame(registros) if registrar_historial else None,
    }


def ejecutar_experimentos_inventario(parametros):
    corridas = []
    historiales = []

    for indice_politica, (politica, valores) in enumerate(parametros["politicas"].items()):
        for corrida in range(1, parametros["corridas"] + 1):
            rng = np.random.default_rng(semilla_deterministica(900, indice_politica, corrida))
            resultado = simular_inventario(
                s=valores["s"],
                S=valores["S"],
                horizonte=parametros["horizonte"],
                stock_inicial=parametros["stock_inicial"],
                demanda_media=parametros["demanda_media"],
                lead_time_min=parametros["lead_time_min"],
                lead_time_max=parametros["lead_time_max"],
                costo_fijo_orden=parametros["costo_fijo_orden"],
                costo_incremental=parametros["costo_incremental"],
                costo_mantenimiento=parametros["costo_mantenimiento"],
                costo_faltante=parametros["costo_faltante"],
                rng=rng,
                registrar_historial=(corrida == 1),
            )
            corridas.append(
                {
                    "politica": politica,
                    "s": valores["s"],
                    "S": valores["S"],
                    "corrida": corrida,
                    "costo_orden": resultado["costo_orden"],
                    "costo_mantenimiento": resultado["costo_mantenimiento"],
                    "costo_faltante": resultado["costo_faltante"],
                    "costo_total": resultado["costo_total"],
                }
            )
            if corrida == 1:
                historial = resultado["historial"].copy()
                historial["politica"] = politica
                historial["s"] = valores["s"]
                historial["S"] = valores["S"]
                historiales.append(historial)

    df_corridas = pd.DataFrame(corridas)
    df_promedios = (
        df_corridas.groupby(["politica", "s", "S"], as_index=False)
        .agg(
            costo_orden=("costo_orden", "mean"),
            costo_mantenimiento=("costo_mantenimiento", "mean"),
            costo_faltante=("costo_faltante", "mean"),
            costo_total=("costo_total", "mean"),
        )
        .sort_values("costo_total")
    )
    df_historiales = pd.concat(historiales, ignore_index=True)

    df_corridas.to_csv(RESULTADOS_DIR / "inventario_resultados_corridas.csv", index=False)
    df_promedios.to_csv(RESULTADOS_DIR / "inventario_resultados_promedios.csv", index=False)
    df_historiales.to_csv(RESULTADOS_DIR / "inventario_evolucion_temporal.csv", index=False)

    return df_corridas, df_promedios, df_historiales


def generar_graficos_inventario(df_promedios, df_historiales):
    fig, ax = plt.subplots(figsize=(12, 6))
    for politica, datos in df_historiales.groupby("politica"):
        ax.plot(datos["dia"], datos["stock"], label=f"Politica {politica}")
    ax.axhline(0, color="black", linewidth=0.8, linestyle=":")
    ax.set_title("Inventario en el tiempo (negativo = faltante / backorder)")
    ax.set_xlabel("Dia")
    ax.set_ylabel("Stock")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(RESULTADOS_DIR / "inventario_stock_tiempo.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 6))
    for politica, datos in df_historiales.groupby("politica"):
        ax.plot(datos["dia"], datos["costo_total_acum"], label=f"Politica {politica}")
    ax.set_title("Costos acumulados en el tiempo")
    ax.set_xlabel("Dia")
    ax.set_ylabel("Costo acumulado")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(RESULTADOS_DIR / "inventario_costos_acumulados.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(df_promedios["politica"], df_promedios["costo_total"])
    ax.set_title("Costo total promedio por politica")
    ax.set_xlabel("Politica")
    ax.set_ylabel("Costo total promedio")
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(RESULTADOS_DIR / "inventario_costo_total_promedio.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 6))
    componentes = ["costo_orden", "costo_mantenimiento", "costo_faltante"]
    x = np.arange(len(df_promedios))
    ancho = 0.25
    for i, componente in enumerate(componentes):
        ax.bar(x + (i - 1) * ancho, df_promedios[componente], ancho, label=componente)
    ax.set_xticks(x)
    ax.set_xticklabels(df_promedios["politica"])
    ax.set_title("Comparacion de componentes de costo")
    ax.set_xlabel("Politica")
    ax.set_ylabel("Costo promedio")
    ax.grid(True, alpha=0.3, axis="y")
    ax.legend()
    fig.tight_layout()
    fig.savefig(RESULTADOS_DIR / "inventario_componentes_costo.png", dpi=150)
    plt.close(fig)


# =========================
# Programa principal
# =========================


def imprimir_resumen(df_inv_promedios):
    print("\nRESUMEN FINAL - INVENTARIO (politica s, S)")
    print("=" * 60)
    print("\nInventario: costo promedio por politica")
    print(df_inv_promedios.round(2).to_string(index=False))

    mejor = df_inv_promedios.iloc[0]
    print(
        f"\nMejor politica promedio: {mejor['politica']} "
        f"(s={int(mejor['s'])}, S={int(mejor['S'])}) con costo total {mejor['costo_total']:.2f}"
    )
    print(f"\nArchivos guardados en: {RESULTADOS_DIR.resolve()}")


def main():
    crear_directorio_resultados()

    (
        _df_inv_corridas,
        df_inv_promedios,
        df_inv_historiales,
    ) = ejecutar_experimentos_inventario(PARAMETROS_INVENTARIO)
    generar_graficos_inventario(df_inv_promedios, df_inv_historiales)

    imprimir_resumen(df_inv_promedios)


if __name__ == "__main__":
    main()
