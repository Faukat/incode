# Especificacao do Projeto

## Visao geral

Este projeto e um indexador semantico de codigo para repositorios locais.
Ele varre uma pasta raiz com varios projetos, identifica arquivos de codigo e texto,
quebra o conteudo em chunks, gera embeddings localmente e salva os vetores em Postgres
com `pgvector`. Depois disso, permite consulta semantica via CLI ou via MCP.

## Objetivo

- Listar projetos disponiveis dentro de uma pasta raiz configurada.
- Indexar um projeto inteiro de forma simples.
- Permitir busca semantica por trechos relevantes de codigo.
- Expor o mesmo fluxo para humanos via CLI e para clientes/agentes via MCP.

## Stack principal

- Python 3.11+
- `uv` para sincronizar dependencias e executar os comandos locais
- `typer` e `rich` para CLI
- `fastmcp` para servidor MCP
- `sentence-transformers` para embeddings locais
- `psycopg` e `pgvector` para persistencia e busca vetorial
- `python-dotenv` para configuracao

## Componentes

- `src/repo_code_indexer/config.py`
  - Carrega variaveis de ambiente.
  - Resolve a pasta raiz dos projetos.
  - Monta o DSN do Postgres.

- `src/repo_code_indexer/projects.py`
  - Lista projetos abaixo da raiz configurada.
  - Ignora diretorios comuns como `.git`, `node_modules` e `.venv`.
  - Permite selecao interativa no modo CLI.

- `src/repo_code_indexer/index_flow.py`
  - Varre arquivos suportados.
  - Le arquivos de texto com fallback de encoding.
  - Detecta linguagem por extensao.
  - Quebra conteudo em chunks.
  - Gera embeddings.

- `src/repo_code_indexer/search.py`
  - Cria tabela e indices basicos no banco.
  - Remove chunks antigos de um projeto.
  - Insere novos chunks com embedding.
  - Executa busca por similaridade vetorial.

- `src/repo_code_indexer/cli.py`
  - Expoe os comandos `projects`, `index` e `query`.

- `src/repo_code_indexer/mcp_server.py`
  - Expoe tools MCP para listar projetos, indexar e consultar.

## Fluxo ponta a ponta

```text
[.env / variaveis]
        |
        v
[get_settings()]
        |
        v
[list_projects(root)]
        |
        +--> CLI: projects
        |
        +--> CLI/MCP: index(project)
                     |
                     v
               [build_chunks()]
                     |
                     +--> iter_files()
                     +--> read_text_file()
                     +--> chunk_text()
                     |
                     v
               [embed_texts()]
                     |
                     v
               [insert_chunks()]
                     |
                     +--> ensure_tables()
                     +--> delete_project_chunks()
                     +--> INSERT no Postgres/pgvector

Consulta:
[CLI query / MCP search_code]
        |
        v
[embed_texts(query)]
        |
        v
[search_code()]
        |
        v
[SELECT por similaridade coseno]
        |
        v
[top resultados com score]
```

## Interface CLI

- `uv run repo-indexer projects`
  - Lista os projetos encontrados na pasta raiz.

- `uv run repo-indexer index [nome-do-projeto]`
  - Indexa um projeto especifico.
  - Sem parametro, entra em modo interativo.

- `uv run repo-indexer query <projeto> "<texto>"`
  - Executa busca semantica dentro do projeto indexado.

## Interface MCP

- `uv run repo-indexer-mcp`
  - Sobe o servidor MCP usando o ambiente gerenciado pelo `uv`.

- `list_projects_tool(root?)`
- `index_project(project_name, root?)`
- `search_code_tool(project_name, query, limit?)`

## Persistencia

O banco usa a tabela `code_chunks`, com os campos principais:

- `project_name`
- `file_path`
- `chunk_index`
- `language`
- `content`
- `embedding VECTOR(384)`

O bootstrap do banco esta em `docker/init.sql`, e o ambiente local de banco esta em
`docker-compose.yml`.

## Escopo de indexacao

O projeto indexa arquivos comuns de codigo e texto, incluindo extensoes como:

- `.py`, `.js`, `.ts`, `.tsx`, `.jsx`
- `.java`, `.kt`, `.go`, `.rs`, `.rb`, `.php`
- `.sql`, `.json`, `.yaml`, `.yml`, `.toml`
- `.md`, `.txt`, `.xml`, `.html`, `.css`, `.scss`

Arquivos fora dessa lista nao entram no indice.

## Limitacoes atuais

- O modelo de embedding e carregado a cada chamada, o que pode aumentar latencia.
- A reindexacao apaga todos os chunks antigos antes de inserir os novos.
- O processo nao e incremental por hash ou por arquivo modificado.
- O chunking e heuristico por caracteres, sem AST ou parser por linguagem.
- A dimensao do vetor esta fixa em `384`, acoplando o schema ao modelo atual.
- A busca retorna top-N sem score minimo obrigatorio na aplicacao.
- CLI e MCP repetem parte do pipeline de indexacao.

## Melhorias prioritarias

1. Cachear o modelo de embedding para evitar recarga a cada operacao.
2. Tornar a indexacao transacional para evitar perda de indice em falhas parciais.
3. Implementar indexacao incremental por hash de arquivo ou chunk.
4. Extrair um servico comum de indexacao usado por CLI e MCP.
5. Garantir criacao do indice vetorial tambem fora do bootstrap do container.
6. Adicionar logs, melhor tratamento de erro e observabilidade minima.
7. Permitir filtros de busca e `min_score` na aplicacao.
8. Melhorar o chunking com estrategia orientada por linguagem.

## Ordem recomendada de evolucao

1. Cache do modelo + logs + erros melhores.
2. Indexacao transacional.
3. Indexacao incremental.
4. Garantia e tuning do indice vetorial.
5. Melhor chunking e filtros de consulta.
