#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================================
 SIMULACION DE UN MODELO DE INVENTARIO  con politica (s, S)
============================================================================
 Trabajo Practico N3 - Simulacion - UTN

 Metodo: simulacion por eventos discretos (next-event time advance),
 segun Law & Kelton (Cap. 1.5).

 Eventos (el numero define la prioridad en caso de empate, menor primero):
   1 ARRIBO_ORDEN : llega al deposito un pedido hecho al proveedor
   2 DEMANDA      : un cliente demanda producto
   3 FIN          : termina la simulacion (a los n meses)
   4 EVALUACION   : revision del inventario al inicio de cada mes (politica s,S)

 Politica (s, S):
   - s : punto de reorden. Si en la evaluacion el inventario I < s, se pide.
   - S : nivel objetivo. Se pide Z = S - I unidades.
   - Costo de la orden = K + i*Z   (K fijo, i incremental por unidad).
   - Si I >= s no se pide y no hay costo.

 Medidas (finales y en relacion al tiempo de simulacion):
   Costo de orden         = costo_total_ordenes / n
   Costo de mantenimiento = h * (area bajo I+(t)) / n     (inventario positivo)
   Costo de faltante      = p * (area bajo I-(t)) / n     (backlog, I negativo)
   Costo total            = suma de los tres

 Se compara: VALOR DE REFERENCIA (Law, Fig 1.44)  vs  SIMULACION en PYTHON.
 (No existe formula analitica cerrada para el costo de una politica (s,S);
  por eso la "fuente teorica" es el resultado publicado en la bibliografia,
  y la tercera fuente es AnyLogic, que se corre en esa herramienta.)

----------------------------------------------------------------------------
 USO RAPIDO (parametros por defecto del TP / Law):
     python simulacion_inventario.py

 VARIAR PARAMETROS EN CLASE (ejemplos):
     python simulacion_inventario.py --corridas 10 --meses 120
     python simulacion_inventario.py --K 32 --i 3 --h 1 --p 5
     python simulacion_inventario.py --politicas 20,40 20,60 40,80
     python simulacion_inventario.py --inv-inicial 60 --media-demanda 0.1
     python simulacion_inventario.py --sin-graficos
