# Método multirreferência

## Objetivo

Uma única referência tende a deixar todas as falas com a mesma intenção. A
versão multirreferência mantém a mesma identidade vocal, mas escolhe uma referência de
interpretação adequada ao contexto de cada linha.

## Perfis usados

| Perfil | Uso esperado |
|---|---|
| `conversa_neutra` | diálogo cotidiano e respostas informativas |
| `investigacao_observacional` | pistas, rastros, deduções e descrição do ambiente |
| `pergunta_cautelosa` | dúvidas, confirmação e desconfiança moderada |
| `alerta_tenso` | perigo próximo e urgência controlada |
| `confronto_firme` | autoridade, ameaça contida e imposição de limites |
| `combate_agressivo` | hostilidade direta e ação iminente |
| `ironia_seca` | sarcasmo curto, humor e provocação |
| `tristeza_contida` | luto, arrependimento e despedida sem teatralidade excessiva |
| `narrativa_contida` | explicações longas, raciocínio e relato de acontecimentos |

## Regra principal

Todas as referências devem preservar a mesma identidade vocal. Não use vozes
de pessoas diferentes para “emprestar” emoção: o OmniVoice não separa timbre e
expressão de forma perfeita, e isso pode causar vazamento de identidade.

## Classificação

`classificar_estilos_multireferencia.py` e
`atribuir_estilos_falas_oficiais.py` produzem uma classificação inicial baseada
em texto, duração e sinais acústicos. Frases ambíguas devem ser revisadas por
contexto.

O arquivo de atribuições deve usar IDs exatos e permanecer fora do repositório:

```csv
id_hex;estilo
0x00000000;conversa_neutra
```

## Aprovação

1. Gere uma amostra representativa.
2. Compare com a referência única.
3. Rejeite referências que alterem o timbre, cortem finais ou criem pausas
   artificiais.
4. Congele a configuração aprovada.
5. Gere o lote completo e rode a auditoria de identidade vocal.
