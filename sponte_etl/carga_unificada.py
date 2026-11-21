"""
Carga unificada Sponte -> PostgreSQL.

Ordem (a frequência depende do cadastro já atualizado no dw):
  1) cadastro: turmas, matrículas, integrantes e alunos  (sponte_loader)
  2) frequência: GetFrequenciaTurma + GetDiarioAulas      (carga_frequencia, modo completo)

Uso:
    python carga_unificada.py                      # cadastro + frequência completa
    python carga_unificada.py --atualizar-alunos   # consulta CPF/e-mail de todos os alunos
    python carga_unificada.py --freq-incremental   # frequência no modo normal (só meses novos/recentes/pendentes)

Variável opcional: FREQ_MODO=completa|incremental (padrão: completa).

Se o cadastro falhar, a frequência NÃO roda. Um lock no banco impede duas cargas ao mesmo tempo.
Código de saída: 0 = ok, 1 = erro.
"""
import os
import sys
import time
import traceback

import carga_frequencia as freq
import sponte_loader as cad

LOCK_KEY = 726001  # identificador do advisory lock desta carga


def etapa(nome, fn):
    print(f"\n===== {nome}: início =====", flush=True)
    t0 = time.time()
    fn()
    print(f"===== {nome}: ok em {time.time() - t0:.0f}s =====", flush=True)


def main(argv):
    completa_freq = not ("--freq-incremental" in argv
                         or os.getenv("FREQ_MODO", "completa").lower() == "incremental")
    atualizar_alunos = "--atualizar-alunos" in argv

    lock = cad.conectar()
    lock.autocommit = True
    with lock.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
        if not cur.fetchone()[0]:
            print("Já existe uma carga em andamento; saindo.")
            lock.close()
            return 0

    conn = cad.conectar()
    t0 = time.time()
    try:
        def cadastro():
            cad.executar_carga(conn, completo=atualizar_alunos)
            cad.processar(conn)

        def frequencia():
            freq.coletar_e_gravar(conn, ["--completa"] if completa_freq else [])
            freq.processar(conn)

        etapa("CADASTRO", cadastro)
        etapa(f"FREQUÊNCIA ({'completa' if completa_freq else 'incremental'})", frequencia)
        print(f"\nCarga unificada concluída em {time.time() - t0:.0f}s")
        return 0
    except SystemExit as e:  # as cargas abortam com SystemExit("mensagem")
        print(f"\nCARGA ABORTADA: {e}")
        return 1
    except Exception:
        print("\nCARGA FALHOU:")
        traceback.print_exc()
        return 1
    finally:
        conn.close()
        lock.close()  # libera o advisory lock


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
