# Instalação e desinstalação

## Requisitos

- *The Witcher 3: Wild Hunt* 4.04 para PC;
- idioma das vozes em português brasileiro;
- Custom Player Characters instalado separadamente;
- nenhum outro mod substituindo o mesmo `brpc.w3speech`.

## Instalação

1. Feche o jogo.
2. Baixe o arquivo da GitHub Release.
3. Confira o SHA-256 publicado nas notas da versão.
4. Extraia a pasta `modCustomPlayerVoiceBR_Feminina` para a pasta `mods` do
   jogo.
5. Confirme a estrutura:

```text
The Witcher 3/
  mods/
    modCustomPlayerVoiceBR_Feminina/
      content/
        brpc.w3speech
```

6. Inicie o jogo com o idioma de voz em português brasileiro.

## Atualização

Remova a pasta da versão anterior antes de copiar a nova. Não mantenha duas
pastas renomeadas contendo `brpc.w3speech`: mesmo renomeadas, ambas podem ser
detectadas como mods e entrar em conflito.

## Desinstalação

Feche o jogo e remova somente:

```text
mods/modCustomPlayerVoiceBR_Feminina
```

Os arquivos oficiais do jogo não são alterados.

## Conflitos

Este mod substitui globalmente as falas portuguesas associadas ao Geralt.
Gerenciadores de mods podem não resolver conflitos entre dois arquivos
`brpc.w3speech`; mantenha apenas uma substituição ativa.
