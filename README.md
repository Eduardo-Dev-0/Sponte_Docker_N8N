# Stack Sponte DW

Ambiente Docker que concentra, num só `docker compose`, tudo o que é preciso para ler a API do **Sponte** (sistema acadêmico), gravar num **Data Warehouse em PostgreSQL** e rodar automações (n8n e WhatsApp) em cima desses dados.

É a versão em contêineres do projeto **Projeto-SPT-DW**, o DW completo (camadas `raw`, `stg`, `dw` e `bi`, histórico de matrículas e views para Power BI). Aqui o foco é ter um ambiente fácil de subir, com o Postgres no Docker, a carga rodando sozinha em ciclo e backup diário.

## O que sobe

| Serviço | Função | Acesso |
| --- | --- | --- |
| `postgres` | PostgreSQL 17 com 3 bases: `sponte_dw`, `n8n` e `evolution` | `localhost:5433` (de fora); `postgres:5432` (entre contêineres) |
| `redis` | Cache da Evolution API | somente interno |
| `etl` | Carga unificada (cadastro + frequência), em ciclo | sem porta |
| `n8n` | Automações e workflows | http://localhost:5678 |
| `evolution` | API do WhatsApp | http://localhost:8080 |
| `backup` | `pg_dump` diário das 3 bases na pasta `backups`, mantendo os últimos 14 dias | sem porta |

Os dados ficam em volumes Docker (`pgdata`, `redisdata`, `n8ndata`, `evolution_instances`), não nos contêineres.

## Como funciona o ETL

```
API Sponte (SOAP/WSDL)
   └─ sponte_loader.py ─────▶ raw.*  ─▶ stg.* ─▶ dw.*   (cadastro: turmas, alunos, matrículas)
   └─ carga_frequencia.py ──▶ raw.*  ─────────▶ dw.*   (frequência por dia de aula)
        ▲
        └─ carga_unificada.py roda as duas em sequência
             ▲
             └─ runner.py repete a cada ETL_INTERVAL_MINUTES
```

- `sponte_loader.py`: carga de cadastro (turmas, matrículas e alunos).
- `carga_frequencia.py`: carga de frequência por dia de aula.
- `carga_unificada.py`: orquestra as duas cargas num único comando.
- `runner.py`: laço que executa a carga unificada no intervalo configurado.
- Um lock no banco impede duas cargas simultâneas: se já houver uma em andamento, a nova avisa e sai sem fazer nada.
- A carga só é marcada como `ok` se nenhuma chamada à API falhou (tudo ou nada).

## Estrutura do repositório

```
stack/
├── docker-compose.yml
├── .env.example                 # modelo das variáveis (copie para .env)
├── Docker comandos da stack Sponte DW.md   # guia de comandos do dia a dia
├── initdb/                      # scripts de criação das bases e schemas (só rodam com o volume novo)
├── sponte_etl/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── runner.py                # agenda a carga em ciclo
│   ├── carga_unificada.py       # cadastro + frequência
│   ├── sponte_loader.py         # cadastro
│   └── carga_frequencia.py      # frequência
└── backups/                     # dumps gerados pelo serviço backup (ignorado pelo Git)
```

## Requisitos

- Docker Desktop (Windows) ou Docker Engine com o plugin Compose.
- Token de acesso da API do Sponte.
- Portas livres no computador: `5433`, `5678` e `8080`.

## Começando

1. Copie o modelo de variáveis e preencha:

   ```powershell
   Copy-Item .env.example .env
   ```

   Edite o `.env` com o token do Sponte, a senha do banco, a chave do n8n (`N8N_ENCRYPTION_KEY`) e o intervalo da carga (`ETL_INTERVAL_MINUTES`).

2. Suba a stack:

   ```powershell
   docker compose up -d
   ```

3. Confira se tudo está de pé:

   ```powershell
   docker compose ps
   docker compose logs --tail 50 etl
   ```

   Uma carga boa termina com `Carga unificada concluída em NNNs`.

Para forçar uma carga na hora:

```powershell
docker compose run --rm etl python carga_unificada.py
docker compose run --rm etl python carga_unificada.py --freq-incremental   # frequência só dos meses novos, recentes e pendentes
docker compose run --rm etl python carga_unificada.py --atualizar-alunos   # reconsulta CPF e e-mail de todos os alunos
```

## Acessando o banco

De fora do Docker (DBeaver, Power BI, scripts), conecte em:

| Campo | Valor |
| --- | --- |
| Host | `localhost` |
| Porta | `5433` |
| Banco | `sponte_dw` |
| Usuário e senha | os definidos no `.env` |

Ou direto pelo terminal:

```powershell
docker compose exec postgres psql -U postgres -d sponte_dw
```

## Backup

O serviço `backup` gera um `.dump` de cada base a cada 24 horas em `backups/` e mantém os últimos 14 dias. Para forçar um backup agora:

```powershell
docker compose restart backup
docker compose logs backup    # deve mostrar: ok sponte_dw / ok n8n / ok evolution
```

Procedimentos de teste e de restauração estão no guia de comandos.

## Quando mudar algo

| O que mudou | O que rodar |
| --- | --- |
| `.env` ou `docker-compose.yml` | `docker compose up -d` (o `restart` não relê o `.env`) |
| `carga_unificada.py`, `sponte_loader.py` ou `carga_frequencia.py` | nada; a pasta é montada e o próximo ciclo já usa o código novo |
| `runner.py` | `docker compose restart etl` |
| `requirements.txt` ou `Dockerfile` | `docker compose up -d --build etl` |

## Segurança

- O `.env` nunca vai para o Git (token do Sponte, senha do banco e `N8N_ENCRYPTION_KEY`). Use o `.env.example` como modelo.
- Sem a `N8N_ENCRYPTION_KEY`, as credenciais salvas no n8n ficam ilegíveis. Guarde uma cópia do `.env` fora do computador.
- Os dumps em `backups/` contêm dados pessoais de alunos (CPF e e-mail). Trate a pasta como dado sensível e mantenha-a fora do repositório.
- `docker compose down -v` apaga os volumes e, com eles, o banco, os fluxos do n8n e as instâncias do WhatsApp. Use só para recomeçar do zero.

## Documentação

- [Docker comandos da stack Sponte DW](<Docker comandos da stack Sponte DW.md>): operação diária, logs, backup e restore, atualização de imagens e diagnóstico.
- **Projeto-SPT-DW**: o projeto de origem, com o modelo de dados completo, as views `bi` e o roadmap.
