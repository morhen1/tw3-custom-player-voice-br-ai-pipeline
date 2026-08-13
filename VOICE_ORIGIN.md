# Origem e transparência da voz sintética

## Origem

A identidade vocal é uma voz sintética criada com o recurso **Voice Design** da
ElevenLabs. A referência usada na pipeline foi gerada durante uma
assinatura paga e posteriormente utilizada como entrada autorizada no
OmniVoice.

Ela não é apresentada como a voz de uma pessoa real, atriz ou dubladora oficial
de *The Witcher 3*. Nenhuma gravação de uma dubladora do jogo foi usada como
fonte de timbre.

## Uso na pipeline

A identidade vocal base foi mantida em todas as referências expressivas. As
referências multirreferência foram geradas com a mesma identidade vocal e separadas
por função narrativa. Áudios oficiais do jogo foram usados localmente para
medir duração e orientar a classificação das falas, mas não são distribuídos.

## O que permanece privado

- áudios brutos e processados de referência;
- prompts `VoiceClonePrompt` (`.pt`);
- configurações que revelem caminhos locais;
- registros de conta ou assinatura;
- arquivos extraídos do jogo;
- datasets e relatórios de trabalho.

## Divulgação recomendada

Na página de download, usar uma declaração equivalente a:

> As falas deste mod foram sintetizadas por IA. A identidade utilizada é uma
> voz sintética criada com Voice Design e não representa uma atriz ou dubladora
> oficial de The Witcher 3.

Este documento registra a origem técnica do ativo; não substitui aconselhamento
jurídico nem os termos das plataformas utilizadas.
