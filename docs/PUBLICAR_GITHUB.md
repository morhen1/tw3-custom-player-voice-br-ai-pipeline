# Publicação segura no GitHub

## Repositório

O Git deve conter somente código, testes, exemplos e documentação. Antes do
primeiro commit, verifique:

```powershell
git status --short
git ls-files
```

Não adicione:

- `brpc.w3speech`, WEM, WAV, MP3 ou `.pt`;
- referências de voz ou arquivos extraídos do jogo;
- corpus comunitário ou planilhas de trabalho;
- consentimentos, credenciais, tokens ou caminhos pessoais;
- relatórios que exponham a instalação local.

## Binário da versão

O `brpc.w3speech` tem mais de 100 MiB e não pode entrar no Git normal. Publique
o `.7z` como **asset da Release**, não por commit e não por Git LFS.

Nome recomendado:

```text
TW3_Custom_Player_Voice_BR_Feminina_v1.0.0-rc.1.7z
```

O arquivo deve conter somente:

```text
modCustomPlayerVoiceBR_Feminina/content/brpc.w3speech
```

## Sequência sugerida

1. criar um repositório público novo;
2. enviar esta árvore sanitizada;
3. confirmar que a Action de testes está verde;
4. criar a tag `v1.0.0-rc.1`;
5. criar uma pre-release com as notas incluídas neste repositório;
6. anexar o `.7z` e um arquivo de checksum;
7. baixar o próprio asset e verificar o hash;
8. somente depois marcar como versão estável.

## Varredura final

Faça uma busca por caminhos, formatos privados e palavras sensíveis:

```powershell
rg -n "C:\\Users|Program Files|api[_-]?key|token|password" .
rg --files -g "*.wav" -g "*.wem" -g "*.w3speech" -g "*.pt"
```
