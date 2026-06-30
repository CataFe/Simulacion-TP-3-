#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================================
 SIMULACION DE UN SISTEMA DE COLAS M/M/1  (y M/M/1/K con cola finita)
============================================================================
 Trabajo Practico N3 - Simulacion - UTN

 Metodo: simulacion por eventos discretos (next-event time advance),
 segun el esquema de Law & Kelton (Cap. 1.4).

 Eventos:  ARRIBO  (arrival)  -> llega un cliente
           PARTIDA (departure) -> un cliente termina su servicio
           FIN     (end)        -> termina la corrida (tiempo fijo)

 Medidas calculadas (finales y en relacion al tiempo de simulacion):
   L   : numero promedio de clientes en el sistema  (time-average)
   Lq  : numero promedio de clientes en la cola      (time-average)
   W   : tiempo promedio de permanencia en el sistema
   Wq  : tiempo promedio de espera en la cola
   rho : utilizacion del servidor
   P_n : probabilidad de encontrar n clientes en cola
   P_denegacion : prob. de rechazo (solo con cola finita: 0, 2, 5, 10, 50)

 Se compara: VALOR TEORICO  vs  SIMULACION en PYTHON
 (la tercera fuente, AnyLogic, se corre aparte en esa herramienta).

----------------------------------------------------------------------------
 USO RAPIDO (parametros por defecto del TP, mu=20):
     python simulacion_mm1.py

 VARIAR PARAMETROS EN CLASE (ejemplos):
     python simulacion_mm1.py --mu 20 --corridas 10 --tmax 5000
     python simulacion_mm1.py --porcentajes 25 50 75 100 125
     python simulacion_mm1.py --rho-bloqueo 0.75 --capacidades 0 2 5 10 50
     python simulacion_mm1.py --sin-graficos     (solo tablas por consola)
