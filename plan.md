# Plan TP3 — Simulación MM1 e Inventario

Estado al 2026-06-30. Cruce entre la **consigna** (`Consigna.md`), el **código** (`MM1/main.py` e `Inventario/main.py`) y el **informe en proceso** (`TP3-en proceso.pdf`, 10 págs).

> Los dos modelos están separados en carpetas independientes: `MM1/` e `Inventario/`, cada una con su `main.py` y su `resultados/` (ignorado por git vía `.gitignore`).

---

## 1. Lo que YA está hecho

### Código Python — MM1 (`MM1/main.py`)
- Simulación por eventos discretos de cola M/M/1 (`simular_mm1`), con cola **infinita** y **finita** (K = tamaño + 1).
- Configuración pedida por la consigna:
  - Tasas de arribo al 25/50/75/100/125% de µ (`factores_lambda = [0.25, 0.50, 0.75, 1.00, 1.25]`).
  - Colas finitas de tamaño **0, 2, 5, 10, 50**.
  - **10 corridas** por experimento con semillas deterministas reproducibles.
- Medidas de rendimiento: **L, Lq, W, Wq, utilización**, probabilidad de denegación y **P(Q=n)** (clientes en cola).
- Valores **teóricos** para cola infinita y bloqueo teórico para cola finita.
- Medidas **en relación al tiempo** (historial `L_t, Lq_t, W_t, Wq_t, utilizacion_t`).
- Exporta CSV (`mm1_*`) y gráficos (métricas vs λ/µ, denegación por tamaño de cola, evolución temporal, P(Q=n)).
- **Revisado y refactorizado** (commit `c1316ee`): flag `registrar_historial` para no armar la traza en cada corrida y limpieza del teórico finito. Sin errores de correctitud; los valores reproducen las tablas teóricas del informe (con µ=20).

### Código Python — Inventario (`Inventario/main.py`)
- **Reescrito como política (s, S)** para coincidir con el informe (§3):
  - Cantidad de pedido variable **Z = S − posición de inventario** (order-up-to S).
  - **Lead time aleatorio** entero ~ Uniforme[`lead_time_min`, `lead_time_max`].
  - **Faltante con backorder**: el stock puede quedar negativo y se cubre con recepciones futuras.
  - **Costo de orden = K + i·Z** (fijo + incremental por unidad).
  - Costos de mantenimiento (`h·stock⁺`) y faltante (`p·stock⁻`) por día.
- Costos: **orden, mantenimiento, faltante y total** — finales y acumulados en el tiempo.
- 3 políticas (A/B/C) con **10 corridas** cada una.
- Exporta CSV (`inventario_*`) y gráficos.

### Resultados generados
- Cada modelo escribe en su propia carpeta `resultados/` (ahora **ignorada por git**; regenerar con `python3 main.py` dentro de cada carpeta).

### Informe PDF (`TP3-en proceso.pdf`, 10 págs)
- Carátula e índice (actualizado con 2.4/2.5 Python/Anylogic y 3.1/3.2 inventario).
- Marco teórico M/M/1: notación de Kendall, ecuaciones (ρ, L, Lq, W, Wq, Pn).
- Parámetros base (cajero, µ=20) y cálculo de las 5 tasas de arribo.
- Tabla de **valores teóricos esperados** (25/50/75%) desde la calculadora.
- Justificación de por qué no se calcula al 100% y 125% (ρ≥1).
- Teoría y cálculo de **denegación M/M/1/K** para colas 0/2/5/10/50.
- **NUEVO:** marco teórico de inventario (§3.1): política (s, S), costo de orden `K + i·Z`, costo de mantenimiento e integral de faltante, costo total esperado.

---

## 2. Lo que FALTA hacer

### A. Discrepancia de modelo de inventario: código ≠ informe ✅ RESUELTO
`Inventario/main.py` fue reescrito como política **(s, S)** con lead time uniforme,
backorders y costo de orden `K + i·Z`, alineado con la teoría del informe (§3.1).
Pendiente derivado: **justificar la elección de parámetros** (s, S, costos, lead time)
→ ver §E (sección 3.2 del informe).

### B. Resolver discrepancia de µ en MM1 (BLOQUEANTE)
- Informe usa **µ = 20**; código usa **`mu = 10.0`**.
- **Acción:** poner `PARAMETROS_MM1["mu"] = 20.0` para reproducir exactamente las tablas teóricas del informe.

### C. Ingreso de parámetros para mostrar en clase (consigna, requisito)
- Hoy los parámetros están hardcodeados en `PARAMETROS_MM1` / `PARAMETROS_INVENTARIO`.
- **Acción:** permitir variarlos fácilmente (argparse o `input()`) para mostrarlos en vivo.

### D. Implementación en AnyLogic (consigna, requisito)
- No hay ningún `.alp` en el repo. La consigna pide comparar **3 fuentes**: teórico, Python y **AnyLogic**.
- **Acción:** construir M/M/1 e inventario en AnyLogic y exportar resultados. (Referencia: directorio `the-art-of-process-centric-modeling-with-anylogic`.)
- Secciones **2.5** (M/M/1 en AnyLogic) y la equivalente de inventario del informe están vacías.

### E. Informe — secciones faltantes
- **1. Introducción** (pág. 3) — vacía.
- **2.4 Construcción del modelo en Python** — vacía: explicar el algoritmo de eventos discretos, mostrar resultados simulados, comparar Simulado vs Teórico (insertar gráficos generados).
- **2.5 Construcción en AnyLogic** — vacía.
- **Tabla comparativa de las 3 fuentes** (Teórico / Python / AnyLogic) para MM1.
- **Resultados MM1**: tablas con promedios de las 10 corridas + gráficos; análisis denegación simulada vs teórica.
- **3.2 Simulación del modelo de inventario** — vacía: justificación de parámetros (la consigna lo exige), resultados por política, gráficos, análisis y comparación de 3 fuentes (teórico/EOQ — Python — AnyLogic).

### F. Detalles a revisar
- `P_n` del informe es probabilidad de *n en el sistema*; el código calcula *n en cola* (P(Q=n)). La consigna pide "n clientes en **cola**" → el código está bien; alinear la notación en el informe.
- En cola finita el código deja L/Lq/W/Wq teóricos en `NaN` (aceptable: la consigna solo pide denegación para finita). Documentarlo.
- Completar nombres/legajos en la carátula (hay varios "11111" de placeholder).

---

## 3. Orden sugerido
1. ~~Alinear el modelo de inventario como (s, S)~~ ✅ hecho.
2. Unificar µ en MM1 (B) y correr el código → validar contra tablas teóricas.
3. Agregar ingreso de parámetros (C).
4. Construir modelos en AnyLogic (D) y exportar resultados.
5. Redactar secciones faltantes del informe con tablas comparativas de 3 fuentes (E).
6. Limpieza final: notación, carátula, justificaciones (F).
