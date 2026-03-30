# Incode

Servico para registrar projetos locais, indexa-los no `Amazon S3 Vectors` e consultar codigo com busca semantica usando `Amazon Titan Text Embeddings v2`.

O fluxo continua direto:

- registrar um ou mais repositorios locais
- indexar quando quiser
- consultar semanticamente via CLI ou MCP

## Requisitos

- Python 3.11+
- `uv`
- credenciais AWS validas na maquina
- permissoes para `s3vectors:*` no bucket/index do projeto e `bedrock:InvokeModel` para `amazon.titan-embed-text-v2:0`

## Instalacao rapida

```bash
git clone <seu-repo>
cd incode
uv sync
cp .env.example .env
uv run incode setup
```

O `setup` cria o bucket vetorial se ele ainda nao existir e prepara o state local em `REPO_INDEXER_STATE_DIR`.

## Configuracao

As variaveis principais ficam no `.env`:

```env
REPO_INDEXER_ROOT=/workspace
REPO_INDEXER_STATE_DIR=~/.incode
AWS_REGION=us-east-1
AWS_VECTOR_BUCKET_NAME=incode-vectors
AWS_VECTOR_INDEX_PREFIX=incode
AWS_VECTOR_DISTANCE_METRIC=cosine
AWS_VECTOR_PUT_BATCH_SIZE=25
EMBEDDING_MODEL=amazon.titan-embed-text-v2:0
EMBEDDING_DIMENSIONS=512
EMBEDDING_NORMALIZE=true
EMBEDDING_MAX_WORKERS=8
CHUNK_MAX_CHARS=1600
CHUNK_OVERLAP=200
QUERY_LIMIT=5
QUERY_MIN_SCORE=0.10
QUERY_FALLBACK_MIN_SCORE=0.03
QUERY_CANDIDATE_MULTIPLIER=2
QUERY_EMBED_CACHE_SIZE=256
LEXICAL_DB_SCORE_WEIGHT=0.25
RESULT_PREVIEW_CHARS=2000
```

### O que cada variavel controla

- `REPO_INDEXER_ROOT`: raiz padrao para descobrir projetos e resolver caminhos relativos
- `REPO_INDEXER_STATE_DIR`: registro local dos projetos e metadados de indexacao
- `AWS_REGION`: regiao do `S3 Vectors` e do `Bedrock Runtime`
- `AWS_VECTOR_BUCKET_NAME`: bucket vetorial onde os indices serao criados
- `AWS_VECTOR_INDEX_PREFIX`: prefixo usado para gerar nomes estaveis dos indices por projeto
- `AWS_VECTOR_DISTANCE_METRIC`: metrica usada no indice vetorial
- `AWS_VECTOR_PUT_BATCH_SIZE`: tamanho do lote de `put_vectors`
- `EMBEDDING_MODEL`: modelo de embedding do Bedrock
- `EMBEDDING_DIMENSIONS`: dimensionalidade usada no Titan v2
- `EMBEDDING_NORMALIZE`: pede embeddings normalizados ao Titan
- `EMBEDDING_MAX_WORKERS`: paralelismo de chamadas ao Bedrock durante indexacao
- `CHUNK_MAX_CHARS`: tamanho maximo de cada chunk
- `CHUNK_OVERLAP`: sobreposicao entre chunks
- `QUERY_LIMIT`: quantidade padrao de resultados na busca
- `QUERY_MIN_SCORE`: score minimo para um resultado ser exibido
- `QUERY_FALLBACK_MIN_SCORE`: limiar secundario para fallback quando nada passa no filtro principal
- `QUERY_CANDIDATE_MULTIPLIER`: quantidade de candidatos semanticos usados antes do reranking local
- `QUERY_EMBED_CACHE_SIZE`: quantidade maxima de consultas com embedding cacheado em memoria
- `LEXICAL_DB_SCORE_WEIGHT`: mantido por compatibilidade; o reranking lexical agora acontece localmente
- `RESULT_PREVIEW_CHARS`: tamanho maximo exibido por resultado na CLI

## Fluxo recomendado

### 1. Ver a configuracao atual

```bash
uv run incode config
```

### 2. Registrar um projeto manualmente

Se o caminho for absoluto:

```bash
uv run incode add-project projeto-a /workspace/projeto-a
```

Se o projeto estiver abaixo de `REPO_INDEXER_ROOT`, basta usar o nome:

```bash
uv run incode add-project projeto-a
```

### 3. Descobrir projetos em lote

```bash
uv run incode discover
uv run incode discover --register
```

### 4. Ver projetos registrados

```bash
uv run incode projects
```

### 5. Indexar

```bash
uv run incode index projeto-a
uv run incode index --all
```

Cada projeto registrado recebe um indice dedicado no `S3 Vectors`.

### 6. Consultar semanticamente

```bash
uv run incode query projeto-a "onde fica a autenticacao?"
uv run incode query projeto-a "como eu me autentico?" --min-score 0.05 --limit 8
```

### 7. Remover um projeto registrado

Somente do cadastro local:

```bash
uv run incode remove-project projeto-a
```

Removendo tambem o indice vetorial do projeto:

```bash
uv run incode remove-project projeto-a --delete-chunks
```

## Comandos disponiveis

- `uv run incode setup`
- `uv run incode config`
- `uv run incode discover [--root CAMINHO] [--register]`
- `uv run incode add-project NOME [CAMINHO]`
- `uv run incode remove-project NOME [--delete-chunks]`
- `uv run incode projects`
- `uv run incode index [NOME] [--all]`
- `uv run incode query NOME "texto" [--limit N] [--min-score F]`

## MCP

Rode o servidor MCP:

```bash
uv run incode-mcp
```

Use `examples/mcp-config.json` como base generica no cliente MCP.
Se estiver usando OpenCode no Windows, pode usar `examples/opencode-mcp-config.json` como base.

Tools expostas:

- `setup_service_tool()`
- `list_projects_tool(root?)`
- `discover_projects_tool(root?, register?)`
- `register_project_tool(project_name, project_path?)`
- `remove_project_tool(project_name, delete_chunks?)`
- `index_project(project_name)`
- `search_code_tool(project_name, query, limit?, min_score?)`

Observacao:

- As respostas MCP retornam payload compacto, com preview resumido (`snippet`) em vez do chunk completo, para reduzir contexto consumido pelo cliente de IA.

## Como o servico funciona

- guarda o cadastro dos projetos em um arquivo local em `REPO_INDEXER_STATE_DIR`
- cria um indice por projeto no `Amazon S3 Vectors`
- gera embeddings com `Amazon Titan Text Embeddings v2`
- enriquece cada chunk com caminho, simbolos, linhas e contexto estrutural
- faz reranking lexical local usando caminho, simbolos e conteudo retornados via metadata

## Observacoes

- O projeto ignora diretorios comuns como `.git`, `node_modules`, `.venv`, `dist` e `build`
- Indexa extensoes comuns de codigo e texto
- Para Python, tenta quebrar por `class`, `function` e `method`, preservando linhas e simbolos
- O bucket vetorial e o state local sao criados sob demanda
- O default de `EMBEDDING_DIMENSIONS=512` busca um equilibrio entre custo, latencia e qualidade

## Teste ponta a ponta

Com as credenciais AWS disponiveis, execute:

```bash
./scripts/e2e.sh
```

O script registra o projeto de exemplo em `examples/sample-workspace/projeto-a`, indexa e valida a busca.

Para ajustar o limiar:

```bash
MIN_SCORE=0.20 ./scripts/e2e.sh
```