============================================================================
"""

import argparse
import csv
import math
import os
import random
import statistics

# matplotlib es opcional: si no esta, igual corren las tablas
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAY_PLT = True
except Exception:
    HAY_PLT = False


# ===========================================================================
#  CONFIGURACION POR DEFECTO  (se puede cambiar por linea de comandos)
# ===========================================================================
CONFIG = {
    "mu": 20.0,                          # tasa de servicio (clientes / hora)
    "porcentajes": [25, 50, 75, 100, 125],  # lambda como % de mu
    "corridas": 10,                      # replicas por experimento (>= 10)
    "tmax": 5000.0,                      # horizonte de cada corrida (horas)
    "n_muestras": 200,                   # puntos para las series temporales
    "rho_bloqueo": 0.75,                 # rho usado en el experimento de cola finita
    "capacidades": [0, 2, 5, 10, 50],    # tamanos de cola finita a evaluar
    "lambda_distribucion": 75,           # % de mu para graficar la distribucion P_n
    "carpeta_salida": "salida_mm1",
}

INF = float("inf")
# t de Student (95%, dos colas) para construir el intervalo de confianza
_T_TABLE = {2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
            8: 2.306, 9: 2.262, 10: 2.228, 15: 2.131, 20: 2.086, 30: 2.042}


def t_critico(n):
    """Valor t de Student (95%) para n replicas; si no esta en tabla usa 1.96."""
    return _T_TABLE.get(n - 1, 1.96)


# ===========================================================================
#  VALORES TEORICOS
# ===========================================================================
def teoria_mm1(lam, mu):
    """Medidas teoricas del M/M/1 con cola infinita (validas solo si rho<1)."""
    rho = lam / mu
    if rho >= 1.0:
        return {"rho": rho, "L": None, "Lq": None, "W": None, "Wq": None}
    L = rho / (1 - rho)
    Lq = rho ** 2 / (1 - rho)
    W = 1.0 / (mu - lam)
    Wq = lam / (mu * (mu - lam))
    return {"rho": rho, "L": L, "Lq": Lq, "W": W, "Wq": Wq}


def teoria_pn_cola(n, rho):
    """P(Nq = n) teorica para M/M/1 (numero de clientes EN COLA)."""
    if rho >= 1.0:
        return None
    if n == 0:
        return 1 - rho ** 2          # P(0 o 1 en sistema)
    return (1 - rho) * rho ** (n + 1)  # P(n+1 en sistema)


def teoria_bloqueo_mm1k(rho, K):
    """Probabilidad de denegacion (sistema lleno) en M/M/1/K.  K = cap_cola + 1."""
    if abs(rho - 1.0) < 1e-12:
        return 1.0 / (K + 1)
    return ((1 - rho) / (1 - rho ** (K + 1))) * (rho ** K)


# ===========================================================================
#  NUCLEO: UNA CORRIDA DE SIMULACION
# ===========================================================================
def simular_una_corrida(lam, mu, tmax, cap_cola=None, seed=None, n_muestras=200):
    """
    Ejecuta una unica corrida del M/M/1 (cap_cola=None) o M/M/1/K (cap_cola finito).

    cap_cola = numero maximo de clientes ESPERANDO en la cola.
               La capacidad del sistema es K = cap_cola + 1 (incluye el que se
               esta atendiendo). Si el sistema esta lleno, el arribo se rechaza.

    Devuelve un diccionario con las medidas finales y las series temporales.
    """
    rng = random.Random(seed)
    K = None if cap_cola is None else cap_cola + 1

    # --- estado del sistema ---
    sim_time = 0.0
    server_busy = False
    arribo_en_servicio = None      # instante de llegada del cliente en servicio
    cola = []                      # instantes de llegada de los que esperan

    # --- lista de eventos ---
    t_arribo = rng.expovariate(lam)
    t_partida = INF
    t_fin = tmax

    # --- acumuladores tiempo-promedio ---
    area_n_sys = 0.0
    area_n_q = 0.0
    area_busy = 0.0

    # --- acumuladores por cliente ---
    total_espera_cola = 0.0        # suma de Wq (clientes que entraron a servicio)
    n_esperas = 0
    total_en_sistema = 0.0         # suma de W (clientes que partieron)
    n_partidas = 0
    n_arribos = 0
    n_rechazados = 0

    # --- distribucion de n en cola y en sistema (tiempo acumulado por nivel) ---
    tiempo_en_nq = {}
    tiempo_en_nsys = {}

    # --- serie temporal (convergencia de las medidas) ---
    serie = []  # (t, L, Lq, W, Wq, rho)
    paso_muestra = tmax / n_muestras
    prox_muestra = paso_muestra

    def num_sistema():
        return (1 if server_busy else 0) + len(cola)

    while True:
        # 1) proximo evento (en caso de empate gana el menor tiempo)
        t_next = min(t_arribo, t_partida, t_fin)
        if t_next == t_arribo:
            tipo = "ARRIBO"
        elif t_next == t_partida:
            tipo = "PARTIDA"
        else:
            tipo = "FIN"

        # 2) acumular areas en el intervalo [sim_time, t_next]
        dt = t_next - sim_time
        if dt > 0:
            ns = num_sistema()
            nq = len(cola)
            area_n_sys += ns * dt
            area_n_q += nq * dt
            area_busy += (1 if server_busy else 0) * dt
            tiempo_en_nq[nq] = tiempo_en_nq.get(nq, 0.0) + dt
            tiempo_en_nsys[ns] = tiempo_en_nsys.get(ns, 0.0) + dt
        sim_time = t_next

        # 3) registrar la serie temporal en la grilla de muestreo
        while sim_time >= prox_muestra and prox_muestra <= tmax:
            L_t = area_n_sys / sim_time
            Lq_t = area_n_q / sim_time
            rho_t = area_busy / sim_time
            W_t = total_en_sistema / n_partidas if n_partidas else 0.0
            Wq_t = total_espera_cola / n_esperas if n_esperas else 0.0
            serie.append((prox_muestra, L_t, Lq_t, W_t, Wq_t, rho_t))
            prox_muestra += paso_muestra

        # 4) procesar el evento
        if tipo == "ARRIBO":
            n_arribos += 1
            t_arribo = sim_time + rng.expovariate(lam)   # proximo arribo
            if K is not None and num_sistema() >= K:
                n_rechazados += 1                         # sistema lleno -> rechazo
            else:
                if not server_busy:                       # servidor libre -> atiende ya
                    server_busy = True
                    arribo_en_servicio = sim_time
                    n_esperas += 1                        # espera 0 (cuenta como espera)
                    t_partida = sim_time + rng.expovariate(mu)
                else:                                     # servidor ocupado -> a la cola
                    cola.append(sim_time)

        elif tipo == "PARTIDA":
            # el cliente en servicio termina y se va
            total_en_sistema += sim_time - arribo_en_servicio
            n_partidas += 1
            if cola:                                      # pasa el primero de la cola
                llegada = cola.pop(0)
                total_espera_cola += sim_time - llegada
                n_esperas += 1
                arribo_en_servicio = llegada
                t_partida = sim_time + rng.expovariate(mu)
            else:                                         # cola vacia -> servidor libre
                server_busy = False
                arribo_en_servicio = None
                t_partida = INF

        else:  # FIN
            break

    # --- medidas finales ---
    L = area_n_sys / sim_time
    Lq = area_n_q / sim_time
    rho = area_busy / sim_time
    W = total_en_sistema / n_partidas if n_partidas else 0.0
    Wq = total_espera_cola / n_esperas if n_esperas else 0.0
    p_deneg = (n_rechazados / n_arribos) if (K is not None and n_arribos) else 0.0

    dist_nq = {n: t / sim_time for n, t in sorted(tiempo_en_nq.items())}
    dist_nsys = {n: t / sim_time for n, t in sorted(tiempo_en_nsys.items())}

    return {
        "L": L, "Lq": Lq, "W": W, "Wq": Wq, "rho": rho,
        "p_deneg": p_deneg, "n_arribos": n_arribos, "n_rechazados": n_rechazados,
        "dist_nq": dist_nq, "dist_nsys": dist_nsys, "serie": serie,
    }


# ===========================================================================
#  AGREGACION DE VARIAS REPLICAS
# ===========================================================================
def resumen(valores):
    """Media e intervalo de confianza (95%) de una lista de valores."""
    n = len(valores)
    media = statistics.mean(valores)
    if n < 2:
        return media, 0.0
    desv = statistics.stdev(valores)
    h = t_critico(n) * desv / math.sqrt(n)
    return media, h


def correr_experimento(lam, mu, tmax, corridas, cap_cola=None, n_muestras=200, semilla_base=0):
    """Corre 'corridas' replicas y agrega los resultados."""
    res = [simular_una_corrida(lam, mu, tmax, cap_cola, seed=semilla_base + 1000 * k,
                               n_muestras=n_muestras) for k in range(corridas)]
    agg = {}
    for clave in ("L", "Lq", "W", "Wq", "rho", "p_deneg"):
        agg[clave] = resumen([r[clave] for r in res])
    # serie temporal promediada entre replicas (las grillas coinciden)
    n_pts = min(len(r["serie"]) for r in res)
    serie_prom = []
    for j in range(n_pts):
        t = res[0]["serie"][j][0]
        fila = [t]
        for col in range(1, 6):
            fila.append(statistics.mean(r["serie"][j][col] for r in res))
        serie_prom.append(tuple(fila))
    agg["serie"] = serie_prom
    # distribucion de n en cola promediada
    max_n = max((max(r["dist_nq"]) for r in res), default=0)
    dist = {}
    for n in range(max_n + 1):
        dist[n] = statistics.mean(r["dist_nq"].get(n, 0.0) for r in res)
    agg["dist_nq"] = dist
    return agg


# ===========================================================================
#  EXPERIMENTO 1: COLA INFINITA, VARIANDO LAMBDA
# ===========================================================================
def experimento_cola_infinita(cfg):
    mu = cfg["mu"]
    print("\n" + "=" * 78)
    print(" EXPERIMENTO 1 - M/M/1 cola INFINITA   (mu = %.3f, %d corridas, tmax=%.0f)"
          % (mu, cfg["corridas"], cfg["tmax"]))
    print("=" * 78)

    resultados = {}
    for pct in cfg["porcentajes"]:
        lam = mu * pct / 100.0
        agg = correr_experimento(lam, mu, cfg["tmax"], cfg["corridas"],
                                 cap_cola=None, n_muestras=cfg["n_muestras"])
        teo = teoria_mm1(lam, mu)
        resultados[pct] = {"lam": lam, "agg": agg, "teo": teo}

    # ---- tabla por consola ----
    encabezado = ("%-6s %-8s | %-22s %-22s" %
                  ("%mu", "lambda", "SIMULACION (media +- IC95)", "TEORIA"))
    for pct in cfg["porcentajes"]:
        r = resultados[pct]
        lam, agg, teo = r["lam"], r["agg"], r["teo"]
        print("\n--- lambda = %.2f  (%d%% de mu)   rho_teorico = %.3f ---"
              % (lam, pct, teo["rho"]))
        for clave, etiqueta in [("L", "L  (en sistema)"), ("Lq", "Lq (en cola)"),
                                ("W", "W  (en sistema)"), ("Wq", "Wq (en cola)"),
                                ("rho", "rho (utilizacion)")]:
            m, h = agg[clave]
            tv = teo[clave]
            tv_str = ("%10.4f" % tv) if tv is not None else "    INESTABLE"
            print("   %-18s sim = %9.4f +- %7.4f   teo = %s"
                  % (etiqueta, m, h, tv_str))

    _guardar_csv_infinita(cfg, resultados)
    if HAY_PLT and not cfg["sin_graficos"]:
        _graficar_infinita(cfg, resultados)
    return resultados


def _guardar_csv_infinita(cfg, resultados):
    ruta = os.path.join(cfg["carpeta_salida"], "resultados_cola_infinita.csv")
    with open(ruta, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pct_mu", "lambda", "medida", "sim_media", "sim_ic95", "teorico"])
        for pct in cfg["porcentajes"]:
            r = resultados[pct]
            for clave in ("L", "Lq", "W", "Wq", "rho"):
                m, h = r["agg"][clave]
                tv = r["teo"][clave]
                w.writerow([pct, "%.4f" % r["lam"], clave, "%.5f" % m, "%.5f" % h,
                            ("%.5f" % tv) if tv is not None else "NA"])
    print("\n[csv]  %s" % ruta)


def _graficar_infinita(cfg, resultados):
    carpeta = cfg["carpeta_salida"]
    # (a) convergencia de L en el tiempo, una curva por lambda
    plt.figure(figsize=(9, 5))
    for pct in cfg["porcentajes"]:
        serie = resultados[pct]["agg"]["serie"]
        ts = [p[0] for p in serie]
        Ls = [p[1] for p in serie]
        plt.plot(ts, Ls, label="lambda=%d%% (rho=%.2f)" % (pct, resultados[pct]["teo"]["rho"]))
    plt.xlabel("Tiempo de simulacion (horas)")
    plt.ylabel("L (numero promedio en el sistema)")
    plt.title("Convergencia de L segun el tiempo de simulacion - M/M/1")
    plt.legend(); plt.grid(True, alpha=0.3); plt.tight_layout()
    plt.savefig(os.path.join(carpeta, "conv_L.png"), dpi=130); plt.close()

    # (b) convergencia de Wq en el tiempo
    plt.figure(figsize=(9, 5))
    for pct in cfg["porcentajes"]:
        serie = resultados[pct]["agg"]["serie"]
        ts = [p[0] for p in serie]
        Wqs = [p[4] for p in serie]
        plt.plot(ts, Wqs, label="lambda=%d%%" % pct)
    plt.xlabel("Tiempo de simulacion (horas)")
    plt.ylabel("Wq (espera promedio en cola)")
    plt.title("Convergencia de Wq segun el tiempo de simulacion - M/M/1")
    plt.legend(); plt.grid(True, alpha=0.3); plt.tight_layout()
    plt.savefig(os.path.join(carpeta, "conv_Wq.png"), dpi=130); plt.close()

    # (c) barras: simulado vs teorico (solo casos estables rho<1)
    estables = [p for p in cfg["porcentajes"] if resultados[p]["teo"]["L"] is not None]
    if estables:
        import numpy as np
        medidas = ["L", "Lq", "W", "Wq"]
        fig, axes = plt.subplots(2, 2, figsize=(11, 8))
        for ax, med in zip(axes.ravel(), medidas):
            x = np.arange(len(estables))
            sim = [resultados[p]["agg"][med][0] for p in estables]
            err = [resultados[p]["agg"][med][1] for p in estables]
            teo = [resultados[p]["teo"][med] for p in estables]
            ax.bar(x - 0.2, sim, 0.4, yerr=err, capsize=4, label="Simulado (Python)")
            ax.bar(x + 0.2, teo, 0.4, label="Teorico")
            ax.set_xticks(x); ax.set_xticklabels(["%d%%" % p for p in estables])
            ax.set_title(med); ax.grid(True, axis="y", alpha=0.3); ax.legend(fontsize=8)
        fig.suptitle("Simulacion vs Teoria - M/M/1 (casos estables)")
        fig.tight_layout(); fig.savefig(os.path.join(carpeta, "barras_medidas.png"), dpi=130)
        plt.close(fig)

    # (d) distribucion P(Nq = n) para un lambda representativo
    pct = cfg["lambda_distribucion"]
    if pct in resultados and resultados[pct]["teo"]["L"] is not None:
        import numpy as np
        rho = resultados[pct]["teo"]["rho"]
        dist = resultados[pct]["agg"]["dist_nq"]
        ns = list(range(0, min(max(dist) + 1, 11)))
        sim = [dist.get(n, 0.0) for n in ns]
        teo = [teoria_pn_cola(n, rho) for n in ns]
        x = np.arange(len(ns))
        plt.figure(figsize=(9, 5))
        plt.bar(x - 0.2, sim, 0.4, label="Simulado")
        plt.bar(x + 0.2, teo, 0.4, label="Teorico")
        plt.xticks(x, ns)
        plt.xlabel("n (clientes en cola)"); plt.ylabel("Probabilidad")
        plt.title("Distribucion P(Nq=n) - lambda=%d%% (rho=%.2f)" % (pct, rho))
        plt.legend(); plt.grid(True, axis="y", alpha=0.3); plt.tight_layout()
        plt.savefig(os.path.join(carpeta, "dist_cola.png"), dpi=130); plt.close()

    print("[png]  graficos de cola infinita guardados en %s/" % carpeta)


# ===========================================================================
#  EXPERIMENTO 2: COLA FINITA, PROBABILIDAD DE DENEGACION
# ===========================================================================
def experimento_cola_finita(cfg):
    mu = cfg["mu"]
    rho = cfg["rho_bloqueo"]
    lam = rho * mu
    print("\n" + "=" * 78)
    print(" EXPERIMENTO 2 - M/M/1/K cola FINITA   (rho = %.2f, lambda = %.2f, mu = %.2f)"
          % (rho, lam, mu))
    print("=" * 78)
    print(" Capacidades de cola evaluadas: %s" % cfg["capacidades"])

    filas = []
    for cap in cfg["capacidades"]:
        agg = correr_experimento(lam, mu, cfg["tmax"], cfg["corridas"],
                                 cap_cola=cap, n_muestras=cfg["n_muestras"])
        m, h = agg["p_deneg"]
        K = cap + 1
        teo = teoria_bloqueo_mm1k(rho, K)
        filas.append((cap, K, m, h, teo))
        print("   cola=%2d (K=%2d):  P_deneg sim = %7.4f%% +- %6.4f%%   teo = %7.4f%%"
              % (cap, K, 100 * m, 100 * h, 100 * teo))

    ruta = os.path.join(cfg["carpeta_salida"], "resultados_cola_finita.csv")
    with open(ruta, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cap_cola", "K", "p_deneg_sim", "ic95", "p_deneg_teorico"])
        for cap, K, m, h, teo in filas:
            w.writerow([cap, K, "%.6f" % m, "%.6f" % h, "%.6f" % teo])
    print("\n[csv]  %s" % ruta)

    if HAY_PLT and not cfg["sin_graficos"]:
        import numpy as np
        caps = [str(c) for c, *_ in filas]
        x = np.arange(len(filas))
        sim = [m for *_, m, h, teo in [(c, K, m, h, teo) for c, K, m, h, teo in filas]]
        sim = [f[2] for f in filas]; err = [f[3] for f in filas]; teo = [f[4] for f in filas]
        plt.figure(figsize=(9, 5))
        plt.bar(x - 0.2, [100 * s for s in sim], 0.4, yerr=[100 * e for e in err],
                capsize=4, label="Simulado (Python)")
        plt.bar(x + 0.2, [100 * t for t in teo], 0.4, label="Teorico")
        plt.xticks(x, caps)
        plt.xlabel("Capacidad de la cola"); plt.ylabel("Prob. de denegacion (%)")
        plt.title("Probabilidad de denegacion vs capacidad - M/M/1/K (rho=%.2f)" % rho)
        plt.legend(); plt.grid(True, axis="y", alpha=0.3); plt.tight_layout()
        plt.savefig(os.path.join(cfg["carpeta_salida"], "bloqueo.png"), dpi=130); plt.close()
        print("[png]  grafico de denegacion guardado")
    return filas


# ===========================================================================
#  MAIN
# ===========================================================================
def main():
    p = argparse.ArgumentParser(description="Simulacion M/M/1 y M/M/1/K (TP3 Simulacion)")
    p.add_argument("--mu", type=float, default=CONFIG["mu"], help="tasa de servicio")
    p.add_argument("--porcentajes", type=int, nargs="+", default=CONFIG["porcentajes"],
                   help="lambda como %% de mu (ej: 25 50 75 100 125)")
    p.add_argument("--corridas", type=int, default=CONFIG["corridas"], help="replicas (>=10)")
    p.add_argument("--tmax", type=float, default=CONFIG["tmax"], help="horizonte por corrida")
    p.add_argument("--n-muestras", type=int, default=CONFIG["n_muestras"])
    p.add_argument("--rho-bloqueo", type=float, default=CONFIG["rho_bloqueo"])
    p.add_argument("--capacidades", type=int, nargs="+", default=CONFIG["capacidades"])
    p.add_argument("--lambda-distribucion", type=int, default=CONFIG["lambda_distribucion"])
    p.add_argument("--carpeta-salida", default=CONFIG["carpeta_salida"])
    p.add_argument("--sin-graficos", action="store_true", help="no generar PNG")
    p.add_argument("--solo", choices=["infinita", "finita"], default=None,
                   help="correr solo un experimento")
    args = p.parse_args()

    cfg = dict(CONFIG)
    cfg.update({
        "mu": args.mu, "porcentajes": args.porcentajes, "corridas": args.corridas,
        "tmax": args.tmax, "n_muestras": args.n_muestras,
        "rho_bloqueo": args.rho_bloqueo, "capacidades": args.capacidades,
        "lambda_distribucion": args.lambda_distribucion,
        "carpeta_salida": args.carpeta_salida, "sin_graficos": args.sin_graficos,
    })
    os.makedirs(cfg["carpeta_salida"], exist_ok=True)

    if not HAY_PLT and not cfg["sin_graficos"]:
        print("[aviso] matplotlib no esta instalado: se generan solo tablas y CSV.")

    if args.solo in (None, "infinita"):
        experimento_cola_infinita(cfg)
    if args.solo in (None, "finita"):
        experimento_cola_finita(cfg)

    print("\nListo. Resultados en la carpeta '%s'." % cfg["carpeta_salida"])


if __name__ == "__main__":
    main()