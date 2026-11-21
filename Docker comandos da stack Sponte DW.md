# Docker: comandos da stack Sponte DW

Stack Sponte DW · atualizado em 14/11/2026

Rode todos os comandos no PowerShell, dentro da pasta da stack (onde está o `docker-compose.yml`, por exemplo `C:\stack`).

## 1. Visão geral

| Serviço | Função | Acesso |
| --- | --- | --- |
| postgres | Banco com 3 bases: sponte\_dw, n8n, evolution (versão 17) | `localhost:5433` de fora; `postgres:5432` entre containers |
| redis | Cache da Evolution | só interno |
| etl | Carga unificada (cadastro + frequência completa), em ciclo | sem porta |
| n8n | Automações | http://localhost:5678 |
| evolution | API do WhatsApp | http://localhost:8080 |
| backup | pg\_dump diário dos 3 bancos na pasta `backups` | sem porta |

Os dados vivem nos volumes `pgdata`, `redisdata`, `n8ndata` e `evolution_instances`, não nos containers. Apagar um container não apaga os dados; apagar o volume apaga.

## 2. Dia a dia

```
docker compose ps                 # estado de todos os serviços
docker compose up -d              # sobe tudo (recria só o que mudou)
docker compose stop               # para tudo, mantém containers
docker compose start              # liga de novo o que foi parado
docker compose restart etl        # reinicia um serviço
docker compose down               # remove containers e rede, MANTÉM os volumes
```

Cada comando aceita o nome de um ou mais serviços no fim, por exemplo `docker compose stop etl n8n`.

## 3. Logs

```
docker compose logs --tail 50 etl          # últimas 50 linhas
docker compose logs -f --tail 100 etl      # acompanha ao vivo (Ctrl+C sai, não para o container)
docker compose logs --since 1h n8n         # última hora
docker compose logs backup                 # deve mostrar: ok sponte_dw / ok n8n / ok evolution
```

Uma carga boa termina com `Carga unificada concluída em NNNs`. Uma carga com problema mostra `CARGA ABORTADA` ou `CARGA FALHOU`.

## 4. Carga de dados (etl)

O serviço `etl` roda sozinho a cada `ETL_INTERVAL_MINUTES` (definido no `.env`). Para rodar na hora:

```
docker compose run --rm etl python carga_unificada.py
docker compose run --rm etl python carga_unificada.py --freq-incremental   # frequência só dos meses novos, recentes e pendentes
docker compose run --rm etl python carga_unificada.py --atualizar-alunos   # reconsulta CPF e e-mail de todos os alunos
```

Se já houver uma carga em andamento, a nova avisa `Já existe uma carga em andamento; saindo.` e termina sem fazer nada. Isso é o lock do banco funcionando, não é erro.

Conferir o resultado das últimas cargas:

```
docker compose exec postgres psql -U postgres -d sponte_dw -c "SELECT carga_id, status, iniciada_em, finalizada_em, observacao FROM raw.carga ORDER BY carga_id DESC LIMIT 5;"
docker compose exec postgres psql -U postgres -d sponte_dw -c "SELECT carga_freq_id, status, iniciada_em, finalizada_em, observacao FROM raw.carga_frequencia ORDER BY carga_freq_id DESC LIMIT 5;"
```

O `status` mais recente deve ser `ok`. Tempos de referência medidos: cerca de 297s (frequência incremental) e 562s (frequência completa).

## 5. Banco de dados

```
docker compose exec postgres psql -U postgres -d sponte_dw     # abre o psql interativo
```

Dentro do psql:

```
\l                 -- lista os bancos
\dn                -- lista os schemas (raw, stg, dw)
\dt dw.*           -- tabelas do schema dw
\q                 -- sai
```

Para DBeaver, Power BI ou scripts rodando na sua máquina, conecte em `localhost`, porta `5433`, banco `sponte_dw`, usuário e senha do `.env`.

## 6. Backup e restore

O serviço `backup` gera um `.dump` de cada banco a cada 24h na pasta `backups` e mantém os últimos 14 dias.

```
docker compose restart backup                  # força um backup agora (ele roda ao iniciar)
docker compose logs backup                     # confirma os três ok
docker compose exec backup pg_dump -Fc -d sponte_dw -f /backups/sponte_dw_manual.dump   # backup manual pontual
```

**Testar um backup** (sem tocar no banco real):

