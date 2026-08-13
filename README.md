# TW3 Custom Player Voice BR — Pipeline de Voz Feminina com IA

**Português** | [English](README_EN.md)

Pipeline e documentação de uma voz feminina sintética em português brasileiro
para as falas normalmente associadas ao Geralt quando o
jogador utiliza uma personagem feminina no mod **Custom Player Characters**, em
*The Witcher 3: Wild Hunt* 4.04 para PC.

Esta edição adapta as autorreferências para **Geralda**, utiliza nove perfis de
interpretação e acrescenta auditorias de português, pronúncia, duração,
qualidade acústica e identidade vocal.

> Este repositório contém código, testes, exemplos e documentação. O pacote
> instalável é distribuído como arquivo de uma GitHub Release e nunca é
> versionado no histórico Git.

## Estado da versão

- candidato de publicação: `1.0.0-rc.1`;
- jogo: *The Witcher 3* 4.04 para PC;
- idioma: português brasileiro (`brpc.w3speech`);
- corpus: 19.376 IDs;
- falas sintéticas: 19.359;
- entradas que preservam o áudio oficial: 17;
- perfis de interpretação: 9;
- WEM: Opus `0x3041`, 48 kHz, mono ou estéreo conforme o original;
- pacote validado: 1.200.855.572 bytes;
- SHA-256 do candidato: `F35F986964F18111E2D0DB1CDDE0ED5766B1E4BB14755E47E1A040F67495334E`.

Ao ser ativado, o arquivo substitui globalmente as falas de Geralt em português
brasileiro. Desative-o quando voltar a jogar com o Geralt original.

## Diferenciais da versão multirreferência

- voz sintética original criada com Voice Design e usada como fonte autorizada
  de timbre para o OmniVoice;
- classificação multirreferência em nove estilos;
- flexão para Geralda em apresentações e referências contextuais;
- pronúncias revisadas para nomes e lugares do universo do jogo;
- remoção conservadora de rubricas e vocalizações escritas;
- pós-processamento adaptativo sem forçar toda fala à duração original;
- auditoria automática dos 19.359 WAVs, seguida de revisão humana dos casos
  priorizados;
- auditoria específica para detectar vazamentos de identidade vocal;
- montagem compacta preservando os CR2W oficiais e validação byte a byte.

## Transparência sobre IA e voz

A identidade vocal foi criada com **ElevenLabs Voice Design** durante uma
assinatura paga. Uma saída gerada por essa voz sintética foi usada
como referência autorizada do OmniVoice. Não foi usado áudio de uma atriz ou
dubladora de *The Witcher 3* como fonte de timbre, e o projeto não afirma que a
voz pertença a uma pessoa real.

O mod e sua página devem informar claramente que as falas são geradas por IA.
Os áudios de referência, prompts `.pt`, arquivos do jogo e dados de trabalho não
são publicados. Consulte [VOICE_ORIGIN.md](VOICE_ORIGIN.md) e
[ASSET_LICENSE.md](ASSET_LICENSE.md).

## Compatibilidade e instalação

Requer:

- *The Witcher 3* 4.04 para PC;
- idioma das vozes configurado como português brasileiro;
- **Custom Player Characters** instalado e configurado separadamente.

É incompatível com outros mods que substituam o mesmo `brpc.w3speech` ou as
falas de Geralt em português brasileiro. Veja o
[guia de instalação](docs/INSTALLATION.md).

Estrutura do pacote:

```text
modCustomPlayerVoiceBR_Feminina/
  content/
    brpc.w3speech
```

## Conteúdo do repositório

- preparação e limpeza conservadora de texto;
- correções contextuais por ID;
- classificação e atribuição dos nove estilos;
- execução do OmniVoice em lotes com retomada;
- pós-processamento adaptativo com FFmpeg;
- auditorias de qualidade e identidade vocal;
- revisão de nomes, lugares e pronúncias;
- conversão para WEM Opus com Wwise;
- montagem e auditoria do `brpc.w3speech` compacto;
- testes automatizados da pipeline.

O repositório **não contém** referências de voz, prompts clonados, áudio do
jogo, CSV comunitário, WAV, WEM, `w3speech`, documentos privados ou resultados
de auditoria com caminhos locais.

## Reproduzir a pipeline

Consulte [docs/PIPELINE.md](docs/PIPELINE.md). São necessários:

- Python 3.11 ou mais recente;
- OmniVoice funcional;
- FFmpeg;
- Wwise 2021.1.7.7796;
- uma referência vocal própria, licenciada ou autorizada;
- uma instalação legítima de *The Witcher 3* 4.04.

A pipeline principal usa somente a biblioteca padrão do Python. As auditorias
acústicas opcionais usam os pacotes de `requirements-audit.txt`.

```powershell
py -3 -m unittest discover -s tests -v
py -3 -m pip install -r requirements-audit.txt
```

## Documentação

- [Pipeline técnica](docs/PIPELINE.md)
- [Método multirreferência](docs/MULTIRREFERENCIA.md)
- [Garantia de qualidade](docs/GARANTIA_DE_QUALIDADE.md)
- [Instalação e desinstalação](docs/INSTALLATION.md)
- [Publicação segura](docs/PUBLICAR_GITHUB.md)
- [Políticas consultadas](docs/POLITICAS_PUBLICACAO.md)
- [Checklist de Release](docs/RELEASE_CHECKLIST.md)
- [Notas do candidato](docs/RELEASE_NOTES_1.0.0-rc.1.md)
- [Origem da voz](VOICE_ORIGIN.md)
- [Política de ativos](ASSET_LICENSE.md)

## Aviso de trabalho de fã

Este é um trabalho de fã não oficial e não é aprovado nem endossado pela
CD PROJEKT RED. *The Witcher*, seus personagens e os arquivos originais do jogo
pertencem aos respectivos titulares. O mod deve permanecer gratuito, sem
paywall, e ser apresentado como conteúdo não oficial.

## Licenças

O código-fonte original deste repositório está sob a licença MIT. A licença MIT
não se estende ao jogo, aos ativos da CD PROJEKT RED, à voz sintética, aos WAVs
ou WEMs produzidos nem ao pacote instalável. Veja
[ASSET_LICENSE.md](ASSET_LICENSE.md).
