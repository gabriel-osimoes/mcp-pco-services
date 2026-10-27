# Atualização de confiabilidade — MCP Planning Center

## Alterações incluídas

- Renovação de refresh tokens com remoção do anterior e criação do novo **na mesma transação PostgreSQL**; qualquer falha da gravação reverte tudo.
- Eventos seguros nos logs para renovação/revogação/401, sem tokens nem PATs.
- Logs HTTP detalhados do Uvicorn desativados: a URL `/authorize` contém `state` sensível.
- Validação estrutural do PAT descriptografado antes da execução.
- Opção de transporte stateless (`MCP_STATELESS_HTTP`) para reduzir sessões efêmeras.

## Segurança: teste obrigatório antes do modo stateless

O servidor anterior vincula as credenciais por `contextvars.ContextVar` no middleware ASGI.
A execução de ferramentas do SDK pode ocorrer em outra tarefa assíncrona e perder ou reter
contexto antigo. **Esse risco não foi resolvido definitivamente nesta revisão.** O modo
stateless começa DESATIVADO. A ativação sem um teste de isolamento entre contas é insegura.

## Publicação sem indisponibilidade

1. Envie os arquivos desta pasta para branch `oauth_test` do GitHub.
2. Configure o serviço Render *de teste* para usar branch `oauth_test`.
3. Em `mcp-pco-oauth-teste` confirme `PUBLIC_URL` no domínio do teste e
   `MCP_STATELESS_HTTP=false`.
4. Faça deploy. Complete OAuth com uma credencial de teste; confirme leitura PCO.
5. Confira os logs `oauth_exchange_success`, `oauth_revoke matched=...` e
   `mcp_request_denied` para saber se a falha realmente é de autenticação.
6. Execute o teste A/B: usuários A e B com dados deliberadamente distintos,
   alternando chamadas de leitura via duas conexões separadas, incluindo após reinício
   do Render. Confirme **nenhum vazamento entre contas**.
7. Somente se o teste passar, considere `MCP_STATELESS_HTTP=true` no serviço de teste,
   repetindo testes A/B e testes de compatibilidade com Grok. Pode ser necessário
   substituir o mecanismo `ContextVar` por identidade vinculada a cada chamada MCP.
8. Somente após isso, faça merge na `main` e configure o serviço principal.

## Interpretação dos logs

`POST /revoke` respondendo 200 não prova que um token existia. Agora o log
`oauth_revoke matched=True/False` diferencia isso. `401` antes de `/authorize`
é etapa normal da descoberta OAuth. O reinício do Render Free não apaga registros
no Supabase, mas encerra sessões MCP em memória.

Nenhuma automação Grok nem nome de ferramenta foi alterado.
