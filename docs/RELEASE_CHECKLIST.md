# Checklist da Release

## Direitos e transparência

- [ ] confirmar que a referência sintética foi gerada no plano pago aplicável;
- [ ] manter a divulgação de voz sintética e IA no README e na Release;
- [ ] não usar nome, imagem ou alegação de voz oficial;
- [ ] publicar gratuitamente e sem paywall;
- [ ] não incluir referência, prompt `.pt` ou áudio extraído do jogo.

## Código

- [ ] testes locais aprovados;
- [ ] GitHub Actions aprovado;
- [ ] nenhum caminho pessoal ou segredo encontrado;
- [ ] somente arquivos permitidos aparecem em `git status`;
- [ ] exemplos não apontam para ativos privados.

## Pacote

- [ ] pasta de origem é exatamente a versão testada no jogo;
- [ ] nome final é `modCustomPlayerVoiceBR_Feminina`;
- [ ] existe somente `content/brpc.w3speech` no pacote;
- [ ] tamanho é 1.200.855.572 bytes;
- [ ] SHA-256 é `F35F986964F18111E2D0DB1CDDE0ED5766B1E4BB14755E47E1A040F67495334E`;
- [ ] arquivo compactado fica abaixo do limite da plataforma;
- [ ] asset baixado da própria Release foi revalidado.

## Página da versão

- [ ] compatibilidade e conflito com outros `brpc.w3speech` explicados;
- [ ] instruções de instalação e desinstalação incluídas;
- [ ] tag e nome do arquivo usam a mesma versão;
- [ ] versão inicialmente marcada como pre-release;
- [ ] canal para relatos de IDs defeituosos disponível.
