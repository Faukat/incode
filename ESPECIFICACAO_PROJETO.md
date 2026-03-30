# Especificacao do Projeto

## Visao geral

Este projeto indexa repositorios locais e publica os vetores no `Amazon S3 Vectors`.
Os embeddings sao gerados com `Amazon Titan Text Embeddings v2` via `Bedrock Runtime`.
A consulta pode ser feita pela CLI ou pelo servidor MCP.

## Objetivo

- Registrar projetos locais por nome e caminho.
- Indexar codigo e documentos em chunks com contexto estrutural.
- Consultar trechos relevantes por busca semantica com reranking lexical local.
- Expor o mesmo fluxo para uso humano e para agentes.

## Stack principal

- Python 3.11+
- `uv` para ambiente e execucao
- `typer` e `rich` para a CLI
- `fastmcp` para o servidor MCP
- `boto3` para `S3 Vectors` e `Bedrock Runtime`
- `python-dotenv` para configuracao

## Arquitetura

- `src/repo_code_indexer/config.py`
  - carrega a configuracao do ambiente
  - define bucket vetorial, modelo, dimensoes, chunking e limites de busca

- `src/repo_code_indexer/projects.py`
  - descobre projetos locais abaixo da raiz configurada
  - ignora diretorios comuns como `.git`, `node_modules` e `.venv`

- `src/repo_code_indexer/index_flow.py`
  - varre arquivos suportados
  - quebra o conteudo em chunks
  - extrai spans estruturais para Python
  - gera embeddings com Titan v2

- `src/repo_code_indexer/search.py`
  - cria o vector bucket sob demanda
  - mantem o cadastro local dos projetos em `projects.json`
  - cria um indice vetorial por projeto no `S3 Vectors`
  - escreve e consulta vetores
  - aplica reranking lexical local nos resultados

- `src/repo_code_indexer/service.py`
  - concentra o fluxo de setup, registro, indexacao e busca

- `src/repo_code_indexer/cli.py`
  - expoe comandos para setup, descoberta, cadastro, indexacao e query

- `src/repo_code_indexer/mcp_server.py`
  - expoe as mesmas capacidades como tools MCP

## Fluxo ponta a ponta

```text
[.env / variaveis]
        |
        v
[get_settings()]
        |
        v
[setup_service()]
        |
        +--> cria state dir local
        +--> garante o vector bucket
        +--> aquece o cliente de embeddings
        |
        v
[register_project()]
        |
        v
[index_project()]
        |
        +--> build_chunks()
        +--> embed_texts()
        +--> replace_project_chunks()
        |
        v
[indice por projeto no S3 Vectors]

Consulta:
[CLI query / MCP search_code]
        |
        v
[embed_texts(query)]
        |
        v
[query_vectors()]
        |
        v
[reranking lexical local]
        |
        v
[top resultados com score]
```

## Persistencia

- Cadastro dos projetos: arquivo local em `REPO_INDEXER_STATE_DIR/projects.json`
- Vetores: um indice por projeto no `Amazon S3 Vectors`
- Metadados por chunk:
  - `file_path`
  - `language`
  - `symbol_name`
  - `symbol_type`
  - `path_tokens`
  - `start_line`
  - `end_line`
  - `content`
  - `chunk_index`

## Configuracao importante

- `REPO_INDEXER_ROOT`
- `REPO_INDEXER_STATE_DIR`
- `AWS_REGION`
- `AWS_VECTOR_BUCKET_NAME`
- `AWS_VECTOR_INDEX_PREFIX`
- `AWS_VECTOR_DISTANCE_METRIC`
- `AWS_VECTOR_PUT_BATCH_SIZE`
- `EMBEDDING_MODEL`
- `EMBEDDING_DIMENSIONS`
- `EMBEDDING_NORMALIZE`
- `EMBEDDING_MAX_WORKERS`
- `CHUNK_MAX_CHARS`
- `CHUNK_OVERLAP`
- `QUERY_LIMIT`
- `QUERY_MIN_SCORE`
- `QUERY_FALLBACK_MIN_SCORE`
- `QUERY_CANDIDATE_MULTIPLIER`

## Limitacoes atuais

- A indexacao continua sendo full refresh por projeto.
- Cada embedding ainda e gerado por chamada individual ao Titan, com paralelismo local.
- O reranking lexical e local e simples; ainda nao ha filtros estruturados por metadata.
- Nao ha controle explicito de consistencia eventual para todos os caminhos do `S3 Vectors`.
- Nao existe suite extensa de testes automatizados.

## Melhorias prioritarias

1. Indexacao incremental por hash ou `mtime`.
2. Embeddings em lotes maiores ou pipeline assincrono para reduzir latencia e custo.
3. Mais filtros e facetas na busca usando metadata.
4. Melhor observabilidade para throughput, retries e falhas por projeto.
5. Testes automatizados para setup, indexacao e consulta.
