"""Executa as etapas em sequência a cada INTERVAL_MINUTES.
Se o Postgres não estiver pronto ou uma etapa falhar, tenta de novo após RETRY_MINUTES.
Quando unificar os loaders, troque ETL_STEPS por um único comando (ex.: 'python carga_unificada.py')."""
import logging, os, shlex, subprocess, time

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("runner")

INTERVAL = int(os.getenv("INTERVAL_MINUTES", "60")) * 60
RETRY = int(os.getenv("RETRY_MINUTES", "10")) * 60
STEP_TIMEOUT = int(os.getenv("STEP_TIMEOUT_MIN", "180")) * 60
PG_RETRIES = int(os.getenv("PG_CONNECT_RETRIES", "40"))
PG_WAIT = 5  # segundos entre tentativas
STEPS = [s.strip() for s in os.getenv("ETL_STEPS", "").split(";") if s.strip()]


def aguardar_postgres():
    """Bloqueia até o Postgres aceitar conexões (ex.: depois do recovery no boot da máquina)."""
    for i in range(1, PG_RETRIES + 1):
        try:
            psycopg2.connect(
                host=os.getenv("PG_HOST", "postgres"),
                port=os.getenv("PG_PORT", "5432"),
                dbname=os.getenv("PG_DB", "sponte_dw"),
                user=os.getenv("PG_USER"),
                password=os.getenv("PG_PASSWORD"),
                connect_timeout=5,
            ).close()
            return True
        except psycopg2.OperationalError as e:
            log.warning("postgres indisponível (%d/%d): %s", i, PG_RETRIES, str(e).strip())
            time.sleep(PG_WAIT)
    return False


def ciclo():
    for step in STEPS:
        log.info("iniciando: %s", step)
        inicio = time.time()
        try:
            r = subprocess.run(shlex.split(step), timeout=STEP_TIMEOUT)
        except subprocess.TimeoutExpired:
            log.error("etapa excedeu o tempo limite de %d min: %s", STEP_TIMEOUT // 60, step)
            return False
        log.info("fim: %s (código %s, %.0fs)", step, r.returncode, time.time() - inicio)
        if r.returncode != 0:
            log.error("etapa falhou; encerrando este ciclo")
            return False
    return True


if __name__ == "__main__":
    if not STEPS:
        raise SystemExit("ETL_STEPS vazio")
    while True:
        ok = aguardar_postgres() and ciclo()
        espera = INTERVAL if ok else RETRY
        if not ok:
            log.warning("ciclo não concluído; nova tentativa mais cedo")
        log.info("próximo ciclo em %d min", espera // 60)
        time.sleep(espera)
