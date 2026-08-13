# Garantia de qualidade

## Camadas de validação

A versão candidata passou pelas seguintes camadas:

1. validação estrutural do JSONL e unicidade de IDs;
2. confirmação de 19.359 WAVs sintéticos esperados;
3. pós-processamento adaptativo com relatório por ID;
4. auditoria de pausas, caudas, velocidade e duração;
5. revisão de português, gênero, rubricas e pronúncia;
6. auditoria acústica de identidade vocal em todo o lote;
7. escuta humana dos candidatos priorizados;
8. conversão para WEM com validação de codec, canais e taxa;
9. montagem de 19.359 entradas no pacote compacto;
10. validação byte a byte dos WEMs e CR2W montados;
11. teste dentro do jogo.

## Resultados registrados

- 19.359 falas auditadas na etapa de identidade vocal;
- 599 WAVs no ciclo final consolidado de pronúncia e qualidade;
- 14 casos de identidade vocal confirmados por escuta e substituídos;
- 19.298 entradas normais, 55 IDs high expandidos e 6 duplicatas equivalentes
  no mapeamento final;
- zero IDs ausentes e zero entradas incompatíveis;
- pacote final de 1.200.855.572 bytes;
- SHA-256 `F35F986964F18111E2D0DB1CDDE0ED5766B1E4BB14755E47E1A040F67495334E`.

## Limitações

Uma auditoria automática não entende atuação como uma pessoa. Sons de combate,
risadas, frases muito curtas e nomes inventados podem gerar falsos positivos ou
escapar dos critérios. Relatos de gameplay devem informar o ID hexadecimal,
texto aproximado, contexto e tipo de defeito.

## Política de correção

- corrigir por ID, evitando substituições globais ambíguas;
- manter sempre o WAV anterior para comparação;
- gerar múltiplas tentativas para defeitos de identidade vocal;
- alterar somente os IDs aprovados na reconstrução incremental;
- comparar os dois `w3speech` e exigir que apenas os IDs esperados mudem.

