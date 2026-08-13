# Pipeline técnica

Este documento descreve a pipeline reproduzível da versão multirreferência sem incluir
ativos privados, arquivos do jogo ou o corpus usado no lote oficial.

## 1. Entradas locais

Prepare, fora do repositório:

- o CSV de falas obtido legalmente;
- uma referência vocal própria, licenciada ou autorizada;
- o texto exato pronunciado na referência;
- uma instalação legítima do jogo;
- FFmpeg, Wwise 2021.1.7.7796 e OmniVoice.

Não coloque referências, prompts `.pt`, WAVs, WEMs ou `w3speech` dentro do
histórico Git.

## 2. Preparação dos textos

`preparar_dataset.py` lê o corpus, elimina duplicatas idênticas, trata marcações
não verbais conhecidas e aplica correções contextuais por ID.

```powershell
py -3 preparar_dataset.py --help
```

Nesta versão, a revisão textual foi feita em camadas:

1. limpeza conservadora;
2. flexões femininas dependentes do contexto;
3. troca de autorreferências para Geralda;
4. remoção de rubricas como suspiro, cheiro e vocalizações escritas quando não
   representam fala pronunciável;
5. pronúncias fonéticas aprovadas por audição.

As grafias fonéticas existem somente no texto enviado ao TTS. Elas não alteram
as legendas exibidas pelo jogo.

## 3. Referências e estilos

Crie uma referência base e referências expressivas com a mesma identidade
vocal. A configuração pública é apenas um exemplo; use um arquivo local
ignorado pelo Git.

```powershell
py -3 criar_voice_clone_prompt.py --help
py -3 preparar_jsonl_multireferencia.py --help
```

O lote usa os nove estilos descritos em
[MULTIRREFERENCIA.md](MULTIRREFERENCIA.md). A atribuição é automática como ponto
de partida, mas deve ser revisada por amostra antes da geração completa.

## 4. Amostra de validação

Antes de gerar milhares de falas, produza uma amostra que cubra frases curtas,
longas, perguntas, combate, tristeza, ironia, nomes próprios e DLCs.

```powershell
py -3 selecionar_amostra_jsonl.py --help
py -3 executar_omnivoice.py --help
```

Mantenha `preprocess_prompt=True`. Não aprove uma referência somente por uma
frase: avalie identidade, articulação, pausas, velocidade, ruído final e
naturalidade em diferentes contextos.

## 5. Geração com retomada

`executar_omnivoice.py` trabalha com JSONL, valida os WAVs já existentes e
retoma apenas os IDs pendentes. Use `--check-only` para conferir cobertura sem
gerar áudio.

```powershell
py -3 executar_omnivoice.py `
  --jsonl .\trabalho\lote.jsonl `
  --output .\saida\wav_bruto `
  --check-only `
  --no-normalize-duration
```

## 6. Pós-processamento

`processar_wavs_adaptativo.py` remove silêncio excessivo nas bordas, normaliza
volume e acelera somente quando necessário, respeitando um limite configurado.
Diferenças de duração são aconselháveis por padrão, não bloqueadoras.

```powershell
py -3 processar_wavs_adaptativo.py --help
```

## 7. Auditorias

Execute antes de converter para WEM:

- `auditar_qualidade_wavs.py`: silêncio interno, caudas, densidade de fala e
  desvios de duração;
- `tools/auditoria_identidade_vocal/auditar_identidade_vocal.py`: desvios de
  pitch e identidade vocal;
- revisão humana dos casos de alta e média prioridade.

As auditorias são triagens heurísticas. Elas reduzem o universo de escuta, mas
não provam que um áudio esteja bom ou ruim.

## 8. Conversão e montagem

Converta os WAVs aprovados para WEM Opus com Wwise e monte um pacote compacto
usando os pacotes oficiais locais como índice e fonte dos CR2W.

```powershell
py -3 converter_wav_para_wem_opus_lote_v2.py --help
py -3 montar_brpc_w3speech_compacto_v4.py --help
py -3 auditar_cobertura.py --help
```

A montagem final deve informar zero IDs ausentes, zero incompatibilidades e
validar WEMs e CR2W byte a byte.

## 9. Release

Copie somente a pasta testada dentro do jogo, gere SHA-256, compacte-a e siga o
[checklist](RELEASE_CHECKLIST.md). Nunca monte a Release a partir de uma pasta
intermediária apenas por ter o nome parecido.