```
docker compose exec postgres psql -U postgres -c "CREATE DATABASE teste_restore;"
docker compose cp backups/NOME_DO_ARQUIVO.dump postgres:/tmp/t.dump
docker compose exec postgres pg_restore -U postgres -d teste_restore --no-owner /tmp/t.dump
docker compose exec postgres psql -U postgres -d teste_restore -c "SELECT count(*) FROM dw.fato_matricula;"
docker compose exec postgres psql -U postgres -c "DROP DATABASE teste_restore;"
```

**Restaurar de verdade** (recuperação de desastre, sobrescreve o banco atual):

```
docker compose stop etl n8n evolution
docker compose cp backups/NOME_DO_ARQUIVO.dump postgres:/tmp/r.dump
docker compose exec postgres pg_restore -U postgres -d sponte_dw --clean --if-exists --no-owner /tmp/r.dump
docker compose start etl n8n evolution
```

Para restaurar o n8n ou a Evolution, troque `sponte_dw` pelo nome do banco e use o dump correspondente.

## 7. Mudei algo: o que rodar?

| O que mudou | Comando |
| --- | --- |
| `.env` ou `docker-compose.yml` | `docker compose up -d` (o `restart` NÃO relê o `.env`) |
| `carga_unificada.py`, `sponte_loader.py`, `carga_frequencia.py` | nada: a pasta é montada e o próximo ciclo já usa o código novo |
| `runner.py` | `docker compose restart etl` |
| `requirements.txt` ou `Dockerfile` | `docker compose up -d --build etl` |
| imagem do n8n ou da Evolution | ver a seção 8 |

## 8. Atualizar n8n e Evolution

Faça um backup antes (`docker compose restart backup` e confira o log).

```
docker compose pull n8n evolution
docker compose up -d n8n evolution
docker compose logs --tail 50 n8n
```

Se algo quebrar, volte a imagem para a versão anterior no `docker-compose.yml` (fixe a tag em vez de `latest`) e rode `docker compose up -d` de novo. Não troque a versão principal do Postgres (por exemplo 17 para 18) sobre o volume existente: ele recusa subir. Esse upgrade exige dump e restore.

## 9. Diagnóstico

```
docker compose config                 # valida o compose e mostra o resultado final
docker compose ps -a                  # inclui containers parados ou que caíram
docker compose logs --tail 100 postgres
docker compose exec etl bash          # abre um terminal dentro do container etl
docker stats                          # uso de CPU e memória ao vivo
docker system df                      # espaço usado pelo Docker
docker compose exec postgres pg_isready -U postgres
```

## 10. Comandos perigosos

- `docker compose down -v` apaga os volumes: **perde o banco, os fluxos do n8n e as instâncias da Evolution**. Só use para recomeçar do zero.
- `docker volume rm` e `docker system prune -a --volumes` também apagam dados. Evite.
- Não apague a pasta `backups`, nem o arquivo `.env`. Sem o `N8N_ENCRYPTION_KEY` do `.env`, as credenciais salvas no n8n ficam ilegíveis.
- Trocar `PG_PASSWORD` no `.env` depois que o volume do banco existe não altera a senha já gravada no Postgres.

## 11. Rotina sugerida

**Depois de reiniciar o Windows:** abra o Docker Desktop (as cargas e os backups só rodam com ele ligado) e confira `docker compose ps`.

**Uma vez por semana:**

1. `docker compose logs --tail 50 etl` e confirmar cargas concluídas.
2. `dir backups` e confirmar arquivos recentes e com tamanho maior que zero.
3. `docker system df` e olhar o espaço livre em disco.
4. Copiar a pasta `backups` e o `.env` para um local fora do computador.

## 12. Erros comuns

| Mensagem ou sintoma | Causa e solução |
| --- | --- |
| `ports are not available` na 5433 | Outra aplicação usa a porta. Troque o lado esquerdo do mapeamento em `ports` do postgres |
| `Já existe uma carga em andamento` | Lock normal; aguarde a carga atual terminar |
| `server version mismatch` no log do backup | A imagem do `backup` precisa ter a mesma versão principal do `postgres` (17) |
| `relation "raw.carga" does not exist` | O restore não rodou ou falhou; confira `\dn` e refaça o `pg_restore` |
| Container `etl` reiniciando sem parar | Veja `docker compose logs --tail 50 etl`; costuma ser falta de variável no `.env` |
| Postgres `unhealthy` | Veja `docker compose logs --tail 100 postgres` |