============================================================================
"""

import argparse
import csv
import math
import os
import random
import statistics

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAY_PLT = True
except Exception:
    HAY_PLT = False


# ===========================================================================
#  CONFIGURACION POR DEFECTO  (justificada con los valores de Law / TP)
# ===========================================================================
CONFIG = {
    "K": 32.0,            # costo fijo de preparacion de la orden ($)
    "i": 3.0,             # costo incremental por articulo pedido ($)
    "h": 1.0,             # costo de mantenimiento por articulo por mes ($)
    "p": 5.0,             # costo de faltante por articulo por mes ($)
    "inv_inicial": 60,    # inventario inicial (articulos)
    "meses": 120,         # duracion de la simulacion (meses)
    "media_demanda": 0.1,    # media del tiempo entre demandas (meses) -> exp
    "minlag": 0.5,           # lead time minimo (meses)  -> uniforme(min,max)
    "maxlag": 1.0,           # lead time maximo (meses)
    # tamano de demanda discreto: valor -> probabilidad
    "demanda_valores": [1, 2, 3, 4],
    "demanda_probs":  [1/6, 1/3, 1/3, 1/6],
    # politicas (s, S) a evaluar (las 9 de Law, Fig 1.44)
    "politicas": [(20, 40), (20, 60), (20, 80), (20, 100),
                  (40, 60), (40, 80), (40, 100), (60, 80), (60, 100)],
    "corridas": 10,
    "n_muestras": 240,
    "carpeta_salida": "salida_inventario",
}

INF = float("inf")
_T_TABLE = {2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
            8: 2.306, 9: 2.262, 10: 2.228, 15: 2.131, 20: 2.086, 30: 2.042}

# Valores de referencia de Law (Fig 1.44): politica -> (total, orden, mant, falt)
REFERENCIA_LAW = {
    (20, 40): (126.61, 99.26, 9.25, 18.10),
    (20, 60): (122.74, 90.52, 17.39, 14.83),
    (20, 80): (123.86, 87.36, 26.24, 10.26),
    (20, 100): (125.32, 81.37, 36.00, 7.95),
    (40, 60): (126.37, 98.43, 25.99, 1.95),
    (40, 80): (125.46, 88.40, 35.92, 1.14),
    (40, 100): (132.34, 84.62, 46.42, 1.30),
    (60, 80): (150.02, 105.69, 44.02, 0.31),
    (60, 100): (143.20, 89.05, 53.91, 0.24),
}


def t_critico(n):
    return _T_TABLE.get(n - 1, 1.96)


def resumen(valores):
    n = len(valores)
    media = statistics.mean(valores)
    if n < 2:
        return media, 0.0
    h = t_critico(n) * statistics.stdev(valores) / math.sqrt(n)
    return media, h


# ===========================================================================
#  NUCLEO: UNA CORRIDA DE SIMULACION
# ===========================================================================
def simular_inventario(s, S, cfg, seed=None, guardar_traza=False):
    """
    Ejecuta una corrida del modelo de inventario (s, S).
    Devuelve costos finales, series temporales y (opcional) la traza de I(t).
    """
    rng = random.Random(seed)
    K, i_cost, h, p = cfg["K"], cfg["i"], cfg["h"], cfg["p"]
    media_dem = cfg["media_demanda"]
    minlag, maxlag = cfg["minlag"], cfg["maxlag"]
    meses = cfg["meses"]
    valores = cfg["demanda_valores"]
    # probabilidades acumuladas para generar el tamano de demanda
    acum = []
    suma = 0.0
    for pr in cfg["demanda_probs"]:
        suma += pr
        acum.append(suma)

    # tipos de evento
    ARRIBO_ORDEN, DEMANDA, FIN, EVALUACION = 1, 2, 3, 4

    # --- estado ---
    sim_time = 0.0
    inv_level = cfg["inv_inicial"]
    cantidad_pedida = 0

    # --- acumuladores ---
    costo_total_ordenes = 0.0
    area_holding = 0.0     # area bajo I+(t)
    area_shortage = 0.0    # area bajo I-(t)
    n_ordenes = 0

    # --- lista de eventos ---
    t_evento = {
        ARRIBO_ORDEN: INF,
        DEMANDA: sim_time + rng.expovariate(1.0 / media_dem),
        FIN: float(meses),
        EVALUACION: 0.0,            # primera evaluacion en t=0
    }

    # --- series ---
    serie = []          # (t, c_orden, c_mant, c_falt, c_total) acumulados
    traza = []          # (t, inv_level) para graficar una corrida
    paso = meses / cfg["n_muestras"]
    prox_muestra = paso

    def generar_demanda():
        u = rng.random()
        for idx, c in enumerate(acum):
            if u < c:
                return valores[idx]
        return valores[-1]

    while True:
        # proximo evento: menor tiempo y, ante empate, menor numero de tipo
        tipo = min(t_evento, key=lambda k: (t_evento[k], k))
        t_next = t_evento[tipo]

        # actualizar areas de I+ / I- en [sim_time, t_next]
        dt = t_next - sim_time
        if dt > 0:
            if inv_level > 0:
                area_holding += inv_level * dt
            elif inv_level < 0:
                area_shortage += -inv_level * dt
        sim_time = t_next

        if guardar_traza:
            traza.append((sim_time, inv_level))

        # muestreo de costos acumulados en el tiempo
        while sim_time >= prox_muestra and prox_muestra <= meses:
            c_ord = costo_total_ordenes / sim_time
            c_man = h * area_holding / sim_time
            c_fal = p * area_shortage / sim_time
            serie.append((prox_muestra, c_ord, c_man, c_fal, c_ord + c_man + c_fal))
            prox_muestra += paso

        # procesar evento
        if tipo == ARRIBO_ORDEN:
            inv_level += cantidad_pedida
            t_evento[ARRIBO_ORDEN] = INF

        elif tipo == DEMANDA:
            inv_level -= generar_demanda()
            t_evento[DEMANDA] = sim_time + rng.expovariate(1.0 / media_dem)

        elif tipo == EVALUACION:
            if inv_level < s:
                cantidad_pedida = S - inv_level
                costo_total_ordenes += K + i_cost * cantidad_pedida
                n_ordenes += 1
                t_evento[ARRIBO_ORDEN] = sim_time + rng.uniform(minlag, maxlag)
            t_evento[EVALUACION] = sim_time + 1.0   # proxima revision (mensual)

        else:  # FIN
            break

    # --- costos finales (promedio mensual) ---
    c_orden = costo_total_ordenes / meses
    c_mant = h * area_holding / meses
    c_falt = p * area_shortage / meses
    c_total = c_orden + c_mant + c_falt

    return {
        "c_orden": c_orden, "c_mant": c_mant, "c_falt": c_falt, "c_total": c_total,
        "n_ordenes": n_ordenes, "serie": serie, "traza": traza,
    }


# ===========================================================================
#  AGREGACION DE REPLICAS POR POLITICA
# ===========================================================================
def correr_politica(s, S, cfg, semilla_base=0):
    res = [simular_inventario(s, S, cfg, seed=semilla_base + 1000 * k)
           for k in range(cfg["corridas"])]
    agg = {}
    for clave in ("c_orden", "c_mant", "c_falt", "c_total"):
        agg[clave] = resumen([r[clave] for r in res])
    # serie temporal promediada
    n_pts = min(len(r["serie"]) for r in res)
    serie_prom = []
    for j in range(n_pts):
        t = res[0]["serie"][j][0]
        fila = [t] + [statistics.mean(r["serie"][j][col] for r in res) for col in range(1, 5)]
        serie_prom.append(tuple(fila))
    agg["serie"] = serie_prom
    return agg


# ===========================================================================
#  EXPERIMENTO PRINCIPAL
# ===========================================================================
def experimento(cfg):
    print("\n" + "=" * 86)
    print(" MODELO DE INVENTARIO (s,S)   "
          "[K=%.0f  i=%.0f  h=%.0f  p=%.0f  inv0=%d  meses=%d  corridas=%d]"
          % (cfg["K"], cfg["i"], cfg["h"], cfg["p"], cfg["inv_inicial"],
             cfg["meses"], cfg["corridas"]))
    print("=" * 86)
    print(" %-9s | %-34s | %-22s" %
          ("(s,S)", "SIMULACION media +- IC95  [C.Total]", "REFERENCIA Law (C.Total)"))
    print("-" * 86)

    resultados = {}
    for (s, S) in cfg["politicas"]:
        agg = correr_politica(s, S, cfg)
        resultados[(s, S)] = agg
        mt, ht = agg["c_total"]
        ref = REFERENCIA_LAW.get((s, S))
        ref_str = ("%8.2f" % ref[0]) if ref else "   --"
        print(" (%3d,%3d) | total=%8.2f +- %6.2f                | %s"
              % (s, S, mt, ht, ref_str))

    # detalle por componentes
    print("\n Detalle por componentes (media de %d corridas):" % cfg["corridas"])
    print(" %-9s %10s %10s %10s %10s" %
          ("(s,S)", "Orden", "Manten.", "Faltante", "TOTAL"))
    for (s, S) in cfg["politicas"]:
        a = resultados[(s, S)]
        print(" (%3d,%3d) %10.2f %10.2f %10.2f %10.2f"
              % (s, S, a["c_orden"][0], a["c_mant"][0], a["c_falt"][0], a["c_total"][0]))

    # mejor politica
    mejor = min(cfg["politicas"], key=lambda k: resultados[k]["c_total"][0])
    print("\n >>> Mejor politica encontrada: (s=%d, S=%d) con costo total medio = %.2f $/mes"
          % (mejor[0], mejor[1], resultados[mejor]["c_total"][0]))

    _guardar_csv(cfg, resultados)
    if HAY_PLT and not cfg["sin_graficos"]:
        _graficar(cfg, resultados, mejor)
    return resultados, mejor


def _guardar_csv(cfg, resultados):
    ruta = os.path.join(cfg["carpeta_salida"], "resultados_inventario.csv")
    with open(ruta, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["s", "S", "componente", "sim_media", "sim_ic95", "referencia_law"])
        for (s, S) in cfg["politicas"]:
            a = resultados[(s, S)]
            ref = REFERENCIA_LAW.get((s, S), (None, None, None, None))
            mapa = {"c_total": ref[0], "c_orden": ref[1], "c_mant": ref[2], "c_falt": ref[3]}
            for clave in ("c_total", "c_orden", "c_mant", "c_falt"):
                m, h = a[clave]
                rv = mapa[clave]
                w.writerow([s, S, clave, "%.4f" % m, "%.4f" % h,
                            ("%.4f" % rv) if rv is not None else "NA"])
    print("\n[csv]  %s" % ruta)


def _graficar(cfg, resultados, mejor):
    import numpy as np
    carpeta = cfg["carpeta_salida"]
    etiquetas = ["(%d,%d)" % (s, S) for (s, S) in cfg["politicas"]]
    x = np.arange(len(cfg["politicas"]))

    # (a) costos apilados por politica
    orden = [resultados[k]["c_orden"][0] for k in cfg["politicas"]]
    mant = [resultados[k]["c_mant"][0] for k in cfg["politicas"]]
    falt = [resultados[k]["c_falt"][0] for k in cfg["politicas"]]
    plt.figure(figsize=(11, 6))
    plt.bar(x, orden, label="Orden")
    plt.bar(x, mant, bottom=orden, label="Mantenimiento")
    plt.bar(x, falt, bottom=[o + m for o, m in zip(orden, mant)], label="Faltante")
    plt.xticks(x, etiquetas, rotation=45)
    plt.ylabel("Costo promedio ($/mes)")
    plt.title("Composicion del costo total por politica (s,S)")
    plt.legend(); plt.grid(True, axis="y", alpha=0.3); plt.tight_layout()
    plt.savefig(os.path.join(carpeta, "costos_apilados.png"), dpi=130); plt.close()

    # (b) costo total: simulado (con IC) vs referencia Law
    sim = [resultados[k]["c_total"][0] for k in cfg["politicas"]]
    err = [resultados[k]["c_total"][1] for k in cfg["politicas"]]
    ref = [REFERENCIA_LAW.get(k, (None,))[0] for k in cfg["politicas"]]
    plt.figure(figsize=(11, 6))
    plt.bar(x - 0.2, sim, 0.4, yerr=err, capsize=4, label="Simulado (Python)")
    if all(r is not None for r in ref):
        plt.bar(x + 0.2, ref, 0.4, label="Referencia (Law)")
    plt.xticks(x, etiquetas, rotation=45)
    plt.ylabel("Costo total ($/mes)")
    plt.title("Costo total por politica: Simulacion vs Referencia")
    plt.legend(); plt.grid(True, axis="y", alpha=0.3); plt.tight_layout()
    plt.savefig(os.path.join(carpeta, "costo_total_vs_referencia.png"), dpi=130); plt.close()

    # (c) convergencia del costo total en el tiempo (mejor politica)
    serie = resultados[mejor]["serie"]
    ts = [r[0] for r in serie]
    plt.figure(figsize=(10, 6))
    plt.plot(ts, [r[1] for r in serie], label="Orden")
    plt.plot(ts, [r[2] for r in serie], label="Mantenimiento")
    plt.plot(ts, [r[3] for r in serie], label="Faltante")
    plt.plot(ts, [r[4] for r in serie], "k-", linewidth=2, label="TOTAL")
    plt.xlabel("Tiempo de simulacion (meses)"); plt.ylabel("Costo promedio ($/mes)")
    plt.title("Convergencia de costos en el tiempo - politica (%d,%d)" % mejor)
    plt.legend(); plt.grid(True, alpha=0.3); plt.tight_layout()
    plt.savefig(os.path.join(carpeta, "convergencia_costos.png"), dpi=130); plt.close()

    # (d) traza del nivel de inventario I(t) de una corrida (mejor politica)
    una = simular_inventario(mejor[0], mejor[1], cfg, seed=12345, guardar_traza=True)
    ts = [t for t, _ in una["traza"]]
    inv = [v for _, v in una["traza"]]
    plt.figure(figsize=(11, 6))
    plt.step(ts, inv, where="post", label="I(t)")
    plt.axhline(mejor[0], color="orange", linestyle="--", label="s = %d" % mejor[0])
    plt.axhline(mejor[1], color="green", linestyle="--", label="S = %d" % mejor[1])
    plt.axhline(0, color="red", linestyle=":", alpha=0.6)
    plt.xlabel("Tiempo (meses)"); plt.ylabel("Nivel de inventario")
    plt.title("Evolucion del inventario I(t) - politica (%d,%d)" % mejor)
    plt.legend(); plt.grid(True, alpha=0.3); plt.tight_layout()
    plt.savefig(os.path.join(carpeta, "nivel_inventario.png"), dpi=130); plt.close()

    print("[png]  graficos guardados en %s/" % carpeta)


# ===========================================================================
#  MAIN
# ===========================================================================
def _parse_politicas(lista):
    out = []
    for item in lista:
        s, S = item.split(",")
        out.append((int(s), int(S)))
    return out


def main():
    p = argparse.ArgumentParser(description="Simulacion de inventario (s,S) - TP3")
    p.add_argument("--K", type=float, default=CONFIG["K"], help="costo fijo de orden")
    p.add_argument("--i", type=float, default=CONFIG["i"], help="costo incremental por unidad")
    p.add_argument("--h", type=float, default=CONFIG["h"], help="costo de mantenimiento")
    p.add_argument("--p", type=float, default=CONFIG["p"], help="costo de faltante")
    p.add_argument("--inv-inicial", type=int, default=CONFIG["inv_inicial"])
    p.add_argument("--meses", type=int, default=CONFIG["meses"])
    p.add_argument("--media-demanda", type=float, default=CONFIG["media_demanda"])
    p.add_argument("--minlag", type=float, default=CONFIG["minlag"])
    p.add_argument("--maxlag", type=float, default=CONFIG["maxlag"])
    p.add_argument("--corridas", type=int, default=CONFIG["corridas"])
    p.add_argument("--n-muestras", type=int, default=CONFIG["n_muestras"])
    p.add_argument("--politicas", nargs="+", default=None,
                   help='pares s,S (ej: --politicas 20,40 20,60 40,80)')
    p.add_argument("--carpeta-salida", default=CONFIG["carpeta_salida"])
    p.add_argument("--sin-graficos", action="store_true")
    args = p.parse_args()

    cfg = dict(CONFIG)
    cfg.update({
        "K": args.K, "i": args.i, "h": args.h, "p": args.p,
        "inv_inicial": args.inv_inicial, "meses": args.meses,
        "media_demanda": args.media_demanda, "minlag": args.minlag, "maxlag": args.maxlag,
        "corridas": args.corridas, "n_muestras": args.n_muestras,
        "carpeta_salida": args.carpeta_salida, "sin_graficos": args.sin_graficos,
    })
    if args.politicas:
        cfg["politicas"] = _parse_politicas(args.politicas)

    os.makedirs(cfg["carpeta_salida"], exist_ok=True)
    if not HAY_PLT and not cfg["sin_graficos"]:
        print("[aviso] matplotlib no esta instalado: se generan solo tablas y CSV.")

    experimento(cfg)
    print("\nListo. Resultados en la carpeta '%s'." % cfg["carpeta_salida"])


if __name__ == "__main__":
    main()